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
from django.db.models import Q, Prefetch
from django.utils import timezone

from orders.models import Order, OrderItem, BillRequest
from restaurant.models import TableInfo, Product, MainCategory, SubCategory
from cashier.models import Payment
from ..serializers import (
    CategorySerializer, TableSerializer, OrderSerializer,
    BillRequestSerializer, SyncPushSerializer, MAX_ORDER_ITEMS,
)
from .helpers import get_restaurant_owner, client_supports_delivery_fee
from .orders import (
    _notify_ws, customer_order_throttle_wait, ORDER_THROTTLED_MESSAGE, safe_client_id,
)
from accounts.security_utils import sanitize_special_instructions, sanitize_notes
from restaurant_system.db_utils import managed_owner_ids

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

    # If the mobile app signals local-print via HTTP header (online path convention),
    # propagate it into every order item so _sync_order/_sync_order_append don't
    # double-print when the app is also printing via Bluetooth.
    _header_local_print = request.META.get('HTTP_X_LOCAL_PRINT') == 'true'
    _fee_supported = client_supports_delivery_fee(request)
    # The restaurant a customer selected (X-Restaurant-ID), used to keep their offline
    # orders inside that one restaurant — same as customer_restaurant_q online.
    _customer_rid = _request_restaurant_id(request) if request.user.is_customer() else None

    for item in data.get('orders', []):
        if _header_local_print:
            item['local_print'] = True
        item['_fee_supported'] = _fee_supported  # server-set; never trust a client value
        item['_customer_rid'] = _customer_rid    # server-set; never trust a client value
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


def _request_restaurant_id(request):
    """Restaurant.id the request is scoped to (same lookup as customer_restaurant_q)."""
    rid = (
        request.headers.get('X-Restaurant-ID')
        or request.GET.get('restaurant_id')
        or (request.data.get('restaurant_id') if hasattr(request, 'data') else None)
    )
    try:
        return int(rid)
    except (TypeError, ValueError):
        return None


