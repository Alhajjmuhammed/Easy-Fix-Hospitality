"""
Expo push notifications (free service).

Everything here is best-effort: messages are sent after the database transaction
commits, from a background thread, so a slow or failing push service can never
delay or break an order.
"""
import json
import logging
import threading
import urllib.request

from django.db import transaction
from django.db.models import Q

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'
_BATCH = 100  # Expo accepts at most 100 messages per request

STATION_ROLES = ('kitchen', 'bar', 'buffet', 'service')
REMOTE_ORDER_ROLES = ('cashier', 'customer_care', 'manager')

CUSTOMER_STATUS_MESSAGES = {
    'confirmed':        ('Order Confirmed ✅', 'Your order has been confirmed and will be prepared shortly.'),
    'preparing':        ('Being Prepared 👨‍🍳', 'Your order is now being prepared.'),
    'ready':            ('Order Ready 🍽️', 'Your order is ready and will be served shortly.'),
    'served':           ('Served 🎉', 'Your order has been served. Enjoy your meal!'),
    'out_for_delivery': ('On the Way 🛵', 'Your order is out for delivery.'),
    'delivered':        ('Delivered ✅', 'Your order has been delivered. Enjoy!'),
    'cancelled':        ('Order Cancelled ❌', 'Your order has been cancelled.'),
}
_READY_BY_TYPE = {
    'pickup':   'Your order is ready for pickup.',
    'delivery': 'Your order is ready and will be handed to the rider shortly.',
}


def _valid(token):
    return bool(token) and token.startswith(('ExponentPushToken[', 'ExpoPushToken[')) and token.endswith(']')


