"""Mobile money: send a payment request to a customer's phone and record the payment when it is confirmed.

Providers
  mpesa_daraja  Kenya, Safaricom M-Pesa Express (STK push). Callbacks are not signed, so a callback
                only triggers a server-to-server status query; the query result decides.
  flutterwave   Tanzania, Uganda, Rwanda, Ghana mobile money. Webhooks carry `verif-hash`; the
                transaction is then verified with GET /v3/transactions/{id}/verify before it counts.

A confirmed charge becomes an ordinary Payment (method 'digital', reference = provider receipt), so
receipts, reports, loyalty points and voids keep working exactly as for any other payment.
"""
import base64
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models_mobile_money import MobileMoneyAccount, MobileMoneyCharge

logger = logging.getLogger(__name__)

EAT = dt_timezone(timedelta(hours=3))  # Kenya time, no daylight saving
TIMEOUT = 8                          # seconds per provider call: well inside the 30 s web worker limit
CHECK_TIMEOUT = 5                    # status checks run inside screen polls: keep web workers free
CHECK_EVERY = timedelta(seconds=10)  # ask a provider about one charge at most this often
SWEEP_SECONDS = 120                  # one background run stops in time for the next (cron every 3 min)
EXPIRED_RECHECK = timedelta(minutes=15)   # timed-out charges: look again now and then, for 24 h
PENDING_LIMIT = {'mpesa_daraja': timedelta(minutes=5),     # the M-Pesa prompt dies after ~1-2 min
                 'flutterwave': timedelta(minutes=20)}     # approval pages can take longer
GIVE_UP_AFTER = timedelta(hours=24)  # stop asking the provider about a charge after this
NOT_PAYABLE_STATUSES = {'cancelled', 'customer_refused', 'kitchen_error', 'quality_issue', 'wasted'}

COUNTRY_CODES = {'KES': '254', 'TZS': '255', 'UGX': '256', 'RWF': '250', 'GHS': '233'}
FLW_TYPES = {
    'TZS': 'mobile_money_tanzania',
    'UGX': 'mobile_money_uganda',
    'RWF': 'mobile_money_rwanda',
    'GHS': 'mobile_money_ghana',
}
FLW_NETWORKS = {'UGX': ('MTN', 'AIRTEL'), 'GHS': ('MTN', 'VODAFONE', 'TIGO')}
PROVIDER_CURRENCIES = {'mpesa_daraja': ('KES',), 'flutterwave': tuple(FLW_TYPES)}


class ProviderError(Exception):
    """A provider refused or could not be reached. The message is safe to show to staff.
    `uncertain` = no answer came back, so the request may still have reached the customer."""

    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_phone(phone, currency):
    """International digits without '+', e.g. 0712 345 678 (KES) → 254712345678."""
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    cc = COUNTRY_CODES.get(currency, '')
    if digits.startswith('00'):
        digits = digits[2:]
    if cc and digits.startswith('0'):
        digits = cc + digits[1:]
    elif cc and len(digits) == 9:
        digits = cc + digits
    if not cc or not digits.startswith(cc) or len(digits) != len(cc) + 9:
        raise ValidationError('Enter a valid mobile number for this country.')
    return digits


def local_phone(international, currency):
    """254712345678 → 0712345678 (the format Flutterwave's examples use)."""
    return '0' + international[len(COUNTRY_CODES[currency]):]


