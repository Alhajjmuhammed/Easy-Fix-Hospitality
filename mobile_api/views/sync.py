"""
Offline sync endpoints.

POST /sync/push/  – bulk upload orders/payments/bill_requests created while offline
GET  /sync/pull/  – pull full current state (menu + tables + active orders)
"""
import uuid
import logging
from decimal import Decimal

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from orders.models import Order, OrderItem, BillRequest
from restaurant.models import TableInfo, Product, MainCategory
from cashier.models import Payment
from ..serializers import (
    CategorySerializer, TableSerializer, OrderSerializer,
    BillRequestSerializer, SyncPushSerializer,
)
from .helpers import get_restaurant_owner
from .orders import _notify_ws

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Push  (offline → server)
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def sync_push(request):
    """
    Body:
      { "orders": [...], "payments": [...], "bill_requests": [...] }

    Each item MUST include offline_id for de-duplication.

    Returns per-item results.
    """
    s = SyncPushSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=400)

    data = s.validated_data
    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    results = {'orders': [], 'payments': [], 'bill_requests': []}

    for item in data.get('orders', []):
        offline_id = item.get('offline_id', '')
        try:
            result = _sync_order(request.user, owner, item)
            results['orders'].append({'offline_id': offline_id, **result})
        except Exception as e:
            logger.error('Sync order error offline_id=%s: %s', offline_id, e)
            results['orders'].append({'offline_id': offline_id, 'status': 'error', 'error': str(e)})

    for item in data.get('payments', []):
        offline_id = item.get('offline_id', '')
        try:
            result = _sync_payment(request.user, owner, item)
            results['payments'].append({'offline_id': offline_id, **result})
        except Exception as e:
            logger.error('Sync payment error offline_id=%s: %s', offline_id, e)
            results['payments'].append({'offline_id': offline_id, 'status': 'error', 'error': str(e)})

    for item in data.get('bill_requests', []):
        offline_id = item.get('offline_id', '')
        try:
            result = _sync_bill_request(request.user, owner, item)
            results['bill_requests'].append({'offline_id': offline_id, **result})
        except Exception as e:
            results['bill_requests'].append({'offline_id': offline_id, 'status': 'error', 'error': str(e)})

    return Response({'results': results, 'synced_at': timezone.now().isoformat()})


