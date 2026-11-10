"""
Security / performance regressions (second review round):

- offline sync append follows the online add-items rule (customer care: own orders only)
- offline-synced special_instructions are sanitised and capped like the online path
- an order carries at most MAX_ORDER_ITEMS lines (online and sync)
- customers are throttled when placing orders; staff are not
- tables / menu / sync pull run a fixed number of queries (no per-row N+1)

Run:  python manage.py test mobile_api.tests_security2
"""
import sys

if sys.version_info >= (3, 14):
    # Django 4.2's test client crashes copying template contexts on Python 3.14.
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None

import datetime
import json
from decimal import Decimal as D
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.authtoken.models import Token

from accounts.models import Role, User, RestaurantSubscription
from orders.models import Order, OrderItem, BillRequest
from restaurant.models import TableInfo, MainCategory, SubCategory, Product
from restaurant.models_restaurant import Restaurant
from mobile_api.serializers import MAX_ORDER_ITEMS
from mobile_api.views.orders import CustomerOrderThrottle, safe_client_id

XSS = '<img src=x onerror=alert(1)>'


def role(name):
    return Role.objects.get_or_create(name=name)[0]


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class Base(TestCase):
    def setUp(self):
        cache.clear()
        for t in ['orders.push.send_push', 'orders.printing.auto_print_order',
                  'orders.printing.auto_print_new_items', 'orders.printing.auto_print_receipt']:
            p = mock.patch(t, return_value={})
            p.start()
            self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.owner = mk('ownA', 'main_owner', restaurant_name='A')
        self.cashier = mk('cashA', 'cashier', owner=self.owner)
        self.cc = mk('ccA', 'customer_care', owner=self.owner)
        self.cc2 = mk('ccA2', 'customer_care', owner=self.owner)
        self.cust = mk('cust', 'customer', phone_number='0712345678')
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.owner, defaults={
            'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        self.r = Restaurant.objects.create(name='A', address='a', main_owner=self.owner, branch_owner=self.owner,
                                           is_main_restaurant=True, qr_code='QA', tax_rate=D('0.18'),
                                           allow_remote_orders=True)
        self.table = TableInfo.objects.create(restaurant=self.r, owner=self.owner, tbl_no='A1')
        self.cat = MainCategory.objects.create(restaurant=self.r, owner=self.owner, name='Food')
        self.sub = SubCategory.objects.create(main_category=self.cat, name='Mains')
        self.p = Product.objects.create(name='PA', description='d', main_category=self.cat, sub_category=self.sub,
                                        price=D('1000'), available_in_stock=5000, station='kitchen')

    def api(self, u, method, url, data=None, **hdr):
        h = {'HTTP_AUTHORIZATION': f'Token {Token.objects.get_or_create(user=u)[0].key}'}
        h.update(hdr)
        fn = getattr(self.client, method)
        if data is not None:
            return fn(url, json.dumps(data), content_type='application/json', **h)
        return fn(url, **h)

    def push(self, u, orders, **hdr):
        r = self.api(u, 'post', '/api/v1/sync/push/', {'orders': orders}, **hdr)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['results']['orders']

    def order_by(self, user, table=None):
        o = Order.objects.create(order_number=f'O-{Order.objects.count() + 1}', table_info=table or self.table,
                                 ordered_by=user, status='pending')
        OrderItem.objects.create(order=o, product=self.p, quantity=1, unit_price=self.p.price)
        o.calculate_total()
        o.save()
        return o

    def place(self, u, n_items=1, **hdr):
        return self.api(u, 'post', '/api/v1/orders/', {
            'table_id': self.table.id,
            'items': [{'product_id': self.p.id, 'quantity': 1, 'price': 1000}] * n_items}, **hdr)


