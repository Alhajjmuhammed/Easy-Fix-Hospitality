"""
Regression tests for customer ordering flows (QR, dine-in, pickup, delivery),
remote-order visibility for staff, and the pages that previously crashed.

Run:  python manage.py test orders.tests_customer_flows
"""
import datetime
import sys
from decimal import Decimal

import django.test.client as _dtc
from asgiref.sync import async_to_sync
from django.test import TestCase, TransactionTestCase, RequestFactory
from django.urls import get_resolver, URLPattern, URLResolver
from rest_framework.test import APIClient

from accounts.models import Role, User, RestaurantSubscription
from restaurant.models_restaurant import Restaurant
from restaurant.models import TableInfo, MainCategory, Product
from orders.models import Order

if sys.version_info >= (3, 14):
    # Django 4.2's test client crashes copying template contexts on Python 3.14.
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class RestaurantWebSocketTests(TransactionTestCase):
    """Staff live-update socket: role checks must not run on the event loop."""

    def setUp(self):
        self.owner = User.objects.create_user('wsowner', password='pw12345!x', role=role('main_owner'))
        self.other_owner = User.objects.create_user('wsother', password='pw12345!x', role=role('main_owner'))
        self.cashier = User.objects.create_user('wscash', password='pw12345!x', role=role('cashier'), owner=self.owner)
        self.kitchen = User.objects.create_user('wskit', password='pw12345!x', role=role('kitchen'), owner=self.owner)
        self.other_cashier = User.objects.create_user('wsocash', password='pw12345!x', role=role('cashier'), owner=self.other_owner)
        self.customer = User.objects.create_user('wscust', password='pw12345!x', role=role('customer'))

    def _connect(self, user, owner_id):
        from channels.testing import WebsocketCommunicator
        from orders.consumers import RestaurantConsumer
        fresh = User.objects.get(pk=user.pk)  # role not cached, as when loaded by the auth middleware
        comm = WebsocketCommunicator(RestaurantConsumer.as_asgi(), f'/ws/restaurant/{owner_id}/')
        comm.scope['user'] = fresh
        comm.scope['url_route'] = {'kwargs': {'owner_id': str(owner_id)}}
        async def run():
            connected, _ = await comm.connect()
            await comm.disconnect()
            return connected
        return async_to_sync(run)()

    def test_staff_and_owner_can_connect(self):
        self.assertTrue(self._connect(self.cashier, self.owner.id))
        self.assertTrue(self._connect(self.kitchen, self.owner.id))
        self.assertTrue(self._connect(self.owner, self.owner.id))

    def test_outsiders_rejected(self):
        self.assertFalse(self._connect(self.customer, self.owner.id))
        self.assertFalse(self._connect(self.other_cashier, self.owner.id))


