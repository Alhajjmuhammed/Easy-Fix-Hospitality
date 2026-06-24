import uuid
import logging
import threading
import urllib.request
import json as _json
from datetime import timedelta

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from orders.models import Order, OrderItem
from restaurant.models import TableInfo, Product
from ..serializers import OrderSerializer, PlaceOrderSerializer
from .helpers import get_restaurant_owner
from accounts.security_utils import sanitize_special_instructions

logger = logging.getLogger(__name__)


def _notify_ws(order, updated_by_user, event_type='order_status_update'):
    """
    Schedule real-time WebSocket notifications to fire AFTER the current transaction
    commits, using transaction.on_commit().

    WHY on_commit(): production_settings.py sets ATOMIC_REQUESTS=True, which wraps
    every HTTP request in a PostgreSQL transaction.  Calling async_to_sync() (used by
    channel_layer.group_send) inside an open PostgreSQL transaction corrupts the DB
    connection and causes a 500.  on_commit() defers the async call until after the
    outermost transaction commits, so it never runs inside a transaction.
    If there is no active transaction on_commit() fires the callback immediately.

    All ORM values are captured NOW (before the callback) so the closure is a pure
    data snapshot with no further DB access.
    """
    # ── Capture all data now, before handing off to on_commit ────────────────
    _order_id       = order.id
    _order_number   = order.order_number
    _owner_id       = order.table_info.owner_id if order.table_info else None
    _table_no       = str(order.table_info.tbl_no) if order.table_info else 'N/A'
    _status         = order.status
    _status_display = order.get_status_display()
    _items_count    = order.order_items.count()
    _total          = str(order.total_amount)
    _customer_name  = (
        order.ordered_by.get_full_name() or order.ordered_by.username
        if order.ordered_by else 'Unknown'
    )
    _actor          = updated_by_user.get_full_name() or updated_by_user.username
    _ts             = timezone.now().isoformat()
    _event_type     = event_type

    def _send():
        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                return

            if _event_type == 'new_order':
                async_to_sync(channel_layer.group_send)(
                    f'restaurant_{_owner_id}',
                    {
                        'type': 'new_order',
                        'order_id': str(_order_id),
                        'order_number': _order_number,
                        'table_number': _table_no,
                        'customer_name': _actor,
                        'items_count': _items_count,
                        'total_amount': _total,
                        'message': f'New order #{_order_number} from Table {_table_no}',
                        'timestamp': _ts,
                    }
                )
                async_to_sync(channel_layer.group_send)(
                    f'order_{_order_id}',
                    {
                        'type': 'order_status_update',
                        'order_id': str(_order_id),
                        'status': _status,
                        'status_display': _status_display,
                        'message': 'Order placed successfully!',
                        'updated_by': _actor,
                        'timestamp': _ts,
                    }
                )
            else:
                msg = f'Order {_order_number} updated to {_status_display}'
                async_to_sync(channel_layer.group_send)(
                    f'order_{_order_id}',
                    {
                        'type': 'order_status_update',
                        'order_id': str(_order_id),
                        'order_number': _order_number,
                        'status': _status,
                        'status_display': _status_display,
                        'message': msg,
                        'updated_by': _actor,
                        'timestamp': _ts,
                    }
                )
                async_to_sync(channel_layer.group_send)(
                    f'restaurant_{_owner_id}',
                    {
                        'type': 'order_status_update',
                        'order_id': str(_order_id),
                        'order_number': _order_number,
                        'status': _status,
                        'status_display': _status_display,
                        'customer': _customer_name,
                        'message': msg,
                        'updated_by': _actor,
                        'timestamp': _ts,
                    }
                )
        except Exception as e:
            logger.warning('WS notification failed (non-critical): %s', e)

    # Fire after the outermost transaction commits (or immediately if no transaction).
    transaction.on_commit(_send)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def orders(request):
    if request.method == 'GET':
        return _list_orders(request)
    return _place_order(request)