def _post(messages):
    """POST one batch to Expo; clear tokens Expo reports as no longer registered."""
    req = urllib.request.Request(
        EXPO_PUSH_URL,
        data=json.dumps(messages).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        tickets = json.loads(resp.read().decode('utf-8')).get('data') or []
    dead = [
        msg['to'] for msg, ticket in zip(messages, tickets)
        if isinstance(ticket, dict) and ticket.get('status') == 'error'
        and (ticket.get('details') or {}).get('error') == 'DeviceNotRegistered'
    ]
    if dead:
        from accounts.models import User
        User.objects.filter(expo_push_token__in=dead).update(expo_push_token=None)


def _deliver(messages):
    try:
        for i in range(0, len(messages), _BATCH):
            _post(messages[i:i + _BATCH])
    except Exception as e:
        logger.warning('Push notification send failed: %s', e)


def send_push(tokens, title, body, data=None):
    """Queue a notification to each token; sent after the current transaction commits."""
    tokens = sorted({t for t in tokens if _valid(t)})
    if not tokens:
        return
    messages = [{
        'to': t, 'title': title, 'body': body, 'data': data or {},
        'sound': 'default', 'priority': 'high', 'channelId': 'orders',
    } for t in tokens]
    transaction.on_commit(lambda: _in_background(_deliver, messages))


def _in_background(fn, *args):
    threading.Thread(target=_run_and_close_db, args=(fn, *args), daemon=True).start()


def _run_and_close_db(fn, *args):
    """Thread body: run fn, then close the DB connection this thread may have opened.
    Only ever runs in its own thread, so it never closes a request's connection."""
    from django.db import connection
    try:
        fn(*args)
    finally:
        connection.close()


def _restaurant_owner(order):
    """The owner account whose staff serve this order (works for legacy and branch tables)."""
    table = order.table_info
    if table is not None:
        if table.owner_id:
            return table.owner
        if table.restaurant_id:
            return table.restaurant.branch_owner or table.restaurant.main_owner
        return None
    if order.restaurant_owner_id:
        return order.restaurant_owner
    return order.ordered_by.owner if order.ordered_by_id else None


def notify_customer_status(order, new_status):
    customer = order.ordered_by
    if not customer or not customer.expo_push_token or not customer.is_customer():
        return
    if new_status not in CUSTOMER_STATUS_MESSAGES:
        return
    title, body = CUSTOMER_STATUS_MESSAGES[new_status]
    if new_status == 'ready':
        body = _READY_BY_TYPE.get(order.order_type, body)
    send_push([customer.expo_push_token], title, body,
              {'kind': 'order_status', 'orderId': order.id, 'status': new_status})


def notify_new_order(order):
    """Alert staff of the restaurant: station staff for their items, front staff for delivery/pickup."""
    from accounts.models import User
    owner = _restaurant_owner(order)
    if owner is None:
        return
    stations = {s or 'kitchen' for s in order.order_items.values_list('product__station', flat=True)}
    roles = [r for r in STATION_ROLES if r in stations]
    if order.order_type in ('delivery', 'pickup'):
        roles += list(REMOTE_ORDER_ROLES)
    if not roles:
        return
    tokens = list(
        User.objects.filter(owner=owner, is_active=True, role__name__in=roles, expo_push_token__isnull=False)
        .exclude(pk=order.ordered_by_id)
        .values_list('expo_push_token', flat=True)
    )
    where = f'Table {order.table_info.tbl_no}' if order.table_info_id else order.get_order_type_display()
    send_push(tokens, f'New Order #{order.order_number}', f'{where} • {order.order_items.count()} item(s)',
              {'kind': 'new_order', 'orderId': order.id})


RESERVATION_ROLES = ('cashier', 'customer_care', 'manager')

RESERVATION_STATUS_MESSAGES = {
    'confirmed': ('Reservation Confirmed ✅', 'Your table for {party} on {when} is confirmed.'),
    'declined':  ('Reservation Not Available', 'Sorry, we could not confirm your table for {when}.'),
    'cancelled': ('Reservation Cancelled', 'Your reservation for {when} has been cancelled.'),
}


def _reservation_when(res):
    from django.utils import timezone as _tz
    return _tz.localtime(res.start).strftime('%a %d %b, %H:%M')


def _reservation_staff_tokens(res, exclude_user_id=None):
    """Front-of-house staff of the restaurant who can see reservations (role set / custom role)."""
    from accounts.models import User
    owner = res.restaurant.branch_owner or res.restaurant.main_owner
    if owner is None:
        return []
    staff = (User.objects.filter(owner=owner, is_active=True, role__name__in=RESERVATION_ROLES,
                                 expo_push_token__isnull=False)
             .exclude(expo_push_token='').exclude(pk=exclude_user_id)
             .select_related('role', 'custom_role'))
    return [u.expo_push_token for u in staff if u.has_feature('view_reservations')]


def notify_new_reservation(res):
    """Never notifies the person who created the booking."""
    status = 'awaiting confirmation' if res.status == 'pending' else 'confirmed'
    send_push(_reservation_staff_tokens(res, exclude_user_id=res.created_by_id),
              f'New Reservation • {res.party_size} people',
              f'{res.name} — {_reservation_when(res)} ({status})',
              {'kind': 'reservation', 'reservationId': res.id})


def notify_reservation_cancelled_by_customer(res):
    send_push(_reservation_staff_tokens(res),
              'Reservation Cancelled',
              f'{res.name} cancelled the table for {res.party_size} on {_reservation_when(res)}.',
              {'kind': 'reservation', 'reservationId': res.id})


def notify_reservation_status(res):
    customer = res.customer
    if not customer or not customer.expo_push_token or not customer.is_customer():
        return
    if res.status not in RESERVATION_STATUS_MESSAGES:
        return
    title, body = RESERVATION_STATUS_MESSAGES[res.status]
    send_push([customer.expo_push_token], title,
              body.format(party=f'{res.party_size} people', when=_reservation_when(res)),
              {'kind': 'reservation', 'reservationId': res.id, 'status': res.status})


def notify_low_rating(rating):
    """Owner + front-of-house staff of that restaurant allowed to see feedback (never other owners)."""
    from accounts.models import User
    from .feedback import FEEDBACK_ROLES
    owner = rating.restaurant_owner
    people = (User.objects.filter(Q(pk=owner.pk) | Q(owner=owner, role__name__in=FEEDBACK_ROLES),
                                  is_active=True, expo_push_token__isnull=False)
              .exclude(expo_push_token='').select_related('role', 'custom_role'))
    tokens = [u.expo_push_token for u in people if u.has_feature('view_feedback')]
    stars = f'{rating.food_stars}★ food' + (f', {rating.delivery_stars}★ delivery' if rating.delivery_stars else '')
    send_push(tokens, f'Low rating on order #{rating.order.order_number}',
              f'{stars}' + (f' — "{rating.comment[:80]}"' if rating.comment else ''),
              {'kind': 'low_rating', 'orderId': rating.order_id})


def notify_rating_reply(rating):
    customer = rating.customer
    if not customer.expo_push_token:
        return
    send_push([customer.expo_push_token], 'The restaurant replied 💬', rating.reply[:120],
              {'kind': 'rating_reply', 'orderId': rating.order_id})


def notify_roster(staff_ids, title, body, week_start):
    from accounts.models import User
    tokens = User.objects.filter(pk__in=staff_ids, is_active=True, expo_push_token__isnull=False) \
        .exclude(expo_push_token='').values_list('expo_push_token', flat=True)
    send_push(list(tokens), title, body, {'kind': 'roster', 'week': week_start.isoformat()})


def notify_rider_assigned(order, rider_user):
    if not rider_user or not rider_user.expo_push_token:
        return
    send_push([rider_user.expo_push_token], 'New Delivery 🛵',
              f'Order #{order.order_number} has been assigned to you.',
              {'kind': 'delivery_assigned', 'orderId': order.id})