class SyncAppendAccessTests(Base):
    def test_cc_cannot_sync_append_to_another_staff_order(self):
        o = self.order_by(self.cashier)
        online = self.api(self.cc, 'post', f'/api/v1/orders/{o.id}/add-items/',
                          {'items': [{'product_id': self.p.id, 'quantity': 1}]})
        self.assertEqual(online.status_code, 403)
        res = self.push(self.cc, [{'offline_id': 'y1', 'existing_order_id': o.id,
                                   'items': [{'product_id': self.p.id, 'quantity': 5}]}])[0]
        self.assertEqual(res['status'], 'error')
        self.assertEqual(res['error'], online.json()['error'])  # same message as online
        self.assertEqual(o.order_items.count(), 1)

    def test_cc_cannot_sync_append_to_other_cc_order(self):
        o = self.order_by(self.cc2)
        res = self.push(self.cc, [{'offline_id': 'y2', 'existing_order_id': o.id,
                                   'items': [{'product_id': self.p.id, 'quantity': 1}]}])[0]
        self.assertEqual(res['status'], 'error')
        self.assertEqual(o.order_items.count(), 1)

    def test_cc_can_sync_append_to_own_order(self):
        o = self.order_by(self.cc)
        res = self.push(self.cc, [{'offline_id': 'y3', 'existing_order_id': o.id,
                                   'items': [{'product_id': self.p.id, 'quantity': 2}]}])[0]
        self.assertEqual(res['status'], 'created', res)
        self.assertEqual(o.order_items.count(), 2)

    def test_cashier_can_still_sync_append_to_any_order(self):
        o = self.order_by(self.cc)
        res = self.push(self.cashier, [{'offline_id': 'y4', 'existing_order_id': o.id,
                                        'items': [{'product_id': self.p.id, 'quantity': 1}]}])[0]
        self.assertEqual(res['status'], 'created', res)

    def test_role_outside_online_rule_refused(self):
        kitchen = User.objects.create_user('kit', password='pw12345!x', role=role('kitchen'), owner=self.owner)
        o = self.order_by(self.cashier)
        with mock.patch.object(User, 'has_feature', return_value=True):
            res = self.push(kitchen, [{'offline_id': 'y5', 'existing_order_id': o.id,
                                       'items': [{'product_id': self.p.id, 'quantity': 1}]}])[0]
        self.assertEqual(res['status'], 'error')
        self.assertEqual(o.order_items.count(), 1)


class SyncInstructionsTests(Base):
    def test_new_order_instructions_sanitised_and_capped(self):
        res = self.push(self.cust, [{'offline_id': 'z1', 'table_id': self.table.id,
                                     'special_instructions': XSS + 'A' * 5000,
                                     'items': [{'product_id': self.p.id, 'quantity': 1}]}],
                        HTTP_X_RESTAURANT_ID=str(self.r.id))[0]
        self.assertEqual(res['status'], 'created', res)
        o = Order.objects.get(id=res['order_id'])
        self.assertNotIn('<', o.special_instructions)
        self.assertEqual(len(o.display_instructions), 500)
        self.assertTrue(o.special_instructions.startswith('[offline:z1]'))

    def test_append_instructions_sanitised_and_capped(self):
        o = self.order_by(self.cashier)
        res = self.push(self.cashier, [{'offline_id': 'z2', 'existing_order_id': o.id,
                                        'special_instructions': XSS + 'B' * 5000,
                                        'items': [{'product_id': self.p.id, 'quantity': 1}]}])[0]
        self.assertEqual(res['status'], 'created', res)
        o.refresh_from_db()
        self.assertNotIn('<', o.special_instructions)
        self.assertEqual(o.special_instructions.count('B'), 500)
        self.assertIn('[offline-append:z2]', o.special_instructions)

    def test_offline_id_cannot_break_out_of_tag(self):
        bad = 'x] ' + XSS
        res = self.push(self.cashier, [{'offline_id': bad, 'table_id': self.table.id,
                                        'items': [{'product_id': self.p.id, 'quantity': 1}]}])[0]
        self.assertEqual(res['status'], 'created', res)
        o = Order.objects.get(id=res['order_id'])
        self.assertNotIn('<', o.special_instructions)
        self.assertNotIn(']', o.special_instructions.split(']', 1)[1])
        # app ids pass through unchanged, so dedup keeps working
        self.assertEqual(safe_client_id('1731234567890-ab12cd3'), '1731234567890-ab12cd3')
        self.assertEqual(safe_client_id('chk-1731234567890-ab12cd34'), 'chk-1731234567890-ab12cd34')

    def test_sync_duplicate_still_detected(self):
        body = [{'offline_id': '1731-abc', 'table_id': self.table.id,
                 'items': [{'product_id': self.p.id, 'quantity': 1}]}]
        self.assertEqual(self.push(self.cashier, body)[0]['status'], 'created')
        self.assertEqual(self.push(self.cashier, body)[0]['status'], 'duplicate')