def _list_orders(request):
    """List orders filtered by role."""
    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    qs = Order.objects.filter(_tq).distinct().select_related('table_info', 'ordered_by').prefetch_related(
        'order_items__product', 'payments'
    )

    user = request.user
    # Customers and customer-care staff only see orders they placed themselves.
    # This matches the web behaviour and ensures CC staff cannot see/modify each other's orders.
    if user.is_customer() or user.is_customer_care():
        qs = qs.filter(ordered_by=user)

    # my_orders=true  → show only orders placed by the requesting user (cashier "My Orders")
    if request.GET.get('my_orders') == 'true':
        qs = qs.filter(ordered_by=user)

    # Period filter: today | week
    period = request.GET.get('period', '')
    if period == 'today':
        today = timezone.now().date()
        qs = qs.filter(created_at__date=today)
    elif period == 'week':
        week_start = timezone.now().date() - timedelta(days=timezone.now().weekday())
        qs = qs.filter(created_at__date__gte=week_start)

    # Payment status filter — supports comma-separated values (e.g. "unpaid,partial")
    payment_status = request.GET.get('payment_status', '')
    if payment_status:
        statuses = [s.strip() for s in payment_status.split(',') if s.strip()]
        if statuses:
            qs = qs.filter(payment_status__in=statuses)

    # Order status filter — supports comma-separated values (e.g. "pending,confirmed,preparing,ready")
    order_status = request.GET.get('status', '')
    if order_status:
        statuses = [s.strip() for s in order_status.split(',') if s.strip()]
        if statuses:
            qs = qs.filter(status__in=statuses)

    qs = qs.order_by('-created_at')[:100]
    return Response({'orders': OrderSerializer(qs, many=True, context={'request': request}).data})


