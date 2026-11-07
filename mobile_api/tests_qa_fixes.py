"""
Regression tests for the mobile API / attendance / staff-push bugs found by QA
(B2 duplicate-row locks, B3/B17 login, B4/B5/B10/B11 status endpoint, B8/B9 offline sync,
B12 lateness at check-in, B13 cancel item below paid, B6/B7 attendance restaurant + QR,
B14 staff pushes in Kiswahili).

Run:  python manage.py test mobile_api.tests_qa_fixes
"""
import datetime
import sys
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import django.test.client as _dtc
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User, RestaurantSubscription
from attendance.models import AttendanceQRToken, AttendanceRecord, Shift, RosterEntry, RosterWeek
from attendance import roster as roster_svc
from cashier.models import Payment
from orders.models import Order
from restaurant.models import TableInfo, MainCategory, Product
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):
    # Django 4.2's test client crashes copying template contexts on Python 3.14.
    _dtc.store_rendered_templates = lambda *a, **k: None

PW = 'Pw12345!xyzQ'


def role(name):
    return Role.objects.get_or_create(name=name)[0]


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class Base(TestCase):
    def setUp(self):
        self.push = mock.patch('orders.push.send_push').start()
        self.addCleanup(mock.patch.stopall)
        today = datetime.date.today()
        mk = lambda u, r, **kw: User.objects.create_user(u, password=PW, role=role(r), **kw)
        self.M = mk('mainown', 'main_owner', restaurant_name='Main R')
        self.B = mk('branchown', 'branch_owner', restaurant_name='Branch R')
        self.sub = RestaurantSubscription.objects.create(
            restaurant_owner=self.M, subscription_start_date=today,
            subscription_end_date=today + timedelta(days=30))
        self.rM = Restaurant.objects.create(name='Main R', address='a', main_owner=self.M, branch_owner=self.M,
                                            is_main_restaurant=True, qr_code='QRM', allow_remote_orders=True,
                                            tax_rate=Decimal('0.18'))
        self.rB = Restaurant.objects.create(name='Branch R', address='b', main_owner=self.M, branch_owner=self.B,
                                            is_main_restaurant=False, parent_restaurant=self.rM, qr_code='QRB',
                                            allow_remote_orders=True, tax_rate=Decimal('0.10'))
        self.cashier = mk('cash', 'cashier', owner=self.M)
        self.kitchen = mk('kit', 'kitchen', owner=self.M)
        self.bar = mk('barman', 'bar', owner=self.M)
        self.bcashier = mk('bcash', 'cashier', owner=self.B)
        self.cust = mk('cust', 'customer', phone_number='0712000000')
        self.tM = TableInfo.objects.create(restaurant=self.rM, owner=self.M, tbl_no='T1')
        self.tM2 = TableInfo.objects.create(restaurant=self.rM, owner=self.M, tbl_no='T2')
        cat = MainCategory.objects.create(restaurant=self.rM, owner=self.M, name='Food')
        bcat = MainCategory.objects.create(restaurant=self.rB, owner=self.B, name='BFood')
        self.food = Product.objects.create(name='Pilau', description='d', main_category=cat,
                                           price=Decimal('5000.00'), available_in_stock=50, station='kitchen')
        self.drink = Product.objects.create(name='Juice', description='d', main_category=cat,
                                            price=Decimal('1500.00'), available_in_stock=50, station='bar')
        self.bfood = Product.objects.create(name='Biryani', description='d', main_category=bcat,
                                            price=Decimal('7000.00'), available_in_stock=50)

    def api(self, user=None, rid=None):
        c = APIClient()
        if user is not None:
            c.force_authenticate(user)
        headers = {'HTTP_X_APP_FEATURES': 'delivery-fee'}
        if rid:
            headers['HTTP_X_RESTAURANT_ID'] = str(rid)
        c.credentials(**headers)
        return c

    def item(self, p=None, q=1):
        p = p or self.food
        return {'product_id': p.id, 'quantity': q, 'price': float(p.price)}

    def place_ok(self, user, payload, rid=None):
        r = self.api(user, rid).post('/api/v1/orders/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return Order.objects.get(id=r.json()['order']['id'])

    def dinein(self, items=None, table=None):
        return self.place_ok(self.cashier, {'table_id': (table or self.tM).id, 'items': items or [self.item(q=2)]})

    def pay(self, order, amount):
        return self.api(self.cashier).post('/api/v1/payments/', {
            'order_id': order.id, 'amount': str(amount), 'payment_method': 'cash'}, format='json')

    def status(self, user, order, new_status, **extra):
        return self.api(user).patch(f'/api/v1/orders/{order.id}/status/', {'status': new_status, **extra},
                                    format='json')

    def sync(self, user, body, rid=None):
        r = self.api(user, rid).post('/api/v1/sync/push/', body, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['results']


class PaymentLockTests(Base):
    """B2: OR'd owner joins return the same order twice → select_for_update().get() crashed."""

    def test_pay_and_void_when_main_owner_also_runs_a_branch(self):
        Restaurant.objects.create(name='Main R2', address='c', main_owner=self.M, branch_owner=self.M,
                                  is_main_restaurant=False, parent_restaurant=self.rM, qr_code='QRM2')
        o = self.place_ok(self.cashier, {'order_type': 'pickup', 'items': [self.item()]})
        r = self.pay(o, o.total_amount)
        self.assertEqual(r.status_code, 201, r.content[:300])
        o.refresh_from_db()
        self.assertEqual(o.payment_status, 'paid')
        pid = r.json()['payment']['id']
        r = self.api(self.cashier).post(f'/api/v1/payments/{pid}/void/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertTrue(Payment.objects.get(pk=pid).is_voided)

    def test_void_unknown_payment_is_404(self):
        r = self.api(self.cashier).post('/api/v1/payments/999999/void/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 404)


class LoginTests(Base):
    """B3: branch owner / branch staff can log in; B17: expired-by-date refused, lockout message."""

    def login(self, username, pw=PW):
        return APIClient().post('/api/v1/auth/login/', {'username': username, 'password': pw},
                                format='json', REMOTE_ADDR='10.0.0.9')

    def test_branch_owner_and_branch_staff_can_log_in(self):
        for u in (self.B, self.bcashier, self.cashier, self.M):
            r = self.login(u.username)
            self.assertEqual(r.status_code, 200, (u.username, r.content))

    def test_expired_by_date_refused_even_if_status_active(self):
        RestaurantSubscription.objects.filter(pk=self.sub.pk).update(
            subscription_end_date=datetime.date.today() - timedelta(days=30))
        for u in (self.cashier, self.B, self.bcashier):
            self.assertEqual(self.login(u.username).status_code, 403, u.username)
        self.assertEqual(self.login('cust').status_code, 200)

    def test_lockout_says_too_many_attempts(self):
        for _ in range(10):
            self.login('cash', 'wrong')
        r = self.login('cash')
        self.assertEqual(r.status_code, 403, r.content)
        self.assertIn('Too many failed attempts', r.json()['error'])

    def test_wrong_password_still_401(self):
        r = self.login('cash', 'wrong')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()['error'], 'Invalid username or password.')


class StatusEndpointTests(Base):
    """B4 pending→preparing for stations, B5 cancel rules, B10 station items, B11 timestamps."""

    def test_station_can_start_a_pending_order(self):
        o = self.dinein()
        r = self.status(self.kitchen, o, 'preparing')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.status, 'preparing')
        self.assertEqual(o.confirmed_by, self.kitchen)
        self.assertIsNotNone(o.confirmed_at)
        self.assertIsNotNone(o.preparing_at)
        self.assertEqual(self.status(self.kitchen, o, 'ready').status_code, 200)

    def test_station_still_limited_to_preparing_and_ready(self):
        o = self.dinein()
        self.assertEqual(self.status(self.kitchen, o, 'confirmed').status_code, 403)

    def test_timestamps_are_stamped(self):
        o = self.dinein()
        self.assertEqual(self.status(self.cashier, o, 'confirmed').status_code, 200)
        self.assertEqual(self.status(self.kitchen, o, 'preparing').status_code, 200)
        self.assertEqual(self.status(self.kitchen, o, 'ready').status_code, 200)
        self.assertEqual(self.status(self.cashier, o, 'served').status_code, 200)
        o.refresh_from_db()
        self.assertTrue(o.confirmed_at and o.preparing_at and o.ready_at and o.served_at)
        self.assertEqual(o.confirmed_by, self.cashier)

    def test_station_needs_items_for_its_station(self):
        o = self.dinein(items=[self.item()])  # kitchen-only
        self.status(self.cashier, o, 'confirmed')
        self.assertEqual(self.status(self.bar, o, 'preparing').status_code, 403)
        o.refresh_from_db()
        self.assertEqual(o.status, 'confirmed')
        mixed = self.dinein(items=[self.item(), self.item(self.drink)], table=self.tM2)
        self.assertEqual(self.status(self.bar, mixed, 'preparing').status_code, 200)

    def test_cancel_via_status_refused_with_payments(self):
        o = self.dinein()
        self.pay(o, o.total_amount)
        r = self.status(self.cashier, o, 'cancelled', reason='mistake')
        self.assertEqual(r.status_code, 400, r.content)
        o.refresh_from_db()
        self.assertNotEqual(o.status, 'cancelled')

    def test_cancel_via_status_needs_reason(self):
        o = self.dinein()
        self.assertEqual(self.status(self.cashier, o, 'cancelled').status_code, 400)
        o.refresh_from_db()
        self.assertEqual(o.status, 'pending')

    def test_cancel_via_status_needs_cancel_orders_permission(self):
        o = self.dinein()
        with mock.patch.object(User, 'has_feature', lambda self, slug: slug != 'cancel_orders'):
            r = self.status(self.cashier, o, 'cancelled', reason='x')
        self.assertEqual(r.status_code, 403)

    def test_cancel_via_status_restores_stock_and_frees_table(self):
        o = self.dinein()
        self.food.refresh_from_db()
        self.assertEqual(self.food.available_in_stock, 48)
        r = self.status(self.cashier, o, 'cancelled', reason='customer left')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db(); self.food.refresh_from_db(); self.tM.refresh_from_db()
        self.assertEqual((o.status, o.reason_if_cancelled), ('cancelled', 'customer left'))
        self.assertEqual(self.food.available_in_stock, 50)
        self.assertTrue(self.tM.is_available)

    def test_cancel_served_order_does_not_restore_stock(self):
        o = self.dinein()
        for s in ('confirmed', 'preparing', 'ready', 'served'):
            self.assertEqual(self.status(self.cashier, o, s).status_code, 200, s)
        r = self.status(self.cashier, o, 'cancelled', cancel_reason='complaint')
        self.assertEqual(r.status_code, 200, r.content)
        self.food.refresh_from_db()
        self.assertEqual(self.food.available_in_stock, 48)


class CancelItemTests(Base):
    """B13: removing an item must not drop the total below what was already paid."""

    def test_refused_when_total_would_drop_below_paid(self):
        o = self.dinein(items=[self.item(q=1), self.item(self.drink, q=4)])  # 11000 * 1.18 = 12980
        self.pay(o, Decimal('12000'))
        item = o.order_items.get(product=self.drink)
        r = self.api(self.cashier).post(f'/api/v1/orders/items/{item.id}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        o.refresh_from_db(); self.drink.refresh_from_db()
        self.assertEqual(o.order_items.count(), 2)
        self.assertEqual(o.total_amount.quantize(Decimal('0.01')), Decimal('12980.00'))
        self.assertEqual(self.drink.available_in_stock, 46)

    def test_payment_status_recomputed(self):
        o = self.dinein(items=[self.item(q=1), self.item(self.drink, q=2)])  # 8000 * 1.18 = 9440
        self.pay(o, Decimal('5900'))  # exactly the food: 5000 * 1.18
        item = o.order_items.get(product=self.drink)
        r = self.api(self.cashier).post(f'/api/v1/orders/items/{item.id}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.total_amount.quantize(Decimal('0.01')), Decimal('5900.00'))
        self.assertEqual(o.payment_status, 'paid')

    def test_unpaid_stays_unpaid(self):
        o = self.dinein(items=[self.item(q=1), self.item(self.drink, q=2)])
        item = o.order_items.get(product=self.drink)
        r = self.api(self.cashier).post(f'/api/v1/orders/items/{item.id}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.payment_status, 'unpaid')


class SyncTests(Base):
    """B8: offline-cancelled order frees its table. B9: customer offline orders follow online rules."""

    def test_offline_cancelled_order_frees_table(self):
        res = self.sync(self.cashier, {'orders': [{'offline_id': 'cx1', 'table_id': self.tM.id,
                                                   'items': [self.item(q=2)], 'status': 'cancelled'}]})
        o = Order.objects.get(id=res['orders'][0]['order_id'])
        self.assertEqual(o.status, 'cancelled')
        self.tM.refresh_from_db(); self.food.refresh_from_db()
        self.assertTrue(self.tM.is_available)
        self.assertEqual(self.food.available_in_stock, 50)

    def test_customer_sync_refused_when_remote_orders_off(self):
        Restaurant.objects.filter(pk=self.rM.pk).update(allow_remote_orders=False)
        res = self.sync(self.cust, {'orders': [{'offline_id': 'c1', 'order_type': 'pickup', 'items': [self.item()],
                                                'restaurant_id': self.rM.id}]}, self.rM.id)
        self.assertEqual(res['orders'][0]['status'], 'error')
        self.assertIn('not accepting', res['orders'][0]['error'])
        self.assertFalse(Order.objects.exists())

    def test_customer_sync_delivery_needs_phone(self):
        res = self.sync(self.cust, {'orders': [{'offline_id': 'c2', 'order_type': 'delivery', 'items': [self.item()],
                                                'restaurant_id': self.rM.id}]}, self.rM.id)
        self.assertEqual(res['orders'][0]['status'], 'error')
        self.assertIn('phone', res['orders'][0]['error'])
        self.assertFalse(Order.objects.exists())

    def test_customer_sync_drops_other_branch_products(self):
        res = self.sync(self.cust, {'orders': [{'offline_id': 'c3', 'order_type': 'pickup',
                                                'items': [self.item(), self.item(self.bfood)],
                                                'restaurant_id': self.rM.id}]}, self.rM.id)
        r = res['orders'][0]
        self.assertEqual(r['status'], 'created', r)
        self.assertEqual(r['dropped_item_ids'], [self.bfood.id])
        o = Order.objects.get(id=r['order_id'])
        self.assertEqual(list(o.order_items.values_list('product_id', flat=True)), [self.food.id])

    def test_customer_sync_only_other_branch_products_is_an_error(self):
        res = self.sync(self.cust, {'orders': [{'offline_id': 'c4', 'order_type': 'pickup',
                                                'items': [self.item(self.bfood)], 'restaurant_id': self.rM.id}]},
                        self.rM.id)
        self.assertEqual(res['orders'][0]['status'], 'error')
        self.assertFalse(Order.objects.exists())

    def test_staff_sync_unchanged(self):
        res = self.sync(self.cashier, {'orders': [{'offline_id': 'd1', 'order_type': 'delivery',
                                                   'items': [self.item()], 'restaurant_id': self.rM.id}]})
        self.assertEqual(res['orders'][0]['status'], 'created', res)  # staff: no phone rule (as online)


def _t(dt):
    return dt.time().replace(second=0, microsecond=0)


class AttendanceTests(Base):
    """B12 lateness at check-in; B6 restaurant/records for owners with branches; B7 branch QR."""

    def setUp(self):
        super().setUp()
        self.qr = AttendanceQRToken.objects.create(owner=self.M, restaurant=self.rM)
        now = timezone.localtime()
        self.cur = Shift.objects.create(owner=self.M, restaurant=self.rM, name='Current',
                                        start_time=_t(now - timedelta(minutes=5)),
                                        end_time=_t(now + timedelta(hours=3)))
        self.early = Shift.objects.create(owner=self.M, restaurant=self.rM, name='Early',
                                          start_time=_t(now - timedelta(hours=2)),
                                          end_time=_t(now - timedelta(minutes=30)))

    def confirm(self, user, token, action):
        return self.api(user).post('/api/v1/attendance/confirm/', {'qr_token': token, 'action': action},
                                   format='json')

    def scan(self, user, token):
        return self.api(user).post('/api/v1/attendance/scan/', {'qr_token': token}, format='json')

    def _roster_early(self):
        if timezone.localtime().hour < 3:
            self.skipTest('the "Early" shift would start yesterday')
        week = RosterWeek.objects.create(owner=self.M, week_start=roster_svc.monday(timezone.localdate()),
                                         status='published')
        RosterEntry.objects.create(week=week, staff=self.cashier, date=timezone.localdate(), kind='shift',
                                   shift=self.early)

    def test_late_known_at_check_in_and_kept_at_check_out(self):
        self._roster_early()
        r = self.confirm(self.cashier, self.qr.token, 'check_in')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['record']['is_late'])
        self.assertTrue(100 <= r.json()['record']['late_minutes'] <= 106, r.json()['record'])
        self.confirm(self.cashier, self.qr.token, 'check_out')
        rec = AttendanceRecord.objects.get(staff=self.cashier)
        self.assertTrue(rec.is_late)
        self.assertTrue(100 <= rec.late_minutes <= 106, rec.late_minutes)

    def test_on_time_check_in_not_late(self):
        r = self.confirm(self.cashier, self.qr.token, 'check_in')
        self.assertFalse(r.json()['record']['is_late'])

    def test_web_scan_check_in_sets_late(self):
        self._roster_early()
        self.client.force_login(self.cashier)
        r = self.client.post('/admin-panel/attendance/checkin/qr-scan/', {'qr_token': self.qr.token})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(AttendanceRecord.objects.get(staff=self.cashier).is_late)

    # ---- B7 ----
    def _qr_page_token(self, user, restaurant=None):
        self.client.force_login(user)
        if restaurant is not None:
            s = self.client.session
            s['selected_restaurant_id'] = restaurant.id
            s.save()
        with mock.patch('attendance.views_web.render',
                        lambda r, t, c=None, *a, **k: HttpResponse(c['qr_token'])):
            resp = self.client.get('/admin-panel/attendance/qr/')
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_branch_qr_made_by_main_owner_works_for_branch(self):
        tok = self._qr_page_token(self.M, self.rB)
        self.assertEqual(AttendanceQRToken.objects.get(token=tok).owner, self.B)
        self.assertEqual(self.scan(self.bcashier, tok).status_code, 200)
        self.assertEqual(self.confirm(self.bcashier, tok, 'check_in').status_code, 200)
        self.assertEqual(self.scan(self.cashier, tok).status_code, 403)  # main staff are not branch staff
        self.assertEqual(self._qr_page_token(self.B), tok)                # branch owner sees the same QR

    def test_old_branch_qr_saved_under_main_owner(self):
        old = AttendanceQRToken.objects.create(owner=self.M, restaurant=self.rB)
        self.assertEqual(self._qr_page_token(self.B), old.token)          # no crash, same QR
        self.assertEqual(self.scan(self.bcashier, old.token).status_code, 200)

    def test_foreign_qr_still_rejected(self):
        other = User.objects.create_user('otherown', password=PW, role=role('main_owner'))
        rO = Restaurant.objects.create(name='Other', address='o', main_owner=other, branch_owner=other,
                                       is_main_restaurant=True, qr_code='QRO')
        oqr = AttendanceQRToken.objects.create(owner=other, restaurant=rO)
        self.assertEqual(self.scan(self.cashier, oqr.token).status_code, 403)
        self.assertEqual(self.scan(self.bcashier, self.qr.token).status_code, 403)

    # ---- B6 ----
    def _ctx(self, user, path, restaurant=None, **params):
        captured = {}
        self.client.force_login(user)
        if restaurant is not None:
            s = self.client.session
            s['selected_restaurant_id'] = restaurant.id
            s.save()
        with mock.patch('attendance.views_web.render',
                        lambda r, t, c=None, *a, **k: captured.update(c or {}) or HttpResponse('ok')):
            resp = self.client.get(path, params)
        self.assertEqual(resp.status_code, 200)
        return captured

    def _record(self, staff, owner, restaurant):
        return AttendanceRecord.objects.create(staff=staff, owner=owner, restaurant=restaurant,
                                               date=timezone.localdate(), check_in=timezone.now())

    def test_default_restaurant_is_main_not_branch(self):
        self._record(self.cashier, self.M, self.rM)
        today = timezone.localdate().isoformat()
        self.assertEqual(self._ctx(self.M, '/admin-panel/attendance/day/', date=today)['checked_in_count'], 1)

    def test_main_owner_sees_branch_records_when_branch_selected(self):
        self._record(self.bcashier, self.B, self.rB)
        self._record(self.cashier, self.M, self.rM)
        today = timezone.localdate().isoformat()
        ctx = self._ctx(self.M, '/admin-panel/attendance/day/', restaurant=self.rB, date=today)
        self.assertEqual(ctx['checked_in_count'], 1)
        self.assertEqual(ctx['records'][0]['staff_name'], 'bcash')

    def test_report_rate_counts_absent_staff_and_never_over_100(self):
        mon = roster_svc.monday(timezone.localdate()) - timedelta(days=7)
        for d in (mon, mon + timedelta(days=5), mon + timedelta(days=6)):  # incl. the weekend
            AttendanceRecord.objects.create(staff=self.cashier, owner=self.M, restaurant=self.rM, date=d,
                                            check_in=timezone.now(), work_minutes=60)
        ctx = self._ctx(self.M, '/admin-panel/attendance/reports/', date_from=mon.isoformat(),
                        date_to=(mon + timedelta(days=6)).isoformat())
        # 3 staff-days present / (3 active staff x 7 days)
        self.assertEqual(ctx['attendance_rate'], round(3 / 21 * 100, 1))

    def test_report_rate_uses_roster_when_there_is_one(self):
        mon = roster_svc.monday(timezone.localdate()) - timedelta(days=7)
        week = RosterWeek.objects.create(owner=self.M, week_start=mon, status='published')
        for i in (0, 1):
            RosterEntry.objects.create(week=week, staff=self.cashier, date=mon + timedelta(days=i),
                                       kind='shift', shift=self.cur)
        AttendanceRecord.objects.create(staff=self.cashier, owner=self.M, restaurant=self.rM, date=mon,
                                        check_in=timezone.now())
        ctx = self._ctx(self.M, '/admin-panel/attendance/reports/', date_from=mon.isoformat(),
                        date_to=(mon + timedelta(days=6)).isoformat())
        self.assertEqual(ctx['attendance_rate'], 50.0)


class StaffPushLanguageTests(Base):
    """B14: staff pushes go out in each person's language; English is unchanged."""

    def setUp(self):
        super().setUp()
        User.objects.filter(pk=self.kitchen.pk).update(expo_push_token='ExpoPushToken[kit]', language='sw')
        User.objects.filter(pk=self.cashier.pk).update(expo_push_token='ExpoPushToken[cash]', language='en')

    def sent_to(self, token):
        return [c.args for c in self.push.call_args_list if token in c.args[0]]

    def test_new_order_push_in_staff_language(self):
        o = self.place_ok(self.cust, {'table_id': self.tM.id, 'items': [self.item()]}, self.rM.id)
        title, body = self.sent_to('ExpoPushToken[kit]')[0][1:3]
        self.assertEqual(title, f'Oda Mpya #{o.order_number}')
        self.assertEqual(body, 'Meza T1 • bidhaa 1')

    def test_new_order_push_english_unchanged(self):
        User.objects.filter(pk=self.kitchen.pk).update(language='en')
        o = self.place_ok(self.cust, {'table_id': self.tM.id, 'items': [self.item()]}, self.rM.id)
        title, body = self.sent_to('ExpoPushToken[kit]')[0][1:3]
        self.assertEqual((title, body), (f'New Order #{o.order_number}', 'Table T1 • 1 item(s)'))

    def test_pickup_push_split_by_language(self):
        self.place_ok(self.cust, {'order_type': 'pickup', 'items': [self.item()]}, self.rM.id)
        self.assertEqual(self.sent_to('ExpoPushToken[kit]')[0][2], 'Kuchukua • bidhaa 1')
        self.assertEqual(self.sent_to('ExpoPushToken[cash]')[0][2], 'Pickup • 1 item(s)')

    def test_roster_push_in_staff_language(self):
        User.objects.filter(pk=self.cashier.pk).update(language='sw')
        nxt = roster_svc.monday(timezone.localdate()) + timedelta(days=7)
        roster_svc.save_week(self.M, nxt, {(self.cashier.id, nxt): 'off'}, self.M)
        roster_svc.publish_week(self.M, nxt, self.M)
        args = self.push.call_args.args
        self.assertEqual(args[0], ['ExpoPushToken[cash]'])
        self.assertEqual(args[1], 'Ratiba yako iko tayari 📅')
        self.assertIn('Jumatatu', args[2])

    def test_roster_push_english_unchanged(self):
        nxt = roster_svc.monday(timezone.localdate()) + timedelta(days=7)
        roster_svc.save_week(self.M, nxt, {(self.cashier.id, nxt): 'off'}, self.M)
        roster_svc.publish_week(self.M, nxt, self.M)
        args = self.push.call_args.args
        self.assertEqual(args[1], 'Your roster is ready 📅')
        self.assertEqual(args[2], f'Your shifts for the week of {nxt:%a %d %b} are published. Tap to see them.')

    def test_rider_assignment_push_in_rider_language(self):
        from orders.push import notify_rider_assigned
        rider = User.objects.create_user('rider', password=PW, role=role('delivery_rider'), owner=self.M,
                                         expo_push_token='ExpoPushToken[rd]', language='sw')
        o = self.place_ok(self.cashier, {'table_id': self.tM.id, 'items': [self.item()]})
        self.push.reset_mock()
        notify_rider_assigned(o, rider)
        args = self.push.call_args.args
        self.assertEqual(args[1], 'Usafirishaji Mpya 🛵')
        self.assertEqual(args[2], f'Oda #{o.order_number} imekabidhiwa kwako.')

    def test_low_rating_push_in_owner_language(self):
        from orders.push import notify_low_rating
        User.objects.filter(pk=self.M.pk).update(expo_push_token='ExpoPushToken[main]', language='sw')
        o = self.place_ok(self.cashier, {'table_id': self.tM.id, 'items': [self.item()]})
        rating = mock.Mock(restaurant_owner=User.objects.get(pk=self.M.pk), food_stars=2, delivery_stars=None,
                           comment='Cold', order=o, order_id=o.id)
        self.push.reset_mock()
        notify_low_rating(rating)
        args = self.sent_to('ExpoPushToken[main]')[0]
        self.assertEqual(args[1], f'Tathmini ya chini kwa oda #{o.order_number}')
        self.assertEqual(args[2], 'chakula 2★ — "Cold"')