def _sync_order(user, owner, data):
    if not user.is_customer() and not user.has_feature('place_orders'):
        return {'status': 'error', 'error': 'Access denied.'}
    offline_id = safe_client_id(data.get('offline_id', ''))

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
    if not offline_id:
        logger.warning('sync_order: missing offline_id for user=%s — duplicate detection disabled for this push', user.pk)
    if offline_id:
        existing = Order.objects.filter(
            ordered_by=user,
            special_instructions__contains=f'[offline:{offline_id}]',
        ).first()
        if existing:
            return {'status': 'duplicate', 'order_id': existing.id, 'order_number': existing.order_number}

    items = data.get('items', [])
    if not items or not isinstance(items, list):
        return {'status': 'error', 'error': 'No items provided.'}
    if len(items) > MAX_ORDER_ITEMS:
        return {'status': 'error', 'error': f'Too many items in one order (maximum {MAX_ORDER_ITEMS}).'}

    # Same per-customer order-flood guard as the online POST /orders/ (staff never throttled).
    # After the dedup check, so re-pushing an order that already synced never counts.
    if user.is_customer() and customer_order_throttle_wait(user) is not None:
        return {'status': 'error', 'error': ORDER_THROTTLED_MESSAGE}

    order_type = data.get('order_type', 'dine-in')
    is_remote = order_type in ('delivery', 'pickup')

    # Customers are limited to the one restaurant they selected (a main owner is also
    # main_owner of every branch, so owner filters alone would mix branch menus in).
    # Mirrors customer_restaurant_q in the online _place_order.
    _table_q = Q(owner=owner) | Q(restaurant__main_owner=owner) | Q(restaurant__branch_owner=owner)
    _product_q = (
        Q(main_category__owner=owner) |
        Q(main_category__restaurant__main_owner=owner) |
        Q(main_category__restaurant__branch_owner=owner)
    )
    _cust_rid = None
    if user.is_customer():
        _cust_rid = data.get('_customer_rid')
        if not _cust_rid:
            try:
                _cust_rid = int(data.get('restaurant_id') or 0) or None
            except (TypeError, ValueError):
                _cust_rid = None
        if _cust_rid:
            _table_q &= Q(restaurant_id=_cust_rid) | Q(restaurant__isnull=True, owner=owner)
            _product_q &= (
                Q(main_category__restaurant_id=_cust_rid) |
                Q(main_category__restaurant__isnull=True, main_category__owner=owner)
            )

    table_id = data.get('table_id')
    table = None
    if table_id:
        table = TableInfo.objects.filter(_table_q, id=table_id).first()

    if table is None and not is_remote:
        return {'status': 'error', 'error': f'Table {table_id} not found.'}

    # Lock the table row so two different users syncing the same table simultaneously
    # cannot both pass validation and create duplicate orders.
    if table is not None:
        table = TableInfo.objects.select_for_update(of=('self',)).get(pk=table.pk)

    # Same sanitising and 500-character cap as the online _place_order.
    special = sanitize_special_instructions(data.get('special_instructions', '') or '')
    if offline_id:
        special = f'[offline:{offline_id}] {special}'.strip()

    total = sum(
        Decimal(str(i.get('unit_price') or i.get('price', 0))) * int(i.get('quantity', 1))
        for i in items
    )

    _r = None
    if table is not None:
        tax_rate = table.get_tax_rate()
    else:
        from restaurant.models_restaurant import Restaurant as _Restaurant
        _rq = Q(main_owner=owner) | Q(branch_owner=owner)
        try:
            _rid = int(_cust_rid or data.get('restaurant_id') or 0)
        except (TypeError, ValueError):
            _rid = 0
        _r = (_Restaurant.objects.filter(_rq, id=_rid).first() if _rid else None) or _Restaurant.for_owner(owner)
        tax_rate = Decimal(str(_r.tax_rate)) if _r and _r.tax_rate else Decimal('0')

    # Same customer checks as the online _place_order, before anything is written.
    if user.is_customer() and is_remote:
        _remote_rest = _r or (table.restaurant if table is not None else None)
        if not _remote_rest or not _remote_rest.allow_remote_orders:
            return {'status': 'error', 'error': 'This restaurant is not accepting delivery or pickup orders.'}
        if order_type == 'delivery' and not (data.get('delivery_phone') or '').strip():
            return {'status': 'error', 'error': 'A phone number is required for delivery orders.'}

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
        restaurant_owner=owner if table is None else None,
        delivery_address=data.get('delivery_address', '') or '',
        delivery_phone=data.get('delivery_phone', '') or '',
        delivery_lat=Decimal(str(_dlat)) if _dlat is not None else None,
        delivery_lng=Decimal(str(_dlng)) if _dlng is not None else None,
    )

    dropped_items = []
    price_changes = []  # server price always wins; the app is told what changed
    for i in items:
        try:
            qty = int(i.get('quantity', 1))
        except (TypeError, ValueError):
            qty = 1
        qty = max(1, min(qty, 100))
        pid = i.get('product_id')
        if not pid:
            dropped_items.append(None)
            continue
        product = Product.objects.select_for_update(of=('self',)).filter(_product_q).filter(id=pid).first()
        if product is None:
            dropped_items.append(pid)  # Unknown / other restaurant's product — skip, note drop
        elif not product.is_available:
            dropped_items.append(pid)  # Product unavailable — skip, note drop
        elif False:  # stock gate removed — negative stock allowed
            dropped_items.append(pid)  # Out of stock — skip, note drop
        else:
            fn = getattr(product, 'get_current_price', None)
            server_price = float(fn()) if fn else float(product.price)
            _note_price_change(price_changes, product, i, server_price)
            _line = OrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                unit_price=server_price,
            )
            from orders.stock import take_for_item
            take_for_item(_line)               # stock never below 0; the line records what it took

    # Reject order if no items were actually created (all product IDs were invalid).
    # Must release the table first — Order.save() called occupy_table() on creation,
    # and order.delete() does NOT call release_table(), leaving the table stuck as occupied.
    if not order.order_items.exists():
        order.release_table()
        order.delete()
        return {'status': 'error', 'error': 'No valid products found. Order was not placed.'}

    # Recalculate total from items that were actually created (excludes skipped products)
    actual_subtotal = sum(oi.get_subtotal() for oi in order.order_items.all())
    # Old staff app builds took this order (and maybe the money) at a total without a fee.
    _charge_fee = data.get('_fee_supported', True) or user.is_customer()
    if order_type == 'delivery' and _charge_fee:
        _fee_rest = _r if table is None else table.restaurant
        if _fee_rest is not None:
            order.delivery_fee, order.delivery_fee_taxed = _fee_rest.delivery_fee_for(actual_subtotal)
    order.total_amount = order.total_for_subtotal(actual_subtotal, tax_rate)
    order.save(update_fields=['total_amount', 'delivery_fee', 'delivery_fee_taxed'])

    if table is not None:
        table.is_available = False
        table.save(update_fields=['is_available'])

    # If the order was cancelled offline before being synced, cancel it immediately
    order_status = data.get('status', 'pending')
    if order_status == 'cancelled':
        from orders.stock import give_back
        for item in order.order_items.select_related('product'):
            give_back(item)                    # exactly what this line took (stock never below 0)
        order.status = 'cancelled'
        order.reason_if_cancelled = data.get('cancel_reason', 'Cancelled offline')
        order.save(update_fields=['status', 'reason_if_cancelled'])
        order.release_table()  # the table was occupied above; a cancelled order frees it

    result = {'status': 'created', 'order_id': order.id, 'order_number': order.order_number,
              'total_amount': str(order.total_amount)}
    _add_change_warnings(result, dropped_items, price_changes)
    return result