def _http(method, url, headers=None, body=None, form=None, timeout=TIMEOUT):
    data = None
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    headers.setdefault('Accept', 'application/json')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    def _dict(raw):
        try:
            parsed = json.loads(raw.decode() or '{}')
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _dict(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, _dict(e.read())
        except Exception:
            return e.code, {}
    except Exception as e:  # timeout, reset, DNS, TLS, incomplete read …
        # We don't know whether the provider received the request (it may have)
        raise ProviderError(f'No answer from the payment provider ({e.__class__.__name__}).', uncertain=True)


def _start_answer_unclear(status, data):
    """A server error or an unreadable answer to a payment request: it may still have gone out."""
    return status >= 500 or not data


def restaurant_currency(owner):
    from restaurant.models_restaurant import Restaurant
    r = Restaurant.for_owner(owner)
    return (getattr(r, 'currency_code', '') or 'USD').upper() if r else 'USD'


# ---------------------------------------------------------------------------
# Safaricom Daraja (Kenya)
# ---------------------------------------------------------------------------

class Daraja:
    HOSTS = {'sandbox': 'https://sandbox.safaricom.co.ke', 'live': 'https://api.safaricom.co.ke'}
    REQUIRED = ('consumer_key', 'consumer_secret', 'shortcode', 'passkey')

    def __init__(self, account):
        self.account = account
        self.creds = account.credentials
        self.host = self.HOSTS[account.environment]

    def _token(self, timeout=TIMEOUT):
        key = f'daraja-token:{self.account.pk}:{self.account.updated_at.timestamp()}'
        token = cache.get(key)
        if token:
            return token
        basic = base64.b64encode(f"{self.creds['consumer_key']}:{self.creds['consumer_secret']}".encode()).decode()
        status, data = _http('GET', f'{self.host}/oauth/v1/generate?grant_type=client_credentials',
                             headers={'Authorization': f'Basic {basic}'}, timeout=timeout)
        token = data.get('access_token')
        if status != 200 or not token:
            raise ProviderError('M-Pesa rejected the account keys. Check the Consumer Key and Secret.')
        cache.set(key, token, 50 * 60)
        return token

    def _password(self):
        # Timestamp is Kenyan time (EAT, UTC+3, no daylight saving)
        ts = (timezone.now().astimezone(EAT)).strftime('%Y%m%d%H%M%S')
        raw = f"{self.creds['shortcode']}{self.creds['passkey']}{ts}"
        return base64.b64encode(raw.encode()).decode(), ts

    def start(self, charge, callback_url):
        if charge.amount != charge.amount.to_integral_value():
            raise ValidationError('M-Pesa takes whole shillings only. Pay the cents another way.')
        password, ts = self._password()
        till = (self.creds.get('till_number') or '').strip()
        body = {
            'BusinessShortCode': self.creds['shortcode'],
            'Password': password,
            'Timestamp': ts,
            'TransactionType': 'CustomerBuyGoodsOnline' if till else 'CustomerPayBillOnline',
            'Amount': int(charge.amount),
            'PartyA': charge.phone,
            'PartyB': till or self.creds['shortcode'],
            'PhoneNumber': charge.phone,
            'CallBackURL': callback_url,
            'AccountReference': charge.order.order_number[:12],
            'TransactionDesc': 'Order payment',
        }
        try:
            token = self._token()
        except ProviderError as e:
            # No login = nothing was sent to the phone: a plain failure the cashier can retry
            raise ProviderError(str(e) if not e.uncertain else 'Could not reach M-Pesa. Please try again.')
        status, data = _http('POST', f'{self.host}/mpesa/stkpush/v1/processrequest',
                             headers={'Authorization': f'Bearer {token}'}, body=body)
        if status == 200 and str(data.get('ResponseCode')) == '0' and data.get('CheckoutRequestID'):
            charge.provider_ref = data['CheckoutRequestID']
            return {}
        if _start_answer_unclear(status, data):
            raise ProviderError(f'M-Pesa gave no clear answer (HTTP {status}).', uncertain=True)
        raise ProviderError(data.get('errorMessage') or data.get('ResponseDescription')
                            or 'M-Pesa could not send the payment request.')

    # Final answers of the status query. Anything else (e.g. 4999 "still under processing", or a
    # code we don't know) keeps the charge waiting; it times out to 'expired', where a late
    # confirmed payment still counts.
    FAILED_CODES = {'1', '1001', '1025', '1026', '2001', '9999'}
    CANCELLED_CODES = {'1032'}
    EXPIRED_CODES = {'1037', '1019'}

    def check(self, charge):
        """→ (status, receipt, reason). Asks Safaricom directly; never trusts the callback body."""
        password, ts = self._password()
        status, data = _http('POST', f'{self.host}/mpesa/stkpushquery/v1/query',
                             headers={'Authorization': f'Bearer {self._token(timeout=CHECK_TIMEOUT)}'},
                             body={'BusinessShortCode': self.creds['shortcode'], 'Password': password,
                                   'Timestamp': ts, 'CheckoutRequestID': charge.provider_ref},
                             timeout=CHECK_TIMEOUT)
        code = str(data.get('ResultCode', '')).strip()
        if code == '0':
            return 'successful', '', ''
        if code in self.CANCELLED_CODES:
            return 'cancelled', '', data.get('ResultDesc', 'Cancelled by the customer')
        if code in self.EXPIRED_CODES:
            return 'expired', '', data.get('ResultDesc', 'The customer did not answer')
        if code in self.FAILED_CODES:
            return 'failed', '', data.get('ResultDesc', 'Payment failed')
        if code:
            logger.warning('M-Pesa status code %s for %s treated as still pending: %s',
                           code, charge.reference, data.get('ResultDesc'))
        return 'pending', '', ''   # still being processed (e.g. errorCode 500.001.1001)

    @staticmethod
    def parse_callback(body):
        """→ dict(checkout_id, receipt, phone, amount) — unsigned data: only used to find the charge
        and to fill in the receipt after Safaricom's own status query confirmed the payment."""
        body = body if isinstance(body, dict) else {}
        cb = (body.get('Body') if isinstance(body.get('Body'), dict) else {}).get('stkCallback') or {}
        cb = cb if isinstance(cb, dict) else {}
        meta = {}
        items = (cb.get('CallbackMetadata') or {}).get('Item') if isinstance(cb.get('CallbackMetadata'), dict) else []
        for item in items or []:
            if isinstance(item, dict) and item.get('Name'):
                meta[item['Name']] = item.get('Value')
        return {'checkout_id': str(cb.get('CheckoutRequestID') or ''),
                'receipt': str(meta.get('MpesaReceiptNumber') or ''),
                'phone': str(meta.get('PhoneNumber') or ''),
                'amount': meta.get('Amount')}


# ---------------------------------------------------------------------------
# Flutterwave (Tanzania, Uganda, Rwanda, Ghana)
# ---------------------------------------------------------------------------

class Flutterwave:
    BASE = 'https://api.flutterwave.com/v3'
    REQUIRED = ('secret_key', 'secret_hash')

    def __init__(self, account):
        self.account = account
        self.creds = account.credentials

    def _headers(self):
        return {'Authorization': f"Bearer {self.creds['secret_key']}"}

    def start(self, charge, callback_url, network='', email=''):
        ctype = FLW_TYPES.get(charge.currency)
        if not ctype:
            raise ValidationError(f'Flutterwave mobile money is not available for {charge.currency}.')
        body = {
            'tx_ref': charge.reference,
            'amount': str(charge.amount),
            'currency': charge.currency,
            'email': email or 'payments@easyfixsoft.com',
            'phone_number': local_phone(charge.phone, charge.currency),
            'meta': {'order_number': charge.order.order_number},
        }
        if charge.currency in FLW_NETWORKS:
            if network not in FLW_NETWORKS[charge.currency]:
                raise ValidationError('Choose the customer\'s mobile network.')
            body['network'] = network
        if charge.currency == 'GHS':
            body['country'] = 'GH'
        status, data = _http('POST', f'{self.BASE}/charges?type={ctype}', headers=self._headers(), body=body)
        if data.get('status') != 'success' and _start_answer_unclear(status, data):
            # e.g. a gateway 502/504 after the charge was created: it can still be found by tx_ref
            raise ProviderError(f'Flutterwave gave no clear answer (HTTP {status}).', uncertain=True)
        if data.get('status') != 'success':
            raise ProviderError(data.get('message') or 'Flutterwave could not send the payment request.')
        info = data.get('data') or {}
        if info.get('id'):
            charge.provider_ref = str(info['id'])
        auth = (data.get('meta') or {}).get('authorization') or {}
        if auth.get('mode') == 'redirect' and auth.get('redirect'):
            return {'redirect_url': auth['redirect']}   # the customer approves on this page
        return {}

    def _find_id(self, charge):
        if charge.provider_ref:
            return charge.provider_ref
        status, data = _http('GET', f'{self.BASE}/transactions?tx_ref={urllib.parse.quote(charge.reference)}',
                             headers=self._headers(), timeout=CHECK_TIMEOUT)
        items = data.get('data') or []
        return str(items[0]['id']) if items and items[0].get('id') else ''

    def check(self, charge):
        tx_id = self._find_id(charge)
        if not tx_id:
            return 'pending', '', ''
        charge.provider_ref = tx_id
        status, data = _http('GET', f'{self.BASE}/transactions/{tx_id}/verify', headers=self._headers(),
                             timeout=CHECK_TIMEOUT)
        info = data.get('data') or {}
        state = info.get('status')
        if state == 'successful':
            try:
                paid = Decimal(str(info.get('amount')))
            except (InvalidOperation, ValueError):
                paid = Decimal('0')
            if info.get('tx_ref') != charge.reference or info.get('currency') != charge.currency or paid < charge.amount:
                logger.error('Flutterwave verify mismatch for %s: %s', charge.reference, info)
                return 'failed', '', 'The payment details did not match. Contact support.'
            return 'successful', str(info.get('flw_ref') or tx_id), ''
        if state == 'failed':
            return 'failed', '', info.get('processor_response') or 'Payment failed'
        return 'pending', '', ''


def test_connection(account):
    """Owner's "Test connection" button: True or raises ProviderError with a readable reason."""
    if any(not account.credentials.get(k) for k in provider_for(account).REQUIRED):
        raise ProviderError('Fill in all the account details first.')
    if account.provider == 'mpesa_daraja':
        Daraja(account)._token()
        return True
    status, data = _http('GET', f'{Flutterwave.BASE}/balances', headers=Flutterwave(account)._headers())
    if status == 200 and data.get('status') == 'success':
        return True
    raise ProviderError(data.get('message') or 'Flutterwave rejected the secret key.')


def callback_base(request):
    """https://<site>/cashier/mm-callback — providers only call https addresses. Uses
    settings.PUBLIC_BASE_URL when set, so a cashier on another domain/IP can't break callbacks."""
    from django.conf import settings
    base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').rstrip('/')
    if base:
        return base + '/cashier/mm-callback/'
    url = request.build_absolute_uri('/cashier/mm-callback/')
    host = request.get_host().split(':')[0]
    if url.startswith('http://') and host not in ('localhost', '127.0.0.1', 'testserver'):
        url = 'https://' + url[len('http://'):]
    return url


def provider_for(account, name=None):
    """The provider class for this account (or for the provider a charge was made with)."""
    return {'mpesa_daraja': Daraja, 'flutterwave': Flutterwave}[name or account.provider](account)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def account_for_owner(owner, enabled_only=True):
    """A branch with its own account uses that one (even when switched off — its money must never
    go into another till); a branch without one uses the main restaurant's."""
    from cashier.loyalty import business_owner
    for candidate in (owner, business_owner(owner)):
        acc = MobileMoneyAccount.objects.filter(owner=candidate).first()
        if acc is not None:
            return acc if (acc.enabled or not enabled_only) else None
    return None


def _order_owner(order):
    from orders.push import _restaurant_owner
    return _restaurant_owner(order)


def balance_due(order):
    from cashier.models import Payment
    paid = Payment.objects.filter(order=order, is_voided=False).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    return max(order.total_amount - paid, Decimal('0'))


# ---------------------------------------------------------------------------
# Charges
#
# None of these may run inside a request-wide transaction (views use non_atomic_requests):
# the charge row is committed before the provider is called, and no lock is held while waiting
# for a provider.
# ---------------------------------------------------------------------------

def start_charge(order, phone, amount, user, callback_url, network=''):
    """Send the payment request to the customer's phone. Returns (charge, extra) where extra may
    hold a redirect_url the customer has to open (some Flutterwave countries)."""
    from orders.models import Order
    owner = _order_owner(order)
    account = account_for_owner(owner) if owner else None
    if account is None:
        raise ValidationError('Mobile money is not set up for this restaurant.')
    missing = [k for k in provider_for(account).REQUIRED if not account.credentials.get(k)]
    if missing:
        raise ValidationError('Mobile money settings are incomplete. Ask the owner to check them.')
    currency = restaurant_currency(account.owner)
    if currency not in PROVIDER_CURRENCIES[account.provider]:
        raise ValidationError(f'{account.get_provider_display()} does not take {currency}.')
    phone = normalize_phone(phone, currency)
    try:
        amount = Decimal(str(amount)).quantize(Decimal('0.01'))
        if not amount.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Enter a valid amount.')

    with transaction.atomic():
        locked = Order.objects.select_for_update(of=('self',)).get(pk=order.pk)
        if locked.status in NOT_PAYABLE_STATUSES:
            raise ValidationError('This order is cancelled.')
        due = balance_due(locked)
        if amount <= 0 or amount > due:
            raise ValidationError(f'The amount must be between 0 and the balance due ({due}).')
        # One open request at a time, for as long as an answer can still realistically come
        window = max(PENDING_LIMIT.get(account.provider, timedelta(minutes=5)), timedelta(minutes=10))
        if MobileMoneyCharge.objects.filter(order=locked, status__in=('pending', 'unknown'),
                                            created_at__gte=timezone.now() - window).exists():
            raise ValidationError('A mobile money request for this order is still open. Wait for it to finish '
                                  '(or check it on the Mobile Money page) before sending another one.')
        charge = MobileMoneyCharge.objects.create(
            account=account, provider=account.provider, order=locked, amount=amount, currency=currency,
            phone=phone, reference=f'RO{locked.pk}-{secrets.token_hex(6)}', initiated_by=user)
    # committed: from here on a provider answer can always be matched to this charge

    provider = provider_for(account)
    url = callback_url.rstrip('/') + f'/{account.provider}/{account.webhook_token}/'
    try:
        if account.provider == 'flutterwave':
            email = getattr(order.ordered_by, 'email', '') if order.ordered_by_id else ''
            extra = provider.start(charge, url, network=network, email=email)
        else:
            extra = provider.start(charge, url)
    except ProviderError as e:
        if e.uncertain:
            # The request may have reached the phone. Flutterwave can still be found by our
            # reference; M-Pesa is matched later by phone + amount when its callback arrives.
            status = 'pending' if account.provider == 'flutterwave' else 'unknown'
            MobileMoneyCharge.objects.filter(pk=charge.pk).update(
                status=status, failure_reason='No answer from the provider yet'[:255])
            logger.error('Mobile money start uncertain for %s: %s', charge.reference, e)
            charge.refresh_from_db()
            return charge, {'warning': 'The provider did not answer. The customer may still get the prompt — '
                                       'check their phone before taking another payment.'}
        _fail(charge, str(e))
        raise ValidationError(str(e))
    except ValidationError as e:
        _fail(charge, e.messages[0])
        raise
    except Exception:
        logger.exception('Mobile money start failed for order %s', order.pk)
        _fail(charge, 'Unexpected error')
        raise ValidationError('The payment request could not be sent. Please try again.')
    MobileMoneyCharge.objects.filter(pk=charge.pk).update(provider_ref=charge.provider_ref)
    charge.refresh_from_db()
    return charge, extra


def _fail(charge, msg):
    MobileMoneyCharge.objects.filter(pk=charge.pk, status='pending').update(
        status='failed', failure_reason=msg[:255], completed_at=timezone.now())


def refresh_charge(charge, force=False, callback_receipt=''):
    """Ask the provider about a charge and settle it. Only one request per charge talks to the
    provider every few seconds (claimed atomically); the others just return the saved state.
    force (provider callbacks, the sweeper) also re-asks about charges we closed as failed/cancelled:
    if the provider now confirms the money arrived, it still counts."""
    if charge.status == 'successful':
        return charge
    if charge.status != 'pending' and not force:
        return charge                            # only callbacks & the sweeper look again
    if not charge.provider_ref and charge.provider == 'mpesa_daraja':
        return charge                            # nothing to ask M-Pesa about yet
    now = timezone.now()
    from django.db.models import Q
    claim = MobileMoneyCharge.objects.filter(pk=charge.pk, status=charge.status)
    if not force:
        claim = claim.filter(Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=now - CHECK_EVERY))
    if not claim.update(last_checked_at=now):
        charge.refresh_from_db()
        return charge
    try:
        state, receipt, reason = provider_for(charge.account, charge.provider or None).check(charge)
    except Exception as e:  # provider down, bad answer, unreadable keys … → keep waiting
        logger.warning('Mobile money check failed for %s: %s', charge.reference, e)
        state, receipt, reason = 'pending', '', ''
    if charge.status == 'pending' and state == 'pending' \
            and now - charge.created_at > PENDING_LIMIT.get(charge.provider, timedelta(minutes=5)):
        state, reason = 'expired', 'The customer did not answer in time'
    if state != 'pending' and (state != charge.status):
        settle_charge(charge.pk, state, receipt or callback_receipt, reason, provider_ref=charge.provider_ref)
    charge.refresh_from_db()
    return charge


