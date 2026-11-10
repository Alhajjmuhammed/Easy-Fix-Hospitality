"""
Money consistency regression tests: every screen that shows money must agree with the stored
orders and payments.

- MoneyScenarioTests: one full trading day, then every report, dashboard, receipt, export and
  app endpoint is compared with ground truth computed from the stored rows.
- The focused tests below pin each fixed bug:
  1  main owner who also runs a branch himself: no doubled rows / MultipleObjectsReturned
  2  offline add-items keeps the order's charged tax rate
  3  a happy-hour promotion never reaches dishes without a sub-category
  4  app / customer-care reports leave out cancelled (not-sold) orders
  5  reports of a branch the main owner runs himself don't get the main restaurant's orders
  6  total_items = quantity sum (not collapsed by DISTINCT)
  7  dashboard tax under an item filter uses each order's charged rate
  8  receipt tax % label = charged rate
  9  payment-method breakdowns add up to the money collected
  10 cashier cancel of handed-over food gives no stock back
  11 cashier web report items = quantities of sold orders
  12 printed receipt shows the balance due
  13 loyalty: whole points, credited = points x value
  14 add-items total = compute_total(new subtotal, charged rate)
  15 OrderSerializer.restaurant_id

Run:  python manage.py test orders.tests_money_consistency
"""
import sys
if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None

import datetime
import json
import re
from decimal import Decimal as D, ROUND_HALF_UP
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.db.models import Sum
from django.test import TestCase, Client, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import Role, User, RestaurantSubscription, Feature
from accounts.permissions_defaults import ALL_FEATURES
from restaurant.models_restaurant import Restaurant
from restaurant.models import TableInfo, MainCategory, SubCategory, Product, HappyHourPromotion
from orders.models import Order, OrderItem
from cashier.models import Payment
from cashier.models_loyalty import LoyaltyProgram, LoyaltyTransaction
from cashier.models_mobile_money import MobileMoneyAccount, MobileMoneyCharge
from inventory.models import InventoryItem, InventoryRecord, RecipeIngredient

OUT = []


def note(*a):
    OUT.append(' '.join(str(x) for x in a))


def role(name):
    return Role.objects.get_or_create(name=name)[0]


def q2(x):
    return D(str(x)).quantize(D('0.01'), rounding=ROUND_HALF_UP)


class capture:
    """Grab the context dict a views module passes to render()."""
    def __init__(self, module, name='render'):
        self.module, self.name, self.ctx = module, name, {}

    def __enter__(self):
        self.real = getattr(self.module, self.name)

        def fake(request, template, context=None, *a, **k):
            self.ctx.clear(); self.ctx.update(context or {})
            return self.real(request, template, context, *a, **k)
        setattr(self.module, self.name, fake)
        return self.ctx

    def __exit__(self, *exc):
        setattr(self.module, self.name, self.real)


