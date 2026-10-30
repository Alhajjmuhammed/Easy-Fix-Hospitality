import datetime
import json
import sys
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, RestaurantSubscription, User
from cashier.models import Payment
from cashier.models_loyalty import LoyaltyOrderCustomer, LoyaltyProgram, LoyaltyTransaction
from cashier import loyalty as svc
from orders.models import Order
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class LoyaltyTests(TestCase):
    def setUp(self):
        for target in ('orders.push.send_push', 'cashier.views.auto_print_receipt', 'orders.printing.auto_print_receipt'):
            p = mock.patch(target, return_value={'receipt_printed': False})
            p.start()
            self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.cust = mk('cust', 'customer', phone_number='0712 345 678', first_name='Asha')
        self.cust2 = mk('cust2', 'customer', phone_number='0755 000 111')
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRMAIN')
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.main, defaults={
            'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        self.program = LoyaltyProgram.objects.create(owner=self.main, enabled=True, spend_per_point=Decimal('1000'),
                                                     point_value=Decimal('50'), min_redeem_points=100)
        self._n = 0

    # ---------- helpers ----------
    def _order(self, total='25000', customer=None, owner=None):
        self._n += 1
        return Order.objects.create(order_number=f'L{self._n}', ordered_by=customer or self.cust,
                                    restaurant_owner=owner or self.main, order_type='pickup', status='served',
                                    total_amount=Decimal(total))

    def _pay(self, order, amount, method='cash', user=None, **extra):
        if method == 'loyalty' and 'loyalty_code' not in extra:
            extra['loyalty_code'] = svc.redeem_code(self.cust)
        self.client.force_login(user or self.cashier)
        r = self.client.post(f'/cashier/process-payment/{order.id}/', json.dumps(
            {'amount': str(amount), 'payment_method': method, **extra}), content_type='application/json')
        return r

    def _void(self, payment):
        self.client.force_login(self.cashier)
        return self.client.post(f'/cashier/void-payment/{payment.id}/', json.dumps({'reason': 'mistake'}),
                                content_type='application/json')

    def _bal(self, customer=None):
        return svc.balance(self.main, customer or self.cust)

    def _give(self, points, customer=None):
        LoyaltyTransaction.objects.create(program_owner=self.main, customer=customer or self.cust, kind='adjust',
                                          points=points)

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    # ---------- earning ----------
    def test_earn_only_when_fully_paid_and_reverse_on_void(self):
        o = self._order()
        self._pay(o, '10000')
        self.assertEqual(self._bal(), 0)                                   # partial: nothing yet
        self.assertEqual(self._pay(o, '15000').status_code, 200)
        self.assertEqual(self._bal(), 25)
        self._void(Payment.objects.filter(order=o).last())
        self.assertEqual(self._bal(), 0)                                   # no longer paid: taken back
        self._pay(o, '15000')
        self.assertEqual(self._bal(), 25)                                  # paid again: earned once
        self.assertEqual(LoyaltyTransaction.objects.filter(kind='earn').count(), 2)

    def test_earn_via_app_payment(self):
        o = self._order(total='3500')
        r = self._api(self.cashier).post('/api/v1/payments/', {'order_id': o.id, 'amount': '3500',
                                                               'payment_method': 'card'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self._bal(), 3)                                   # floor(3500/1000)

    def test_programme_off_or_staff_order_earns_nothing(self):
        LoyaltyProgram.objects.filter(pk=self.program.pk).update(enabled=False)
        self._pay(self._order(), '25000')
        self.assertEqual(self._bal(), 0)
        LoyaltyProgram.objects.filter(pk=self.program.pk).update(enabled=True)
        self._pay(self._order(customer=self.cashier), '25000')             # walk-in, not linked
        self.assertFalse(LoyaltyTransaction.objects.exists())

    # ---------- redeeming ----------
    def test_pay_with_points_and_points_payment_earns_nothing(self):
        self._give(150)
        o = self._order()
        r = self._pay(o, '5000', method='loyalty')                          # 100 points × 50
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._bal(), 50)
        self._pay(o, '20000')
        self.assertEqual(self._bal(), 70)                                  # earns on the 20,000 cash only
        loyalty_payment = Payment.objects.get(order=o, payment_method='loyalty')
        self._void(loyalty_payment)
        self.assertEqual(LoyaltyTransaction.objects.filter(kind='refund').get().points, 100)
        self.assertEqual(self._bal(), 150)                                 # 50 + 100 back; earn reversed (unpaid)
        loyalty_payment.refresh_from_db()
        loyalty_payment.save()                                             # saving again never refunds twice
        self.assertEqual(LoyaltyTransaction.objects.filter(kind='refund').count(), 1)

    def test_redeem_refusals(self):
        o = self._order()
        self._give(90)
        self.assertEqual(self._pay(o, '4500', method='loyalty').status_code, 400)       # below minimum
        self._give(60)
        self.assertEqual(self._pay(o, '9000', method='loyalty').status_code, 400)       # needs 180 > 150
        self.assertEqual(self._pay(o, '5000', method='loyalty',
                                   selected_items=[{'id': 1, 'quantity': 1}]).status_code, 400)
        staff_order = self._order(customer=self.cashier)
        self.assertEqual(self._pay(staff_order, '5000', method='loyalty').status_code, 400)  # no customer
        LoyaltyProgram.objects.filter(pk=self.program.pk).update(enabled=False)
        self.assertEqual(self._pay(o, '5000', method='loyalty').status_code, 400)
        self.assertEqual(self._pay(o, '100', method='bitcoin').status_code, 400)        # unknown method
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self._bal(), 150)

    def test_app_loyalty_payment_online_only_and_sync_refuses(self):
        self._give(200)
        o = self._order()
        api = self._api(self.cashier)
        r = api.post('/api/v1/payments/', {'order_id': o.id, 'amount': '5000', 'payment_method': 'loyalty',
                                           'offline_id': 'abc123'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = api.post('/api/v1/payments/', {'order_id': o.id, 'amount': '5000', 'payment_method': 'loyalty',
                                           'loyalty_code': svc.redeem_code(self.cust)}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self._bal(), 100)
        from mobile_api.views.sync import _sync_payment  # offline queue can never spend points
        res = _sync_payment(self.cashier, self.main, {'order_id': o.id, 'amount': '5000',
                                                      'payment_method': 'loyalty', 'offline_id': 'zz'})
        self.assertEqual(res['status'], 'error')
        self.assertEqual(self._bal(), 100)

    # ---------- review fixes ----------
    def test_redeem_needs_customer_code_and_code_changes_after_use(self):
        from django.core.cache import cache
        cache.clear()
        self._give(500)
        o = self._order()
        self.assertEqual(self._pay(o, '5000', method='loyalty', loyalty_code='').status_code, 400)
        self.assertEqual(self._pay(o, '5000', method='loyalty', loyalty_code='000000'
                                   if svc.redeem_code(self.cust) != '000000' else '111111').status_code, 400)
        old = svc.redeem_code(self.cust)
        self.assertEqual(self._pay(o, '5000', method='loyalty', loyalty_code=old).status_code, 200)
        self.assertNotEqual(svc.redeem_code(self.cust), old)                    # rotated
        o2 = self._order()
        self.assertEqual(self._pay(o2, '5000', method='loyalty', loyalty_code=old).status_code, 400)  # reuse
        self.assertEqual(self._bal(), 400)

    def test_wrong_codes_lock_redeeming(self):
        from django.core.cache import cache
        cache.clear()
        self._give(500)
        o = self._order()
        real = svc.redeem_code(self.cust)
        wrong = '123456' if real != '123456' else '654321'
        for _ in range(5):
            self._pay(o, '5000', method='loyalty', loyalty_code=wrong)
        r = self._pay(o, '5000', method='loyalty', loyalty_code=real)
        self.assertEqual(r.status_code, 400)
        self.assertIn('Too many', r.json()['error'])
        cache.clear()

    def test_customer_care_mobile_method_still_works(self):
        o = self._order(total='3000')
        cc = User.objects.create_user('cc', password='pw12345!x', role=role('customer_care'), owner=self.main)
        cc_order = self._order(total='3000', customer=cc)
        r = self._pay(cc_order, '3000', method='mobile', user=cc)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Payment.objects.get(order=cc_order).payment_method, 'mobile')
        self.client.force_login(cc)                     # customer care: only their own orders
        self.assertEqual(self.client.get(f'/cashier/order-loyalty/{o.id}/').status_code, 403)

    def test_void_points_payment_refunds_points_not_money(self):
        from cashier.models import VoidTransaction
        self._give(200)
        o = self._order()
        self._pay(o, '5000', method='loyalty')
        p = Payment.objects.get(order=o)
        self.client.force_login(self.cashier)
        r = self.client.post(f'/cashier/void-payment/{p.id}/', json.dumps({'reason': 'x', 'refund_method': 'cash'}),
                             content_type='application/json')
        self.assertIn('points were returned', r.json()['message'])
        self.assertEqual(VoidTransaction.objects.get().refund_method, 'loyalty')
        self.assertEqual(self._bal(), 200)

    def test_failed_payment_keeps_nothing(self):
        self._give(200)
        o = self._order(total='5000')
        with mock.patch('orders.models.Order.release_table', side_effect=RuntimeError('boom')):
            r = self._pay(o, '5000', method='loyalty')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self._bal(), 200)

    def test_programme_off_still_takes_back_on_void(self):
        o = self._order()
        self._pay(o, '25000')
        LoyaltyProgram.objects.filter(pk=self.program.pk).update(enabled=False)
        self._void(Payment.objects.get(order=o))
        self.assertEqual(self._bal(), 0)

    def test_bad_link_body_and_cancelled_order(self):
        o = self._order(customer=self.cashier)
        self.client.force_login(self.cashier)
        for body in ('[1, 2]', '"x"', 'not json'):
            r = self.client.post(f'/cashier/order-loyalty/{o.id}/', body, content_type='application/json')
            self.assertEqual(r.status_code, 400, body)
        self._give(200)
        c = self._order()
        Order.objects.filter(pk=c.pk).update(status='cancelled')
        self.assertEqual(self._pay(Order.objects.get(pk=c.pk), '5000', method='loyalty').status_code, 400)

    # ---------- walk-in customers ----------
    def test_link_walk_in_customer_by_phone(self):
        o = self._order(customer=self.cashier)
        self.client.force_login(self.cashier)
        url = f'/cashier/order-loyalty/{o.id}/'
        self.assertIsNone(self.client.get(url).json()['customer'])
        for phone in ('', '123', '0799 999 999'):
            self.assertEqual(self.client.post(url, json.dumps({'phone': phone}), content_type='application/json')
                             .status_code, 400, phone)
        r = self.client.post(url, json.dumps({'phone': '+255 712 345 678'}), content_type='application/json')
        self.assertEqual((r.json()['customer']['name'], r.json()['customer']['phone']), ('Asha', '••• 678'))  # masked
        self._pay(o, '25000')
        self.assertEqual(self._bal(), 25)
        r = self.client.post(url, json.dumps({'phone': '0755000111'}), content_type='application/json')
        self.assertEqual(r.status_code, 400)                               # already paid
        own = self._order()
        self.assertEqual(self.client.post(f'/cashier/order-loyalty/{own.id}/', json.dumps({'phone': '0755000111'}),
                                          content_type='application/json').status_code, 400)

    def test_ambiguous_phone_refused(self):
        User.objects.create_user('dup', password='pw12345!x', role=role('customer'), phone_number='+255712345678')
        o = self._order(customer=self.cashier)
        self.client.force_login(self.cashier)
        r = self.client.post(f'/cashier/order-loyalty/{o.id}/', json.dumps({'phone': '0712345678'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(LoyaltyOrderCustomer.objects.exists())

    def test_order_loyalty_scope(self):
        other = User.objects.create_user('oth', password='pw12345!x', role=role('main_owner'))
        o = self._order(owner=other)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(f'/cashier/order-loyalty/{o.id}/').status_code, 404)
        self.client.force_login(self.cust)
        self.assertEqual(self.client.get(f'/cashier/order-loyalty/{o.id}/').status_code, 403)

    # ---------- branches, settings, customer view ----------
    def test_branch_orders_use_main_programme(self):
        bown = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'), owner=self.main)
        Restaurant.objects.create(name='Branch R', address='b', main_owner=self.main, branch_owner=bown,
                                  is_main_restaurant=False, parent_restaurant=self.r, qr_code='QRBR')
        self.assertEqual(svc.business_owner(bown), self.main)
        self.assertEqual(svc.business_owner(self.main), self.main)
        o = self._order(owner=bown)
        Payment.objects.create(order=o, amount=o.total_amount, payment_method='cash', processed_by=self.main)
        o.payment_status = 'paid'
        o.save(update_fields=['payment_status'])
        self.assertEqual(self._bal(), 25)

    def test_settings_page(self):
        self.client.force_login(self.main)
        self.client.post('/cashier/loyalty/', {'action': 'settings', 'enabled': 'on', 'spend_per_point': '2,000',
                                               'point_value': '100', 'min_redeem_points': '50'})
        self.program.refresh_from_db()
        self.assertEqual((self.program.spend_per_point, self.program.point_value, self.program.min_redeem_points),
                         (Decimal('2000.00'), Decimal('100.00'), 50))
        for bad in ({'spend_per_point': '0'}, {'point_value': 'abc'}, {'spend_per_point': 'NaN'}):
            data = {'action': 'settings', 'enabled': 'on', 'spend_per_point': '2000', 'point_value': '100',
                    'min_redeem_points': '50', **bad}
            self.client.post('/cashier/loyalty/', data)
            self.program.refresh_from_db()
            self.assertEqual(self.program.spend_per_point, Decimal('2000.00'), bad)
        self._give(10)
        self.client.post('/cashier/loyalty/', {'action': 'adjust', 'customer_id': self.cust.id, 'points': '-20'})
        self.assertEqual(self._bal(), 10)                                  # can't go below 0
        self.client.post('/cashier/loyalty/', {'action': 'adjust', 'customer_id': self.cust.id, 'points': '5',
                                               'note': 'Birthday'})
        self.assertEqual(self._bal(), 15)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get('/cashier/loyalty/').status_code, 302)
        bown = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'), owner=self.main)
        Restaurant.objects.create(name='Branch R', address='b', main_owner=self.main, branch_owner=bown,
                                  is_main_restaurant=False, parent_restaurant=self.r, qr_code='QRBR')
        self.client.force_login(bown)
        self.client.post('/cashier/loyalty/', {'action': 'settings', 'spend_per_point': '1', 'point_value': '1',
                                               'min_redeem_points': '1'})
        self.program.refresh_from_db()
        self.assertTrue(self.program.enabled)                              # branch owner: read-only

    def test_customer_sees_points(self):
        self._pay(self._order(), '25000')
        self.client.force_login(self.cust)
        page = self.client.get('/orders/my-points/').content.decode()
        self.assertIn('25 pts', page)
        data = self._api(self.cust).get('/api/v1/loyalty/me/').json()
        self.assertEqual((data['programs'][0]['points'], data['programs'][0]['worth']), (25, '1250.00'))
        self.assertEqual(self._api(self.cust2).get('/api/v1/loyalty/me/').json(), {'programs': [], 'code': None})
        self.assertEqual(data['code'], svc.redeem_code(self.cust))
        self.assertIn(data['code'], page if data['code'] in page else self.client.get('/orders/my-points/').content.decode())