class CustomerFlowTests(TestCase):
    def setUp(self):
        self.main = User.objects.create_user('main', password='pw12345!x', role=role('main_owner'), restaurant_name='Main R')
        self.branch_owner = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'), owner=self.main, restaurant_name='Branch R')
        self.other_owner = User.objects.create_user('oth', password='pw12345!x', role=role('main_owner'), restaurant_name='Other R')
        self.cust = User.objects.create_user('cust', password='pw12345!x', role=role('customer'))
        self.cust2 = User.objects.create_user('cust2', password='pw12345!x', role=role('customer'))
        self.cashier = User.objects.create_user('cash', password='pw12345!x', role=role('cashier'), owner=self.main)
        self.kitchen = User.objects.create_user('kit', password='pw12345!x', role=role('kitchen'), owner=self.main)
        self.cc = User.objects.create_user('cc', password='pw12345!x', role=role('customer_care'), owner=self.main)
        self.admin = User.objects.create_user('adm', password='pw12345!x', role=role('administrator'), is_staff=True, is_superuser=True)
        self.other_cashier = User.objects.create_user('ocash', password='pw12345!x', role=role('cashier'), owner=self.other_owner)
        self.r_main = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                                is_main_restaurant=True, qr_code='QRMAIN', allow_remote_orders=True)
        self.r_branch = Restaurant.objects.create(name='Branch R', address='b', main_owner=self.main, branch_owner=self.branch_owner,
                                                  is_main_restaurant=False, parent_restaurant=self.r_main, qr_code='QRBR', allow_remote_orders=True)
        today = datetime.date.today()
        self.sub = RestaurantSubscription.objects.create(restaurant_owner=self.main, subscription_start_date=today,
                                                         subscription_end_date=today + datetime.timedelta(days=30))
        RestaurantSubscription.objects.create(restaurant_owner=self.other_owner, subscription_start_date=today,
                                              subscription_end_date=today + datetime.timedelta(days=30))
        self.table = TableInfo.objects.create(restaurant=self.r_main, owner=self.main, tbl_no='T1')
        TableInfo.objects.create(restaurant=self.r_branch, owner=self.branch_owner, tbl_no='B1')
        cat = MainCategory.objects.create(restaurant=self.r_main, owner=self.main, name='Food')
        bcat = MainCategory.objects.create(restaurant=self.r_branch, owner=self.branch_owner, name='Branch Food')
        self.p = Product.objects.create(name='Pilau', description='d', main_category=cat, price=Decimal('5000.00'), available_in_stock=50)
        self.bp = Product.objects.create(name='Biryani', description='d', main_category=bcat, price=Decimal('7000.00'), available_in_stock=50)

    def _api(self, user, rid=None):
        c = APIClient()
        c.force_authenticate(user)
        if rid:
            c.credentials(HTTP_X_RESTAURANT_ID=str(rid))
        return c

    def _place(self, payload, rid, user=None):
        return self._api(user or self.cust, rid).post('/api/v1/orders/', payload, format='json')

    def _item(self, p=None, q=1):
        p = p or self.p
        return [{'product_id': p.id, 'quantity': q, 'price': float(p.price)}]

    def _web_cart(self, qty=1):
        s = self.client.session
        s['cart'] = {str(self.p.id): {'name': 'Pilau', 'price': '5000.00', 'quantity': qty}}
        s.save()

    # Remote (delivery/pickup) orders are linked to their restaurant and visible to its staff only
    def test_mobile_remote_order_visible_to_own_staff_only(self):
        self.assertIn(self._place({'order_type': 'pickup', 'items': self._item()}, self.r_main.id).status_code, (200, 201))
        o = Order.objects.get(ordered_by=self.cust)
        self.assertEqual((o.restaurant_owner, o.owner), (self.main, self.main))
        self.assertIn(o.id, [x['id'] for x in self._api(self.cashier).get('/api/v1/orders/').json()['orders']])
        self.assertNotIn(o.id, [x['id'] for x in self._api(self.other_cashier).get('/api/v1/orders/').json()['orders']])

    def test_web_remote_order_on_kitchen_dashboard(self):
        self.client.force_login(self.cust)
        self.client.post(f'/restaurant/browse/{self.r_main.id}/order-type/', {'order_type': 'pickup'})
        self._web_cart()
        self.client.post('/orders/place-order/', {'special_instructions': ''})
        o = Order.objects.get(ordered_by=self.cust)
        self.assertEqual(o.restaurant_owner, self.main)
        self.client.force_login(self.kitchen)
        page = self.client.get('/orders/kitchen/')
        self.assertEqual(page.status_code, 200)
        self.assertIn(o.order_number, page.content.decode())

    def test_offline_sync_remote_and_staff_dine_in(self):
        from mobile_api.views.sync import _sync_order
        res = _sync_order(self.cust, self.main, {'offline_id': 's1', 'order_type': 'pickup', 'items': self._item()})
        self.assertEqual(Order.objects.get(id=res['order_id']).restaurant_owner, self.main)
        r = self._api(self.cashier).post('/api/v1/orders/', {'table_id': self.table.id, 'items': self._item(q=2)}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        o = Order.objects.get(ordered_by=self.cashier)
        self.assertEqual((o.table_info_id, o.order_type, o.restaurant_owner_id), (self.table.id, 'dine-in', None))

    # Customers only see the restaurant they selected (main vs branch)
    def test_customer_menu_and_tables_scoped(self):
        names = [c['name'] for c in self._api(self.cust, self.r_main.id).get('/api/v1/menu/').json()['categories']]
        self.assertEqual(names, ['Food'])
        tbl = [x['tbl_no'] for x in self._api(self.cust, self.r_main.id).get('/api/v1/tables/').json()['tables']]
        self.assertEqual(tbl, ['T1'])
        self.assertEqual(self._place({'table_id': self.table.id, 'items': self._item(self.bp)}, self.r_main.id).status_code, 400)
        staff = [c['name'] for c in self._api(self.cashier).get('/api/v1/menu/').json()['categories']]
        self.assertIn('Branch Food', staff)

    def test_retry_does_not_duplicate_and_tag_hidden(self):
        payload = {'order_type': 'pickup', 'items': self._item(), 'offline_id': 'chk-1', 'special_instructions': 'no onions'}
        self._place(payload, self.r_main.id)
        self.assertTrue(self._place(payload, self.r_main.id).json().get('already_synced'))
        o = Order.objects.get(ordered_by=self.cust)
        self.assertEqual(o.display_instructions, 'no onions')

    def test_blocked_restaurant_rejects_customers(self):
        from mobile_api.views.helpers import get_restaurant_owner

        def resolve(u, rid):
            req = RequestFactory().get('/', HTTP_X_RESTAURANT_ID=str(rid))
            req.user = u
            return get_restaurant_owner(req)
        self.sub.block_restaurant(reason='t')
        self.assertIsNone(resolve(self.cust, self.r_main.id))
        self.assertIsNone(resolve(self.cust, self.r_branch.id))

    def test_append_to_others_order_and_remote_checks(self):
        from mobile_api.views.sync import _sync_order
        other = Order.objects.create(order_number='ORD-OTHER', table_info=self.table, ordered_by=self.cust2, status='pending')
        self.assertEqual(_sync_order(self.cust, self.main, {'offline_id': 'x2', 'existing_order_id': other.id, 'items': self._item()})['status'], 'error')
        self.assertIn('phone', str(self._place({'order_type': 'delivery', 'delivery_address': 'x', 'items': self._item()}, self.r_main.id).content))
        Restaurant.objects.filter(id=self.r_main.id).update(allow_remote_orders=False)
        self.assertIn('not accepting', self._place({'order_type': 'pickup', 'items': self._item()}, self.r_main.id).json().get('error', ''))

    def test_table_selection_resets_session_and_dine_in_works(self):
        self.client.force_login(self.cashier)
        s = self.client.session
        s.update({'order_type': 'pickup', 'add_to_order_id': 5, 'delivery_lat': '1.0'})
        s.save()
        self.client.post('/orders/table/', {'table_id': self.table.id})
        s = self.client.session
        self.assertEqual(s.get('order_type'), 'dine-in')
        self.assertNotIn('add_to_order_id', s)
        self.assertNotIn('delivery_lat', s)
        self._web_cart(2)
        self.client.post('/orders/place-order/', {'special_instructions': ''})
        o = Order.objects.get(ordered_by=self.cashier)
        self.assertEqual((o.table_info_id, o.order_type), (self.table.id, 'dine-in'))

    def test_profile_tax_updates_restaurant(self):
        self.client.force_login(self.main)
        self.client.post('/accounts/update-tax-rate/', data='{"tax_rate": 0.18}', content_type='application/json')
        self.r_main.refresh_from_db()
        self.assertEqual(self.r_main.tax_rate, Decimal('0.1800'))

    def test_gps_pin_saved_on_web_delivery(self):
        self.client.force_login(self.cust)
        self.client.post(f'/restaurant/browse/{self.r_main.id}/delivery/',
                         {'delivery_address': 'Stone Town', 'delivery_phone': '0777', 'delivery_lat': '-6.1659', 'delivery_lng': '39.2026'})
        self._web_cart()
        self.client.post('/orders/place-order/', {'special_instructions': ''})
        o = Order.objects.get(ordered_by=self.cust)
        self.assertEqual((o.order_type, o.delivery_lat, o.delivery_lng), ('delivery', Decimal('-6.1659000'), Decimal('39.2026000')))

    def test_gps_pin_invalid_ignored_and_optional(self):
        self.client.force_login(self.cust)
        self.client.post(f'/restaurant/browse/{self.r_main.id}/delivery/',
                         {'delivery_address': 'x', 'delivery_phone': '0777', 'delivery_lat': '999', 'delivery_lng': 'abc'})
        self.assertNotIn('delivery_lat', self.client.session)
        self._web_cart()
        self.client.post('/orders/place-order/', {'special_instructions': ''})
        o = Order.objects.get(ordered_by=self.cust)
        self.assertEqual((o.order_type, o.delivery_lat), ('delivery', None))

    def test_previously_crashing_pages(self):
        self.client.force_login(self.main)
        r = self.client.get('/admin-panel/consolidated-reports/')
        self.assertEqual((r.status_code, r['Location']), (302, '/reports/'))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/accounts/profile/').status_code, 200)
        self.client.force_login(self.cashier)
        for u in ('/cashier/receipts/', '/cashier/reports/'):
            self.assertLess(self.client.get(u).status_code, 500, u)

    def test_smoke_all_pages(self):
        def collect(resolver, prefix=''):
            out = []
            for p in resolver.url_patterns:
                if isinstance(p, URLResolver):
                    out += collect(p, prefix + str(p.pattern))
                elif isinstance(p, URLPattern):
                    route = prefix + str(p.pattern)
                    if '<' not in route and '(?P' not in route and not route.startswith('^'):
                        out.append('/' + route.rstrip('$'))
            return out
        skip = ('logout', 'delete', 'export', 'pdf', 'csv', 'regenerate', 'print', 'download', 'debug', 'upload', 'secure-management-portal')
        urls = sorted(set(u for u in collect(get_resolver()) if not any(s in u for s in skip)))
        self._place({'order_type': 'delivery', 'delivery_phone': '0777', 'delivery_address': 'x', 'items': self._item()}, self.r_main.id)
        errors = []
        for user in (self.main, self.cashier, self.kitchen, self.cc, self.admin):
            self.client.force_login(user)
            api = self._api(user)
            for u in urls:
                try:
                    r = (api if u.startswith('/api/') else self.client).get(u)
                    if r.status_code >= 500:
                        errors.append(f'{user.username} {u} -> {r.status_code}')
                except Exception as e:
                    errors.append(f'{user.username} {u} -> {e.__class__.__name__}: {str(e)[:100]}')
        print(f'\nSMOKE: {len(urls)} urls x 5 users, errors={len(errors)}')
        for e in errors:
            print('SMOKEERR', e)
        self.assertEqual(errors, [])
