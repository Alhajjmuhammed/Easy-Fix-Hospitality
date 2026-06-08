import logging
from decimal import Decimal

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.db.models import Sum, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from orders.models import Order
from cashier.models import Payment
from ..serializers import PaymentSerializer, ProcessPaymentSerializer
from .helpers import get_restaurant_owner
from .orders import _notify_ws

logger = logging.getLogger(__name__)


def _is_payment_staff(user):
    return (
        user.is_cashier() or user.is_customer_care() or
        user.is_owner() or user.is_main_owner() or
        user.is_branch_owner() or user.is_manager()
    )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def payments(request):
    if request.method == 'GET':
        return _list_payments(request)
    return _process_payment(request)




def _list_payments(request):
    if not _is_payment_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    from django.db.models import Q as _Q

    _otq = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner)
    )
    qs = Payment.objects.filter(
        _otq,
        is_voided=False,
    ).distinct().select_related('order', 'order__table_info', 'processed_by').order_by('-created_at')

    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(
            _Q(order__order_number__icontains=search) |
            _Q(id=search if search.isdigit() else 0)
        )

    date_from = request.GET.get('date_from', '')
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to', '')
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    qs = qs[:50]

    return Response({'payments': PaymentSerializer(qs, many=True).data})


def _process_payment(request):
    if not _is_payment_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)

    s = ProcessPaymentSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)

    data = s.validated_data
    offline_id = data.get('offline_id', '').strip()

    # De-duplication for offline payments
    if offline_id:
        existing = Payment.objects.filter(notes__contains=f'[offline:{offline_id}]').first()
        if existing:
            return Response({
                'payment': PaymentSerializer(existing).data,
                'already_synced': True,
            })

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    order = get_object_or_404(Order.objects.filter(_tq).distinct(), id=data['order_id'])

    if request.user.is_customer_care() and order.ordered_by != request.user:
        return Response({'error': 'Access denied.'}, status=403)

    if order.status == 'cancelled':
        return Response({'error': 'Cannot process payment for a cancelled order.'}, status=400)

    total_paid = order.payments.filter(is_voided=False).aggregate(
        t=Sum('amount')
    )['t'] or Decimal('0.00')

    amount = Decimal(str(data['amount']))
    if amount <= 0:
        return Response({'error': 'Payment amount must be positive.'}, status=400)

    # Reject overpayment — mirrors web's cashier process_payment check.
    remaining_balance = order.total_amount - total_paid
    if amount > remaining_balance:
        return Response(
            {'error': f'Payment amount ({amount}) exceeds remaining balance ({remaining_balance}).'},
            status=400,
        )

    notes = data.get('notes', '')
    if offline_id:
        notes = f'[offline:{offline_id}] {notes}'.strip()

    # ── DB writes inside atomic block — no _notify_ws inside (PostgreSQL safe) ──
    with transaction.atomic():
        payment = Payment.objects.create(
            order=order,
            amount=amount,
            payment_method=data['payment_method'],
            processed_by=request.user,
            reference_number=data.get('reference_number', ''),
            notes=notes,
            is_voided=False,
        )

        # Update order payment status
        new_total = total_paid + amount
        if new_total >= order.total_amount:
            order.payment_status = 'paid'
            order.release_table()
        elif new_total > 0:
            order.payment_status = 'partial'
        order.save(update_fields=['payment_status', 'updated_at'])
        # --- transaction commits here ---

    # ── Outside transaction: WebSocket + print ────────────────────────────────
    _notify_ws(order, request.user)

    try:
        from orders.printing import auto_print_receipt
        auto_print_receipt(payment, printed_by=request.user)
    except Exception as e:
        logger.warning('Auto-print receipt failed: %s', e)

    logger.info('Mobile payment: order %s amount %s by %s', order.order_number, amount, request.user.username)

    return Response(
        {'payment': PaymentSerializer(payment).data, 'order_payment_status': order.payment_status},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def void_payment(request, payment_id):
    """Void a payment with a mandatory reason."""
    if not _is_payment_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _otq3 = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner)
    )
    payment = get_object_or_404(Payment.objects.filter(_otq3).distinct(), id=payment_id)

    if payment.is_voided:
        return Response({'error': 'Payment is already voided.'}, status=400)

    reason = request.data.get('reason', '').strip()
    if not reason:
        return Response({'error': 'Void reason is required.'}, status=400)

    with transaction.atomic():
        payment.is_voided = True
        payment.void_reason = reason
        payment.voided_by = request.user
        payment.voided_at = timezone.now()
        payment.save()

        # Recalculate payment status on the order
        still_paid = payment.order.payments.filter(is_voided=False).aggregate(
            t=Sum('amount')
        )['t'] or Decimal('0.00')

        order = payment.order
        if still_paid <= 0:
            order.payment_status = 'unpaid'
        elif still_paid < order.total_amount:
            order.payment_status = 'partial'
        else:
            order.payment_status = 'paid'
        order.save(update_fields=['payment_status', 'updated_at'])
        # --- transaction commits here ---

    # Outside transaction: WebSocket notification
    _notify_ws(order, request.user)

    return Response({'message': 'Payment voided successfully.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def payment_receipt(request, payment_id):
    """Get full receipt data for a payment."""
    if not _is_payment_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    from orders.models import Order as _Order
    from ..serializers import OrderSerializer
    from decimal import Decimal as _Dec

    _otq = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner)
    )
    payment = get_object_or_404(
        Payment.objects.filter(_otq).distinct().select_related('order', 'order__table_info', 'processed_by'),
        id=payment_id,
    )

    order = _Order.objects.prefetch_related('order_items__product').get(pk=payment.order_id)
    order_total = _Dec(str(order.get_total()))
    change_amount = float(payment.amount - order_total) if payment.payment_method == 'cash' and payment.amount > order_total else 0.0
    remaining_balance = float(order_total - payment.amount) if payment.amount < order_total else 0.0

    return Response({
        'payment': PaymentSerializer(payment).data,
        'order': OrderSerializer(order, context={'request': request}).data,
        'change_amount': change_amount,
        'remaining_balance': remaining_balance,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def reprint_receipt(request, payment_id):
    """Reprint the receipt for a payment."""
    if not _is_payment_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _otq2 = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner)
    )
    payment = get_object_or_404(
        Payment.objects.filter(_otq2).distinct(),
        id=payment_id,
    )

    try:
        from orders.printing import auto_print_receipt
        result = auto_print_receipt(payment, printed_by=request.user)
        if result.get('receipt_printed'):
            return Response({'success': True, 'message': f'Receipt reprinted for payment #{payment_id}'})
        errors = result.get('errors', ['Unknown error'])
        return Response({'success': False, 'message': f'Reprint failed: {", ".join(errors)}'})
    except Exception as e:
        logger.error('Mobile reprint_receipt error for payment %s: %s', payment_id, e)
        return Response({'success': False, 'message': 'Reprint failed. Check printer connection.'})
