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
            results['orders'].append({'offline_id': offline_id, 'status': 'error', 'error': 'Order sync failed. Please retry.'})

    for item in data.get('payments', []):
        offline_id = item.get('offline_id', '')
        try:
            result = _sync_payment(request.user, owner, item)
            results['payments'].append({'offline_id': offline_id, **result})
        except Exception as e:
            logger.error('Sync payment error offline_id=%s: %s', offline_id, e)
            results['payments'].append({'offline_id': offline_id, 'status': 'error', 'error': 'Payment sync failed. Please retry.'})

    for item in data.get('bill_requests', []):
        offline_id = item.get('offline_id', '')
        try:
            result = _sync_bill_request(request.user, owner, item)
            results['bill_requests'].append({'offline_id': offline_id, **result})
        except Exception as e:
            logger.error('Sync bill_request error offline_id=%s: %s', offline_id, e)
            results['bill_requests'].append({'offline_id': offline_id, 'status': 'error', 'error': 'Bill request sync failed. Please retry.'})

    return Response({'results': results, 'synced_at': timezone.now().isoformat()})


def _sync_order(user, owner, data):
    offline_id = data.get('offline_id', '').strip()

    # All DB writes are in the atomic block; _notify_ws (async_to_sync) is called after.
    # Dedup check is also inside the transaction so two concurrent pushes with the same
    # offline_id cannot both pass the check and create two orders (TOCTOU fix).
    with transaction.atomic():
        result = _sync_order_atomic(user, owner, data, offline_id)

    if result.get('status') == 'created':
        try:
            from orders.models import Order as _Ord
            _order = _Ord.objects.get(id=result['order_id'])
            is_append = bool(data.get('existing_order_id'))
            # Append syncs: _sync_order_append already called auto_print_new_items —
            # only broadcast an update event, never re-print the full order.
            # New order syncs: broadcast new_order and print all items (if not printed locally).
            _notify_ws(_order, user,
                       event_type='new_order' if not is_append else 'order_status_update')
            if not is_append and not bool(data.get('local_print')):
                from orders.printing import auto_print_order
                auto_print_order(_order)
        except Exception as e:
            logger.warning('Post-sync processing failed for order %s: %s', result.get('order_number'), e)

    return result


def _sync_order_atomic(user, owner, data, offline_id):
    # Serialise concurrent sync requests from the same user so two simultaneous
    # pushes with the same offline_id cannot both pass the dedup check before
    # either has committed (TOCTOU fix — mirrors _place_order in orders.py).
    from django.contrib.auth import get_user_model as _gum
    _gum().objects.select_for_update(of=('self',)).get(pk=user.pk)

    # Route append-to-existing-order syncs to a dedicated handler.
    existing_order_id = data.get('existing_order_id')
    if existing_order_id:
        return _sync_order_append(user, owner, data, offline_id, int(existing_order_id))

    # Dedup check inside the transaction to prevent TOCTOU duplicate creation.
    if offline_id:
        existing = Order.objects.filter(
            ordered_by=user,
            special_instructions__contains=f'[offline:{offline_id}]',
        ).first()
        if existing:
            return {'status': 'duplicate', 'order_id': existing.id, 'order_number': existing.order_number}

    order_type = data.get('order_type', 'dine-in')
    is_remote = order_type in ('delivery', 'pickup')

    table_id = data.get('table_id')
    table = None
    if table_id:
        table = TableInfo.objects.filter(
            Q(owner=owner) | Q(restaurant__main_owner=owner) | Q(restaurant__branch_owner=owner),
            id=table_id,
        ).first()

    if table is None and not is_remote:
        return {'status': 'error', 'error': f'Table {table_id} not found.'}

    items = data.get('items', [])
    if not items:
        return {'status': 'error', 'error': 'No items provided.'}

    special = data.get('special_instructions', '')
    if offline_id:
        special = f'[offline:{offline_id}] {special}'.strip()

    total = sum(
        Decimal(str(i.get('unit_price') or i.get('price', 0))) * int(i.get('quantity', 1))
        for i in items
    )

    if table is not None:
        tax_rate = table.get_tax_rate()
    else:
        from restaurant.models_restaurant import Restaurant as _Restaurant
        _rq = Q(main_owner=owner) | Q(branch_owner=owner)
        _rid = data.get('restaurant_id') or 0
        _r = _Restaurant.objects.filter(_rq, id=_rid).first() or _Restaurant.objects.filter(_rq).first()
        tax_rate = Decimal(str(_r.tax_rate)) if _r and _r.tax_rate else Decimal('0')

    _dlat = data.get('delivery_lat')
    _dlng = data.get('delivery_lng')

    for _attempt in range(5):
        _on = f'ORD-{uuid.uuid4().hex[:8].upper()}'
        if not Order.objects.filter(order_number=_on).exists():
            break
    else:
        _on = f'ORD-{uuid.uuid4().hex[:12].upper()}'
    order = Order.objects.create(
        order_number=_on,
        table_info=table,
        ordered_by=user,
        status='pending',
        total_amount=total * (Decimal('1') + tax_rate),
        special_instructions=special,
        order_type=order_type,
        delivery_address=data.get('delivery_address', '') or '',
        delivery_phone=data.get('delivery_phone', '') or '',
        delivery_lat=Decimal(str(_dlat)) if _dlat is not None else None,
        delivery_lng=Decimal(str(_dlng)) if _dlng is not None else None,
    )

    dropped_items = []
    for i in items:
        try:
            qty = int(i.get('quantity', 1))
        except (TypeError, ValueError):
            qty = 1
        qty = max(1, min(qty, 100))
        product = Product.objects.select_for_update(of=('self',)).filter(
            Q(main_category__owner=owner) |
            Q(main_category__restaurant__main_owner=owner) |
            Q(main_category__restaurant__branch_owner=owner)
        ).filter(id=i['product_id']).first()
        if product is None:
            dropped_items.append(i.get('product_id'))  # Unknown product — skip, note drop
        elif not product.is_available:
            dropped_items.append(i.get('product_id'))  # Product unavailable — skip, note drop
        elif product.available_in_stock is not None and product.available_in_stock < qty:
            dropped_items.append(i.get('product_id'))  # Out of stock — skip, note drop
        else:
            fn = getattr(product, 'get_current_price', None)
            server_price = float(fn()) if fn else float(product.price)
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                unit_price=server_price,
            )
            if product.available_in_stock is not None:
                product.available_in_stock = max(0, product.available_in_stock - qty)
                product.save(update_fields=['available_in_stock'])

    # Reject order if no items were actually created (all product IDs were invalid).
    # Must release the table first — Order.save() called occupy_table() on creation,
    # and order.delete() does NOT call release_table(), leaving the table stuck as occupied.
    if not order.order_items.exists():
        order.release_table()
        order.delete()
        return {'status': 'error', 'error': 'No valid products found. Order was not placed.'}

    # Recalculate total from items that were actually created (excludes skipped products)
    actual_subtotal = sum(oi.get_subtotal() for oi in order.order_items.all())
    order.total_amount = actual_subtotal * (Decimal('1') + tax_rate)
    order.save(update_fields=['total_amount'])

    if table is not None:
        table.is_available = False
        table.save(update_fields=['is_available'])

    result = {'status': 'created', 'order_id': order.id, 'order_number': order.order_number}
    if dropped_items:
        result['warning'] = f'{len(dropped_items)} item(s) were unavailable and removed from the order.'
        result['dropped_item_ids'] = dropped_items
    return result


