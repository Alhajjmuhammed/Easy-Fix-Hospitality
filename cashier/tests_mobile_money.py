import base64
import datetime
import json
import sys
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, RestaurantSubscription, User
from cashier import mobile_money as svc
from cashier.models import Payment
from cashier.models_mobile_money import MobileMoneyAccount, MobileMoneyCharge
from orders.models import Order
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class FakeProvider:
    """Records every call to a provider and answers like it would."""

    def __init__(self):
        self.calls = []
        self.stk_result = None           # None → still processing; '0' paid; '1032' cancelled …
        self.flw_verify = {'status': 'successful'}
        self.flw_start = {'status': 'success', 'message': 'Charge initiated', 'data': {'id': 777, 'status': 'pending'}}

    def __call__(self, method, url, headers=None, body=None, form=None, timeout=None):
        self.calls.append((method, url, headers or {}, body))
        if '/oauth/v1/generate' in url:
            return 200, {'access_token': 'tok123', 'expires_in': '3599'}
        if url.endswith('/mpesa/stkpush/v1/processrequest'):
            return 200, {'MerchantRequestID': 'm1', 'CheckoutRequestID': 'ws_CO_1', 'ResponseCode': '0',
                         'ResponseDescription': 'Success', 'CustomerMessage': 'ok'}
        if url.endswith('/mpesa/stkpushquery/v1/query'):
            if self.stk_result is None:
                return 500, {'errorCode': '500.001.1001', 'errorMessage': 'The transaction is being processed'}
            return 200, {'ResultCode': self.stk_result, 'ResultDesc': 'desc'}
        if '/v3/charges?type=' in url:
            return 200, self.flw_start
        if url.endswith('/verify'):
            charge = MobileMoneyCharge.objects.order_by('-id').first()
            data = {'id': 777, 'tx_ref': charge.reference, 'currency': charge.currency,
                    'amount': float(charge.amount), 'flw_ref': 'FLW-REF-9'}
            data.update(self.flw_verify)
            return 200, {'status': 'success', 'data': data}
        if url.endswith('/v3/balances'):
            return 200, {'status': 'success', 'data': []}
        raise AssertionError(f'unexpected call {url}')


class MobileMoneyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.fake = FakeProvider()
        for target, kw in (('cashier.mobile_money._http', {'side_effect': self.fake}),
                           ('orders.push.send_push', {}),
                           ('orders.printing.auto_print_receipt', {}),
                           ('mobile_api.views.orders._notify_ws', {})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.cust = mk('cust', 'customer', phone_number='0712345678', email='c@x.test')
        self.cust2 = mk('cust2', 'customer')
        self.other = mk('oth', 'main_owner', restaurant_name='Other R')
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRMAIN', currency_code='KES')
        today = datetime.date.today()
        for o in (self.main, self.other):
            RestaurantSubscription.objects.get_or_create(restaurant_owner=o, defaults={
                'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        self.acc = MobileMoneyAccount(owner=self.main, provider='mpesa_daraja', enabled=True)
        self.acc.credentials = {'consumer_key': 'ck', 'consumer_secret': 'cs', 'shortcode': '174379',
                                'passkey': 'pk', 'till_number': ''}
        self.acc.save()
        self._n = 0

    # ---------- helpers ----------
    def _order(self, total='1500', customer=None):
        self._n += 1
        return Order.objects.create(order_number=f'M{self._n}', ordered_by=customer or self.cust,
                                    restaurant_owner=self.main, order_type='pickup', status='served',
                                    total_amount=Decimal(total))

    def _start(self, order, user=None, **body):
        self.client.force_login(user or self.cashier)
        body.setdefault('phone', '0712 345 678')
        url = (f'/orders/order/{order.id}/mobile-money/' if (user and user.is_customer())
               else f'/cashier/mobile-money/order/{order.id}/')
        return self.client.post(url, json.dumps(body), content_type='application/json')

    def _daraja_callback(self, checkout='ws_CO_1', receipt='QK12ABC', token=None):
        body = {'Body': {'stkCallback': {
            'MerchantRequestID': 'm1', 'CheckoutRequestID': checkout, 'ResultCode': 0, 'ResultDesc': 'ok',
            'CallbackMetadata': {'Item': [{'Name': 'Amount', 'Value': 1500},
                                          {'Name': 'MpesaReceiptNumber', 'Value': receipt}]}}}}
        return self.client.post(f'/cashier/mm-callback/mpesa_daraja/{token or self.acc.webhook_token}/',
                                json.dumps(body), content_type='application/json')

    # ---------- phone numbers ----------
    def test_phone_numbers(self):
        for raw in ('0712345678', '712345678', '+254 712 345 678', '00254712345678', '254-712-345-678'):
            self.assertEqual(svc.normalize_phone(raw, 'KES'), '254712345678', raw)
        self.assertEqual(svc.normalize_phone('0754 111 222', 'TZS'), '255754111222')
        self.assertEqual(svc.local_phone('255754111222', 'TZS'), '0754111222')
        for bad in ('', '12345', '0712 345 67', '+255712345678'):
            with self.assertRaises(ValidationError, msg=bad):
                svc.normalize_phone(bad, 'KES')

    # ---------- M-Pesa (Daraja) ----------
    def test_mpesa_request_is_correct(self):
        o = self._order()
        r = self._start(o)
        self.assertEqual(r.status_code, 200, r.content)
        stk = [c for c in self.fake.calls if c[1].endswith('processrequest')][0]
        self.assertTrue(stk[1].startswith('https://sandbox.safaricom.co.ke'))
        self.assertEqual(stk[2]['Authorization'], 'Bearer tok123')
        b = stk[3]
        self.assertEqual((b['BusinessShortCode'], b['PartyB'], b['TransactionType']),
                         ('174379', '174379', 'CustomerPayBillOnline'))
        self.assertEqual((b['Amount'], b['PartyA'], b['PhoneNumber']), (1500, '254712345678', '254712345678'))
        self.assertEqual(base64.b64decode(b['Password']).decode(), f"174379pk{b['Timestamp']}")
        self.assertEqual(len(b['Timestamp']), 14)
        self.assertEqual(b['CallBackURL'], f'http://testserver/cashier/mm-callback/mpesa_daraja/{self.acc.webhook_token}/')
        self.assertEqual(MobileMoneyCharge.objects.get().provider_ref, 'ws_CO_1')

    def test_till_number_uses_buy_goods(self):
        creds = self.acc.credentials
        creds['till_number'] = '5551234'
        self.acc.credentials = creds
        self.acc.save()
        self._start(self._order())
        b = [c for c in self.fake.calls if c[1].endswith('processrequest')][0][3]
        self.assertEqual((b['TransactionType'], b['PartyB'], b['BusinessShortCode']),
                         ('CustomerBuyGoodsOnline', '5551234', '174379'))

    def test_callback_is_checked_with_safaricom_before_it_counts(self):
        o = self._order()
        self._start(o)
        self.fake.stk_result = None                     # Safaricom: still processing
        self.assertEqual(self._daraja_callback().json(), {'ResultCode': 0, 'ResultDesc': 'Accepted'})
        self.assertFalse(Payment.objects.exists())       # a forged "success" callback pays nothing
        self.fake.stk_result = '0'
        self._daraja_callback()
        p = Payment.objects.get()
        self.assertEqual((p.payment_method, p.amount, p.reference_number, p.processed_by),
                         ('digital', Decimal('1500.00'), 'QK12ABC', self.cashier))
        self.assertEqual(Order.objects.get(pk=o.pk).payment_status, 'paid')
        self._daraja_callback()                         # Safaricom resends: still one payment
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self._daraja_callback(token='wrong').status_code, 404)

    def test_polling_cancelled_and_expired(self):
        o = self._order()
        charge_id = self._start(o).json()['id']
        self.fake.stk_result = '1032'
        r = self.client.get(f'/cashier/mobile-money/charge/{charge_id}/').json()
        self.assertEqual(r['status'], 'cancelled')
        self.assertFalse(Payment.objects.exists())
        o2 = self._order()
        cid = self._start(o2).json()['id']
        self.fake.stk_result = None
        MobileMoneyCharge.objects.filter(pk=cid).update(created_at=timezone.now() - datetime.timedelta(minutes=6))
        self.assertEqual(self.client.get(f'/cashier/mobile-money/charge/{cid}/').json()['status'], 'expired')

    def test_refusals(self):
        o = self._order(total='1500.50')
        self.assertEqual(self._start(o).status_code, 400)                      # M-Pesa: whole amounts
        o = self._order()
        self.assertEqual(self._start(o, amount='2000').status_code, 400)       # more than due
        self.assertEqual(self._start(o, phone='123').status_code, 400)
        self.assertEqual(self._start(o).status_code, 200)
        self.assertEqual(self._start(o).status_code, 400)                      # one waiting request at a time
        c = self._order()
        Order.objects.filter(pk=c.pk).update(status='cancelled')
        self.assertEqual(self._start(c).status_code, 400)
        MobileMoneyAccount.objects.filter(pk=self.acc.pk).update(enabled=False)
        self.assertEqual(self._start(self._order()).status_code, 400)

    def test_cash_paid_meanwhile_records_only_what_was_due(self):
        o = self._order()
        self._start(o)
        Payment.objects.create(order=o, amount=Decimal('1000'), payment_method='cash', processed_by=self.cashier)
        self.fake.stk_result = '0'
        self._daraja_callback()
        mm = Payment.objects.get(payment_method='digital')
        self.assertEqual(mm.amount, Decimal('500.00'))
        self.assertIn('refund 1000.00 to 254712345678', MobileMoneyCharge.objects.get().failure_reason)
        self.client.force_login(self.cashier)
        s = self.client.get(f'/cashier/mobile-money/charge/{MobileMoneyCharge.objects.get().id}/').json()
        self.assertTrue(s['needs_refund'])

    def test_customer_pays_own_order(self):
        o = self._order()
        r = self._start(o, user=self.cust)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(MobileMoneyCharge.objects.get().initiated_by, self.cust)
        self.fake.stk_result = '0'
        self._daraja_callback()
        self.assertEqual(Payment.objects.get().processed_by, self.main)        # staff field: the owner
        self.client.force_login(self.cust2)
        self.assertEqual(self.client.post(f'/orders/order/{o.id}/mobile-money/', '{}',
                                          content_type='application/json').status_code, 404)
        MobileMoneyAccount.objects.filter(pk=self.acc.pk).update(allow_customer_payments=False)
        self.assertEqual(self._start(self._order(), user=self.cust).status_code, 400)

    def test_other_restaurant_staff_blocked(self):
        o = self._order()
        intruder = User.objects.create_user('ic', password='pw12345!x', role=role('cashier'), owner=self.other)
        self.assertEqual(self._start(o, user=intruder).status_code, 404)
        charge_id = self._start(o).json()['id']
        self.client.force_login(intruder)
        self.assertEqual(self.client.get(f'/cashier/mobile-money/charge/{charge_id}/').status_code, 404)
        self.client.force_login(self.cust2)
        self.assertIn(self.client.get(f'/orders/mobile-money/{charge_id}/').status_code, (403, 404))

    def test_app_endpoints(self):
        o = self._order()
        api = APIClient()
        api.force_authenticate(self.cashier)
        info = api.get(f'/api/v1/orders/{o.id}/mobile-money/').json()
        self.assertEqual((info['enabled'], info['whole_amounts_only'], info['customer_phone']), (True, True, '0712345678'))
        r = api.post(f'/api/v1/orders/{o.id}/mobile-money/', {'phone': '0712345678'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.fake.stk_result = '0'
        s = api.get(f"/api/v1/mobile-money/{r.json()['id']}/").json()
        self.assertEqual(s['status'], 'successful')
        self.assertEqual(Order.objects.get(pk=o.pk).payment_status, 'paid')

    # ---------- review fixes ----------
    def test_views_never_hold_a_transaction_while_calling_providers(self):
        from cashier import views_mobile_money as v
        for view in (v.start_web, v.charge_status_web, v.start_api, v.charge_status_api, v.provider_callback):
            self.assertTrue(getattr(view, '_non_atomic_requests', None), view)

    def _timeout_on(self, url_part):
        real = self.fake.__call__

        def flaky(method, url, headers=None, body=None, form=None, timeout=None):
            if url_part in url:
                self.fake.calls.append((method, url, headers or {}, body))
                raise svc.ProviderError('No answer', uncertain=True)
            return real(method, url, headers, body, form)
        return mock.patch('cashier.mobile_money._http', side_effect=flaky)

    def test_mpesa_timeout_then_callback_matched_by_phone_and_amount(self):
        o = self._order()
        with self._timeout_on('processrequest'):
            r = self._start(o).json()
        self.assertIn('warning', r)
        charge = MobileMoneyCharge.objects.get()
        self.assertEqual((charge.status, charge.provider_ref), ('unknown', ''))
        self.assertEqual(self._start(o).status_code, 400)          # no second prompt while it may still come
        self.fake.stk_result = '0'
        body = {'Body': {'stkCallback': {'CheckoutRequestID': 'ws_CO_late', 'ResultCode': 0, 'CallbackMetadata': {
            'Item': [{'Name': 'Amount', 'Value': 1500}, {'Name': 'MpesaReceiptNumber', 'Value': 'QLATE1'},
                     {'Name': 'PhoneNumber', 'Value': 254712345678}]}}}}
        self.client.post(f'/cashier/mm-callback/mpesa_daraja/{self.acc.webhook_token}/', json.dumps(body),
                         content_type='application/json')
        p = Payment.objects.get()
        self.assertEqual((p.reference_number, Order.objects.get(pk=o.pk).payment_status), ('QLATE1', 'paid'))

    def test_flutterwave_timeout_stays_pending_and_resolves(self):
        self._flutterwave('TZS')
        o = self._order(total='15000')
        with self._timeout_on('charges?type='):
            self._start(o, phone='0754111222')
        self.assertEqual(MobileMoneyCharge.objects.get().status, 'pending')
        self.fake.calls.clear()
        with mock.patch.object(self.fake, '__call__'):
            pass
        cid = MobileMoneyCharge.objects.get().id

        def by_ref(method, url, headers=None, body=None, form=None, timeout=None):
            if '/transactions?tx_ref=' in url:
                return 200, {'status': 'success', 'data': [{'id': 777}]}
            return self.fake(method, url, headers, body, form)
        with mock.patch('cashier.mobile_money._http', side_effect=by_ref):
            self.assertEqual(self.client.get(f'/cashier/mobile-money/charge/{cid}/').json()['status'], 'successful')

    def test_late_payment_after_expiry_still_counts_and_receipt_kept(self):
        o = self._order()
        cid = self._start(o).json()['id']
        self.fake.stk_result = None
        MobileMoneyCharge.objects.filter(pk=cid).update(created_at=timezone.now() - datetime.timedelta(minutes=6))
        self.client.get(f'/cashier/mobile-money/charge/{cid}/')
        self.assertEqual(MobileMoneyCharge.objects.get().status, 'expired')
        self.fake.stk_result = '0'
        self._daraja_callback(receipt='QLATE2')                     # Safaricom says: it was paid after all
        self.assertEqual(Payment.objects.get().reference_number, 'QLATE2')

    def test_receipt_added_when_poll_settled_first(self):
        o = self._order()
        cid = self._start(o).json()['id']
        self.fake.stk_result = '0'
        self.client.get(f'/cashier/mobile-money/charge/{cid}/')      # poll wins: no receipt yet
        self.assertEqual(Payment.objects.get().reference_number, 'ws_CO_1')
        self._daraja_callback(receipt='QRCPT9')
        self.assertEqual(Payment.objects.get().reference_number, 'QRCPT9')
        self.assertEqual(MobileMoneyCharge.objects.get().receipt, 'QRCPT9')

    def test_status_polls_are_throttled_and_errors_contained(self):
        o = self._order()
        cid = self._start(o).json()['id']
        self.fake.calls.clear()
        for _ in range(3):
            self.client.get(f'/cashier/mobile-money/charge/{cid}/')
        self.assertEqual(len([c for c in self.fake.calls if c[1].endswith('/query')]), 1)
        MobileMoneyCharge.objects.filter(pk=cid).update(last_checked_at=None)
        self.acc.credentials = {}                                    # unreadable keys after a key change
        self.acc.save()
        r = self.client.get(f'/cashier/mobile-money/charge/{cid}/')
        self.assertEqual((r.status_code, r.json()['status']), (200, 'pending'))

    def test_nan_amount_and_customer_only_own_numbers(self):
        o = self._order()
        self.assertEqual(self._start(o, amount='NaN').status_code, 400)
        self.assertEqual(self._start(o, user=self.cust, phone='0799 999 999').status_code, 400)
        self.assertEqual(self._start(o, user=self.cust, phone='+254 712 345 678').status_code, 200)

    def test_branch_with_disabled_account_never_uses_main_account(self):
        bown = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'), owner=self.main)
        Restaurant.objects.create(name='Branch', address='b', main_owner=self.main, branch_owner=bown,
                                  is_main_restaurant=False, parent_restaurant=self.r, qr_code='QRBR')
        self.assertEqual(svc.account_for_owner(bown), self.acc)                # no own account: main's
        MobileMoneyAccount.objects.create(owner=bown, provider='mpesa_daraja', enabled=False)
        self.assertIsNone(svc.account_for_owner(bown))

    def test_sweeper_settles_forgotten_requests(self):
        from django.core.management import call_command
        o = self._order()
        self._start(o)
        self.fake.stk_result = '0'
        MobileMoneyCharge.objects.update(last_checked_at=None)
        call_command('check_mobile_money')
        self.assertEqual(Order.objects.get(pk=o.pk).payment_status, 'paid')

    def test_public_base_url_setting(self):
        from django.test import override_settings
        with override_settings(PUBLIC_BASE_URL='https://hospitality.example.com'):
            self._start(self._order())
        b = [c for c in self.fake.calls if c[1].endswith('processrequest')][-1][3]
        self.assertTrue(b['CallBackURL'].startswith('https://hospitality.example.com/cashier/mm-callback/mpesa_daraja/'))

    # ---------- Flutterwave ----------
    def _flutterwave(self, currency='TZS'):
        Restaurant.objects.filter(pk=self.r.pk).update(currency_code=currency)
        self.acc.provider = 'flutterwave'
        self.acc.credentials = {'secret_key': 'FLWSECK_TEST-x', 'secret_hash': 'myhash'}
        self.acc.save()

    def test_flutterwave_tanzania_and_signed_webhook(self):
        self._flutterwave('TZS')
        o = self._order(total='15000')
        r = self._start(o, phone='0754 111 222')
        self.assertEqual(r.status_code, 200, r.content)
        call = [c for c in self.fake.calls if 'charges?type=' in c[1]][0]
        self.assertIn('type=mobile_money_tanzania', call[1])
        self.assertEqual((call[3]['phone_number'], call[3]['currency'], call[3]['email']), ('0754111222', 'TZS', 'c@x.test'))
        charge = MobileMoneyCharge.objects.get()
        hook = {'event': 'charge.completed', 'data': {'id': 777, 'tx_ref': charge.reference, 'status': 'successful'}}
        url = f'/cashier/mm-callback/flutterwave/{self.acc.webhook_token}/'
        self.assertEqual(self.client.post(url, json.dumps(hook), content_type='application/json',
                                          HTTP_VERIF_HASH='wrong').status_code, 401)
        self.assertFalse(Payment.objects.exists())
        self.client.post(url, json.dumps(hook), content_type='application/json', HTTP_VERIF_HASH='myhash')
        self.assertEqual(Payment.objects.get().reference_number, 'FLW-REF-9')

    def test_flutterwave_verify_mismatch_is_refused(self):
        self._flutterwave('TZS')
        o = self._order(total='15000')
        self._start(o, phone='0754111222')
        self.fake.flw_verify = {'status': 'successful', 'amount': 100.0}           # paid less than asked
        cid = MobileMoneyCharge.objects.get().id
        self.assertEqual(self.client.get(f'/cashier/mobile-money/charge/{cid}/').json()['status'], 'failed')
        self.assertFalse(Payment.objects.exists())

    def test_flutterwave_uganda_needs_network_and_returns_approval_link(self):
        self._flutterwave('UGX')
        self.fake.flw_start = {'status': 'success', 'message': 'Charge initiated',
                               'meta': {'authorization': {'mode': 'redirect', 'redirect': 'https://pay.example/x'}}}
        o = self._order(total='15000')
        self.assertEqual(self._start(o, phone='0772111222').status_code, 400)          # no network
        r = self._start(o, phone='0772111222', network='MTN').json()
        self.assertEqual(r['redirect_url'], 'https://pay.example/x')

    def test_wrong_currency_for_provider(self):
        Restaurant.objects.filter(pk=self.r.pk).update(currency_code='TZS')       # Daraja is Kenya only
        self.assertEqual(self._start(self._order()).status_code, 400)

    # ---------- settings ----------
    def test_settings_page_encrypts_and_keeps_secrets(self):
        self.client.force_login(self.main)
        self.client.post('/cashier/mobile-money/settings/', {
            'provider': 'mpesa_daraja', 'consumer_key': 'newkey', 'consumer_secret': '', 'shortcode': '600000',
            'passkey': '', 'till_number': '', 'environment': 'live', 'enabled': 'on', 'allow_customer_payments': 'on'})
        acc = MobileMoneyAccount.objects.get(owner=self.main)
        self.assertEqual(acc.credentials['consumer_secret'], 'cs')        # empty secret field keeps the old one
        self.assertEqual((acc.credentials['consumer_key'], acc.environment), ('newkey', 'live'))
        self.assertNotIn('newkey', acc.credentials_encrypted)               # stored encrypted
        page = self.client.get('/cashier/mobile-money/settings/').content.decode()
        self.assertNotIn('"pk"', page)
        self.assertIn(acc.webhook_token, page)
        r = self.client.post('/cashier/mobile-money/settings/', {
            'provider': 'flutterwave', 'secret_key': '', 'secret_hash': '', 'enabled': 'on', 'action': 'test'})
        acc.refresh_from_db()
        self.assertFalse(acc.enabled)                                     # incomplete → switched off
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get('/cashier/mobile-money/settings/').status_code, 302)

    def test_loyalty_points_earned_on_mobile_money(self):
        from cashier.models_loyalty import LoyaltyProgram
        from cashier import loyalty
        LoyaltyProgram.objects.create(owner=self.main, enabled=True, spend_per_point=Decimal('100'))
        o = self._order()
        self._start(o)
        self.fake.stk_result = '0'
        self._daraja_callback()
        self.assertEqual(loyalty.balance(self.main, self.cust), 15)

    # ---------- final deep-scan fixes ----------
    def _poll(self, cid):
        MobileMoneyCharge.objects.filter(pk=cid).update(last_checked_at=None)
        return self.client.get(f'/cashier/mobile-money/charge/{cid}/').json()

    def test_unknown_daraja_code_keeps_waiting_and_success_after_failed_still_counts(self):
        o = self._order()
        cid = self._start(o).json()['id']
        self.fake.stk_result = '4999'                                 # "still under processing"
        self.assertEqual(self._poll(cid)['status'], 'pending')
        self.fake.stk_result = '1'                                    # insufficient balance: final
        self.assertEqual(self._poll(cid)['status'], 'failed')
        self.fake.stk_result = '0'                                    # … then the customer paid after all
        self._daraja_callback(receipt='QAFTER1')
        self.assertEqual(Payment.objects.get().reference_number, 'QAFTER1')
        self.assertEqual(Order.objects.get(pk=o.pk).payment_status, 'paid')
        self.assertEqual(MobileMoneyCharge.objects.get().status, 'successful')

    def test_start_server_error_is_uncertain_not_failed(self):
        def gateway(method, url, headers=None, body=None, form=None, timeout=None):
            if url.endswith('processrequest'):
                return 502, {}
            return self.fake(method, url, headers, body, form)
        o = self._order()
        with mock.patch('cashier.mobile_money._http', side_effect=gateway):
            r = self._start(o).json()
        self.assertIn('warning', r)
        self.assertEqual(MobileMoneyCharge.objects.get().status, 'unknown')

        self._flutterwave('TZS')
        o2 = self._order(total='15000')
        def flw_gateway(method, url, headers=None, body=None, form=None, timeout=None):
            if 'charges?type=' in url:
                return 504, {}
            return self.fake(method, url, headers, body, form)
        with mock.patch('cashier.mobile_money._http', side_effect=flw_gateway):
            self._start(o2, phone='0754111222')
        self.assertEqual(MobileMoneyCharge.objects.get(order=o2).status, 'pending')

    def test_mpesa_login_timeout_is_a_plain_failure(self):
        o = self._order()
        with self._timeout_on('/oauth/v1/generate'):
            r = self._start(o)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(MobileMoneyCharge.objects.get().status, 'failed')
        self.assertFalse([c for c in self.fake.calls if c[1].endswith('processrequest')])
        self.assertEqual(self._start(o).status_code, 200)              # the cashier can retry at once

    def test_money_on_cancelled_order_is_flagged_for_refund(self):
        o = self._order()
        cid = self._start(o).json()['id']
        Order.objects.filter(pk=o.pk).update(status='cancelled')
        self.fake.stk_result = '0'
        c = self._poll(cid)
        self.assertEqual((c['status'], c['needs_refund']), ('successful', True))
        self.assertIn('cancelled', c['message'])
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(Order.objects.get(pk=o.pk).payment_status, 'unpaid')

    def test_cannot_switch_provider_while_a_request_is_open(self):
        self._start(self._order())
        self.client.force_login(self.main)
        self.client.post('/cashier/mobile-money/settings/', {
            'provider': 'flutterwave', 'secret_key': 'x', 'secret_hash': 'y', 'enabled': 'on'})
        acc = MobileMoneyAccount.objects.get(owner=self.main)
        self.assertEqual((acc.provider, acc.credentials['shortcode']), ('mpesa_daraja', '174379'))

    def test_customer_pays_whole_shillings_and_is_rate_limited(self):
        o = self._order(total='1500.50')
        self.client.force_login(self.cust)
        info = self.client.get(f'/orders/order/{o.id}/mobile-money/').json()
        self.assertEqual(info['balance_due'], '1500')
        r = self._start(o, user=self.cust, phone='0712345678', amount='9999')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(MobileMoneyCharge.objects.get().amount, Decimal('1500.00'))
        MobileMoneyCharge.objects.update(status='failed')
        for _ in range(4):
            MobileMoneyCharge.objects.create(account=self.acc, provider='mpesa_daraja', order=o, amount=1,
                                             currency='KES', phone='254712345678', status='failed',
                                             reference=f'R{MobileMoneyCharge.objects.count()}', initiated_by=self.cust)
        r = self._start(self._order(), user=self.cust, phone='0712345678')
        self.assertEqual(r.status_code, 400)

    def test_callback_receipt_kept_while_safaricom_still_processing(self):
        o = self._order()
        cid = self._start(o).json()['id']
        self.fake.stk_result = None                                   # status query: still processing
        self._daraja_callback(receipt='QEARLY1')
        self.assertEqual(MobileMoneyCharge.objects.get().status, 'pending')
        self.fake.stk_result = '0'
        self._poll(cid)
        self.assertEqual(Payment.objects.get().reference_number, 'QEARLY1')

    def test_open_request_is_returned_so_screens_can_follow_it(self):
        o = self._order()
        cid = self._start(o).json()['id']
        info = self.client.get(f'/cashier/mobile-money/order/{o.id}/').json()
        self.assertEqual(info['open_charge']['id'], cid)
        self.fake.stk_result = '1032'
        self._poll(cid)
        self.assertIsNone(self.client.get(f'/cashier/mobile-money/order/{o.id}/').json()['open_charge'])

    def test_sweep_skips_recently_checked_timed_out_charges_and_closes_final_ones(self):
        o = self._order()
        cid = self._start(o).json()['id']
        MobileMoneyCharge.objects.filter(pk=cid).update(status='expired', last_checked_at=timezone.now())
        self.fake.calls.clear()
        svc.sweep()
        self.assertFalse([c for c in self.fake.calls if c[1].endswith('/query')])   # backed off
        MobileMoneyCharge.objects.filter(pk=cid).update(last_checked_at=timezone.now() - datetime.timedelta(minutes=20))
        self.fake.stk_result = '1032'
        svc.sweep()
        self.assertEqual(MobileMoneyCharge.objects.get().status, 'cancelled')       # final: no more asking
        self.fake.calls.clear()
        svc.sweep(seconds=0)
        self.assertFalse([c for c in self.fake.calls if c[1].endswith('/query')])