class ItemsCapTests(Base):
    def test_online_place_order_rejects_more_than_cap(self):
        r = self.place(self.cashier, n_items=MAX_ORDER_ITEMS + 1)
        self.assertEqual(r.status_code, 400)
        self.assertIn('items', r.json())
        self.assertEqual(Order.objects.count(), 0)

    def test_online_place_order_accepts_cap(self):
        r = self.place(self.cashier, n_items=MAX_ORDER_ITEMS)
        self.assertEqual(r.status_code, 201, r.content)

    def test_sync_rejects_more_than_cap(self):
        res = self.push(self.cashier, [{'offline_id': 'c1', 'table_id': self.table.id,
                                        'items': [{'product_id': self.p.id, 'quantity': 1}] * (MAX_ORDER_ITEMS + 1)}])[0]
        self.assertEqual(res['status'], 'error')
        self.assertIn('error', res)
        self.assertEqual(Order.objects.count(), 0)

    def test_sync_append_rejects_more_than_cap(self):
        o = self.order_by(self.cashier)
        res = self.push(self.cashier, [{'offline_id': 'c2', 'existing_order_id': o.id,
                                        'items': [{'product_id': self.p.id, 'quantity': 1}] * (MAX_ORDER_ITEMS + 1)}])[0]
        self.assertEqual(res['status'], 'error')
        self.assertEqual(o.order_items.count(), 1)


class CustomerThrottleTests(Base):
    def test_default_rate(self):
        self.assertEqual(CustomerOrderThrottle.rate, '20/hour')

    def test_customer_throttled_with_json_error(self):
        with mock.patch.object(CustomerOrderThrottle, 'rate', '3/hour'):
            codes = [self.place(self.cust, HTTP_X_RESTAURANT_ID=str(self.r.id)).status_code for _ in range(3)]
            self.assertEqual(codes, [201, 201, 201])
            r = self.place(self.cust, HTTP_X_RESTAURANT_ID=str(self.r.id))
        self.assertEqual(r.status_code, 429)
        self.assertIn('error', r.json())
        self.assertEqual(Order.objects.filter(ordered_by=self.cust).count(), 3)

    def test_customer_retry_of_synced_order_not_counted(self):
        with mock.patch.object(CustomerOrderThrottle, 'rate', '1/hour'):
            body = {'table_id': self.table.id, 'offline_id': 'same-1',
                    'items': [{'product_id': self.p.id, 'quantity': 1, 'price': 1000}]}
            r1 = self.api(self.cust, 'post', '/api/v1/orders/', body, HTTP_X_RESTAURANT_ID=str(self.r.id))
            r2 = self.api(self.cust, 'post', '/api/v1/orders/', body, HTTP_X_RESTAURANT_ID=str(self.r.id))
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()['already_synced'])

    def test_customer_sync_push_shares_the_limit(self):
        with mock.patch.object(CustomerOrderThrottle, 'rate', '2/hour'):
            res = self.push(self.cust, [{'offline_id': f's{i}', 'table_id': self.table.id,
                                         'items': [{'product_id': self.p.id, 'quantity': 1}]} for i in range(3)],
                            HTTP_X_RESTAURANT_ID=str(self.r.id))
            self.assertEqual([x['status'] for x in res], ['created', 'created', 'error'])
            self.assertIn('error', res[2])
            r = self.place(self.cust, HTTP_X_RESTAURANT_ID=str(self.r.id))
            self.assertEqual(r.status_code, 429)

    def test_staff_not_throttled(self):
        with mock.patch.object(CustomerOrderThrottle, 'rate', '2/hour'):
            codes = [self.place(self.cashier).status_code for _ in range(5)]
            res = self.push(self.cashier, [{'offline_id': f't{i}', 'table_id': self.table.id,
                                            'items': [{'product_id': self.p.id, 'quantity': 1}]} for i in range(4)])
        self.assertEqual(codes, [201] * 5)
        self.assertEqual([x['status'] for x in res], ['created'] * 4)