def _sync_order_append(user, owner, data, offline_id, existing_order_id):
    """
    Append items to an existing order that was synced while the device was offline.
    Called by _sync_order_atomic when existing_order_id is present in the payload.
    """
    dedup_tag = f'[offline-append:{offline_id}]'

    # Dedup: if this append was already applied, the tag will be in the order's notes.
    already = Order.objects.filter(
        id=existing_order_id,
        special_instructions__contains=dedup_tag,
    ).first()
    if already:
        return {'status': 'duplicate', 'order_id': already.id, 'order_number': already.order_number}

    # Find the target order — must belong to this restaurant.
    # Q(ordered_by__owner=owner) covers delivery/pickup orders where table_info is None.
    order = Order.objects.select_for_update().filter(
        Q(ordered_by__owner=owner) | Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner),
        id=existing_order_id,
    ).first()
    if not order:
        return {'status': 'error', 'error': f'Order #{existing_order_id} not found.'}
    if order.status in ('cancelled', 'closed'):
        return {'status': 'error', 'error': f'Order #{order.order_number} is already {order.status}.'}

    items = data.get('items', [])
    if not items:
        return {'status': 'error', 'error': 'No items provided.'}

    new_items = []
    for i in items:
        try:
            qty = max(1, min(int(i.get('quantity', 1)), 100))
        except (TypeError, ValueError):
            qty = 1
        product = Product.objects.select_for_update(of=('self',)).filter(
            Q(main_category__owner=owner) |
            Q(main_category__restaurant__main_owner=owner) |
            Q(main_category__restaurant__branch_owner=owner),
            id=i.get('product_id'),
            is_available=True,
        ).first()
        if product:
            fn = getattr(product, 'get_current_price', None)
            unit_price = float(fn()) if fn else float(product.price)
            oi = OrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                unit_price=unit_price,
            )
            new_items.append(oi)
            if product.available_in_stock is not None:
                product.available_in_stock = max(0, product.available_in_stock - qty)
                product.save(update_fields=['available_in_stock'])

    if not new_items:
        return {'status': 'error', 'error': 'No valid products found — items could not be added.'}

    # Recalculate total — use table tax rate when available, otherwise reverse-calculate
    # the effective rate from the existing total/subtotal so delivery/pickup orders
    # don't lose their tax when items are appended offline.
    all_items = list(order.order_items.all())
    actual_subtotal = sum(oi.get_subtotal() for oi in all_items)
    if order.table_info:
        tax_rate = order.table_info.get_tax_rate()
    else:
        orig_subtotal = sum(
            oi.get_subtotal() for oi in all_items if oi not in new_items
        )
        tax_rate = (
            (Decimal(str(order.total_amount)) / Decimal(str(orig_subtotal)) - Decimal('1'))
            if orig_subtotal else Decimal('0')
        )
    order.total_amount = actual_subtotal * (Decimal('1') + tax_rate)
    # Stamp the dedup tag so a retry push doesn't double-add the same items.
    order.special_instructions = ((order.special_instructions or '').rstrip() + f' {dedup_tag}').strip()
    order.save(update_fields=['total_amount', 'special_instructions'])

    # Server-side KOT/BOT for the newly added items (same as the online add-items flow).
    request_local_print = bool(data.get('local_print'))
    if not request_local_print:
        try:
            from orders.printing import auto_print_new_items
            auto_print_new_items(order, new_items)
        except Exception:
            pass

    return {'status': 'created', 'order_id': order.id, 'order_number': order.order_number}