class FakeProvider:
    def __init__(self):
        self.stk_result = None

    def __call__(self, method, url, headers=None, body=None, form=None, timeout=None):
        if '/oauth/v1/generate' in url:
            return 200, {'access_token': 'tok123', 'expires_in': '3599'}
        if url.endswith('/mpesa/stkpush/v1/processrequest'):
            n = MobileMoneyCharge.objects.count()
            return 200, {'MerchantRequestID': 'm1', 'CheckoutRequestID': f'ws_CO_{n}', 'ResponseCode': '0',
                         'ResponseDescription': 'Success', 'CustomerMessage': 'ok'}
        if url.endswith('/mpesa/stkpushquery/v1/query'):
            if self.stk_result is None:
                return 500, {'errorCode': '500.001.1001', 'errorMessage': 'The transaction is being processed'}
            return 200, {'ResultCode': self.stk_result, 'ResultDesc': 'desc'}
        raise AssertionError(f'unexpected call {url}')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class MoneyScenarioTests(TestCase):
    """A full day of orders (partial/split/voided payments, offline orders, a tax change,
    loyalty, M-Pesa, cancellations, a branch the main owner runs himself and a branch with
    its own owner), then EVERY money screen is checked against the stored rows."""
    maxDiff = None

    def setUp(self):
        cache.clear()
        self.fake = FakeProvider()
        for target, kw in (('cashier.mobile_money._http', {'side_effect': self.fake}),
                           ('orders.push.send_push', {}),
                           ('cashier.views.auto_print_receipt', {'return_value': {'receipt_printed': False}}),
                           ('orders.printing.auto_print_receipt', {'return_value': {'receipt_printed': False}}),
                           ('orders.printing.auto_print_order', {'return_value': {}}),
                           ('orders.printing.auto_print_new_items', {'return_value': {}}),
                           ('orders.views.auto_print_order', {'return_value': {}}),
                           ('orders.views.auto_print_new_items', {'return_value': {}}),
                           ('mobile_api.views.orders._notify_ws', {}),
                           ('mobile_api.views.payments._notify_ws', {}),
                           ('mobile_api.views.sync._notify_ws', {})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        for slug, name, desc, cat in ALL_FEATURES:
            Feature.objects.get_or_create(slug=slug, defaults={'name': name, 'description': desc, 'category': cat})
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.M = mk('main', 'main_owner', restaurant_name='Main R', currency_code='KES')
        self.B = mk('bown', 'branch_owner', owner=self.M, restaurant_name='Branch3', currency_code='KES')
        self.C = mk('cash', 'cashier', owner=self.M, first_name='Cash')
        self.C2 = mk('cash2', 'cashier', owner=self.M, first_name='Cash2')
        self.CC = mk('cc', 'customer_care', owner=self.M)
        self.K = mk('kit', 'kitchen', owner=self.M)
        self.CB = mk('cashb', 'cashier', owner=self.B)
        self.U = mk('cust', 'customer', phone_number='0712 345 678', first_name='Asha', last_name='K')
        today = datetime.date.today()
        RestaurantSubscription.objects.create(restaurant_owner=self.M, subscription_start_date=today,
                                              subscription_end_date=today + datetime.timedelta(days=30))
        self.R1 = Restaurant.objects.create(name='Main R', address='a', main_owner=self.M, branch_owner=self.M,
                                            is_main_restaurant=True, qr_code='QR1', tax_rate=D('0.1600'),
                                            currency_code='KES', allow_remote_orders=True, subscription_plan='PRO',
                                            delivery_fee=D('200.00'), delivery_fee_taxable=False)
        self.R2 = Restaurant.objects.create(name='Self Branch', address='b', main_owner=self.M, branch_owner=self.M,
                                            is_main_restaurant=False, parent_restaurant=self.R1, qr_code='QR2',
                                            tax_rate=D('0.0000'), currency_code='KES')
        self.R3 = Restaurant.objects.create(name='Branch3', address='c', main_owner=self.M, branch_owner=self.B,
                                            is_main_restaurant=False, parent_restaurant=self.R1, qr_code='QR3',
                                            tax_rate=D('0.1800'), currency_code='KES')
        self.T1 = TableInfo.objects.create(restaurant=self.R1, owner=self.M, tbl_no='T1')
        self.T2 = TableInfo.objects.create(restaurant=self.R1, owner=self.M, tbl_no='T2')
        self.T5 = TableInfo.objects.create(restaurant=self.R2, owner=self.M, tbl_no='S5')
        self.T9 = TableInfo.objects.create(restaurant=self.R3, owner=self.B, tbl_no='B9')
        c1 = MainCategory.objects.create(restaurant=self.R1, owner=self.M, name='Food1')
        c2 = MainCategory.objects.create(restaurant=self.R2, owner=self.M, name='Food2')
        c3 = MainCategory.objects.create(restaurant=self.R3, owner=self.B, name='Food3')
        subs = {c.id: SubCategory.objects.create(main_category=c, name='Sub' + c.name) for c in (c1, c2, c3)}
        P = lambda c, n, price, st, stock: Product.objects.create(
            name=n, description='d', main_category=c, sub_category=subs[c.id], price=D(price),
            available_in_stock=stock, station=st)
        self.pilau = P(c1, 'Pilau', '1234.56', 'kitchen', 10)
        self.soda = P(c1, 'Soda', '150.50', 'bar', 0)        # stock not counted
        self.chips = P(c1, 'Chips', '333.33', 'kitchen', 3)   # happy hour 15%
        self.tea = P(c2, 'Tea', '100.00', 'bar', 5)
        self.ugali = P(c3, 'Ugali', '500.00', 'kitchen', 20)
        promo = HappyHourPromotion.objects.create(owner=self.M, name='HH', discount_percentage=D('15'),
                                                  start_time=datetime.time(0, 0), end_time=datetime.time(23, 59, 59),
                                                  days_of_week='1,2,3,4,5,6,7')
        promo.products.add(self.chips)
        # recipe: 1 pilau uses 0.25 kg rice
        self.rice = InventoryItem.objects.create(owner=self.M, name='Rice', unit='kg', unit_price=D('2000'))
        InventoryRecord.objects.create(item=self.rice, record_type='opening', quantity_change=D('10'),
                                       recorded_by=self.M)
        RecipeIngredient.objects.create(product=self.pilau, item=self.rice, quantity=D('0.25'))
        LoyaltyProgram.objects.create(owner=self.M, enabled=True, spend_per_point=D('100'), point_value=D('10'),
                                      min_redeem_points=1)
        self.acc = MobileMoneyAccount(owner=self.M, provider='mpesa_daraja', enabled=True)
        self.acc.credentials = {'consumer_key': 'ck', 'consumer_secret': 'cs', 'shortcode': '174379',
                                'passkey': 'pk', 'till_number': ''}
        self.acc.save()

    # ---------------- helpers ----------------
    def api(self, user, **headers):
        c = APIClient(raise_request_exception=getattr(self, 'RAISE', True))
        c.force_authenticate(user)
        c.credentials(HTTP_X_APP_FEATURES='delivery-fee', **headers)
        return c

    def place(self, user, items, table=None, otype='dine-in', **extra):
        body = {'items': [{'product_id': p.id, 'quantity': q, 'price': float(p.get_current_price())} for p, q in items],
                'order_type': otype, **extra}
        if table is not None:
            body['table_id'] = table.id
        hdr = {}
        if user.is_customer():
            hdr['HTTP_X_RESTAURANT_ID'] = str(self.R1.id)
        r = self.api(user, **hdr).post('/api/v1/orders/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return Order.objects.get(pk=r.json()['order']['id'])

    def webpay(self, order, amount, method='cash', user=None, **extra):
        self.client.force_login(user or self.C)
        r = self.client.post(f'/cashier/process-payment/{order.id}/', json.dumps(
            {'amount': str(q2(amount)), 'payment_method': method, **extra}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def apipay(self, order, amount, method='cash', user=None, **extra):
        r = self.api(user or self.C).post('/api/v1/payments/', {'order_id': order.id, 'amount': str(q2(amount)),
                                                               'payment_method': method, **extra}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def status(self, order, *steps):
        self.client.force_login(self.K)
        for s in steps:
            r = self.client.post(f'/orders/update-status/{order.id}/', json.dumps({'status': s}),
                                 content_type='application/json').json()
            self.assertTrue(r.get('success'), (s, r))

    def R(self, o):
        o.refresh_from_db()
        return o

    # ---------------- the day ----------------
    def run_day(self):
        S = {}
        # O1: R1 T1, partial cash on web, add items in app, rest by card in app
        o1 = self.place(self.C, [(self.pilau, 2), (self.soda, 1)], table=self.T1)
        S['o1_total_initial'] = o1.total_amount
        self.webpay(o1, '1000')
        r = self.api(self.C).post(f'/api/v1/orders/{o1.id}/add-items/', {'items': [
            {'product_id': self.chips.id, 'quantity': 1, 'price': 283.33}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o1 = self.R(o1)
        self.apipay(o1, o1.total_amount - D('1000'), 'card')
        self.status(o1, 'confirmed', 'preparing', 'ready', 'served')
        S['o1'] = o1

        # O2: split by items, void, re-pay
        o2 = self.place(self.C, [(self.pilau, 3), (self.soda, 2)], table=self.T2)
        self.client.force_login(self.C)
        items = {i.product_id: i for i in o2.order_items.all()}
        self.webpay(o2, '0.01', selected_items=[{'id': items[self.pilau.id].id, 'quantity': 2}])
        card = self.webpay(o2, '0.01', 'card', selected_items=[{'id': items[self.soda.id].id, 'quantity': 2}])
        o2 = self.R(o2)
        rest = o2.total_amount - Payment.objects.filter(order=o2, is_voided=False).aggregate(t=Sum('amount'))['t']
        self.webpay(o2, rest, 'digital')
        self.client.force_login(self.C)
        r = self.client.post(f'/cashier/void-payment/{card["payment_id"]}/', json.dumps({'reason': 'wrong card'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        S['o2_status_after_void'] = self.R(o2).payment_status
        S['t2_after_void'] = TableInfo.objects.get(pk=self.T2.pk).is_available
        note("O2 PAYMENTS", list(Payment.objects.filter(order=o2).values_list("amount","payment_method","is_voided")), self.R(o2).total_amount)
        self.apipay(o2, self.R(o2).total_amount - Payment.objects.filter(order=o2, is_voided=False).aggregate(t=Sum("amount"))["t"], "cash")
        self.status(o2, 'confirmed', 'preparing')
        S['o2'] = self.R(o2)

        # O3: customer pickup, paid cash -> earns points
        o3 = self.place(self.U, [(self.pilau, 4)], otype='pickup')
        self.webpay(o3, o3.total_amount)
        S['o3'] = self.R(o3)

        # O4: walk-in, link customer, pay with points, pay rest, void points payment, pay again by card
        o4 = self.place(self.C, [(self.pilau, 1)], table=self.T1)
        self.client.force_login(self.C)
        r = self.client.post(f'/cashier/order-loyalty/{o4.id}/', json.dumps({'phone': '0712345678'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        from cashier.loyalty import redeem_code
        code = redeem_code(self.U)
        lp = self.webpay(o4, '500', 'loyalty', loyalty_code=code)
        o4 = self.R(o4)
        self.webpay(o4, o4.total_amount - D('500'), 'cash')
        S['pts_after_o4_paid'] = LoyaltyTransaction.objects.filter(customer=self.U).aggregate(t=Sum('points'))['t']
        r = self.api(self.C).post(f'/api/v1/payments/{lp["payment_id"]}/void/', {'reason': 'customer changed mind'},
                                  format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.apipay(self.R(o4), '500', 'card')
        S['o4'] = self.R(o4)

        # O5: offline order with stale prices + capped offline payment + extra not-recorded payment
        r = self.api(self.C).post('/api/v1/sync/push/', {
            'orders': [{'offline_id': 'off-5', 'table_id': self.T2.id, 'order_type': 'dine-in',
                        'items': [{'product_id': self.pilau.id, 'quantity': 1, 'unit_price': 1200},
                                  {'product_id': self.chips.id, 'quantity': 1, 'unit_price': 333.33}]}],
            'payments': [{'offline_id': 'pay-5a', 'order_offline_id': 'off-5', 'amount': '1778.66',
                          'payment_method': 'cash', 'accepts_not_recorded': True},
                         {'offline_id': 'pay-5b', 'order_offline_id': 'off-5', 'amount': '50.00',
                          'payment_method': 'cash', 'accepts_not_recorded': True}],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        S['sync5'] = r.json()['results']
        o5 = Order.objects.get(special_instructions__contains='[offline:off-5]')
        S['o5'] = o5

        # O8: customer delivery order with fee, paid by M-Pesa (whole shillings), cents left
        o8 = self.place(self.U, [(self.pilau, 1)], otype='delivery', delivery_phone='0712345678',
                        delivery_address='x', restaurant_id=self.R1.id)
        self.client.force_login(self.C)
        r = self.client.post(f'/cashier/mobile-money/order/{o8.id}/', json.dumps(
            {'phone': '0712345678', 'amount': str(int(o8.total_amount))}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        ch8 = r.json()['id']
        self.fake.stk_result = '0'
        st = self.client.get(f'/cashier/mobile-money/charge/{ch8}/').json()
        S['ch8'] = st
        S['o8'] = self.R(o8)

        # O9: pickup by cashier; M-Pesa requested, cash taken meanwhile, M-Pesa then succeeds -> refund flag
        self.fake.stk_result = None
        o9 = self.place(self.C, [(self.soda, 1)], otype='pickup')
        self.client.force_login(self.C)
        r = self.client.post(f'/cashier/mobile-money/order/{o9.id}/', json.dumps(
            {'phone': '0712345678', 'amount': '174'}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        ch9 = r.json()['id']
        self.webpay(o9, self.R(o9).total_amount, 'cash')
        self.fake.stk_result = '0'
        MobileMoneyCharge.objects.filter(pk=ch9).update(last_checked_at=None)
        S['ch9'] = self.client.get(f'/cashier/mobile-money/charge/{ch9}/').json()
        S['o9'] = self.R(o9)

        # O10: cancelled after preparing (chips stock)
        o10 = self.place(self.C, [(self.chips, 2), (self.pilau, 1)], table=self.T2)
        S['o10_lines'] = list(o10.order_items.values_list('product__name', 'quantity', 'stock_taken'))
        self.status(o10, 'confirmed', 'preparing')
        self.client.force_login(self.C)
        r = self.client.post(f'/cashier/cancel-order/{o10.id}/', json.dumps({'reason': 'customer left'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        S['o10'] = self.R(o10)

        # O6: offline order at old tax, then the TAX CHANGES (R1 16% -> 0%), then offline append
        r = self.api(self.C).post('/api/v1/sync/push/', {'orders': [
            {'offline_id': 'off-6', 'table_id': self.T1.id, 'items': [
                {'product_id': self.soda.id, 'quantity': 1, 'unit_price': 150.50}]}]}, format='json')
        o6 = Order.objects.get(special_instructions__contains='[offline:off-6]')
        S['o6_total_before'] = o6.total_amount
        # O7 placed before the change too, add items online after the change
        o7 = self.place(self.C, [(self.pilau, 1), (self.soda, 1)], table=self.T2)
        S['o7_total_before'] = o7.total_amount
        Restaurant.objects.filter(pk=self.R1.pk).update(tax_rate=D('0.0000'))
        r = self.api(self.C).post('/api/v1/sync/push/', {'orders': [
            {'offline_id': 'app-6', 'existing_order_id': o6.id, 'items': [
                {'product_id': self.pilau.id, 'quantity': 1, 'unit_price': 1234.56}]}]}, format='json')
        S['sync6'] = r.json()['results']
        o6 = self.R(o6)
        S['o6'] = o6
        # web item removal on O7 (soda) after the tax change
        soda7 = o7.order_items.get(product=self.soda)
        self.client.force_login(self.C)
        r = self.client.post(f'/orders/cancel-item/{soda7.id}/', json.dumps({'reason': 'x'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        o7 = self.R(o7)
        self.apipay(o7, o7.total_amount, 'cash')
        S['o7'] = self.R(o7)
        self.apipay(o6, o6.total_amount, 'cash')
        S['o6'] = self.R(o6)
        # O11 after the change: 0% tax
        o11 = self.place(self.C, [(self.pilau, 1)], table=self.T1)
        self.webpay(o11, o11.total_amount)
        S['o11'] = self.R(o11)

        # O12: main owner runs his own branch R2 (0% tax), pays it himself in the app
        o12 = self.place(self.M, [(self.tea, 2)], table=self.T5)
        self.apipay(o12, o12.total_amount, 'cash', user=self.M)
        S['o12'] = self.R(o12)

        # O13: branch R3 with its own owner, partial card
        o13 = self.place(self.CB, [(self.ugali, 3)], table=self.T9)
        self.apipay(o13, '770', 'card', user=self.CB)
        S['o13'] = self.R(o13)

        # O14: staff delivery order at R1 (0% now) with fee, unpaid
        o14 = self.place(self.C, [(self.soda, 2)], otype='delivery', delivery_phone='0700000000',
                         delivery_address='y', restaurant_id=self.R1.id)
        S['o14'] = self.R(o14)
        # O15: customer care order cancelled in the app; O16: CC order paid with legacy 'mobile' method
        o15 = self.place(self.CC, [(self.soda, 1)], otype='pickup')
        r = self.api(self.CC).post(f'/api/v1/orders/{o15.id}/cancel/', {'reason': 'dup'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o16 = self.place(self.CC, [(self.soda, 1)], otype='pickup')
        self.webpay(o16, o16.total_amount, 'mobile', user=self.CC)
        S['o15'], S['o16'] = self.R(o15), self.R(o16)
        for k, v in list(S.items()):
            if isinstance(v, Order):
                S[k] = self.R(v)
        return S

    def test_day(self):
        del OUT[:]
        self.diffs = []
        S = self.run_day()
        self.S = S
        self.check_all(S)
        # Owner decision (cashier/mobile_money.py): M-Pesa takes whole shillings and the order is
        # marked paid with the leftover cents unpaid. Not a bug: documented, so skipped here.
        o8 = S['o8'].order_number
        diffs = [d for d in self.diffs if 'mpesa cents rule' not in d and o8 not in d]
        http500 = [n for n in OUT if n.startswith('HTTP500')]
        self.assertEqual(diffs + http500, [], '\n'.join(OUT))

    # ---------------- checks ----------------
    def cmp(self, label, got, want):
        try:
            ok = q2(got) == q2(want)
        except Exception:
            ok = got == want
        OUT.append(f"{'OK  ' if ok else 'DIFF'} {label}: got={got} want={want}")
        if not ok:
            self.diffs.append(f'{label}: got={got} want={want}')
        return ok

    def truth(self, orders):
        """Ground truth from the stored rows of these orders."""
        sold = [o for o in orders if o.status not in ('cancelled', 'customer_refused', 'kitchen_error',
                                                    'quality_issue', 'wasted')]
        def paid(o):
            return sum((p.amount for p in o.payments.all() if not p.is_voided), D('0'))
        t = {
            'n': len(sold),
            'gross': sum((o.total_amount for o in sold), D('0')),
            'food': sum((o.get_subtotal() for o in sold), D('0')),
            'fees': sum((o.delivery_fee for o in sold), D('0')),
            'collected': sum((paid(o) for o in sold), D('0')),
            'collected_all': sum((paid(o) for o in orders), D('0')),
            'paid_gross': sum((o.total_amount for o in sold if o.payment_status == 'paid'), D('0')),
            'unpaid_gross': sum((o.total_amount for o in sold if o.payment_status == 'unpaid'), D('0')),
            'partial_gross': sum((o.total_amount for o in sold if o.payment_status == 'partial'), D('0')),
            'outstanding': sum((max(D('0'), o.total_amount - paid(o)) for o in sold), D('0')),
            'items_qty': sum((i.quantity for o in sold for i in o.order_items.all()), 0),
            'by_method': {},
        }
        t['tax'] = t['gross'] - t['food'] - t['fees']
        t['net'] = t['gross'] - t['tax']
        for o in sold:
            for p in o.payments.all():
                if not p.is_voided:
                    t['by_method'][p.payment_method] = t['by_method'].get(p.payment_method, D('0')) + p.amount
        return t

    def check_all(self, S):
        from orders.printing import _generate_receipt_content, _generate_bill_content
        from django.test import Client
        self.RAISE = False
        self.client = Client(raise_request_exception=False)
        _orig_get = self.client.get
        def _get(path, *a, **k):
            r = _orig_get(path, *a, **k)
            if r.status_code >= 500:
                note('HTTP500', path, a, k)
            return r
        self.client.get = _get
        allo = list(Order.objects.all().order_by('id'))
        T = self.truth(allo)
        note('TRUTH all', {k: v for k, v in T.items()})
        rest_of = {}
        for o in allo:
            if o.table_info_id:
                rest_of[o.id] = o.table_info.restaurant_id
            else:
                rest_of[o.id] = self.R1.id      # all remote orders were placed with R1 / main owner
        TR = {r.id: self.truth([o for o in allo if rest_of[o.id] == r.id]) for r in (self.R1, self.R2, self.R3)}
        for rid, t in TR.items():
            note('TRUTH rest', rid, {k: v for k, v in t.items() if k != 'by_method'}, t['by_method'])

        # ---------- 1. per-order invariants ----------
        expected_total = {
            'o1': '3367.42', 'o2': '4645.43', 'o3': '5728.36', 'o4': '1432.09', 'o5': '1760.75',
            'o6': '1606.67',  # soda+pilau at the 16% the order was charged (tax changed to 0% before the append)
            'o7': '1432.09', 'o8': '1632.09', 'o9': '174.58', 'o11': '1234.56', 'o12': '200.00',
            'o13': '1770.00', 'o14': '501.00', 'o16': '150.50',
        }
        for k, want in expected_total.items():
            self.cmp(f'order {k} total_amount', S[k].total_amount, D(want))
        for o in allo:
            lines = o.get_subtotal()
            paid = Payment.objects.filter(order=o, is_voided=False).aggregate(t=Sum('amount'))['t'] or D('0')
            st = 'paid' if paid >= o.total_amount else ('partial' if paid > 0 else 'unpaid')
            if o.status != 'cancelled':
                self.cmp(f'{o.order_number} payment_status vs payments (paid={paid} total={o.total_amount})',
                         o.payment_status, st)
            self.cmp(f'{o.order_number} total >= lines+fee', o.total_amount >= lines + o.delivery_fee, True)
        for t in TableInfo.objects.all():
            active = Order.objects.filter(table_info=t, status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
                                          payment_status__in=['unpaid', 'partial']).exists()
            self.cmp(f'table {t.tbl_no} is_available', t.is_available, not active)

        # ---------- 2. receipts ----------
        api = self.api(self.C)
        for pay in Payment.objects.select_related('order').order_by('id'):
            o = Order.objects.get(pk=pay.order_id)
            paid = Payment.objects.filter(order=o, is_voided=False).aggregate(t=Sum('amount'))['t'] or D('0')
            bal = max(D('0'), o.total_amount - paid)
            tag = f'receipt pay#{pay.id} {pay.payment_method} {pay.amount} {o.order_number}'
            from cashier import views as cviews
            self.client.force_login(self.M)
            with capture(cviews) as ctx:
                r = self.client.get(f'/cashier/receipt/{pay.id}/')
            if r.status_code == 200:
                self.cmp(tag + ' web total', ctx['order'].get_total(), o.total_amount)
                self.cmp(tag + ' web balance', ctx['remaining_balance'], bal)
                self.cmp(tag + ' web tax', ctx['order'].get_tax_amount(), o.total_amount - o.get_subtotal() - o.delivery_fee)
                html = r.content.decode()
                import re
                m = re.search(r'Tax \(([\d.]+)%\)', html)
                charged = (o.total_amount - o.get_subtotal() - o.delivery_fee)
                base = o.get_subtotal() + (o.delivery_fee if o.delivery_fee_taxed else 0)
                charged_pct = q2(charged / base * 100) if base else D('0')
                if m:
                    self.cmp(tag + ' web tax % label vs charged', D(m.group(1)), charged_pct.quantize(D('0.1')))
            else:
                note('web receipt status', pay.id, r.status_code)
            from orders import views as oviews
            with capture(oviews) as ctx2:
                r = self.client.get(f'/orders/customer-care/receipt/{pay.id}/')
            if r.status_code == 200:
                self.cmp(tag + ' cc total', ctx2['order'].get_total(), o.total_amount)
                self.cmp(tag + ' cc balance', ctx2['remaining_balance'], bal)
            else:
                note('cc receipt status', pay.id, r.status_code)
            txt = _generate_receipt_content(pay)
            import re
            mt = re.search(r'TOTAL:\s+\D*([\d.]+)', txt)
            self.cmp(tag + ' printed TOTAL', D(mt.group(1)) if mt else None, o.total_amount)
            printed_paid = sum(D(x) for x in re.findall(r'(?:Payment \([^)]*\)|  [A-Za-z /]+):\s+\D*([\d.]+)', txt))
            self.cmp(tag + ' printed payments sum', printed_paid, paid)
            mtax = re.search(r'Tax \(([\d.]+)%\):\s+\D*([\d.]+)', txt)
            if mtax:
                self.cmp(tag + ' printed tax', D(mtax.group(2)), o.total_amount - o.get_subtotal() - o.delivery_fee)
            mbal = re.search(r'BALANCE DUE:\s+\D*([\d.]+)', txt)
            self.cmp(tag + ' printed balance due', D(mbal.group(1)) if mbal else D('0'), bal)
            ar = api.get(f'/api/v1/payments/{pay.id}/receipt/')
            if ar.status_code >= 500: note('HTTP500 app receipt', pay.id)
            if ar.status_code == 200:
                j = ar.json()
                self.cmp(tag + ' app total', j['order']['total'], o.total_amount)
                self.cmp(tag + ' app total_paid', j['order']['total_paid'], paid)
                self.cmp(tag + ' app balance_due', j['order']['balance_due'], bal)
                self.cmp(tag + ' app remaining_balance', j['remaining_balance'], bal)
                self.cmp(tag + ' app tax', j['order']['tax_amount'], o.total_amount - o.get_subtotal() - o.delivery_fee)
            else:
                note('app receipt status', pay.id, ar.status_code, ar.content[:200])
        # customer's own receipt page
        for o in Order.objects.filter(ordered_by=self.U):
            self.client.force_login(self.U)
            from orders import views as oviews
            with capture(oviews) as ctx3:
                r = self.client.get(f'/orders/receipt/{o.id}/')
            if r.status_code == 200 and 'total_amount' in ctx3:
                paid = Payment.objects.filter(order=o, is_voided=False).aggregate(t=Sum('amount'))['t'] or D('0')
                self.cmp(f'customer receipt {o.order_number} total', ctx3['total_amount'], o.total_amount)
                self.cmp(f'customer receipt {o.order_number} payments listed', sum(p.amount for p in ctx3['payments']), paid)
                self.cmp(f'customer receipt {o.order_number} subtotal+tax+fee=total',
                         ctx3['subtotal'] + ctx3['tax_amount'] + o.delivery_fee, ctx3['total_amount'])
                if paid < o.total_amount:
                    note(f'NOTE customer receipt {o.order_number} shown as PAID receipt while {o.total_amount - paid} unpaid')
        # bill text
        for k in ('o13',):
            txt = _generate_bill_content(S[k])
            note('BILL', k, txt.split('TOTAL DUE')[1][:200].replace('\n', ' | '))

        # ---------- 3. reports ----------
        self.check_reports(S, T, TR)
        self.check_extra(S, T, TR)
        # ---------- 4. loyalty / mobile money / stock ----------
        bal = LoyaltyTransaction.objects.filter(customer=self.U).aggregate(t=Sum('points'))['t']
        note('LOYALTY tx', list(LoyaltyTransaction.objects.filter(customer=self.U).order_by('id')
                                .values_list('kind', 'points', 'order__order_number', 'payment_id')))
        # expected: o3 +57; o4 -50 +9 ; void: +50 -9 ; repaid +14 ; o8 delivery paid by mpesa
        o8paid = Payment.objects.filter(order=S['o8'], is_voided=False).exclude(payment_method='loyalty').aggregate(t=Sum('amount'))['t'] or 0
        self.cmp('loyalty balance', bal, 57 - 50 + 9 + 50 - 9 + 14 + int(D(o8paid) // 100))
        self.client.force_login(self.U)
        for ch in MobileMoneyCharge.objects.all():
            pays = list(Payment.objects.filter(notes__contains=ch.reference))
            note('MM charge', ch.reference, ch.status, ch.amount, 'payment', ch.payment_id,
                 [(p.amount, p.is_voided) for p in pays], 'reason', ch.failure_reason)
            self.cmp(f'MM {ch.reference} payments created', len(pays), 1 if ch.payment_id else 0)
        self.cmp('o8 paid sum vs total (mpesa cents rule)', Payment.objects.filter(order=S['o8'], is_voided=False)
                 .aggregate(t=Sum('amount'))['t'], S['o8'].total_amount)
        for p, want in ((self.pilau, 0), (self.chips, 1), (self.tea, 3), (self.ugali, 17), (self.soda, 0)):
            p.refresh_from_db()
            self.cmp(f'stock {p.name}', p.available_in_stock, want)
        for o in allo:
            for i in o.order_items.all():
                if i.stock_taken is not None and i.stock_taken > i.quantity:
                    note('stock_taken > quantity', o.order_number, i.id)
        self.rice.refresh_from_db()
        note('RICE records', list(self.rice.records.values_list('record_type', 'quantity_change', 'notes')))
        self.cmp('rice stock (O1 2 served + O2 3 preparing; O10 cancelled before handover gives back)',
                 self.rice.current_stock() if callable(self.rice.current_stock) else self.rice.current_stock, D('8.75'))

    def check_reports(self, S, T, TR):
        from reports import views as rviews
        from cashier import views as cviews
        from admin_panel import views as aviews, views_main_owner as mviews
        # --- web reports dashboard (main owner, all locations) ---
        self.client.force_login(self.M)
        self.client.get('/admin-panel/set-view-all-restaurants/')
        with capture(rviews) as ctx:
            r = self.client.get('/reports/', {'period': 'today'})
        self.assertEqual(r.status_code, 200)
        self.cmp('dash ALL total_orders', ctx['total_orders'], T['n'])
        self.cmp('dash ALL total_revenue_with_tax', ctx['total_revenue_with_tax'], T['gross'])
        self.cmp('dash ALL total_tax', ctx['total_tax'], T['tax'])
        self.cmp('dash ALL total_revenue (ex tax)', ctx['total_revenue'], T['net'])
        self.cmp('dash ALL paid_revenue_with_tax', ctx['paid_revenue_with_tax'], T['paid_gross'])
        self.cmp('dash ALL unpaid_revenue_with_tax', ctx['unpaid_revenue_with_tax'], T['unpaid_gross'])
        self.cmp('dash ALL partial_revenue_with_tax', ctx['partial_revenue_with_tax'], T['partial_gross'])
        self.cmp('dash ALL total_items', ctx['total_items'], T['items_qty'])
        meth = {m: ctx[f'{m}_total'] for m in ('cash', 'card', 'digital', 'voucher', 'loyalty', 'mobile')}
        self.cmp('dash ALL payment_method_breakdown sum vs collected',
                 sum(D(str(r['total'])) for r in ctx['payment_method_breakdown']), T['collected'])
        for m in set(T['by_method']) | set(meth):
            self.cmp(f'dash ALL method {m}', meth.get(m, 'NOT SHOWN'), T['by_method'].get(m, 0))
        self.cmp('dash ALL methods shown sum vs collected', sum(D(str(v)) for v in meth.values()), T['collected'])
        for rest in (self.R1, self.R2, self.R3):
            with capture(rviews) as ctx:
                self.client.get('/reports/', {'period': 'today', 'restaurant': rest.id})
            t = TR[rest.id]
            self.cmp(f'dash {rest.name} total_orders', ctx['total_orders'], t['n'])
            self.cmp(f'dash {rest.name} total_revenue_with_tax', ctx['total_revenue_with_tax'], t['gross'])
            self.cmp(f'dash {rest.name} total_tax', ctx['total_tax'], t['tax'])
            self.cmp(f'dash {rest.name} paid_revenue_with_tax', ctx['paid_revenue_with_tax'], t['paid_gross'])
        # item filter (product) tax: Pilau only, R1
        with capture(rviews) as ctx:
            self.client.get('/reports/', {'period': 'today', 'restaurant': self.R1.id, 'product_ids': self.pilau.id})
        pil_items = OrderItem.objects.filter(product=self.pilau).exclude(order__status='cancelled')
        pil_food = sum((i.get_subtotal() for i in pil_items), D('0'))
        # tax actually charged on those lines: each order's charged rate x line
        pil_tax = D('0')
        for i in pil_items:
            o = i.order
            base = o.get_subtotal() + (o.delivery_fee if o.delivery_fee_taxed else 0)
            rate = (o.total_amount - o.get_subtotal() - o.delivery_fee) / base if base else 0
            pil_tax += i.get_subtotal() * rate
        self.cmp('dash R1 product filter revenue', ctx['total_revenue'], pil_food)
        self.cmp('dash R1 product filter tax (charged)', ctx['total_tax'], pil_tax)
        # --- CSV ---
        r = self.client.get('/reports/export/', {'period': 'today'})
        csvtxt = r.content.decode('utf-8', 'replace')
        note('CSV head', csvtxt.split('ORDER')[0][:1600].replace('\r\n', ' | '))
        import re
        m = re.search(r'Revenue:,\D*([\d,]+\.\d\d)', csvtxt)
        self.cmp('CSV ALL Revenue (ex tax)', D(m.group(1).replace(',', '')) if m else None, T['net'])
        for label, key in (('Paid Orders', 'paid_gross'), ('Unpaid Orders', 'unpaid_gross'), ('Partial Payments', 'partial_gross')):
            m = re.search(label + r':,\d+,\D*([\d,]+\.\d\d)', csvtxt)
            note('CSV', label, m.group(1) if m else None, '(ex-tax) truth gross', T[key])
        mm = dict((a.strip(), D(b.replace(',', ''))) for a, b in re.findall(r'\n(Cash|Card|Digital|Voucher|Loyalty points|Mobile money),\d+,\D*([\d,]+\.\d\d)', csvtxt))
        self.cmp('CSV method rows sum vs collected', sum(mm.values()), T['collected'])
        locs = re.findall(r'\n([^,\n]+),(\d+),[\d.]+%,\D*([\d,]+\.\d\d),', csvtxt)
        note('CSV locations', locs)
        # --- PDF ---
        r = self.client.get('/reports/export-pdf/', {'period': 'today'})
        try:
            from pypdf import PdfReader
        except ImportError:
            PdfReader = None
        if PdfReader:
            import io
            pdftxt = '\n'.join(pg.extract_text() for pg in PdfReader(io.BytesIO(r.content)).pages)
            note('PDF text head', pdftxt[:1500].replace('\n', ' | '))
        else:
            note('PDF: pypdf not installed; status', r.status_code, len(r.content))
        # --- money flow ---
        with capture(rviews) as ctx:
            self.client.get('/reports/money-flow/', {'period': 'today'})
        for k in ('sales_revenue', 'sales_unpaid', 'sales_partial', 'sales_collected', 'sales_outstanding',
                  'sales_total_orders'):
            note('money_flow', k, ctx.get(k))
        self.cmp('money_flow sales_collected', ctx.get('sales_collected'), T['collected'])
        self.cmp('money_flow sales_outstanding', ctx.get('sales_outstanding'), T['outstanding'])
        self.cmp('money_flow sales_revenue (paid gross)', ctx.get('sales_revenue'), T['paid_gross'])
        self.cmp('money_flow sales_total_orders', ctx.get('sales_total_orders'), T['n'])
        # --- branch reports ---
        with capture(mviews) as ctx:
            self.client.get('/admin-panel/branch-reports/')
        self.cmp('branch_reports total_orders (all incl cancelled?)', ctx['total_orders'], T['n'])
        self.cmp('branch_reports total_revenue', ctx['total_revenue'], T['gross'])
        for row in ctx['restaurant_revenue']:
            self.cmp(f"branch_reports row {row['restaurant'].name} revenue", row['revenue'], TR[row['restaurant'].id]['gross'])
            self.cmp(f"branch_reports row {row['restaurant'].name} orders", row['orders'], TR[row['restaurant'].id]['n'])
        # --- main owner dashboard ---
        with capture(mviews) as ctx:
            self.client.get('/admin-panel/main-owner-dashboard/')
        for st in ctx['branch_stats']:
            self.cmp(f"main_owner_dash {st['restaurant'].name} today_revenue", st['today_revenue'], TR[st['restaurant'].id]['gross'])
        self.cmp('main_owner_dash total_revenue', ctx['total_revenue'], T['gross'])
        # --- admin dashboard ---
        with capture(aviews) as ctx:
            self.client.get('/admin-panel/')
        self.cmp('admin_dash ALL today_revenue', ctx.get('today_revenue'), T['gross'])
        for rest in (self.R1, self.R2, self.R3):
            self.client.get('/admin-panel/switch-restaurant/', {'restaurant_id': rest.id})
            with capture(aviews) as ctx:
                self.client.get('/admin-panel/')
            self.cmp(f'admin_dash {rest.name} today_revenue', ctx.get('today_revenue'), TR[rest.id]['gross'])
            with capture(rviews) as ctx:
                self.client.get('/reports/money-flow/', {'period': 'today'})
            self.cmp(f'money_flow {rest.name} collected', ctx.get('sales_collected'), TR[rest.id]['collected'])
            self.cmp(f'money_flow {rest.name} paid gross', ctx.get('sales_revenue'), TR[rest.id]['paid_gross'])
        self.client.get('/admin-panel/set-view-all-restaurants/')
        # --- cashier report (web) ---
        self.client.force_login(self.C)
        with capture(cviews) as ctx:
            self.client.get('/cashier/reports/', {'period': 'today'})
        # cashier C belongs to the main owner: his report covers every restaurant of the main owner?
        scope = T
        note('cashier web', {k: ctx.get(k) for k in ('total_revenue', 'paid_amount', 'unpaid_amount', 'total_orders', 'total_items')},
             [(m['method'], m['total']) for m in ctx['payment_method_totals']])
        self.cmp('cashier web total_revenue', ctx['total_revenue'], scope['gross'])
        self.cmp('cashier web paid_amount', ctx['paid_amount'], scope['collected'])
        self.cmp('cashier web unpaid_amount', ctx['unpaid_amount'], scope['outstanding'])
        self.cmp('cashier web total_orders', ctx['total_orders'], scope['n'])
        self.cmp('cashier web methods sum', sum(m['total'] for m in ctx['payment_method_totals']), ctx['paid_amount'])
        self.cmp('cashier web total_items (qty)', ctx['total_items'], scope['items_qty'])
        r = self.client.get('/cashier/reports/', {'period': 'today', 'export': 'csv'})
        note('cashier CSV tail', r.content.decode()[-400:].replace('\r\n', ' | '))
        # branch cashier
        self.client.force_login(self.CB)
        with capture(cviews) as ctx:
            self.client.get('/cashier/reports/', {'period': 'today'})
        self.cmp('cashier web (branch3) total_revenue', ctx['total_revenue'], TR[self.R3.id]['gross'])
        self.cmp('cashier web (branch3) paid', ctx['paid_amount'], TR[self.R3.id]['collected'])
        # --- mobile reports ---
        j = self.api(self.M).get('/api/v1/reports/revenue/', {'period': 'today'}).json()
        note('app owner_reports stats', j['stats'], j['cashier_totals'])
        for row in j['orders']:
            self.assertIn(row['order_type'], ('dine-in', 'delivery', 'pickup'))
            if row['order_type'] != 'dine-in':
                self.assertEqual(row['table_number'], 'N/A')   # kept for old app builds
        self.cmp('app owner total_revenue', j['stats']['total_revenue'], T['gross'])
        self.cmp('app owner total_orders', j['stats']['total_orders'], T['n'])
        self.cmp('app owner total_items', j['stats']['total_items'], T['items_qty'])
        self.cmp('app owner cashier_totals sum vs collected', sum(D(str(c['collected'])) for c in j['cashier_totals']),
                 T['collected'])
        j = self.api(self.C).get('/api/v1/reports/cashier/', {'period': 'today'}).json()
        mine = Payment.objects.filter(processed_by=self.C, is_voided=False).aggregate(t=Sum('amount'))['t']
        note('app cashier stats', j['stats'], j['my_payment_methods'])
        self.cmp('app cashier total_revenue', j['stats']['total_revenue'], T['gross'])
        self.cmp('app cashier total_orders', j['stats']['total_orders'], T['n'])
        self.cmp('app cashier my_total_collected', j['stats']['my_total_collected'], mine)
        self.cmp('app cashier method sum', sum(D(str(m['total'])) for m in j['my_payment_methods']), mine)
        ccs = [o for o in Order.objects.filter(ordered_by=self.CC)]
        tcc = self.truth(ccs)
        j = self.api(self.CC).get('/api/v1/reports/cc/', {'period': 'today'}).json()
        note('app cc stats', j['stats'])
        self.cmp('app cc total_revenue', j['stats']['total_revenue'], tcc['gross'])
        self.cmp('app cc total_orders', j['stats']['total_orders'], tcc['n'])
        self.client.force_login(self.CC)
        from orders import views as oviews
        with capture(oviews) as ctx:
            self.client.get('/orders/customer-care/reports/', {'period': 'today'})
        note('web cc report', {k: ctx.get(k) for k in ('total_revenue', 'total_orders', 'paid_revenue', 'total_paid', 'paid_amount')})
        self.cmp('web cc total_revenue', ctx.get('total_revenue'), tcc['gross'])
        # --- forecast (today counted as history by asking for tomorrow) ---
        from reports import forecast
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        try:
            from django.utils import timezone
            fc = forecast.build(self.M, today=timezone.localdate() + datetime.timedelta(days=1))
            note('forecast keys', list(fc.keys()) if isinstance(fc, dict) else type(fc))
            from orders.models import Order as _O
            ids = list(forecast.orders_for_owner(self.M).values_list('id', flat=True))
            self.cmp('forecast history revenue (orders_for_owner)',
                     _O.objects.filter(id__in=ids).aggregate(t=Sum('total_amount'))['t'], T['gross'])
            for k in ('history', 'daily', 'last_days', 'days'):
                if isinstance(fc, dict) and k in fc:
                    note('forecast', k, str(fc[k])[:600])
        except Exception as e:
            note('forecast error', repr(e))

    def check_extra(self, S, T, TR):
        import re, csv, io
        from reports import views as rviews
        from cashier import views as cviews
        from orders import views as oviews
        # PDF: capture the tables handed to reportlab
        tables = []
        real = rviews.Table
        def T_(data, *a, **k):
            tables.append(data)
            return real(data, *a, **k)
        rviews.Table = T_
        try:
            self.client.force_login(self.M)
            self.client.get('/admin-panel/set-view-all-restaurants/')
            r = self.client.get('/reports/export-pdf/', {'period': 'today'})
        finally:
            rviews.Table = real
        for t in tables[:5]:
            note('PDF table', t[:6])
        # CSV locations section
        r = self.client.get('/reports/export/', {'period': 'today'})
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        sec = False
        locsum = D('0')
        for row in rows:
            if row and row[0].startswith('BRANCH/LOCATION'):
                sec = True; continue
            if sec:
                if not row:
                    break
                note('CSV loc row', row)
                if row[0] != 'Location':
                    locsum += D(re.sub(r'[^\d.]', '', row[3]))
        self.cmp('CSV location revenues add up (ex tax)', locsum, T['net'])
        # receipts as the cashier / CC / branch cashier (owner filter M → join duplication?)
        for user, pays in ((self.C, Payment.objects.filter(processed_by=self.C)[:2]),
                           (self.CC, Payment.objects.filter(processed_by=self.CC)[:1]),
                           (self.CB, Payment.objects.filter(processed_by=self.CB)[:1])):
            self.client.force_login(user)
            for pay in pays:
                url = (f'/orders/customer-care/receipt/{pay.id}/' if user.is_customer_care() else f'/cashier/receipt/{pay.id}/')
                mod = oviews if user.is_customer_care() else cviews
                with capture(mod) as ctx:
                    r = self.client.get(url)
                note('receipt as', user.username, url, r.status_code)
                if r.status_code == 200:
                    o = Order.objects.get(pk=pay.order_id)
                    paid = Payment.objects.filter(order=o, is_voided=False).aggregate(t=Sum('amount'))['t'] or D('0')
                    self.cmp(f'receipt as {user.username} total', ctx['order'].get_total(), o.total_amount)
                    self.cmp(f'receipt as {user.username} balance', ctx['remaining_balance'], max(D(0), o.total_amount - paid))
                    m = re.search(r'Tax \(([\d.]+)%\)', r.content.decode())
                    base = o.get_subtotal() + (o.delivery_fee if o.delivery_fee_taxed else 0)
                    pct = ((o.total_amount - o.get_subtotal() - o.delivery_fee) / base * 100).quantize(D('0.1'))
                    self.cmp(f'receipt as {user.username} {o.order_number} tax% label vs charged', D(m.group(1)) if m else None, pct)
        # cashier dashboard rows for the main owner's cashier
        self.client.force_login(self.C)
        with capture(cviews) as ctx:
            self.client.get('/cashier/', {'period': 'today'})
        ids = [o.id for o in ctx['orders']]
        self.cmp('cashier dashboard order rows unique', len(ids), len(set(ids)))
        with capture(cviews) as ctx:
            self.client.get('/cashier/receipts/')
        ids = [p.id for p in ctx['payments']]
        self.cmp('receipt management rows unique', len(ids), len(set(ids)))
        # app: list of payments
        j = self.api(self.C).get('/api/v1/payments/').json()
        self.cmp('app payments list sum', sum(D(str(p['amount'])) for p in j['payments']), T['collected'])
        # app owner total_items without cancelled duplicates
        from orders.models import Order as O_
        qs = O_.objects.filter(created_at__date__isnull=False)
        note('items qty all incl cancelled', OrderItem.objects.aggregate(t=Sum('quantity'))['t'])
        # branch owner dashboards
        self.client.force_login(self.B)
        from reports import views as rv
        with capture(rv) as ctx:
            self.client.get('/reports/', {'period': 'today'})
        self.cmp('dash as branch owner B gross', ctx.get('total_revenue_with_tax'), TR[self.R3.id]['gross'])
        with capture(rv) as ctx:
            self.client.get('/reports/money-flow/', {'period': 'today'})
        self.cmp('money_flow as B collected', ctx.get('sales_collected'), TR[self.R3.id]['collected'])
        from admin_panel import views as av
        with capture(av) as ctx:
            self.client.get('/admin-panel/')
        self.cmp('admin_dash as B today_revenue', ctx.get('today_revenue'), TR[self.R3.id]['gross'])
        j = self.api(self.B).get('/api/v1/reports/revenue/', {'period': 'today'}).json()
        self.cmp('app owner_reports as B revenue', j['stats']['total_revenue'], TR[self.R3.id]['gross'])
        self.cmp('app owner_reports as B cashier_totals', sum(D(str(c['collected'])) for c in j['cashier_totals']), TR[self.R3.id]['collected'])


# ---------------------------------------------------------------------------
# Focused regression tests, one small set-up each
# ---------------------------------------------------------------------------

_PATCHES = ('orders.push.send_push', 'cashier.views.auto_print_receipt', 'orders.printing.auto_print_receipt',
            'orders.printing.auto_print_order', 'orders.printing.auto_print_new_items',
            'orders.views.auto_print_order', 'orders.views.auto_print_new_items',
            'mobile_api.views.orders._notify_ws', 'mobile_api.views.payments._notify_ws',
            'mobile_api.views.sync._notify_ws')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class Base(TestCase):
    SELF_BRANCH = True

    def setUp(self):
        cache.clear()
        for t in _PATCHES:
            p = mock.patch(t, return_value={'receipt_printed': False})
            p.start()
            self.addCleanup(p.stop)
        for slug, name, desc, cat in ALL_FEATURES:
            Feature.objects.get_or_create(slug=slug, defaults={'name': name, 'description': desc, 'category': cat})
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.M = mk('main', 'main_owner', restaurant_name='Main R')
        self.C = mk('cash', 'cashier', owner=self.M)
        self.CC = mk('cc', 'customer_care', owner=self.M)
        self.cust = mk('cust', 'customer')
        today = datetime.date.today()
        RestaurantSubscription.objects.create(restaurant_owner=self.M, subscription_start_date=today,
                                              subscription_end_date=today + datetime.timedelta(days=30))
        self.R1 = Restaurant.objects.create(name='Main R', address='a', main_owner=self.M, branch_owner=self.M,
                                            is_main_restaurant=True, tax_rate=D('0.1600'), subscription_plan='PRO',
                                            allow_remote_orders=True, qr_code='Q1')
        if self.SELF_BRANCH:
            self.R2 = Restaurant.objects.create(name='Self Branch', address='b', main_owner=self.M,
                                                branch_owner=self.M, parent_restaurant=self.R1,
                                                tax_rate=D('0.0000'), qr_code='Q2')
            self.T5 = TableInfo.objects.create(restaurant=self.R2, owner=self.M, tbl_no='S5')
        self.T1 = TableInfo.objects.create(restaurant=self.R1, owner=self.M, tbl_no='T1')
        self.cat = MainCategory.objects.create(restaurant=self.R1, owner=self.M, name='Food')
        self.sub = SubCategory.objects.create(main_category=self.cat, name='Rice')
        self.p = Product.objects.create(name='Pilau', description='d', main_category=self.cat, sub_category=self.sub,
                                        price=D('1000.00'), available_in_stock=10)
        self.web = Client(raise_request_exception=False)

    def api(self, u):
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(u)
        c.credentials(HTTP_X_APP_FEATURES='delivery-fee')
        return c

    def place(self, items, table=None, otype='dine-in', user=None):
        body = {'items': [{'product_id': p.id, 'quantity': q, 'price': float(p.get_current_price())} for p, q in items],
                'order_type': otype}
        if table:
            body['table_id'] = table.id
        r = self.api(user or self.C).post('/api/v1/orders/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return Order.objects.get(pk=r.json()['order']['id'])

    def pay(self, o, amount, method='cash', user=None):
        r = self.api(user or self.C).post('/api/v1/payments/', {'order_id': o.id, 'amount': str(amount),
                                                                'payment_method': method}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return Payment.objects.get(pk=r.json()['payment']['id'])

    def cancel(self, o, user=None):
        r = self.api(user or self.C).post(f'/api/v1/orders/{o.id}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)


class SelfRunBranchNoDuplicateRowsTests(Base):
    """Bug 1: M is branch_owner of two restaurants; the old reverse join repeated every row."""

    def test_receipts_lists_and_totals_count_each_order_once(self):
        o = self.place([(self.p, 1)], table=self.T1)                    # 1160.00
        pay = self.pay(o, '1160.00')
        self.web.force_login(self.C)
        self.assertEqual(self.web.get(f'/cashier/receipt/{pay.id}/').status_code, 200)
        from cashier import views as cv
        with capture(cv) as ctx:
            self.web.get('/cashier/', {'period': 'today'})
        self.assertEqual([x.id for x in ctx['orders']], [o.id])
        with capture(cv) as ctx:
            self.web.get('/cashier/receipts/')
        self.assertEqual([x.id for x in ctx['payments']], [pay.id])
        # customer care receipt (own order)
        o2 = self.place([(self.p, 1)], otype='pickup', user=self.CC)
        pay2 = self.pay(o2, o2.total_amount)
        self.web.force_login(self.CC)
        self.assertEqual(self.web.get(f'/orders/customer-care/receipt/{pay2.id}/').status_code, 200)
        self.web.force_login(self.M)
        self.web.get('/admin-panel/set-view-all-restaurants/')
        from admin_panel import views as av, views_main_owner as mv
        with capture(av) as ctx:
            self.web.get('/admin-panel/')
        self.assertEqual(q2(ctx['today_revenue']), D('2320.00'))
        with capture(mv) as ctx:
            self.web.get('/admin-panel/branch-reports/')
        self.assertEqual(q2(ctx['total_revenue']), D('2320.00'))
        self.assertEqual(ctx['total_orders'], 2)
        rows = {x['restaurant'].name: (q2(x['revenue']), x['orders']) for x in ctx['restaurant_revenue']}
        self.assertEqual(rows, {'Main R': (D('2320.00'), 2), 'Self Branch': (D('0.00'), 0)})
        j = self.api(self.M).get('/api/v1/reports/revenue/', {'period': 'today'}).json()
        self.assertEqual(sum(D(str(c['collected'])) for c in j['cashier_totals']), D('2320.00'))

    def test_branch_reports_leave_out_cancelled_and_scope_tables(self):
        a = self.place([(self.p, 1)], table=self.T1)
        b = self.place([(self.p, 1)], table=self.T1)
        self.cancel(b)
        t = self.place([(self.p, 1)], table=self.T5, user=self.M)        # self-run branch, 0% tax
        self.web.force_login(self.M)
        from admin_panel import views_main_owner as mv
        with capture(mv) as ctx:
            self.web.get('/admin-panel/branch-reports/')
        self.assertEqual(ctx['total_orders'], 2)
        self.assertEqual(q2(ctx['total_revenue']), q2(a.total_amount + t.total_amount))
        rows = {x['restaurant'].name: q2(x['revenue']) for x in ctx['restaurant_revenue']}
        self.assertEqual(rows, {'Main R': q2(a.total_amount), 'Self Branch': q2(t.total_amount)})
        from django.urls import reverse
        with capture(mv) as ctx:
            self.web.get(reverse('admin_panel:branch_detail', args=[self.R2.id]))
        self.assertEqual(q2(ctx['total_revenue']), q2(t.total_amount))
        self.assertEqual(list(ctx['tables'].values_list('tbl_no', flat=True)), ['S5'])

    def test_managed_owner_ids_never_repeats_rows(self):
        from restaurant_system.db_utils import managed_owner_ids
        self.place([(self.p, 1)], otype='pickup')
        qs = Order.objects.filter(ordered_by__owner__in=managed_owner_ids(self.M))
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.get().ordered_by, self.C)


class OfflineAppendTaxTests(Base):
    SELF_BRANCH = False

    def test_offline_append_keeps_charged_rate(self):                 # bug 2
        self.api(self.C).post('/api/v1/sync/push/', {'orders': [
            {'offline_id': 'o1', 'table_id': self.T1.id, 'items': [{'product_id': self.p.id, 'quantity': 1}]}]},
            format='json')
        o = Order.objects.get()
        self.assertEqual(o.total_amount, D('1160.00'))
        Restaurant.objects.filter(pk=self.R1.pk).update(tax_rate=D('0'))
        self.api(self.C).post('/api/v1/sync/push/', {'orders': [
            {'offline_id': 'a1', 'existing_order_id': o.id, 'items': [{'product_id': self.p.id, 'quantity': 1}]}]},
            format='json')
        o.refresh_from_db()
        self.assertEqual(o.total_amount, D('2320.00'))

    def test_add_items_total_is_compute_total_of_new_subtotal(self):  # bug 14
        p = Product.objects.create(name='Pricey', description='d', main_category=self.cat, sub_category=self.sub,
                                   price=D('1234.56'))
        big = Product.objects.create(name='Feast', description='d', main_category=self.cat, sub_category=self.sub,
                                     price=D('123456.00'))
        o = self.place([(p, 1)], table=self.T1)
        self.assertEqual(o.total_amount, D('1432.09'))             # 1234.56 x 1.16, rounded
        r = self.api(self.C).post(f'/api/v1/orders/{o.id}/add-items/', {'items': [
            {'product_id': big.id, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        # the old "+ added x (1 + 0.16000032)" gave 144641.13
        self.assertEqual(o.total_amount, Order.compute_total(D('124690.56'), D('0.16')))
        self.api(self.C).post('/api/v1/sync/push/', {'orders': [
            {'offline_id': 'a2', 'existing_order_id': o.id, 'items': [{'product_id': big.id, 'quantity': 1}]}]},
            format='json')
        o.refresh_from_db()
        self.assertEqual(o.total_amount, Order.compute_total(D('248146.56'), D('0.16')))

    def test_charged_tax_rate_recovers_the_set_rate(self):
        x = Product.objects.create(name='X', description='d', main_category=self.cat, price=D('1234.56'))
        o = self.place([(x, 1)], table=self.T1)
        self.assertEqual(o.charged_tax_rate(), D('0.1600'))
        self.assertEqual(o.charged_tax_percentage, 16.0)


class PromotionScopeTests(Base):
    SELF_BRANCH = False

    def test_product_promotion_does_not_reach_dishes_without_sub_category(self):   # bug 3
        loose = Product.objects.create(name='Soda', description='d', main_category=self.cat, price=D('100.00'))
        promo = HappyHourPromotion.objects.create(owner=self.M, name='HH', discount_percentage=D('50'),
                                                  start_time=datetime.time(0, 0), end_time=datetime.time(23, 59, 59),
                                                  days_of_week='1,2,3,4,5,6,7')
        promo.products.add(self.p)
        self.assertEqual(loose.get_current_price(), D('100.00'))
        self.assertIsNone(loose.get_active_promotion())
        self.assertEqual(self.p.get_current_price(), D('500.00'))
        o = self.place([(loose, 1)], table=self.T1)
        self.assertEqual(o.total_amount, D('116.00'))
        # a category promotion still reaches a dish without a sub-category
        promo2 = HappyHourPromotion.objects.create(owner=self.M, name='Cat', discount_percentage=D('10'),
                                                   start_time=datetime.time(0, 0), end_time=datetime.time(23, 59, 59),
                                                   days_of_week='1,2,3,4,5,6,7')
        promo2.main_categories.add(self.cat)
        self.assertEqual(Product.objects.get(pk=loose.pk).get_current_price(), D('90.00'))


class ReportsSoldOnlyTests(Base):
    SELF_BRANCH = False

    def test_app_and_cc_reports_leave_out_cancelled(self):            # bug 4
        self.place([(self.p, 1)], table=self.T1)
        self.cancel(self.place([(self.p, 1)], table=self.T1))
        for url, u in (('/api/v1/reports/revenue/', self.M), ('/api/v1/reports/cashier/', self.C)):
            st = self.api(u).get(url, {'period': 'today'}).json()['stats']
            self.assertEqual((st['total_revenue'], st['total_orders'], st['total_items']), (1160.0, 1, 1), url)
        c1 = self.place([(self.p, 1)], otype='pickup', user=self.CC)
        self.cancel(self.place([(self.p, 1)], otype='pickup', user=self.CC), user=self.CC)
        st = self.api(self.CC).get('/api/v1/reports/cc/', {'period': 'today'}).json()['stats']
        self.assertEqual((st['total_revenue'], st['total_orders']), (float(c1.total_amount), 1))
        self.web.force_login(self.CC)
        from orders import views as ov
        with capture(ov) as ctx:
            self.web.get('/orders/customer-care/reports/', {'period': 'today'})
        self.assertEqual((q2(ctx['total_revenue']), ctx['total_orders'], ctx['total_items']),
                         (q2(c1.total_amount), 1, 1))

    def test_total_items_counts_equal_quantities(self):              # bug 6
        p2 = Product.objects.create(name='Soda', description='d', main_category=self.cat, sub_category=self.sub,
                                    price=D('100.00'))
        self.place([(self.p, 1), (p2, 1)], table=self.T1)
        self.place([(p2, 1)], table=self.T1)
        for url, u in (('/api/v1/reports/revenue/', self.M), ('/api/v1/reports/cashier/', self.C)):
            self.assertEqual(self.api(u).get(url, {'period': 'today'}).json()['stats']['total_items'], 3, url)
            j = self.api(u).get(url, {'period': 'today', 'product_ids': str(p2.id)}).json()
            self.assertEqual((j['stats']['total_orders'], j['stats']['total_items']), (2, 3), url)

    def test_cashier_web_report_items_are_quantities_of_sold_orders(self):   # bug 11
        self.place([(self.p, 3)], table=self.T1)
        self.cancel(self.place([(self.p, 2)], table=self.T1))
        self.web.force_login(self.C)
        from cashier import views as cv
        with capture(cv) as ctx:
            self.web.get('/cashier/reports/', {'period': 'today'})
        self.assertEqual(ctx['total_items'], 3)

    def test_report_rows_carry_order_type_and_na_table(self):
        self.place([(self.p, 1)], otype='pickup')
        self.place([(self.p, 1)], table=self.T1)
        rows = self.api(self.M).get('/api/v1/reports/revenue/', {'period': 'today'}).json()['orders']
        self.assertEqual(sorted(((r['order_type'], r['table_number']) for r in rows), key=str),
                         sorted([('dine-in', 'T1'), ('pickup', 'N/A')], key=str))


class SelfRunBranchReportsTests(Base):
    def test_self_run_branch_gets_only_its_own_orders(self):         # bug 5
        o = self.place([(self.p, 1)], otype='pickup')                  # main restaurant pickup 1160
        self.pay(o, '1160.00')
        self.web.force_login(self.M)
        self.web.get('/admin-panel/set-view-all-restaurants/')
        from reports import views as rv
        with capture(rv) as ctx:
            self.web.get('/reports/', {'period': 'today', 'restaurant': self.R2.id})
        self.assertEqual((ctx['total_orders'], q2(ctx['total_revenue_with_tax'])), (0, D('0.00')))
        with capture(rv) as ctx:
            self.web.get('/reports/', {'period': 'today', 'restaurant': self.R1.id})
        self.assertEqual((ctx['total_orders'], q2(ctx['total_revenue_with_tax'])), (1, D('1160.00')))
        self.web.get('/admin-panel/switch-restaurant/', {'restaurant_id': self.R2.id})
        with capture(rv) as ctx:
            self.web.get('/reports/money-flow/', {'period': 'today'})
        self.assertEqual(q2(ctx['sales_collected']), D('0.00'))


class TaxLabelAndFilterTests(Base):
    SELF_BRANCH = False

    def test_charged_rate_after_tax_change(self):                    # bugs 7 and 8
        o = self.place([(self.p, 1)], table=self.T1)                   # charged 16% -> 1160
        pay = self.pay(o, '1160.00')
        Restaurant.objects.filter(pk=self.R1.pk).update(tax_rate=D('0.18'))
        self.web.force_login(self.C)
        html = self.web.get(f'/cashier/receipt/{pay.id}/').content.decode()
        self.assertEqual(re.findall(r'Tax \(([\d.]+)%\):', html), ['16.0'])
        self.web.force_login(self.M)
        from reports import views as rv
        with capture(rv) as ctx:
            self.web.get('/reports/', {'period': 'today', 'product_ids': self.p.id})
        self.assertEqual((q2(ctx['total_revenue']), q2(ctx['total_tax'])), (D('1000.00'), D('160.00')))
        self.assertEqual(q2(ctx['paid_revenue_with_tax']), D('1160.00'))

    def test_customer_care_receipt_label(self):
        o = self.place([(self.p, 1)], otype='pickup', user=self.CC)
        pay = self.pay(o, o.total_amount)
        Restaurant.objects.filter(pk=self.R1.pk).update(tax_rate=D('0.18'))
        self.web.force_login(self.CC)
        html = self.web.get(f'/orders/customer-care/receipt/{pay.id}/').content.decode()
        self.assertEqual(re.findall(r'Tax \(([\d.]+)%\):', html), ['16.0'])


class PaymentMethodBreakdownTests(Base):
    SELF_BRANCH = False

    def test_breakdowns_add_up_to_collected(self):                   # bug 9
        a = self.place([(self.p, 1)], table=self.T1)
        self.pay(a, '160.00', 'card')
        b = self.place([(self.p, 1)], otype='pickup', user=self.CC)
        self.web.force_login(self.CC)
        r = self.web.post(f'/cashier/process-payment/{b.id}/', json.dumps(
            {'amount': str(b.total_amount), 'payment_method': 'mobile'}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        collected = Payment.objects.filter(is_voided=False).aggregate(t=Sum('amount'))['t']
        self.web.force_login(self.M)
        from reports import views as rv
        with capture(rv) as ctx:
            self.web.get('/reports/', {'period': 'today'})
        self.assertEqual(sum(D(str(x['total'])) for x in ctx['payment_method_breakdown']), collected)
        self.assertEqual(D(str(ctx['mobile_total'])), b.total_amount)
        csvtxt = self.web.get('/reports/export/', {'period': 'today'}).content.decode().replace('\r\n', '\n')
        sec = csvtxt.split('PAYMENT METHOD BREAKDOWN')[1].split('\n\n')[0]
        rows = re.findall(r'\n([^,\n]+),\d+,\D*([\d,]+\.\d\d)', sec)
        self.assertEqual(sum(D(v.replace(',', '')) for _, v in rows), collected)
        self.assertIn('Mobile money', [k for k, _ in rows])


class CashierCancelStockTests(Base):
    SELF_BRANCH = False

    def test_handed_over_food_is_not_put_back(self):                 # bug 10
        o = self.place([(self.p, 2)], otype='pickup')
        Order.objects.filter(pk=o.pk).update(status='delivered')
        self.web.force_login(self.C)
        r = self.web.post(f'/cashier/cancel-order/{o.id}/', json.dumps({'reason': 'x'}),
                          content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.p.refresh_from_db()
        self.assertEqual(self.p.available_in_stock, 8)
        # still in the kitchen: given back
        o2 = self.place([(self.p, 3)], table=self.T1)
        self.web.post(f'/cashier/cancel-order/{o2.id}/', json.dumps({'reason': 'x'}), content_type='application/json')
        self.p.refresh_from_db()
        self.assertEqual(self.p.available_in_stock, 8)


class PrintedBalanceTests(Base):
    SELF_BRANCH = False

    def test_partial_payment_prints_balance_due(self):               # bug 12
        from orders.printing import _generate_receipt_content
        o = self.place([(self.p, 1)], table=self.T1)
        pay = self.pay(o, '1000.00')
        m = re.search(r'BALANCE DUE:\s+\D*([\d.]+)', _generate_receipt_content(pay))
        self.assertEqual(D(m.group(1)), D('160.00'))
        pay2 = self.pay(o, '160.00')
        self.assertNotIn('BALANCE DUE', _generate_receipt_content(pay2))


class LoyaltyWholePointsTests(Base):
    SELF_BRANCH = False

    def test_points_never_worth_more_than_credited(self):           # bug 13
        from cashier.loyalty import redeem_code
        LoyaltyProgram.objects.create(owner=self.M, enabled=True, spend_per_point=D('100'), point_value=D('50'),
                                      min_redeem_points=1)
        cu = User.objects.create_user('lc', password='x', role=role('customer'), phone_number='0711111111')
        LoyaltyTransaction.objects.create(program_owner=self.M, customer=cu, kind='adjust', points=10)
        o = self.place([(self.p, 1)], table=self.T1)
        self.web.force_login(self.C)
        self.web.post(f'/cashier/order-loyalty/{o.id}/', json.dumps({'phone': '0711111111'}),
                      content_type='application/json')
        r = self.web.post(f'/cashier/process-payment/{o.id}/', json.dumps(
            {'amount': '60', 'payment_method': 'loyalty', 'loyalty_code': redeem_code(cu)}),
            content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        red = LoyaltyTransaction.objects.get(kind='redeem')
        pay = Payment.objects.get(payment_method='loyalty')
        self.assertEqual((red.points, pay.amount), (-1, D('50.00')))     # 1 point = 50 credited, 10 still due
        # less than one point's worth: refused, nothing taken
        r = self.api(self.C).post('/api/v1/payments/', {'order_id': o.id, 'amount': '10', 'payment_method': 'loyalty',
                                                        'loyalty_code': redeem_code(cu)}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(LoyaltyTransaction.objects.filter(kind='redeem').count(), 1)
        # app path: same rule
        r = self.api(self.C).post('/api/v1/payments/', {'order_id': o.id, 'amount': '120', 'payment_method': 'loyalty',
                                                        'loyalty_code': redeem_code(cu)}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(D(str(r.json()['payment']['amount'])), D('100.00'))
        self.assertEqual(LoyaltyTransaction.objects.filter(kind='redeem').order_by('-id').first().points, -2)


class OrderRestaurantIdTests(Base):
    def test_restaurant_id_and_no_n_plus_one(self):                  # bug 15
        from mobile_api.serializers import OrderSerializer
        B = User.objects.create_user('bown', password='x', role=role('branch_owner'), owner=self.M)
        R3 = Restaurant.objects.create(name='B3', address='c', main_owner=self.M, branch_owner=B,
                                       parent_restaurant=self.R1, qr_code='Q3')
        CB = User.objects.create_user('cashb', password='x', role=role('cashier'), owner=B)
        legacy = TableInfo.objects.create(owner=self.M, tbl_no='L1')
        dine = self.place([(self.p, 1)], table=self.T1)
        own = self.place([(self.p, 1)], table=self.T5, user=self.M)
        remote = [self.place([(self.p, 1)], otype='pickup') for _ in range(4)]
        b_remote = Order.objects.create(order_type='pickup', ordered_by=CB, restaurant_owner=B, total_amount=1, order_number='T-B1')
        old = Order.objects.create(table_info=legacy, ordered_by=self.C, total_amount=1, order_number='T-L1')
        stray = Order.objects.create(order_type='pickup', ordered_by=self.cust, total_amount=1, order_number='T-S1')
        orders = list(Order.objects.select_related('table_info', 'ordered_by').order_by('id'))
        with CaptureQueriesContext(connection) as q:
            ser = OrderSerializer(context={})
            got = {o.id: ser.get_restaurant_id(o) for o in orders}
        self.assertLessEqual(len(q), 6)                     # per distinct owner (M, B), not per order
        self.assertEqual(got[dine.id], self.R1.id)
        self.assertEqual(got[own.id], self.R2.id)
        self.assertEqual({got[o.id] for o in remote}, {self.R1.id})
        self.assertEqual(got[b_remote.id], R3.id)
        self.assertEqual(got[old.id], self.R1.id)
        self.assertIsNone(got[stray.id])
        j = self.api(self.C).get(f'/api/v1/orders/{dine.id}/').json()
        self.assertEqual((j.get('order') or j).get('restaurant_id'), self.R1.id)