def _sync_order(user, owner, data):
    offline_id = data.get('offline_id', '').strip()

    if offline_id:
        existing = Order.objects.filter(
            ordered_by=user,
            special_instructions__contains=f'[offline:{offline_id}]',
        ).first()
        if existing:
            return {'status': 'duplicate', 'order_id': existing.id, 'order_number': existing.order_number}

    table_id = data.get('table_id')
    table = TableInfo.objects.filter(
        Q(owner=owner) | Q(restaurant__main_owner=owner) | Q(restaurant__branch_owner=owner),
        id=table_id,
    ).first()
    if table is None:
        return {'status': 'error', 'error': f'Table {table_id} not found.'}

    items = data.get('items', [])
    if not items:
        return {'status': 'error', 'error': 'No items provided.'}

    special = data.get('special_instructions', '')
    if offline_id:
        special = f'[offline:{offline_id}] {special}'.strip()

    total = sum(
        Decimal(str(i.get('unit_price', 0))) * int(i.get('quantity', 1))
        for i in items
    )
    tax_rate = table.get_tax_rate()

    order = Order.objects.create(
        order_number=f'ORD-{uuid.uuid4().hex[:8].upper()}',
        table_info=table,
        ordered_by=user,
        status='pending',
        total_amount=total * (Decimal('1') + tax_rate),
        special_instructions=special,
    )

    for i in items:
        try:
            qty = int(i.get('quantity', 1))
        except (TypeError, ValueError):
            qty = 1
        qty = max(1, min(qty, 100))  # clamp to valid range — mirrors _place_order bounds check
        # NOTE: select_for_update() requires an active transaction (with transaction.atomic()).
        # _sync_order runs outside any transaction so we use a plain filter here.
        # Concurrency risk on offline sync is acceptable — stock is clamped to max(0, ...).
        product = Product.objects.filter(
            Q(main_category__owner=owner) |
            Q(main_category__restaurant__main_owner=owner) |
            Q(main_category__restaurant__branch_owner=owner)
        ).filter(id=i['product_id']).first()
        if product is None:
            pass  # Skip unknown products rather than failing whole import
        else:
            # Always use the authoritative server-side price — never trust the client.
            # An offline client may send a stale or manipulated price; the server
            # price (including any active happy-hour promotion) is the source of truth.
            fn = getattr(product, 'get_current_price', None)
            server_price = float(fn()) if fn else float(product.price)
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                unit_price=server_price,
            )
            # Decrement stock (best-effort; offline orders may arrive after stock changed).
            # Use `is not None` — mirrors _place_order — to avoid TypeError when stock
            # tracking is disabled (available_in_stock = NULL in the DB).
            if product.available_in_stock is not None:
                product.available_in_stock = max(0, product.available_in_stock - qty)
                product.save(update_fields=['available_in_stock'])

    # Reject order if no items were actually created (all product IDs were invalid)
    if not order.order_items.exists():
        order.delete()
        return {'status': 'error', 'error': 'No valid products found. Order was not placed.'}

    # Recalculate total from items that were actually created (excludes skipped products)
    actual_subtotal = sum(oi.get_subtotal() for oi in order.order_items.all())
    order.total_amount = actual_subtotal * (Decimal('1') + tax_rate)
    order.save(update_fields=['total_amount'])

    table.is_available = False
    table.save(update_fields=['is_available'])

    # _notify_ws uses async_to_sync which must NOT run inside @transaction.atomic
    # on PostgreSQL — call it after the decorated function returns (already outside).
    # Since _sync_order is called from sync_push (no transaction), this is safe here.
    try:
        _notify_ws(order, user, event_type='new_order')
    except Exception as e:
        logger.warning('WS notify failed for synced order %s: %s', order.order_number, e)

    return {'status': 'created', 'order_id': order.id, 'order_number': order.order_number}


def _sync_payment(user, owner, data):
    offline_id = data.get('offline_id', '').strip()

    if offline_id:
        existing = Payment.objects.filter(notes__contains=f'[offline:{offline_id}]').first()
        if existing:
            return {'status': 'duplicate', 'payment_id': existing.id}

    order_id = data.get('order_id')
    order_number = data.get('order_number', '')
    is_privileged = (
        user.is_cashier() or user.is_owner() or user.is_main_owner()
        or user.is_branch_owner() or user.is_manager()
    )
    # Build the base lookup — privileged staff can process payments for any order
    # at their restaurant; customers/CC are restricted to orders they placed themselves.
    # Use dual-FK filter to cover both legacy (owner FK) and PRO-plan (restaurant FK) tables.
    restaurant_q = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    if not is_privileged:
        restaurant_q = restaurant_q & Q(ordered_by=user)
    try:
        order = Order.objects.get(restaurant_q, id=order_id)
    except Order.DoesNotExist:
        try:
            order = Order.objects.get(restaurant_q, order_number=order_number)
        except Order.DoesNotExist:
            return {'status': 'error', 'error': f'Order {order_id} not found.'}
    # CC staff can only pay for their own orders (same constraint as regular payments endpoint).
    if user.is_customer_care() and order.ordered_by != user:
        return {'status': 'error', 'error': 'Access denied.'}

    notes = data.get('notes', '')
    if offline_id:
        notes = f'[offline:{offline_id}] {notes}'.strip()

    amount = Decimal(str(data.get('amount', 0)))
    if amount <= 0:
        return {'status': 'error', 'error': 'Payment amount must be positive.'}

    from django.db.models import Sum as _Sum2
    already_paid = order.payments.filter(is_voided=False).aggregate(t=_Sum2('amount'))['t'] or Decimal('0.00')
    remaining = order.total_amount - already_paid
    if amount > remaining:
        return {'status': 'error', 'error': f'Payment amount ({amount}) exceeds remaining balance ({remaining}).'}

    payment = Payment.objects.create(
        order=order,
        amount=amount,
        payment_method=data.get('payment_method', 'cash'),
        processed_by=user,
        reference_number=data.get('reference_number', ''),
        notes=notes,
        is_voided=False,
    )

    from django.db.models import Sum
    total_paid = order.payments.filter(is_voided=False).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    if total_paid >= order.total_amount:
        order.payment_status = 'paid'
        order.release_table()
    elif total_paid > 0:
        order.payment_status = 'partial'
    order.save(update_fields=['payment_status', 'updated_at'])

    # _notify_ws uses async_to_sync — must not run inside @transaction.atomic.
    try:
        _notify_ws(order, user)
    except Exception as e:
        logger.warning('WS notify failed for synced payment: %s', e)

    return {'status': 'created', 'payment_id': payment.id}