def _note_price_change(price_changes, product, item, server_price):
    """Record a line whose offline (client) price differs from the server price used."""
    raw = item.get('unit_price') or item.get('price')
    try:
        client_price = float(raw) if raw not in (None, '') else None
    except (TypeError, ValueError):
        client_price = None
    if client_price is not None and abs(client_price - server_price) > 0.005:
        price_changes.append({'product_id': product.id, 'name': product.name,
                              'client_price': client_price, 'server_price': server_price})


def _add_change_warnings(result, dropped_items, price_changes):
    """Tell the app what differs from what the cashier saw offline (old apps ignore it)."""
    parts = []
    if dropped_items:
        parts.append(f'{len(dropped_items)} item(s) were unavailable and removed from the order.')
        result['dropped_item_ids'] = dropped_items
    if price_changes:
        parts.append(f'{len(price_changes)} item price(s) changed since the order was taken offline.')
        result['price_changes'] = price_changes
    if parts:
        result['warning'] = ' '.join(parts)


def _sync_order_append(user, owner, data, offline_id, existing_order_id):
    """
    Append items to an existing order that was synced while the device was offline.
    Called by _sync_order_atomic when existing_order_id is present in the payload.
    """
    dedup_tag = f'[offline-append:{offline_id}]'

    # Who may append: exactly the online add_items_to_order rule (orders.py).
    # The place_orders feature is already checked by _sync_order for non-customers.
    is_staff = (user.is_customer_care() or user.is_cashier() or
                user.is_owner() or user.is_main_owner() or
                user.is_branch_owner() or user.is_manager())
    if not (is_staff or user.is_customer()):
        return {'status': 'error', 'error': 'Access denied.'}

    # Find the target order — must belong to this restaurant.
    # Q(ordered_by__owner=owner) covers delivery/pickup orders where table_info is None.
    order = Order.objects.select_for_update(of=('self',)).filter(
        Q(ordered_by__owner=owner) | Q(restaurant_owner=owner) | Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner),
        id=existing_order_id,
    ).first()
    if not order or (user.is_customer() and order.ordered_by_id != user.id):
        return {'status': 'error', 'error': f'Order #{existing_order_id} not found.'}
    # CC staff can only add to their own orders (same rule and message as online add-items).
    if user.is_customer_care() and order.ordered_by_id != user.id:
        return {'status': 'error', 'error': 'Access denied.'}
    # Dedup (checked under the row lock): if this append was already applied, the tag is
    # in the order's notes — also covers an online add-items with the same client_id.
    if dedup_tag in (order.special_instructions or ''):
        return {'status': 'duplicate', 'order_id': order.id, 'order_number': order.order_number}
    TERMINAL_STATUSES = {'cancelled', 'delivered', 'customer_refused', 'kitchen_error', 'quality_issue', 'wasted', 'out_for_delivery'}
    if order.status in TERMINAL_STATUSES:
        return {'status': 'error', 'error': f'Cannot add items to an order with status {order.status}.'}
    if order.payment_status == 'paid':
        return {'status': 'error', 'error': 'Cannot add items to a fully paid order.'}

    items = data.get('items', [])
    if not items or not isinstance(items, list):
        return {'status': 'error', 'error': 'No items provided.'}
    if len(items) > MAX_ORDER_ITEMS:
        return {'status': 'error', 'error': f'Too many items in one order (maximum {MAX_ORDER_ITEMS}).'}

    # Product scope, same as online add-items: the restaurant's menu; for a customer only
    # the restaurant they selected, and a customer's delivery/pickup order (no table) only
    # takes more of the products already in it.
    _append_pq = (
        Q(main_category__owner=owner) |
        Q(main_category__restaurant__main_owner=owner) |
        Q(main_category__restaurant__branch_owner=owner)
    )
    if user.is_customer():
        if order.table_info_id is None:
            _append_pq &= Q(id__in=list(order.order_items.values_list('product_id', flat=True)))
        else:
            _cust_rid = data.get('_customer_rid')
            if _cust_rid:
                _append_pq &= (
                    Q(main_category__restaurant_id=_cust_rid) |
                    Q(main_category__restaurant__isnull=True, main_category__owner=owner)
                )

    new_items = []
    dropped_items = []
    price_changes = []
    for i in items:
        try:
            qty = max(1, min(int(i.get('quantity', 1)), 100))
        except (TypeError, ValueError):
            qty = 1
        product = Product.objects.select_for_update(of=('self',)).filter(
            _append_pq,
            id=i.get('product_id'),
            is_available=True,
        ).first()
        if not product:
            dropped_items.append(i.get('product_id'))
        if product:
            fn = getattr(product, 'get_current_price', None)
            unit_price = float(fn()) if fn else float(product.price)
            _note_price_change(price_changes, product, i, unit_price)
            oi = OrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                unit_price=unit_price,
            )
            new_items.append(oi)
            from orders.stock import take_for_item
            take_for_item(oi)                  # stock never below 0; the line records what it took

    if not new_items:
        return {'status': 'error', 'error': 'No valid products found — items could not be added.'}

    # Recalculate total at the rate this order was CHARGED (every order type, same rule as the
    # online add-items): today's restaurant rate may have changed since the order was placed.
    all_items = list(order.order_items.all())
    actual_subtotal = sum(oi.get_subtotal() for oi in all_items)
    orig_subtotal = sum(
        oi.get_subtotal() for oi in all_items if oi not in new_items
    )
    tax_rate = order.charged_tax_rate(orig_subtotal)  # excludes the delivery fee
    order.total_amount = order.total_for_subtotal(actual_subtotal, tax_rate)
    # Extra notes sent with the append: sanitised and capped like online add-items.
    extra_notes = sanitize_special_instructions((data.get('special_instructions', '') or '').strip())
    if extra_notes:
        order.special_instructions = ((order.special_instructions or '') + '\n' + extra_notes).strip()
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

    result = {'status': 'created', 'order_id': order.id, 'order_number': order.order_number,
              'total_amount': str(order.total_amount)}
    _add_change_warnings(result, dropped_items, price_changes)
    return result