def settle_charge(charge_id, state, receipt='', reason='', provider_ref=''):
    """Final result of a charge. Paid → an ordinary Payment on the order (exactly once). A payment
    the provider confirms after we stopped waiting, or after an earlier 'failed'/'cancelled'
    answer, still counts: the money did arrive."""
    from cashier.models import Payment
    from orders.models import Order
    with transaction.atomic():
        charge = MobileMoneyCharge.objects.select_for_update().select_related('order', 'account').get(pk=charge_id)
        if state == 'successful':
            allowed = ('pending', 'expired', 'unknown', 'failed', 'cancelled')
        else:
            allowed = MobileMoneyCharge.LATE_SUCCESS_OK     # a final "no" also closes a timed-out charge
        if charge.status not in allowed:
            return charge                     # already settled (callback + poll both arrived)
        late = charge.status != 'pending'
        charge.status = state
        charge.completed_at = timezone.now()
        charge.failure_reason = (reason or '')[:255]
        if receipt:
            charge.receipt = receipt[:100]
        if provider_ref:
            charge.provider_ref = provider_ref[:100]
        if state == 'successful':
            order = Order.objects.select_for_update(of=('self',)).get(pk=charge.order_id)
            cancelled = order.status in NOT_PAYABLE_STATUSES
            due = Decimal('0') if cancelled else balance_due(order)
            amount = min(charge.amount, due) if due > 0 else Decimal('0')
            if amount > 0:
                staff = charge.initiated_by if charge.initiated_by and not charge.initiated_by.is_customer() \
                    else charge.account.owner
                ref = charge.receipt or charge.provider_ref or charge.reference
                charge.payment = Payment.objects.create(
                    order=order, amount=amount, payment_method='digital', processed_by=staff,
                    reference_number=ref[:50],
                    notes=f'Mobile money ({charge.account.get_provider_display()}) {charge.phone} ref {charge.reference}')
                paid = Payment.objects.filter(order=order, is_voided=False).aggregate(t=Sum('amount'))['t'] or 0
                order.payment_status = 'paid' if paid >= order.total_amount else 'partial'
                if order.payment_status == 'paid':
                    order.release_table()
                order.save(update_fields=['payment_status', 'updated_at'])
            if cancelled:
                # Money arrived for an order that was cancelled meanwhile: not a sale, refund it all
                charge.failure_reason = (f'Customer paid {charge.amount} but the order was cancelled — '
                                         f'refund {charge.amount} to {charge.phone}.')
                logger.error('Mobile money paid on cancelled order %s: %s', charge.order_id, charge.reference)
            elif amount < charge.amount:
                # Paid more than was still due (e.g. cash was taken meanwhile): the cashier must refund
                charge.failure_reason = (f'Customer paid {charge.amount} but only {amount} was still due — '
                                         f'refund {charge.amount - amount} to {charge.phone}.')
                logger.error('Mobile money overpayment on order %s: %s', charge.order_id, charge.reference)
            if late:
                logger.error('Mobile money paid after we stopped waiting: %s (order %s)',
                             charge.reference, charge.order_id)
        charge.save()
    if state == 'successful' and charge.payment_id:
        transaction.on_commit(lambda: _after_paid(charge.pk))
    return charge