def _sync_bill_request(user, owner, data):
    # Only customers may request bills — mirrors _create_bill_request in bill_requests.py.
    if not user.is_customer():
        return {'status': 'error', 'error': 'Only customers can request bills.'}

    table_id = data.get('table_id')
    table = TableInfo.objects.filter(
        Q(owner=owner) | Q(restaurant__main_owner=owner) | Q(restaurant__branch_owner=owner),
        id=table_id,
    ).first()
    if table is None:
        return {'status': 'error', 'error': f'Table {table_id} not found.'}

    # Mirror _create_bill_request: the customer must have an active unpaid order here.
    from orders.models import Order as _Order
    has_active_order = _Order.objects.filter(
        table_info=table,
        ordered_by=user,
        status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
        payment_status__in=['unpaid', 'partial'],
    ).exists()
    if not has_active_order:
        return {'status': 'error', 'error': 'You do not have an active order at this table.'}

    # Prevent duplicate pending bill requests — mirrors _create_bill_request.
    existing = BillRequest.objects.filter(table_info=table, status='pending').first()
    if existing:
        return {'status': 'duplicate', 'bill_request_id': existing.id}

    br = BillRequest.objects.create(table_info=table, requested_by=user, status='pending')
    return {'status': 'created', 'bill_request_id': br.id}


# ---------------------------------------------------------------------------
# Pull  (server → app)
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def sync_pull(request):
    """
    Return full current state for the restaurant:
    menu, tables, active orders, pending bill requests.
    Used on app launch or manual refresh.
    """
    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    user = request.user

    _cat_q = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )
    categories = MainCategory.objects.filter(_cat_q).distinct().prefetch_related(
        'products__sub_category'
    ).order_by('name')

    pull_table_q = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )
    tables = TableInfo.objects.filter(pull_table_q).distinct().order_by('tbl_no')

    order_table_q = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    orders_qs = Order.objects.filter(
        order_table_q,
        status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
        payment_status__in=['unpaid', 'partial'],
    ).distinct().select_related('table_info', 'ordered_by').prefetch_related('order_items__product', 'payments')

    if user.is_customer() or user.is_customer_care():
        orders_qs = orders_qs.filter(ordered_by=user)

    pending_brs = []
    if not user.is_customer():
        br_qs = BillRequest.objects.filter(
            order_table_q, status='pending',
        ).distinct().select_related('table_info', 'requested_by')
        pending_brs = BillRequestSerializer(br_qs, many=True).data

    return Response({
        'categories': CategorySerializer(categories, many=True, context={'request': request}).data,
        'tables': TableSerializer(tables, many=True).data,
        'active_orders': OrderSerializer(orders_qs, many=True, context={'request': request}).data,
        'pending_bill_requests': pending_brs,
        'synced_at': timezone.now().isoformat(),
        'restaurant_name': getattr(owner, 'restaurant_name', ''),
    })