def _sync_payment(user, owner, data):
    # Customers cannot create payment records — only cashiers/owners/managers may.
    # This mirrors the guard on the direct payments endpoint (_is_payment_staff).
    is_privileged = (
        user.is_cashier() or user.is_owner() or user.is_main_owner()
        or user.is_branch_owner() or user.is_manager()
    )
    if not is_privileged and not user.is_customer_care():
        return {'status': 'error', 'error': 'Only staff can process payments.'}

    offline_id = data.get('offline_id', '').strip()

    order_id = data.get('order_id')
    order_number = data.get('order_number', '')
    # Build the base lookup — privileged staff can process payments for any order
    # at their restaurant; customers/CC are restricted to orders they placed themselves.
    # Use dual-FK filter to cover both legacy (owner FK) and PRO-plan (restaurant FK) tables.
    restaurant_q = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
    )
    if not is_privileged:
        restaurant_q = restaurant_q & Q(ordered_by=user)
    # order_id may be None when the client only knows the order_number (offline order
    # synced in the same cycle but whose server ID wasn't resolved yet).  get(id=None)
    # raises ValueError (not DoesNotExist), so we catch both.
    try:
        order = Order.objects.filter(restaurant_q, id=order_id).distinct().get()
    except (Order.DoesNotExist, Order.MultipleObjectsReturned, ValueError):
        try:
            order = Order.objects.filter(restaurant_q, order_number=order_number).distinct().get()
        except (Order.DoesNotExist, Order.MultipleObjectsReturned):
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

    from django.db.models import Sum as _Sum2, Sum
    with transaction.atomic():
        # Lock the order row first, then dedup-check — this serialises concurrent
        # sync pushes so only one can create a payment for a given offline_id.
        order = Order.objects.select_for_update().get(pk=order.pk)
        if offline_id:
            existing = Payment.objects.filter(notes__contains=f'[offline:{offline_id}]', processed_by=user).first()
            if existing:
                return {'status': 'duplicate', 'payment_id': existing.id}
        if order.status == 'cancelled':
            return {'status': 'error', 'error': 'Cannot process payment for a cancelled order.'}
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
    # Wrap in a transaction with select_for_update so two simultaneous offline
    # syncs from the same table cannot both pass the exists() check.
    from django.db import transaction as _tx
    with _tx.atomic():
        existing = BillRequest.objects.select_for_update().filter(table_info=table, status='pending').first()
        if existing:
            return {'status': 'duplicate', 'bill_request_id': existing.id}
        br = BillRequest.objects.create(table_info=table, requested_by=user, status='pending')

    # Notify restaurant staff via WebSocket so they see the bill request in real-time.
    # Deferred via on_commit so the WS send happens after the ATOMIC_REQUESTS
    # transaction closes — avoids corrupting the DB connection with async_to_sync.
    def _notify():
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            from django.utils.timezone import now as _now
            ch = get_channel_layer()
            if ch and table.owner_id:
                async_to_sync(ch.group_send)(
                    f'restaurant_{table.owner_id}',
                    {
                        'type': 'bill_request',
                        'table_number': str(table.tbl_no),
                        'bill_request_id': br.id,
                        'message': f'Bill requested at Table {table.tbl_no}',
                        'timestamp': _now().isoformat(),
                    },
                )
        except Exception as _e:
            logger.warning('WS notify failed for synced bill_request: %s', _e)
    transaction.on_commit(_notify)

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
        'subcategories__products'
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
        Q(table_info__restaurant__branch_owner=owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
    )
    orders_qs = Order.objects.filter(
        order_table_q,
        status__in=['pending', 'confirmed', 'preparing', 'ready', 'served', 'out_for_delivery', 'delivered'],
        payment_status__in=['unpaid', 'partial'],
    ).distinct().select_related('table_info', 'ordered_by').prefetch_related('order_items__product', 'payments')

    if user.is_customer() or user.is_customer_care():
        orders_qs = orders_qs.filter(ordered_by=user)

    # Bill requests are always dine-in (require a table), so use the table-only filter.
    bill_table_q = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    pending_brs = []
    if not user.is_customer():
        br_qs = BillRequest.objects.filter(
            bill_table_q, status='pending',
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
