"""Mobile money pages: owner settings, cashier/customer payment requests, status, provider callbacks."""
import hmac
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from mobile_api.permissions import IsSubscriptionActive
from orders.models import Order
from . import mobile_money as svc
from .models_mobile_money import MobileMoneyAccount, MobileMoneyCharge
from .views_loyalty import _order_for_staff

logger = logging.getLogger(__name__)

CREDENTIAL_FIELDS = {
    'mpesa_daraja': [('consumer_key', 'Consumer Key'), ('consumer_secret', 'Consumer Secret'),
                     ('shortcode', 'Business Shortcode (Paybill or Store number)'), ('passkey', 'Passkey'),
                     ('till_number', 'Till number (only for Buy Goods tills)')],
    'flutterwave': [('secret_key', 'Secret Key'), ('secret_hash', 'Webhook Secret Hash')],
}
SECRET_FIELDS = {'consumer_secret', 'passkey', 'secret_key', 'secret_hash'}


# ---------------------------------------------------------------------------
# Owner settings
# ---------------------------------------------------------------------------

@login_required
def mobile_money_settings(request):
    user = request.user
    if not user.is_any_owner():
        messages.error(request, 'Only restaurant owners can set up mobile money.')
        return redirect('restaurant:home')
    account = MobileMoneyAccount.objects.filter(owner=user).first()
    inherited = None if account else svc.account_for_owner(user, enabled_only=False)

    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        provider = request.POST.get('provider') or (account.provider if account else '')
        if provider not in dict(MobileMoneyAccount.PROVIDER_CHOICES):
            messages.error(request, 'Choose a provider.')
            return redirect('cashier:mobile_money_settings')
        if account is None:
            account = MobileMoneyAccount(owner=user, provider=provider)
        if account.provider != provider:
            account.credentials = {}          # switching provider: old keys don't apply
            account.provider = provider
        creds = account.credentials
        for key, _ in CREDENTIAL_FIELDS[provider]:
            value = (request.POST.get(key) or '').strip().replace('\x00', '')[:500]
            if value or key not in SECRET_FIELDS:   # empty secret field = keep the saved one
                creds[key] = value
        account.credentials = creds
        account.environment = 'live' if request.POST.get('environment') == 'live' else 'sandbox'
        account.enabled = request.POST.get('enabled') == 'on'
        account.allow_customer_payments = request.POST.get('allow_customer_payments') == 'on'
        missing = [label for key, label in CREDENTIAL_FIELDS[provider]
                   if key != 'till_number' and not creds.get(key)]
        if account.enabled and missing:
            account.enabled = False
            messages.warning(request, 'Saved, but switched off until these are filled in: ' + ', '.join(missing))
        account.save()
        if action == 'test':
            try:
                svc.test_connection(account)
                messages.success(request, 'Connection works. The provider accepted your keys.')
            except svc.ProviderError as e:
                messages.error(request, f'Connection failed: {e}')
        else:
            messages.success(request, 'Mobile money settings saved.')
        return redirect('cashier:mobile_money_settings')

    base = svc.callback_base(request)
    creds = account.credentials if account else {}
    return render(request, 'cashier/mobile_money_settings.html', {
        'account': account,
        'inherited': inherited,
        'provider_choices': MobileMoneyAccount.PROVIDER_CHOICES,
        'fields': {p: [{'key': k, 'label': l, 'secret': k in SECRET_FIELDS,
                        'value': '' if k in SECRET_FIELDS else creds.get(k, '') if account and account.provider == p else '',
                        'is_set': bool(creds.get(k)) if account and account.provider == p else False}
                       for k, l in f] for p, f in CREDENTIAL_FIELDS.items()},
        'callback_url': f'{base}{account.provider}/{account.webhook_token}/' if account else '',
        'currency': svc.restaurant_currency(user),
        'recent': MobileMoneyCharge.objects.filter(account=account).select_related('order')[:20] if account else [],
    })


# ---------------------------------------------------------------------------
# Starting a payment request and following it
# ---------------------------------------------------------------------------

def _order_for_customer(user, order_id):
    order = get_object_or_404(Order, id=order_id, ordered_by=user)
    from orders.push import _restaurant_owner
    owner = _restaurant_owner(order)
    account = svc.account_for_owner(owner) if owner else None
    if account is None or not account.allow_customer_payments:
        raise ValidationError('This restaurant does not take mobile money payments online.')
    return order


def _start(request, order, data):
    if not isinstance(data, dict):
        data = {}
    amount = data.get('amount') or svc.balance_due(order)
    if request.user.is_customer():
        # Customers can only prompt their own numbers (no PIN-prompt spam to strangers)
        currency = svc.restaurant_currency(svc.account_for_owner(svc._order_owner(order)).owner)
        own = set()
        for p in (getattr(request.user, 'phone_number', ''), order.delivery_phone):
            try:
                own.add(svc.normalize_phone(p, currency))
            except ValidationError:
                pass
        try:
            wanted = svc.normalize_phone(data.get('phone', ''), currency)
        except ValidationError:
            wanted = None
        if wanted not in own:
            raise ValidationError('Use the phone number saved on your account or on this order.')
    charge, extra = svc.start_charge(order, data.get('phone', ''), amount, request.user,
                                     svc.callback_base(request), network=str(data.get('network') or ''))
    return svc.charge_to_dict(charge, extra)


def _charge_for(user, charge_id, owner=None):
    charge = get_object_or_404(MobileMoneyCharge.objects.select_related('order', 'account'), pk=charge_id)
    if charge.order.ordered_by_id == user.id:
        return charge
    _order_for_staff(user, charge.order_id, owner=owner)   # raises / 404 when not this restaurant's
    return charge