class QueryCountTests(Base):
    """Query count must not grow with the number of tables / categories / orders."""

    def count(self, u, url):
        Token.objects.get_or_create(user=u)  # token creation is not part of the request
        with CaptureQueriesContext(connection) as ctx:
            r = self.api(u, 'get', url)
        self.assertEqual(r.status_code, 200, r.content)
        return len(ctx.captured_queries), r.json()

    def add_tables(self, n, start):
        for i in range(n):
            t = TableInfo.objects.create(restaurant=self.r, owner=self.owner, tbl_no=f'T{start + i}')
            if i % 2 == 0:
                self.order_by(self.cashier, table=t)
                BillRequest.objects.create(table_info=t, requested_by=self.cashier, status='pending')

    def add_categories(self, n, start):
        for i in range(n):
            c = MainCategory.objects.create(restaurant=self.r, owner=self.owner, name=f'C{start + i}')
            SubCategory.objects.create(main_category=c, name=f'S{start + i}')

    def test_tables_constant_queries_and_same_result(self):
        self.add_tables(2, 10)
        q1, _ = self.count(self.cashier, '/api/v1/tables/')
        self.add_tables(6, 20)
        q2, data = self.count(self.cashier, '/api/v1/tables/')
        self.assertEqual(q1, q2)
        self.assertLessEqual(q2, 12)
        for row in data['tables']:
            t = TableInfo.objects.get(id=row['id'])
            self.assertEqual(row['is_available'], t.is_truly_available(), row)
        self.assertEqual(set(data['tables'][0]),
                         {'id', 'tbl_no', 'table_number', 'is_available', 'capacity', 'display_name', 'restaurant_id'})

    def test_menu_constant_queries(self):
        self.add_categories(2, 10)
        q1, _ = self.count(self.cashier, '/api/v1/menu/')
        self.add_categories(6, 20)
        q2, data = self.count(self.cashier, '/api/v1/menu/')
        self.assertEqual(q1, q2)
        self.assertLessEqual(q2, 15)
        self.assertEqual(set(data), {'categories', 'synced_at', 'restaurant_name'})
        food = next(c for c in data['categories'] if c['name'] == 'Food')
        self.assertEqual([s['name'] for s in food['subcategories']], ['Mains'])
        self.assertEqual([p['name'] for p in food['subcategories'][0]['products']], ['PA'])

    def test_sync_pull_constant_queries(self):
        self.add_tables(2, 10)
        self.add_categories(2, 10)
        q1, _ = self.count(self.cashier, '/api/v1/sync/pull/')
        self.add_tables(6, 20)
        self.add_categories(6, 20)
        q2, data = self.count(self.cashier, '/api/v1/sync/pull/')
        self.assertEqual(q1, q2)
        self.assertLessEqual(q2, 25)
        pending = [o for o in data['active_orders'] if o['pending_bill_requested']]
        self.assertTrue(pending)
        self.assertTrue(all(o['pending_bill_requested_at'] for o in pending))