def add_receipt(charge, receipt):
    """M-Pesa sends its receipt number only in the callback; the status query (which decides) has
    none. Fill it in afterwards on a charge Safaricom already confirmed. If Safaricom still says
    "processing", keep it on the charge: it becomes the payment's reference only once the status
    query confirms the payment (settle_charge keeps a saved receipt)."""
    if not receipt or charge.receipt:
        return
    if charge.status != 'successful':
        if MobileMoneyCharge.objects.filter(pk=charge.pk, receipt='').exclude(status='successful') \
                .update(receipt=receipt[:100]):
            return
        charge.refresh_from_db()              # settled meanwhile by a poll: fill in the payment too
        if charge.status != 'successful' or charge.receipt:
            return
    from cashier.models import Payment
    MobileMoneyCharge.objects.filter(pk=charge.pk, receipt='').update(receipt=receipt[:100])
    if charge.payment_id:
        Payment.objects.filter(pk=charge.payment_id).update(reference_number=receipt[:50])


def match_unknown_mpesa(account, checkout_id, phone, amount):
    """An M-Pesa callback we can't match by id: a request whose answer we never got (timeout).
    Match it by phone + amount among this account's 'unknown' charges of the last hour."""
    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        return None
    candidates = MobileMoneyCharge.objects.filter(
        account=account, provider='mpesa_daraja', status='unknown', provider_ref='', phone=str(phone),
        amount=amount, created_at__gte=timezone.now() - timedelta(hours=1)).order_by('-created_at')
    charge = candidates.first()
    if charge is not None and candidates.count() == 1:
        MobileMoneyCharge.objects.filter(pk=charge.pk, provider_ref='').update(provider_ref=checkout_id[:100])
        charge.refresh_from_db()
        return charge
    return None