def _place_order(request):
    """Create a new order. Supports offline de-duplication via offline_id."""
    s = PlaceOrderSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)

    data = s.validated_data
    user = request.user
    offline_id = data.get('offline_id', '').strip()

    # De-duplication: already synced?
    if offline_id:
        existing = Order.objects.filter(
            ordered_by=user,
            special_instructions__contains=f'[offline:{offline_id}]',
        ).first()
        if existing:
            return Response({
                'order': OrderSerializer(existing, context={'request': request}).data,
                'already_synced': True,
            })

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    order_type = data.get('order_type', 'dine-in')

    _tq_place = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )

    # Delivery and pickup orders do not require a table.
    # Dine-in orders (default) still require a valid table_id.
    table = None
    if order_type == 'dine-in':
        if not data.get('table_id'):
            return Response({'error': 'table_id is required for dine-in orders.'}, status=400)
        table = get_object_or_404(TableInfo.objects.filter(_tq_place).distinct(), id=data['table_id'])
    elif data.get('table_id'):
        # Optional table for delivery/pickup — ignore silently if provided
        table = TableInfo.objects.filter(_tq_place, id=data['table_id']).first()

    # For delivery/pickup get tax rate from the Restaurant model
    if table is None:
        from restaurant.models_restaurant import Restaurant as _Restaurant
        _rq = Q(main_owner=owner) | Q(branch_owner=owner)
        _rid = (
            request.headers.get('X-Restaurant-ID')
            or (request.data.get('restaurant_id') if hasattr(request, 'data') else None)
        )
        if _rid:
            try:
                _rq = _rq & Q(id=int(_rid))
            except (TypeError, ValueError):
                pass
        _rest_obj = _Restaurant.objects.filter(_rq).first()
        from decimal import Decimal as _D
        _delivery_tax_rate = _rest_obj.tax_rate if _rest_obj else getattr(owner, 'tax_rate', _D('0.08'))
    else:
        _delivery_tax_rate = None  # will use table.get_tax_rate() below

    # ── Phase 1: validate all items BEFORE opening the transaction ────────────
    # This ensures no return/error response happens inside the atomic block,
    # which would corrupt the PostgreSQL connection.
    pre_validated = []
    unavailable = []
    price_changes = []

    for item in data['items']:
        product_id = item.get('product_id')
        try:
            quantity = int(item.get('quantity', 1))
        except (TypeError, ValueError):
            return Response({'error': f'Invalid quantity for product {product_id}.'}, status=400)
        if quantity < 1 or quantity > 100:
            return Response(
                {'error': f'Quantity must be between 1 and 100 (got {quantity}).'},
                status=400,
            )
        client_price = float(item.get('price', 0))

        product = Product.objects.filter(
            Q(main_category__owner=owner) |
            Q(main_category__restaurant__main_owner=owner) |
            Q(main_category__restaurant__branch_owner=owner)
        ).filter(id=product_id).first()

        if product is None:
            return Response({'error': f'Product {product_id} not found.'}, status=400)

        if not product.is_available:
            unavailable.append({'product_id': product_id, 'name': product.name})
            continue

        if product.available_in_stock is not None and product.available_in_stock < quantity:
            return Response(
                {'error': f'Only {product.available_in_stock} of "{product.name}" left in stock.'},
                status=status.HTTP_409_CONFLICT,
            )

        fn = getattr(product, 'get_current_price', None)
        server_price = float(fn()) if fn else float(product.price)

        if abs(server_price - client_price) > 0.01:
            price_changes.append({
                'product_id': product_id,
                'name': product.name,
                'old_price': client_price,
                'new_price': server_price,
            })

        pre_validated.append({'product_id': product_id, 'quantity': quantity, 'unit_price': server_price})

    if unavailable:
        return Response(
            {'error': 'Some items are no longer available.', 'unavailable_items': unavailable},
            status=status.HTTP_409_CONFLICT,
        )
    if price_changes:
        return Response(
            {'error': 'Prices have changed since you loaded the menu.', 'price_changes': price_changes},
            status=status.HTTP_409_CONFLICT,
        )
    if not pre_validated:
        return Response({'error': 'No valid items to order.'}, status=400)

    # Build special instructions before the transaction.
    raw_special = data.get('special_instructions', '') or ''
    special = sanitize_special_instructions(raw_special)
    if offline_id:
        special = f'[offline:{offline_id}] {special}'.strip()

    order_number = f'ORD-{uuid.uuid4().hex[:8].upper()}'

    # ── Phase 2: DB writes inside atomic block (no return statements inside) ──
    # async_to_sync (used by _notify_ws) must NOT run inside a transaction on
    # PostgreSQL — it corrupts the connection. Keep only pure DB writes here.
    with transaction.atomic():
        validated_items = []
        for pv in pre_validated:
            # Re-fetch with row lock to prevent overselling under concurrent load
            product = Product.objects.select_for_update(of=('self',)).filter(
                Q(main_category__owner=owner) |
                Q(main_category__restaurant__main_owner=owner) |
                Q(main_category__restaurant__branch_owner=owner),
                id=pv['product_id'],
            ).first()
            if product is None or not product.is_available:
                continue
            # Re-check stock under lock
            if product.available_in_stock is not None and product.available_in_stock < pv['quantity']:
                continue
            validated_items.append({'product': product, 'quantity': pv['quantity'], 'unit_price': pv['unit_price']})

        if not validated_items:
            # All items became unavailable between validation and lock — safe to raise
            raise Exception('No valid items could be locked for order.')

        from decimal import Decimal as _Dec
        total_amount = sum(_Dec(str(i['unit_price'])) * _Dec(str(i['quantity'])) for i in validated_items)
        tax_rate = table.get_tax_rate() if table is not None else _delivery_tax_rate
        total_amount = total_amount * (_Dec('1') + tax_rate)

        order = Order.objects.create(
            order_number=order_number,
            table_info=table,
            ordered_by=user,
            status='pending',
            total_amount=total_amount,
            special_instructions=special,
            order_type=order_type,
            delivery_address=data.get('delivery_address', '') or '',
            delivery_phone=data.get('delivery_phone', '') or '',
        )

        for item in validated_items:
            OrderItem.objects.create(
                order=order,
                product=item['product'],
                quantity=item['quantity'],
                unit_price=item['unit_price'],
            )
            p = item['product']
            if p.available_in_stock is not None:
                p.available_in_stock = max(0, p.available_in_stock - item['quantity'])
                p.save(update_fields=['available_in_stock'])
        # Mark table unavailable only for dine-in orders
        if table is not None:
            table.is_available = False
            table.save(update_fields=['is_available'])
        # --- transaction commits here ---

    # ── Phase 3: outside transaction — WebSocket + print ─────────────────
    _notify_ws(order, user, event_type='new_order')

    # X-Local-Print: true means the mobile app is printing KOT/BOT itself
    # (Bluetooth or system dialog). Skip server queue to avoid orphan PrintJob
    # rows accumulating in the DB for restaurants without a Windows Print Client.
    # Default (header absent) = existing behaviour: server queue handles printing.
    if request.META.get('HTTP_X_LOCAL_PRINT') != 'true':
        try:
            from orders.printing import auto_print_order
            auto_print_order(order)
        except Exception as e:
            logger.warning('Auto-print failed for order %s: %s', order.order_number, e)

    logger.info('Mobile order created: %s by %s', order.order_number, user.username)

    return Response(
        {'order': OrderSerializer(order, context={'request': request}).data,
         'message': f'Order {order.order_number} placed successfully.'},
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def order_detail(request, order_id):
    """Retrieve a single order."""
    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    order = get_object_or_404(
        Order.objects.filter(_tq).distinct().select_related('table_info', 'ordered_by').prefetch_related(
            'order_items__product', 'payments'
        ),
        id=order_id,
    )

    user = request.user
    if (user.is_customer() or user.is_customer_care()) and order.ordered_by != user:
        return Response({'error': 'Access denied.'}, status=403)

    return Response({'order': OrderSerializer(order, context={'request': request}).data})


_PUSH_STATUS_MESSAGES = {
    'confirmed': ('Order Confirmed! ✅', 'Your order has been confirmed and will be prepared shortly.'),
    'preparing': ('Being Prepared 👨‍🍳', 'Your order is now being prepared!'),
    'ready':     ('Order Ready! 🍽️', 'Your order is ready and will be served shortly.'),
    'served':    ('Served! 🎉', 'Your order has been served. Enjoy your meal!'),
    'cancelled': ('Order Cancelled ❌', 'Your order has been cancelled.'),
}


def _send_expo_push(token, title, body, data=None):
    """Fire-and-forget Expo push notification using Python stdlib only."""
    try:
        payload = _json.dumps({
            'to': token,
            'title': title,
            'body': body,
            'data': data or {},
            'sound': 'default',
        }).encode('utf-8')
        req = urllib.request.Request(
            'https://exp.host/--/api/v2/push/send',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning('Expo push notification failed: %s', e)  # Best-effort — never block the order update


def _send_push_async(token, title, body, data=None):
    t = threading.Thread(target=_send_expo_push, args=(token, title, body, data))
    t.daemon = True
    t.start()


@api_view(['PATCH'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def update_order_status(request, order_id):
    """Update order status (staff only)."""
    user = request.user
    if not (user.is_cashier() or user.is_customer_care() or
            user.is_owner() or user.is_main_owner() or
            user.is_branch_owner() or user.is_manager()):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    order = get_object_or_404(
        Order.objects.filter(_tq).distinct().prefetch_related('order_items__product'),
        id=order_id,
    )
    new_status = request.data.get('status')
    valid = [s[0] for s in Order.STATUS_CHOICES]

    if new_status not in valid:
        return Response({'error': f'Invalid status. Valid values: {valid}'}, status=400)

    # Enforce directed status transition rules — mirrors web's update_order_status.
    valid_transitions = {
        'pending':   ['confirmed', 'cancelled'],
        'confirmed': ['preparing', 'cancelled'],
        'preparing': ['ready', 'cancelled'],
        'ready':     ['served', 'cancelled'],
        'served':    ['cancelled'],
        'cancelled': [],
    }
    # Owners, managers, and cashiers may step backwards for corrections.
    if (user.is_owner() or user.is_main_owner() or user.is_branch_owner()
            or user.is_manager() or user.is_cashier()):
        valid_transitions.update({
            'confirmed': ['pending', 'preparing', 'cancelled'],
            'preparing': ['confirmed', 'ready', 'cancelled'],
            'ready':     ['preparing', 'served', 'cancelled'],
            'served':    ['ready', 'cancelled'],
        })

    if new_status not in valid_transitions.get(order.status, []):
        return Response(
            {'error': f'Cannot transition order from "{order.status}" to "{new_status}".'},
            status=400,
        )

    with transaction.atomic():
        order.status = new_status
        if new_status == 'confirmed' and not order.confirmed_by:
            order.confirmed_by = user
            order.save(update_fields=['status', 'confirmed_by', 'updated_at'])
        elif new_status == 'cancelled':
            for item in order.order_items.all():
                p = item.product
                if p.available_in_stock is not None:
                    p.available_in_stock += item.quantity
                    p.save(update_fields=['available_in_stock'])
            order.release_table()
            order.save(update_fields=['status', 'updated_at'])
        else:
            order.save(update_fields=['status', 'updated_at'])
        # --- transaction commits here ---

    # Outside transaction: push notification + WebSocket
    if new_status in _PUSH_STATUS_MESSAGES:
        try:
            customer = order.ordered_by
            push_token = getattr(customer, 'expo_push_token', None)
            if customer and push_token:
                title, body = _PUSH_STATUS_MESSAGES[new_status]
                _send_push_async(push_token, title, body,
                                 {'orderId': order.id, 'status': new_status})
        except Exception as e:
            logger.warning('Push notification for order %s failed: %s', order.id, e)

    _notify_ws(order, user)

    return Response(OrderSerializer(order, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def print_bill(request, order_id):
    """Print bill for an order (before payment) — same as web's /cashier/print-bill/<id>/"""
    user = request.user
    if not (user.is_cashier() or user.is_customer_care() or
            user.is_owner() or user.is_main_owner() or
            user.is_branch_owner() or user.is_manager()):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    order = get_object_or_404(
        Order.objects.filter(_tq).distinct().prefetch_related('order_items__product'),
        id=order_id,
    )

    if user.is_customer_care() and order.ordered_by != user:
        return Response({'error': 'Access denied.'}, status=403)

    if order.status == 'cancelled':
        return Response({'error': 'Cannot print bill for a cancelled order.'}, status=400)

    from decimal import Decimal
    from django.db.models import Sum as _Sum
    total_paid = order.payments.filter(is_voided=False).aggregate(
        total=_Sum('amount'))['total'] or Decimal('0.00')
    if total_paid >= order.total_amount:
        return Response({'error': 'Order is already fully paid. Use receipt instead.'}, status=400)

    try:
        from orders.printing import auto_print_bill
        result = auto_print_bill(order, printed_by=user)
        if result.get('bill_printed'):
            return Response({'success': True, 'message': f'Bill printed for Order #{order.order_number}'})
        errors = result.get('errors', ['Unknown error'])
        return Response({'success': False, 'message': f'Print failed: {", ".join(errors)}'})
    except Exception as e:
        logger.error('Mobile print_bill error for order %s: %s', order_id, e)
        return Response({'error': 'Bill print failed. Check printer connection.'}, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def transfer_table(request, order_id):
    """Transfer an order to a different table — same as web's /cashier/transfer-table/<id>/"""
    user = request.user
    if not (user.is_cashier() or user.is_customer_care() or
            user.is_owner() or user.is_main_owner() or
            user.is_branch_owner() or user.is_manager()):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    order = get_object_or_404(Order.objects.filter(_tq).distinct(), id=order_id)

    if user.is_customer_care() and order.ordered_by != user:
        return Response({'error': 'Access denied.'}, status=403)

    if order.status == 'cancelled':
        return Response({'error': 'Cannot transfer a cancelled order.'}, status=400)
    if order.payment_status == 'paid':
        return Response({'error': 'Cannot transfer a fully paid order.'}, status=400)

    target_table_id = request.data.get('target_table_id')
    if not target_table_id:
        return Response({'error': 'target_table_id is required.'}, status=400)

    _ttq = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )
    target_table = get_object_or_404(TableInfo.objects.filter(_ttq).distinct(), id=target_table_id)

    if target_table.id == order.table_info_id:
        return Response({'error': 'Order is already on this table.'}, status=400)

    with transaction.atomic():
        old_table = order.table_info
        order.table_info = target_table
        order.save(update_fields=['table_info'])
        still_active = Order.objects.filter(
            table_info=old_table,
            status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
            payment_status__in=['unpaid', 'partial'],
        ).exclude(id=order.id).exists()
        if not still_active:
            old_table.is_available = True
            old_table.save(update_fields=['is_available'])
        target_table.is_available = False
        target_table.save(update_fields=['is_available'])
        from orders.models import BillRequest
        BillRequest.objects.filter(table_info=old_table, status='pending').update(table_info=target_table)
        # --- transaction commits here ---

    logger.info('Mobile: Order %s transferred from Table %s to Table %s by %s',
                order.order_number, old_table.tbl_no, target_table.tbl_no, user.username)
    _notify_ws(order, user)

    return Response({
        'success': True,
        'message': f'Order {order.order_number} transferred to Table {target_table.tbl_no}',
        'order': OrderSerializer(order, context={'request': request}).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def cancel_order(request, order_id):
    """Cancel an order.
    - Customers / CC: can only cancel their own PENDING orders.
    - Owners, managers, cashiers: can cancel pending/confirmed/preparing/ready orders
      (mirrors web kitchen cancel_order which blocks only 'served' and 'cancelled').
    """
    user = request.user
    is_privileged = (user.is_owner() or user.is_main_owner() or
                     user.is_branch_owner() or user.is_manager() or user.is_cashier())
    if not (user.is_customer() or user.is_customer_care() or is_privileged):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    order = get_object_or_404(
        Order.objects.filter(_tq).distinct().prefetch_related('order_items__product'),
        id=order_id,
    )

    # Customers and CC can only cancel their own orders.
    if (user.is_customer() or user.is_customer_care()) and order.ordered_by != user:
        return Response({'error': 'Access denied.'}, status=403)

    # Status guard: customers/CC → pending only; privileged staff → anything not served/cancelled.
    if user.is_customer() or user.is_customer_care():
        if order.status != 'pending':
            return Response({'error': 'Only pending orders can be cancelled.'}, status=400)
    else:
        if order.status in ['served', 'cancelled']:
            return Response(
                {'error': f'Cannot cancel an order with status "{order.status}".'},
                status=400,
            )

    # Mirrors cashier/views.py cancel_order: block if any non-voided payments exist so
    # we do not cancel orders with partial/full payments without reversing them first.
    has_payments = order.payments.filter(is_voided=False).exists()
    if has_payments:
        return Response(
            {'error': 'Cannot cancel order with payments. Void all payments first.'},
            status=400,
        )

    reason = (request.data.get('reason', '') or '').strip()
    if not reason:
        # Require a reason from privileged staff so the audit trail is meaningful.
        if is_privileged:
            return Response({'error': 'Cancellation reason is required.'}, status=400)
        reason = 'Cancelled by customer'

    with transaction.atomic():
        for item in order.order_items.select_related('product').all():
            p = item.product
            if p.available_in_stock is not None:
                p.available_in_stock += item.quantity
                p.save(update_fields=['available_in_stock'])
        order.status = 'cancelled'
        order.reason_if_cancelled = reason
        order.release_table()
        order.save()
        # --- transaction commits here ---

    _notify_ws(order, user)
    logger.info('Mobile: Order %s cancelled by %s. Reason: %s', order.order_number, user.username, reason)
    return Response({'success': True, 'message': f'Order {order.order_number} cancelled.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def add_items_to_order(request, order_id):
    """Add more items to an existing order.
    Staff can add to any order. Customers can only add to their own orders.
    Mirrors the web's handle_add_to_existing_order logic.
    """
    user = request.user
    is_staff = (user.is_customer_care() or user.is_cashier() or
                user.is_owner() or user.is_main_owner() or
                user.is_branch_owner() or user.is_manager())

    if not (is_staff or user.is_customer()):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    order = get_object_or_404(
        Order.objects.filter(_tq).distinct().prefetch_related('order_items__product'),
        id=order_id,
    )

    # Customers and CC staff can only add to orders they placed themselves.
    # This mirrors the web's handle_add_to_existing_order which fetches the order
    # with ordered_by=request.user for all non-owner/manager roles.
    if (user.is_customer() or user.is_customer_care()) and order.ordered_by != user:
        return Response({'error': 'Access denied.'}, status=403)

    # Block cancelled orders only.
    # 'served' is intentionally allowed for unpaid orders — the web's
    # handle_add_to_existing_order includes status='served' in its lookup so a
    # customer can order more (e.g. dessert) after the main course has been served.
    if order.status == 'cancelled':
        return Response({'error': 'Cannot add items to a cancelled order.'}, status=400)

    # Prevent adding items to an already-paid order — mirrors the web's
    # payment_status__in=['unpaid', 'partial'] guard in handle_add_to_existing_order.
    if order.payment_status == 'paid':
        return Response({'error': 'Cannot add items to an already-paid order.'}, status=400)

    items_data = request.data.get('items', [])
    if not items_data:
        return Response({'error': 'No items provided.'}, status=400)

    validated = []
    for item in items_data:
        product_id = item.get('product_id')
        try:
            quantity = int(item.get('quantity', 1))
        except (TypeError, ValueError):
            return Response({'error': f'Invalid quantity for product {product_id}.'}, status=400)
        if quantity < 1 or quantity > 100:
            return Response(
                {'error': f'Quantity must be between 1 and 100 (got {quantity}).'},
                status=400,
            )
        try:
            product = Product.objects.filter(
                Q(main_category__owner=owner) |
                Q(main_category__restaurant__main_owner=owner) |
                Q(main_category__restaurant__branch_owner=owner)
            ).filter(id=product_id).first()
            if product is None:
                raise Product.DoesNotExist
        except Product.DoesNotExist:
            return Response({'error': f'Product {product_id} not found.'}, status=400)
        if not product.is_available:
            return Response({'error': f'Product {product.name} is not available.'}, status=400)
        # Mirror the web's handle_add_to_existing_order stock check
        if product.available_in_stock is not None and product.available_in_stock < quantity:
            return Response(
                {'error': f'Only {product.available_in_stock} of "{product.name}" left in stock.'},
                status=status.HTTP_409_CONFLICT,
            )
        fn = getattr(product, 'get_current_price', None)
        server_price = float(fn()) if fn else float(product.price)
        validated.append({'product': product, 'quantity': quantity, 'unit_price': server_price})

    if not validated:
        return Response({'error': 'No valid items to add.'}, status=400)

    with transaction.atomic():
        for item in validated:
            OrderItem.objects.create(
                order=order,
                product=item['product'],
                quantity=item['quantity'],
                unit_price=item['unit_price'],
            )
            p = item['product']
            if p.available_in_stock is not None:
                p.available_in_stock = max(0, p.available_in_stock - item['quantity'])
                p.save(update_fields=['available_in_stock'])
        from decimal import Decimal as _Dec
        added = sum(_Dec(str(i['unit_price'])) * _Dec(str(i['quantity'])) for i in validated)
        tax_rate = order.table_info.get_tax_rate() if order.table_info else _Dec('0')
        order.total_amount = _Dec(str(order.total_amount)) + added * (_Dec('1') + tax_rate)
        extra_notes = sanitize_special_instructions(
            (request.data.get('special_instructions', '') or '').strip()
        )
        if extra_notes:
            order.special_instructions = (order.special_instructions + '\n' + extra_notes).strip()
        order.save(update_fields=['total_amount', 'special_instructions', 'updated_at'])
        # --- transaction commits here ---

    # X-Local-Print: true → mobile prints locally; skip server queue (same as _place_order)
    if request.META.get('HTTP_X_LOCAL_PRINT') != 'true':
        try:
            from orders.printing import auto_print_order
            auto_print_order(order)
        except Exception as e:
            logger.warning('Auto-print failed adding items to order %s: %s', order.order_number, e)

    _notify_ws(order, user)

    return Response({
        'order': OrderSerializer(order, context={'request': request}).data,
        'message': f'Items added to order {order.order_number}.',
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def active_order_for_table(request, table_id):
    """Return the active (non-cancelled, non-served) order for a table, or null."""
    user = request.user
    if not (user.is_customer_care() or user.is_cashier() or
            user.is_owner() or user.is_main_owner() or
            user.is_branch_owner() or user.is_manager()):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq_aot = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )
    table = get_object_or_404(TableInfo.objects.filter(_tq_aot).distinct(), id=table_id)

    active = Order.objects.filter(
        table_info=table,
        status__in=['pending', 'confirmed', 'preparing', 'ready'],
    ).select_related('table_info', 'ordered_by').prefetch_related(
        'order_items__product', 'payments'
    ).order_by('-created_at').first()

    if not active:
        return Response({'order': None})

    return Response({'order': OrderSerializer(active, context={'request': request}).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def active_orders_for_table(request, table_id):
    """Return the requesting user's own active unpaid orders for a table.

    Used exclusively for the 'Add to Existing Order' flow.
    Both customers and CC staff only see orders THEY placed — matching the web's
    add_to_existing_order view which always filters by ordered_by=request.user.
    """
    user = request.user
    is_staff = (user.is_customer_care() or user.is_cashier() or
                user.is_owner() or user.is_main_owner() or
                user.is_branch_owner() or user.is_manager())

    if not (is_staff or user.is_customer()):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq_aots = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )
    table = get_object_or_404(TableInfo.objects.filter(_tq_aots).distinct(), id=table_id)

    today = timezone.now().date()
    # Always filter by the requesting user and unpaid status — mirrors the web's
    # add_to_existing_order: ordered_by=request.user, payment_status__in=['unpaid','partial']
    # 'served' is included because the web allows adding to a served-but-unpaid order.
    qs = Order.objects.filter(
        table_info=table,
        ordered_by=user,
        status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
        payment_status__in=['unpaid', 'partial'],
        created_at__date=today,
    ).select_related('table_info', 'ordered_by').prefetch_related(
        'order_items__product', 'payments'
    )

    return Response({
        'orders': OrderSerializer(qs.order_by('-created_at'), many=True, context={'request': request}).data
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def cancel_order_item(request, item_id):
    """Cancel a single item from an order. Mirrors web /orders/cancel-item/<item_id>/"""
    user = request.user
    if not (user.is_customer_care() or user.is_cashier() or
            user.is_owner() or user.is_main_owner() or
            user.is_branch_owner() or user.is_manager()):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _itq = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner)
    )
    item = get_object_or_404(
        OrderItem.objects.filter(_itq).distinct().select_related('order', 'product'),
        id=item_id,
    )
    order = item.order

    if order.status == 'cancelled':
        return Response({'error': 'Cannot cancel item from a cancelled order.'}, status=400)
    if order.payment_status == 'paid':
        return Response({'error': 'Cannot cancel item from a fully paid order.'}, status=400)
    if order.order_items.count() <= 1:
        return Response({'error': 'Cannot cancel the last item. Please cancel the whole order instead.'}, status=400)

    reason = (request.data.get('reason', '') or '').strip() or 'Item cancelled by staff'
    item_name = item.product.name if item.product else 'Item'

    with transaction.atomic():
        p = item.product
        if p and p.available_in_stock is not None:
            p.available_in_stock += item.quantity
            p.save(update_fields=['available_in_stock'])
        item.delete()
        subtotal = sum(
            oi.get_subtotal() for oi in order.order_items.select_related('product').all()
        )
        from decimal import Decimal as _Dec
        tax_rate = order.table_info.get_tax_rate() if order.table_info else _Dec('0')
        order.total_amount = subtotal * (_Dec('1') + tax_rate)
        order.save(update_fields=['total_amount', 'updated_at'])
        # --- transaction commits here ---

    logger.info('Mobile: Item "%s" cancelled from Order %s by %s. Reason: %s',
                item_name, order.order_number, user.username, reason)
    _notify_ws(order, user)

    return Response({
        'success': True,
        'message': f'"{item_name}" removed from order.',
        'new_total': float(order.total_amount),
        'remaining_items': order.order_items.count(),
        'order': OrderSerializer(order, context={'request': request}).data,
    })