def availability(order):
    """What the payment screens need to show the mobile money option."""
    from orders.push import _restaurant_owner
    owner = _restaurant_owner(order)
    account = svc.account_for_owner(owner) if owner else None
    if account is None:
        return {'enabled': False}
    currency = svc.restaurant_currency(account.owner)
    # Opening the pay screen also settles any request whose answer we may have missed
    for open_charge in MobileMoneyCharge.objects.filter(order=order, status='pending').select_related('account'):
        svc.refresh_charge(open_charge)
    return {
        'enabled': currency in svc.PROVIDER_CURRENCIES[account.provider],
        'provider': account.get_provider_display(),
        'currency': currency,
        'networks': list(svc.FLW_NETWORKS.get(currency, ())) if account.provider == 'flutterwave' else [],
        'whole_amounts_only': account.provider == 'mpesa_daraja',
        'balance_due': str(svc.balance_due(order)),
        'customer_phone': (order.delivery_phone or getattr(order.ordered_by, 'phone_number', '') or '')
        if order.ordered_by_id and order.ordered_by.is_customer() else (order.delivery_phone or ''),
    }


@transaction.non_atomic_requests   # never wait for a provider inside the request transaction
@login_required
@require_http_methods(['GET', 'POST'])
def start_web(request, order_id):
    """GET: is mobile money available for this order. POST: send a payment request to a phone
    (cashier, or the customer on their own order)."""
    try:
        data = json.loads(request.body or b'{}') if request.method == 'POST' else {}
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid request'}, status=400)
    try:
        if request.user.is_customer():
            order = _order_for_customer(request.user, order_id)
        else:
            order = _order_for_staff(request.user, order_id)
        if request.method == 'GET':
            return JsonResponse(availability(order))
        return JsonResponse(_start(request, order, data))
    except PermissionDenied:
        return JsonResponse({'error': 'Access denied'}, status=403)
    except ValidationError as e:
        return JsonResponse({'error': ' '.join(e.messages)}, status=400)


@transaction.non_atomic_requests
@login_required
def charge_status_web(request, charge_id):
    try:
        charge = _charge_for(request.user, charge_id)
    except PermissionDenied:
        return JsonResponse({'error': 'Access denied'}, status=403)
    return JsonResponse(svc.charge_to_dict(svc.refresh_charge(charge)))


@transaction.non_atomic_requests
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def start_api(request, order_id):
    from mobile_api.views.helpers import get_restaurant_owner
    try:
        if request.user.is_customer():
            order = _order_for_customer(request.user, order_id)
        else:
            order = _order_for_staff(request.user, order_id, owner=get_restaurant_owner(request))
        if request.method == 'GET':
            return Response(availability(order))
        return Response(_start(request, order, request.data), status=status.HTTP_201_CREATED)
    except PermissionDenied:
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
    except ValidationError as e:
        return Response({'error': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)


@transaction.non_atomic_requests
@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def charge_status_api(request, charge_id):
    from mobile_api.views.helpers import get_restaurant_owner
    try:
        owner = None if request.user.is_customer() else get_restaurant_owner(request)
        charge = _charge_for(request.user, charge_id, owner=owner)
    except PermissionDenied:
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
    return Response(svc.charge_to_dict(svc.refresh_charge(charge)))


# ---------------------------------------------------------------------------
# Provider callbacks (no login: the secret token in the address identifies the account)
# ---------------------------------------------------------------------------

@transaction.non_atomic_requests
@csrf_exempt
@require_http_methods(['POST'])
def provider_callback(request, provider, token):
    # The token identifies the account (the owner may have changed provider since: charges keep theirs)
    account = MobileMoneyAccount.objects.filter(webhook_token=token).first()
    if account is None or provider not in ('mpesa_daraja', 'flutterwave'):
        return HttpResponse(status=404)
    try:
        body = json.loads(request.body or b'{}')
    except (ValueError, TypeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        if provider == 'mpesa_daraja':
            info = svc.Daraja.parse_callback(body)
            charge = MobileMoneyCharge.objects.filter(account=account, provider='mpesa_daraja',
                                                      provider_ref=info['checkout_id']).first() \
                if info['checkout_id'] else None
            if charge is None and info['checkout_id'] and info['receipt']:
                # A request whose answer we never got (timeout): match by phone + amount
                charge = svc.match_unknown_mpesa(account, info['checkout_id'], info['phone'], info['amount'])
            if charge is None:
                if info['receipt']:
                    logger.error('Unmatched M-Pesa payment: account %s checkout %s receipt %s phone %s amount %s',
                                 account.pk, info['checkout_id'], info['receipt'], info['phone'], info['amount'])
                return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})
            # The callback is not signed: Safaricom is asked directly before anything counts
            charge = svc.refresh_charge(charge, force=True, callback_receipt=info['receipt'])
            svc.add_receipt(charge, info['receipt'])
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        expected = account.credentials.get('secret_hash') or ''
        if not expected or not hmac.compare_digest(request.headers.get('verif-hash', ''), expected):
            return HttpResponse(status=401)
        data = body.get('data') if isinstance(body.get('data'), dict) else {}
        charge = MobileMoneyCharge.objects.filter(account=account, provider='flutterwave',
                                                  reference=str(data.get('tx_ref') or '')).first()
        if charge is None:
            if data.get('status') == 'successful':
                logger.error('Unmatched Flutterwave payment: account %s tx_ref %s id %s amount %s',
                             account.pk, data.get('tx_ref'), data.get('id'), data.get('amount'))
            return HttpResponse(status=200)
        svc.refresh_charge(charge, force=True)       # verified with Flutterwave before it counts
        return HttpResponse(status=200)
    except Exception:
        # Never let a provider see a 500 for a payment we may still settle by polling
        logger.exception('Mobile money callback failed (%s)', provider)
        return HttpResponse(status=200)