def sweep(limit=200, seconds=SWEEP_SECONDS):
    """For the scheduled job: look again at charges that are still open (closed screens, lost callbacks).
    Least recently checked first, timed-out charges only every EXPIRED_RECHECK, and the run stops after
    `seconds` so runs never pile up behind each other."""
    import time
    from django.db.models import F, Q
    now = timezone.now()
    open_charges = MobileMoneyCharge.objects.filter(
        status__in=('pending', 'unknown', 'expired'), created_at__gte=now - GIVE_UP_AFTER,
    ).filter(
        ~Q(status='expired') | Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=now - EXPIRED_RECHECK)
    ).select_related('account').order_by(F('last_checked_at').asc(nulls_first=True), 'created_at')[:limit]
    started, done = time.monotonic(), 0
    for charge in open_charges:
        if time.monotonic() - started > seconds:
            break
        refresh_charge(charge, force=charge.status != 'pending')
        done += 1
    return done


def _after_paid(charge_id):
    """Tell the screens, print the receipt and write the audit entry — never allowed to fail the payment."""
    try:
        charge = MobileMoneyCharge.objects.select_related('payment', 'order').get(pk=charge_id)
    except MobileMoneyCharge.DoesNotExist:
        return
    try:
        from mobile_api.views.orders import _notify_ws
        _notify_ws(charge.order, charge.payment.processed_by)
    except Exception:
        logger.warning('Mobile money notify failed for charge %s', charge_id, exc_info=True)
    try:
        from orders.printing import auto_print_receipt
        auto_print_receipt(charge.payment)
    except Exception:
        logger.warning('Mobile money receipt print failed for charge %s', charge_id, exc_info=True)
    try:
        from accounts.security_utils import log_security_event
        log_security_event(
            event_type='payment_processed', user=charge.payment.processed_by,
            description=f'Mobile money payment of {charge.payment.amount} for Order #{charge.order.order_number}',
            ip_address=None,
            extra_data={'order_id': charge.order_id, 'payment_id': str(charge.payment_id),
                        'payment_method': 'digital', 'mobile_money_reference': charge.reference,
                        'receipt': charge.receipt or charge.provider_ref})
    except Exception:
        logger.warning('Mobile money audit log failed for charge %s', charge_id, exc_info=True)


def charge_to_dict(charge, extra=None):
    data = {
        'id': charge.id,
        'status': charge.status,
        'status_display': charge.get_status_display(),
        'amount': str(charge.amount),
        'currency': charge.currency,
        'phone': charge.phone,
        'receipt': charge.receipt,
        'message': charge.failure_reason,
        # Paid, but more than was still due: the cashier has to refund the difference
        'needs_refund': charge.status == 'successful' and bool(charge.failure_reason),
        'order_id': charge.order_id,
    }
    if extra:
        data.update(extra)
    return data