def _capped_message(capped):
    # Worded so nobody refunds before checking: the difference may be items still syncing.
    return (f'Offline payment {capped["amount_requested"]} recorded as {capped["amount_recorded"]} — '
            f'order total changed at sync. Check the order before settling the '
            f'{capped["difference"]} difference with the customer.')


def _sync_payment(user, owner, data):
    if not user.has_feature('process_payments'):
        return {'status': 'error', 'error': 'Access denied.'}
    # Customers cannot create payment records — only cashiers/owners/managers may.
    # This mirrors the guard on the direct payments endpoint (_is_payment_staff).
    is_privileged = (
        user.is_cashier() or user.is_owner() or user.is_main_owner()
        or user.is_branch_owner() or user.is_manager()
    )
    if not is_privileged and not user.is_customer_care():
        return {'status': 'error', 'error': 'Only staff can process payments.'}

    offline_id = safe_client_id(data.get('offline_id', ''))

    order_id = data.get('order_id')
    order_number = data.get('order_number', '')
    # Build the base lookup — privileged staff can process payments for any order
    # at their restaurant; customers/CC are restricted to orders they placed themselves.
    # Use dual-FK filter to cover both legacy (owner FK) and PRO-plan (restaurant FK) tables.
    restaurant_q = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner) |
        (Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) | Q(order_type__in=['delivery', 'pickup'], restaurant_owner=owner)) |
        (Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=managed_owner_ids(owner)) | Q(order_type__in=['delivery', 'pickup'], restaurant_owner__in=managed_owner_ids(owner)))
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
            # Third fallback: order was created in the same sync push so the client
            # only knows its offline_id — look up by the dedup tag in special_instructions.
            order_offline_id = safe_client_id(data.get('order_offline_id', ''))
            if order_offline_id:
                _tag = f'[offline:{order_offline_id}]'
                try:
                    order = Order.objects.filter(
                        restaurant_q,
                        special_instructions__contains=_tag,
                    ).distinct().get()
                except (Order.DoesNotExist, Order.MultipleObjectsReturned):
                    return {'status': 'error', 'error': f'Order {order_id} not found.'}
            else:
                return {'status': 'error', 'error': f'Order {order_id} not found.'}
    # CC staff can only pay for their own orders (same constraint as regular payments endpoint).
    if user.is_customer_care() and order.ordered_by != user:
        return {'status': 'error', 'error': 'Access denied.'}

    notes = sanitize_notes(data.get('notes', '') or '')
    if offline_id:
        notes = f'[offline:{offline_id}] {notes}'.strip()

    amount = Decimal(str(data.get('amount', 0)))
    if amount <= 0:
        return {'status': 'error', 'error': 'Payment amount must be positive.'}

    _valid_methods = {'cash', 'card', 'digital', 'voucher'}
    payment_method = data.get('payment_method', 'cash')
    if payment_method not in _valid_methods:
        return {'status': 'error', 'error': f'Invalid payment method. Allowed: {", ".join(sorted(_valid_methods))}'}

    from django.db.models import Sum as _Sum2, Sum
    with transaction.atomic():
        # Lock the order row first, then dedup-check — this serialises concurrent
        # sync pushes so only one can create a payment for a given offline_id.
        order = Order.objects.select_for_update(of=('self',)).get(pk=order.pk)
        if offline_id:
            existing = Payment.objects.filter(notes__contains=f'[offline:{offline_id}]', processed_by=user).first()
            if existing:
                return {'status': 'duplicate', 'payment_id': existing.id}
        PAYMENT_BLOCKED_STATUSES = {'cancelled', 'customer_refused', 'kitchen_error', 'quality_issue', 'wasted'}
        if order.status in PAYMENT_BLOCKED_STATUSES:
            return {'status': 'error', 'error': f'Cannot process payment for a {order.status} order.'}
        already_paid = order.payments.filter(is_voided=False).aggregate(t=_Sum2('amount'))['t'] or Decimal('0.00')
        remaining = order.total_amount - already_paid
        capped = None
        if amount > remaining:
            # Money taken offline against the total the phone showed. If the order total
            # changed at sync (price change, item unavailable, edit on the web) it no longer
            # fits: refusing would retry forever and the cash would never be recorded.
            # Record what is still owed and flag the difference for the cashier to settle.
            # Only for real offline payments (offline_id); nothing is owed → still refused.
            if offline_id and remaining <= 0 and data.get('accepts_not_recorded'):
                # Money taken offline for an order that is already fully paid (e.g. a second
                # offline payment after the first was capped, or paid online meanwhile).
                # Nothing can be recorded; tell the app once so it stops retrying.
                # Builds that do not send accepts_not_recorded keep the old 'error' shape:
                # they would treat an unknown status as an error anyway.
                return {
                    'status': 'not_recorded', 'order_id': order.id, 'order_number': order.order_number,
                    'amount_requested': str(amount),
                    'warning': (f'Offline payment {amount} could not be recorded: the order was already '
                                f'fully paid — settle/refund with the customer.'),
                }
            if not offline_id or remaining <= 0:
                return {'status': 'error', 'error': f'Payment amount ({amount}) exceeds remaining balance ({remaining}).'}
            capped = {'amount_requested': amount, 'amount_recorded': remaining, 'difference': amount - remaining}
            notes = (f'{notes} {_capped_message(capped)}').strip()
            amount = remaining

        payment = Payment.objects.create(
            order=order,
            amount=amount,
            payment_method=payment_method,
            processed_by=user,
            # Payment.reference_number is 50 chars: longer would fail on PostgreSQL and the
            # sale would be retried forever.
            reference_number=(sanitize_notes(str(data.get('reference_number') or '')) or '')[:50],
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

    result = {'status': 'created', 'payment_id': payment.id}
    if capped:
        logger.warning('Offline payment %s capped at sync: order %s requested %s recorded %s',
                       offline_id, order.order_number, capped['amount_requested'], capped['amount_recorded'])
        result.update({
            'order_id': order.id,
            'order_number': order.order_number,
            'amount_requested': str(capped['amount_requested']),
            'amount_recorded': str(capped['amount_recorded']),
            'difference': str(capped['difference']),
            'warning': _capped_message(capped),
        })
    return result


def _sync_bill_request(user, owner, data):
    if not user.is_customer() and not user.has_feature('request_bill'):
        return {'status': 'error', 'error': 'Access denied.'}
    table_id = data.get('table_id')
    table = TableInfo.objects.filter(
        Q(owner=owner) | Q(restaurant__main_owner=owner) | Q(restaurant__branch_owner=owner),
        id=table_id,
    ).first()
    if table is None:
        return {'status': 'error', 'error': f'Table {table_id} not found.'}

    # Mirror _create_bill_request: verify there is an active unpaid order at the table.
    from orders.models import Order as _Order
    if user.is_customer():
        # Customer: must have their own order at the table
        has_active_order = _Order.objects.filter(
            table_info=table,
            ordered_by=user,
            status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
            payment_status__in=['unpaid', 'partial'],
        ).exists()
        if not has_active_order:
            already_paid = _Order.objects.filter(
                table_info=table,
                ordered_by=user,
                payment_status='paid',
            ).exists()
            if already_paid:
                return {'status': 'already_paid', 'message': 'Order at this table is already paid.'}
            return {'status': 'error', 'error': 'You do not have an active order at this table.'}
    else:
        # Staff (cashier, waiter, etc.): check that any active order exists at the table
        has_active_order = _Order.objects.filter(
            table_info=table,
            status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
            payment_status__in=['unpaid', 'partial'],
        ).exists()
        if not has_active_order:
            # If the order was already paid in the same sync cycle (payment processed
            # first in sync_push), treat this as a no-op rather than an error so
            # the client doesn't show a confusing failure message.
            already_paid = _Order.objects.filter(
                table_info=table,
                status__in=['pending', 'confirmed', 'preparing', 'ready', 'served',
                            'out_for_delivery', 'delivered'],
                payment_status='paid',
            ).exists()
            if already_paid:
                return {'status': 'already_paid', 'message': 'Order at this table is already paid.'}
            return {'status': 'error', 'error': 'No active order at this table.'}

    # Prevent duplicate pending bill requests — mirrors _create_bill_request.
    # Wrap in a transaction with select_for_update so two simultaneous offline
    # syncs from the same table cannot both pass the exists() check.
    from django.db import transaction as _tx
    with _tx.atomic():
        existing = BillRequest.objects.select_for_update(of=('self',)).filter(table_info=table, status='pending').first()
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
    categories = MainCategory.objects.filter(_cat_q, is_active=True).distinct().prefetch_related(
        Prefetch(
            'subcategories',
            queryset=SubCategory.objects.filter(is_active=True).prefetch_related(
                Prefetch('products', queryset=Product.objects.filter(is_available=True).select_related(
                        'main_category__restaurant__main_owner', 'main_category__restaurant__branch_owner',
                        'main_category__owner', 'sub_category',
                    ), to_attr='_available_products')
            ),
            to_attr='_active_subs',
        ),
    ).order_by('name')

    pull_table_q = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )
    tables = TableInfo.objects.filter(pull_table_q).distinct().order_by('tbl_no').prefetch_related(
        Prefetch(
            'orders',
            queryset=Order.objects.filter(
                status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
                payment_status__in=['unpaid', 'partial'],
            ),
            to_attr='_active_orders_prefetch',
        )
    )

    order_table_q = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner) |
        (Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) | Q(order_type__in=['delivery', 'pickup'], restaurant_owner=owner)) |
        (Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=managed_owner_ids(owner)) | Q(order_type__in=['delivery', 'pickup'], restaurant_owner__in=managed_owner_ids(owner))) |
        # Self-registered customers (owner=None) — their delivery/pickup orders have no owner FK
        Q(order_type__in=['delivery', 'pickup'], ordered_by=user, ordered_by__owner__isnull=True)
    )
    orders_qs = Order.objects.filter(
        order_table_q,
        status__in=['pending', 'confirmed', 'preparing', 'ready', 'served', 'out_for_delivery', 'delivered'],
        payment_status__in=['unpaid', 'partial'],
    ).distinct().select_related('table_info', 'ordered_by').prefetch_related(
        'order_items__product', 'payments', 'table_info__bill_requests',
    )

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
