import logging
from decimal import Decimal

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.db.models import Prefetch, Sum, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from orders.models import Order
from cashier.models import Payment, VoidTransaction
from ..serializers import PaymentSerializer, ProcessPaymentSerializer
from .helpers import get_restaurant_owner
from .orders import _notify_ws
from restaurant_system.db_utils import managed_owner_ids

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
    if not request.user.is_administrator() and not request.user.has_feature('process_payments'):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    from django.db.models import Q as _Q

    _otq = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner) |
        (Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner=owner) | Q(order__order_type__in=['delivery', 'pickup'], order__restaurant_owner=owner)) |
        (Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner__in=managed_owner_ids(owner)) | Q(order__order_type__in=['delivery', 'pickup'], order__restaurant_owner__in=managed_owner_ids(owner)))
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

    from datetime import datetime as _dt_parse
    date_from = request.GET.get('date_from', '')
    if date_from:
        try:
            date_from = _dt_parse.strptime(date_from, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date_from. Use YYYY-MM-DD.'}, status=400)
        qs = qs.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to', '')
    if date_to:
        try:
            date_to = _dt_parse.strptime(date_to, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date_to. Use YYYY-MM-DD.'}, status=400)
        qs = qs.filter(created_at__date__lte=date_to)

    qs = qs[:50]

    return Response({'payments': PaymentSerializer(qs, many=True).data})


def _process_payment(request):
    if not _is_payment_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)
    if not request.user.has_feature('process_payments'):
        return Response({'error': 'Access denied.'}, status=403)

    s = ProcessPaymentSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)

    data = s.validated_data
    from mobile_api.views.orders import safe_client_id
    from accounts.security_utils import sanitize_notes
    offline_id = safe_client_id(data.get('offline_id', ''))

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner) |
        (Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) | Q(order_type__in=['delivery', 'pickup'], restaurant_owner=owner)) |
        (Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=managed_owner_ids(owner)) | Q(order_type__in=['delivery', 'pickup'], restaurant_owner__in=managed_owner_ids(owner)))
    )

    # Quick access check before acquiring lock (avoids holding lock during CC IDOR check)
    order_check = get_object_or_404(Order.objects.filter(_tq).distinct(), id=data['order_id'])
    if request.user.is_customer_care() and order_check.ordered_by != request.user:
        return Response({'error': 'Access denied.'}, status=403)

    amount = Decimal(str(data['amount']))
    if amount <= 0:
        return Response({'error': 'Payment amount must be positive.'}, status=400)

    notes = sanitize_notes(data.get('notes', '')) or ''
    if offline_id:
        notes = f'[offline:{offline_id}] {notes}'.strip()

    # ── DB writes inside atomic block with row lock — prevents concurrent double-payment ──
    with transaction.atomic():
        # Acquire the row lock FIRST so that the dedup check runs with a fully
        # serialized view — two concurrent identical offline POSTs cannot both pass
        # the filter before either has committed (TOCTOU fix).
        # No distinct() — FOR UPDATE + DISTINCT is forbidden in PostgreSQL. The OR'd
        # joins in _tq can return the same order more than once (e.g. a main owner who
        # also runs a second restaurant as its branch owner), so the access check is
        # done above (with distinct) and the row is locked by primary key only.
        order = Order.objects.select_for_update(of=('self',)).get(pk=order_check.pk)
        # Dedup check AFTER the lock so the second duplicate request sees the
        # Payment row the first already created.
        if offline_id:
            _existing = Payment.objects.filter(notes__contains=f'[offline:{offline_id}]', processed_by=request.user).first()
            if _existing:
                return Response({'payment': PaymentSerializer(_existing).data, 'already_synced': True})

        from cashier.mobile_money import NOT_PAYABLE_STATUSES
        if order.status in NOT_PAYABLE_STATUSES:     # cancelled / wasted / refused: same rule as the web
            return Response({'error': 'Cannot process payment for a cancelled order.'}, status=400)

        # Re-read total_paid inside the lock so the overpayment check is race-free
        total_paid = order.payments.filter(is_voided=False).aggregate(
            t=Sum('amount')
        )['t'] or Decimal('0.00')

        # Reject overpayment — mirrors web's cashier process_payment check.
        remaining_balance = order.total_amount - total_paid
        if amount > remaining_balance:
            return Response(
                {'error': f'Payment amount ({amount}) exceeds remaining balance ({remaining_balance}).'},
                status=400,
            )

        loyalty_redeem = None
        if data['payment_method'] == 'loyalty':
            if offline_id:
                return Response({'error': 'Loyalty points can only be used online.'}, status=400)
            from cashier import loyalty as loyalty_svc
            from django.core.exceptions import ValidationError as _VE
            try:
                loyalty_redeem = loyalty_svc.prepare_redeem(order, amount, data.get('loyalty_code'))
            except _VE as e:
                return Response({'error': ' '.join(e.messages)}, status=400)
            amount = loyalty_redeem[3]     # exactly what the points taken are worth (rest stays due)

        payment = Payment.objects.create(
            order=order,
            amount=amount,
            payment_method=data['payment_method'],
            processed_by=request.user,
            reference_number=(sanitize_notes(data.get('reference_number', '')) or '')[:50],
            notes=notes,
            is_voided=False,
        )
        if loyalty_redeem:
            program, customer, points, _credited = loyalty_redeem
            loyalty_svc.record_redeem(program, customer, payment, points, request.user)

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
        auto_print_receipt(payment)
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
    if not request.user.has_feature('void_payments'):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _otq3 = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner) |
        (Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner=owner) | Q(order__order_type__in=['delivery', 'pickup'], order__restaurant_owner=owner)) |
        (Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner__in=managed_owner_ids(owner)) | Q(order__order_type__in=['delivery', 'pickup'], order__restaurant_owner__in=managed_owner_ids(owner)))
    )

    reason = request.data.get('reason', '').strip()
    if not reason:
        return Response({'error': 'Void reason is required.'}, status=400)

    # Scope check first (the OR'd joins can repeat a row, and FOR UPDATE cannot be
    # combined with DISTINCT), then lock the single payment row by primary key.
    _payment_ids = list(
        Payment.objects.filter(_otq3, id=payment_id).values_list('id', flat=True)[:1]
    )
    if not _payment_ids:
        from django.http import Http404
        raise Http404('No Payment matches the given query.')

    with transaction.atomic():
        payment = Payment.objects.select_for_update(of=('self',)).get(pk=_payment_ids[0])

        if request.user.is_customer_care() and payment.order.ordered_by != request.user:
            return Response({'error': 'Access denied.'}, status=403)

        if payment.is_voided:
            return Response({'error': 'Payment is already voided.'}, status=400)

        # Lock the order row so a concurrent _process_payment cannot commit
        # 'paid' while void_payment is recalculating the payment_status.
        from orders.models import Order as _Order
        order = _Order.objects.select_for_update(of=('self',)).get(pk=payment.order_id)

        VoidTransaction.objects.create(
            original_payment=payment,
            voided_by=request.user,
            void_reason=reason,
            refund_amount=payment.amount,
            refund_method=payment.payment_method,
        )

        payment.is_voided = True
        payment.void_reason = reason
        payment.voided_by = request.user
        payment.voided_at = timezone.now()
        payment.save(update_fields=['is_voided', 'void_reason', 'voided_by', 'voided_at'])

        # Recalculate payment status on the order (re-query after voiding this payment)
        still_paid = Payment.objects.filter(order=order, is_voided=False).aggregate(
            t=Sum('amount')
        )['t'] or Decimal('0.00')

        if still_paid <= 0:
            order.payment_status = 'unpaid'
            order.occupy_table()
        elif still_paid < order.total_amount:
            order.payment_status = 'partial'
            order.occupy_table()
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
    if not request.user.has_feature('view_receipts'):
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
        Q(order__table_info__restaurant__branch_owner=owner) |
        (Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner=owner) | Q(order__order_type__in=['delivery', 'pickup'], order__restaurant_owner=owner)) |
        (Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner__in=managed_owner_ids(owner)) | Q(order__order_type__in=['delivery', 'pickup'], order__restaurant_owner__in=managed_owner_ids(owner)))
    )
    payment = get_object_or_404(
        Payment.objects.filter(_otq).distinct().select_related('order', 'order__table_info', 'processed_by'),
        id=payment_id,
    )

    if request.user.is_customer_care() and payment.order.ordered_by != request.user:
        return Response({'error': 'Access denied.'}, status=403)

    order = _Order.objects.select_related(
        'table_info', 'ordered_by', 'confirmed_by', 'entered_by'
    ).prefetch_related(
        Prefetch('payments', queryset=Payment.objects.select_related('processed_by')),
        'order_items__product',
        'table_info__bill_requests',
    ).get(pk=payment.order_id)
    order_total = _Dec(str(order.get_total()))
    total_paid = sum((p.amount for p in order.payments.all() if not p.is_voided), _Dec('0'))
    change_amount = float(total_paid - order_total) if payment.payment_method == 'cash' and total_paid > order_total else 0.0
    remaining_balance = float(order_total - total_paid) if total_paid < order_total else 0.0

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
    if not request.user.has_feature('view_receipts'):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _otq2 = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner) |
        (Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner=owner) | Q(order__order_type__in=['delivery', 'pickup'], order__restaurant_owner=owner)) |
        (Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner__in=managed_owner_ids(owner)) | Q(order__order_type__in=['delivery', 'pickup'], order__restaurant_owner__in=managed_owner_ids(owner)))
    )
    payment = get_object_or_404(
        Payment.objects.filter(_otq2).distinct().select_related('order'),
        id=payment_id,
    )

    if request.user.is_customer_care() and payment.order.ordered_by != request.user:
        return Response({'error': 'Access denied.'}, status=403)

    try:
        from orders.printing import auto_print_receipt
        result = auto_print_receipt(payment)
        if result.get('receipt_printed'):
            return Response({'success': True, 'message': f'Receipt reprinted for payment #{payment_id}'})
        errors = result.get('errors', ['Unknown error'])
        return Response({'success': False, 'message': f'Reprint failed: {", ".join(errors)}'})
    except Exception as e:
        logger.error('Mobile reprint_receipt error for payment %s: %s', payment_id, e)
        return Response({'success': False, 'message': 'Reprint failed. Check printer connection.'})
