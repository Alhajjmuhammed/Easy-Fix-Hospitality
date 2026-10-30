"""SMS to customers through the restaurant's own Africa's Talking account.

Nothing SMS-related runs inside an order / payment / reservation request: the hooks below only
register a job that starts after the transaction commits, in a background thread (like push
notifications). The job does every lookup, de-duplication and the provider call, so SMS can never
slow down, fail or roll back an order — even if its tables are missing or the provider is down.

Cost guards: one text per (order, event) (enforced by the database), texts only to the
restaurant's own country, at most MAX_PER_NUMBER_PER_DAY texts per number, plain GSM characters
and at most 160 characters (one SMS part).
"""
import json
import logging
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .i18n import language_of, tr, when_text
from .models_sms import SmsAccount, SmsLog

logger = logging.getLogger(__name__)


def sms_enabled():
    """SMS costs money per message: it stays completely off until settings.SMS_ENABLED = True."""
    from django.conf import settings
    return bool(getattr(settings, 'SMS_ENABLED', False))


def _lang(user):
    """The customer's chosen language (staff-entered bookings and walk-ins: English)."""
    return language_of(user) if user is not None and user.is_customer() else 'en'

AT_URLS = {
    'live': 'https://api.africastalking.com/version1/messaging',
    'sandbox': 'https://api.sandbox.africastalking.com/version1/messaging',
}
SUCCESS_CODES = {100, 101, 102}   # processed / sent / queued
COUNTRY_CODES = {'KES': '254', 'TZS': '255', 'UGX': '256', 'RWF': '250', 'GHS': '233', 'NGN': '234'}
NATIONAL_DIGITS = {'234': 10}       # mobile number length after the country code (default 9)
MAX_PER_NUMBER_PER_DAY = 6
MAX_LEN = 160
NAME_LEN = 30

# GSM 03.38 basic set: anything else switches the whole text to Unicode (70 chars per part)
_GSM = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZ"
           "ÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
_REPLACE = {'’': "'", '‘': "'", '“': '"', '”': '"', '–': '-', '—': '-', '…': '...', ' ': ' '}


def gsm_text(text, limit=MAX_LEN):
    """Plain GSM characters only and at most one SMS part — keeps every text at the price of one."""
    out = []
    for ch in str(text or ''):
        ch = _REPLACE.get(ch, ch)
        if all(c in _GSM for c in ch):
            out.append(ch)
            continue
        plain = unicodedata.normalize('NFKD', ch).encode('ascii', 'ignore').decode()
        out.append(''.join(c for c in plain if c in _GSM))
    text = ' '.join(''.join(out).split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + '...'


def short_name(name):
    name = gsm_text(name, limit=200)
    return name if len(name) <= NAME_LEN else name[:NAME_LEN - 1].rstrip() + '.'


def account_for(owner):
    from cashier.loyalty import business_owner
    if owner is None:
        return None
    acc = SmsAccount.objects.filter(owner=business_owner(owner), enabled=True).first()
    if acc is None:
        return None
    creds = acc.credentials                       # decrypt once
    if not (creds.get('username') and creds.get('api_key')):
        return None
    acc._creds = creds
    return acc


def to_international(phone, currency):
    """'0712 345 678' + KES → '+254712345678'. Only numbers of the restaurant's own country."""
    cc = COUNTRY_CODES.get(currency)
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if not cc or not digits:
        return ''
    if digits.startswith('00'):
        digits = digits[2:]
    n = NATIONAL_DIGITS.get(cc, 9)
    if digits.startswith(cc + '0'):
        digits = cc + digits[len(cc) + 1:]         # "+255 0712…" typed with an extra 0
    if digits.startswith(cc) and len(digits) == len(cc) + n:
        return '+' + digits
    if digits.startswith('0') and len(digits) == n + 1:
        return '+' + cc + digits[1:]
    if len(digits) == n and not digits.startswith('0'):
        return '+' + cc + digits
    return ''


def _restaurant_of(owner):
    from restaurant.models_restaurant import Restaurant
    return Restaurant.for_owner(owner)


# ---------------------------------------------------------------------------
# Sending (background only)
# ---------------------------------------------------------------------------

def send(owner, event, phone, message, order=None, reservation_id=None, force=False, restaurant=None):
    """Create the log row and deliver it. Call from background jobs (or the settings test button).
    Returns the SmsLog, or None when not sent (switched off, no/foreign number, already sent, limit)."""
    if not sms_enabled():
        return None
    acc = account_for(owner)
    if acc is None or (not force and event not in (acc.events or [])):
        return None
    restaurant = restaurant or _restaurant_of(owner)
    currency = (getattr(restaurant, 'currency_code', '') or 'USD').upper()
    to = to_international(phone, currency)
    if not to:
        return None
    if not force and SmsLog.objects.filter(account=acc, to=to,
                                           created_at__gte=timezone.now() - timedelta(days=1)).count() \
            >= MAX_PER_NUMBER_PER_DAY:
        logger.warning('SMS daily limit reached for %s (account %s)', to, acc.pk)
        return None
    if not force and reservation_id and SmsLog.objects.filter(reservation_id=reservation_id, event=event,
                                                             message=gsm_text(message)).exists():
        return None
    try:
        with transaction.atomic():
            log = SmsLog.objects.create(account=acc, event=event, to=to, message=gsm_text(message), order=order,
                                        reservation_id=reservation_id)
    except IntegrityError:
        return None                                 # this order already got this text
    _deliver(log.pk, acc)
    return log


def _post(acc, to, message):
    creds = getattr(acc, '_creds', None) or acc.credentials
    form = {'username': creds['username'], 'to': to, 'message': message}
    if acc.sender_id:
        form['from'] = acc.sender_id
    req = urllib.request.Request(
        AT_URLS[acc.environment], data=urllib.parse.urlencode(form).encode(), method='POST',
        headers={'apiKey': creds['api_key'], 'Accept': 'application/json',
                 'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode() or '{}')
            return data if isinstance(data, dict) else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')[:200]
        raise RuntimeError(f'HTTP {e.code}: {body}')


def _deliver(log_id, acc=None):
    log = SmsLog.objects.select_related('account').filter(pk=log_id).first()
    if log is None:
        return
    acc = acc or log.account
    try:
        data = _post(acc, log.to, log.message)
        recipients = (data.get('SMSMessageData') or {}).get('Recipients') or []
        r = recipients[0] if recipients and isinstance(recipients[0], dict) else {}
        if r.get('statusCode') in SUCCESS_CODES:
            SmsLog.objects.filter(pk=log.pk).update(status='sent', provider_message_id=str(r.get('messageId', ''))[:100],
                                                   cost=str(r.get('cost', ''))[:30])
        else:
            reason = r.get('status') or (data.get('SMSMessageData') or {}).get('Message') or 'Not sent'
            SmsLog.objects.filter(pk=log.pk).update(status='failed', error=str(reason)[:255])
    except Exception as e:
        logger.warning('SMS send failed (%s): %s', log.pk, e)
        SmsLog.objects.filter(pk=log.pk).update(status='failed', error=str(e)[:255])


def retry_stuck(minutes=5):
    """For the scheduled job: texts left 'queued' (worker restarted mid-send) are tried once more."""
    if not sms_enabled():
        return 0
    import time
    stuck = SmsLog.objects.filter(status='queued', created_at__lt=timezone.now() - timedelta(minutes=minutes),
                                  created_at__gte=timezone.now() - timedelta(hours=6)).select_related('account')
    started, n = time.monotonic(), 0
    for log in stuck[:100]:
        if time.monotonic() - started > 120:        # stop in time for the next scheduled run
            break
        if not log.account.enabled:
            SmsLog.objects.filter(pk=log.pk).update(status='failed', error='SMS was switched off')
            continue
        # Claim it first: an overlapping run must never send the same text twice. If this run dies
        # mid-send the text stays 'failed' rather than risk a duplicate.
        if not SmsLog.objects.filter(pk=log.pk, status='queued').update(status='failed', error='Retrying'):
            continue
        _deliver(log.pk)
        n += 1
    return n


def _later(job, *args):
    """Run job(*args) after the current transaction commits, in a background thread. No queries here."""
    if not sms_enabled():
        return
    from .push import _in_background

    def run():
        try:
            job(*args)
        except Exception:
            logger.warning('SMS job %s%s failed', job.__name__, args, exc_info=True)
    transaction.on_commit(lambda: _in_background(run))


# ---------------------------------------------------------------------------
# Events — the hooks only schedule; the jobs do the work
# ---------------------------------------------------------------------------

STATUS_EVENTS = {
    'confirmed': 'order_confirmed',
    'ready': 'order_ready',
    'out_for_delivery': 'out_for_delivery',
    'delivered': 'order_delivered',
}


def order_status_changed(order):
    status = getattr(order, 'status', None)
    if status in STATUS_EVENTS and getattr(order, 'order_type', None) in ('delivery', 'pickup'):
        _later(_order_status_job, order.pk, status)


def order_paid(order):
    _later(_order_paid_job, order.pk)


def reservation_changed(res):
    if getattr(res, 'status', None) in ('confirmed', 'declined', 'cancelled'):
        _later(_reservation_job, res.pk, res.status)


def _customer_phone(order):
    if order.delivery_phone:
        return order.delivery_phone
    if order.ordered_by_id and order.ordered_by.is_customer():
        return getattr(order.ordered_by, 'phone_number', '') or ''
    return ''


def _order_context(order_id):
    from orders.models import Order
    from .push import _restaurant_owner
    order = Order.objects.select_related('ordered_by', 'ordered_by__role').filter(pk=order_id).first()
    if order is None:
        return None, None, None
    owner = _restaurant_owner(order)
    if owner is None or account_for(owner) is None:     # cheapest check first
        return None, None, None
    return order, owner, _restaurant_of(owner)


def _order_status_job(order_id, status):
    order, owner, restaurant = _order_context(order_id)
    if order is None or order.status != status:
        return                                          # changed again meanwhile
    event = STATUS_EVENTS[status]
    if (event == 'order_ready' and order.order_type != 'pickup') or \
            (event == 'order_delivered' and order.order_type != 'delivery'):
        return
    name = short_name(restaurant.name if restaurant else (owner.restaurant_name or 'Restaurant'))
    template = {
        'order_confirmed': '{name}: order #{number} confirmed.',
        'order_ready': '{name}: order #{number} is ready for pickup.',
        'out_for_delivery': '{name}: order #{number} is on the way.',
        'order_delivered': '{name}: order #{number} delivered. Enjoy!',
    }[event]
    text = tr(_lang(order.ordered_by), template, name=name, number=order.order_number)
    send(owner, event, _customer_phone(order), text, order=order, restaurant=restaurant)


def _order_paid_job(order_id):
    from django.db.models import Sum
    order, owner, restaurant = _order_context(order_id)
    if order is None or order.payment_status != 'paid':
        return
    phone = _customer_phone(order)
    if not phone:
        return
    paid = order.payments.filter(is_voided=False).aggregate(t=Sum('amount'))['t'] or 0
    currency = (getattr(restaurant, 'currency_code', '') or '').upper()
    name = short_name(restaurant.name if restaurant else (owner.restaurant_name or 'Restaurant'))
    send(owner, 'payment_receipt', phone,
         tr(_lang(order.ordered_by), '{name}: received {currency} {amount} for order #{number}. Thank you!',
            name=name, currency=currency, amount=f'{paid:,.2f}', number=order.order_number),
         order=order, restaurant=restaurant)


def _reservation_job(res_id, status):
    from restaurant.models_reservation import Reservation
    res = Reservation.objects.select_related('restaurant', 'customer', 'customer__role').filter(pk=res_id).first()
    if res is None or res.status != status:
        return
    r = res.restaurant
    owner = r.branch_owner or r.main_owner
    if account_for(owner) is None:
        return
    # A customer's own booking is texted only to the number on their account: nobody can make the
    # restaurant pay for texts to a number they typed. Staff bookings use the number staff entered.
    if res.customer_id and res.customer.is_customer():
        phone = getattr(res.customer, 'phone_number', '') or ''
    else:
        phone = res.phone
    lang = _lang(res.customer)
    when = when_text(lang, timezone.localtime(res.start), '%a %d %b %H:%M')
    name = short_name(r.name)
    text = tr(lang, {
        'confirmed': '{name}: table for {party} on {when} confirmed.',
        'declined': '{name}: sorry, we cannot confirm your table for {when}.',
        'cancelled': '{name}: your booking for {when} is cancelled.',
    }[status], name=name, party=res.party_size, when=when)
    send(owner, 'reservation', phone, text, reservation_id=res.pk, restaurant=r)
