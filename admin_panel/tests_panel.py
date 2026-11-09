"""
Regression tests for the owner/manager web panel (admin_panel).

Covers: printer settings tenancy, branch deletion scope, dashboard numbers,
main-owner dashboard, QR regenerate/image for the selected branch, cancelling from
the panel, table deletion with open orders, profile saves, product prices, tax
parsing, staff role allow-list and orphan branch owners.

Run:  python manage.py test admin_panel.tests_panel
"""
import datetime
import sys
import uuid
from decimal import Decimal as D
from unittest import mock

import django.test.client as _dtc
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, User, RestaurantSubscription, Feature
from accounts.permissions_defaults import ALL_FEATURES
from restaurant.models_restaurant import Restaurant
from restaurant.models import TableInfo, MainCategory, SubCategory, Product
from orders.models import Order, OrderItem

if sys.version_info >= (3, 14):
    # Django 4.2's test client crashes copying template contexts on Python 3.14.
    _dtc.store_rendered_templates = lambda *a, **k: None

PW = 'pw12345!x'


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class capture:
    """Grab the context dict a views module passes to render()."""
    def __init__(self, module):
        self.module, self.ctx = module, {}

    def __enter__(self):
        self.real = self.module.render

        def fake(request, template, context=None, *a, **k):
            self.ctx.clear(); self.ctx.update(context or {})
            return self.real(request, template, context, *a, **k)
        self.module.render = fake
        return self.ctx

    def __exit__(self, *exc):
        self.module.render = self.real


class PanelBase(TestCase):
    """main owner `main` (PRO): r_main, branch r_a (bo_a), branch r_b (bo_b); other tenant r_other."""

    def setUp(self):
        for target in ('orders.push.send_push', 'orders.printing.auto_print_receipt',
                       'orders.printing.auto_print_order'):
            p = mock.patch(target, return_value={'kot_printed': False, 'bot_printed': False})
            p.start(); self.addCleanup(p.stop)
        for slug, name, desc, cat in ALL_FEATURES:
            Feature.objects.get_or_create(slug=slug, defaults={'name': name, 'description': desc, 'category': cat})
        for name, _ in Role.ROLE_CHOICES:
            role(name)
        # Shift user ids away from restaurant ids, so an id mix-up cannot hide.
        User.objects.bulk_create([User(username=f'pfill{i}', role=role('customer')) for i in range(30)])

        def mk(u, r, **kw):
            return User.objects.create_user(u, password=PW, role=role(r), email=f'{u}@t.tz', **kw)
        self.main = mk('pmain', 'main_owner')
        self.bo_a = mk('pbo_a', 'branch_owner')
        self.bo_b = mk('pbo_b', 'branch_owner')
        self.other = mk('pother', 'main_owner')
        self.cust = mk('pcust', 'customer')
        today = datetime.date.today()
        for o in (self.main, self.other):
            RestaurantSubscription.objects.create(restaurant_owner=o, subscription_start_date=today,
                                                  subscription_end_date=today + datetime.timedelta(days=30))
        common = dict(tax_rate=D('0.1800'), currency_code='TZS', allow_remote_orders=True)
        self.r_main = Restaurant.objects.create(name='Main', address='x', main_owner=self.main, branch_owner=self.main,
                                                is_main_restaurant=True, subscription_plan='PRO', **common)
        self.r_a = Restaurant.objects.create(name='Branch A', address='x', main_owner=self.main, branch_owner=self.bo_a,
                                             parent_restaurant=self.r_main, **common)
        self.r_b = Restaurant.objects.create(name='Branch B', address='x', main_owner=self.main, branch_owner=self.bo_b,
                                             parent_restaurant=self.r_main, **common)
        self.r_other = Restaurant.objects.create(name='Other', address='x', main_owner=self.other,
                                                 branch_owner=self.other, is_main_restaurant=True, **common)
        self.mgr_a = mk('pmgr_a', 'manager', owner=self.bo_a)
        self.cash_a = mk('pcash_a', 'cashier', owner=self.bo_a)
        self.t, self.cat, self.prod = {}, {}, {}
        for key, r, owner in (('main', self.r_main, self.main), ('a', self.r_a, self.bo_a),
                              ('b', self.r_b, self.bo_b), ('other', self.r_other, self.other)):
            self.t[key] = TableInfo.objects.create(restaurant=r, owner=owner, tbl_no=f'{key.upper()}1')
            self.cat[key] = MainCategory.objects.create(restaurant=r, owner=owner, name=f'Food {key}')
            sub = SubCategory.objects.create(main_category=self.cat[key], name=f'Rice {key}')
            self.prod[key] = Product.objects.create(name=f'Pilau {key}', description='x', main_category=self.cat[key],
                                                    sub_category=sub, price=D('5000.00'), available_in_stock=100)

    def login(self, user, restaurant=None):
        self.client.force_login(user)
        if restaurant is not None:
            self.assertEqual(self.client.get('/admin-panel/switch-restaurant/',
                                             {'restaurant_id': restaurant.id}).status_code, 302)

    def order(self, table, items, status='pending', order_type='dine-in', **kw):
        o = Order.objects.create(order_number=uuid.uuid4().hex[:10], table_info=table, ordered_by=self.cust,
                                 status=status, order_type=order_type, **kw)
        for p, q in items:
            OrderItem.objects.create(order=o, product=p, quantity=q, unit_price=p.price)
        o.calculate_total()
        o.save()
        return o

    def self_managed_branch(self):
        """A branch the main owner runs himself (branch_owner == main_owner)."""
        return Restaurant.objects.create(name='Self Branch', address='x', main_owner=self.main,
                                         branch_owner=self.main, parent_restaurant=self.r_main,
                                         tax_rate=D('0.1800'))


class PrinterSettingsTests(PanelBase):
    """Bug 1: the session holds a USER id; it must never be used as a Restaurant id."""

    def test_never_writes_another_tenants_restaurant(self):
        # A restaurant whose id equals bo_a's user id (what the old code looked up)
        victim = self.r_other
        Restaurant.objects.filter(pk=victim.pk).update(kitchen_printer_name='Victim')
        self.login(self.bo_a)
        s = self.client.session
        s['selected_restaurant_id'] = victim.id      # forged / coincidental id
        s.save()
        self.client.post('/admin-panel/printer-settings/save/', {'kitchen_printer': 'Mine'})
        victim.refresh_from_db(); self.r_a.refresh_from_db()
        self.assertEqual(victim.kitchen_printer_name, 'Victim')
        self.assertEqual(self.r_a.kitchen_printer_name, 'Mine')

    def test_main_owner_saves_selected_branch(self):
        self.login(self.main, self.r_b)
        self.client.post('/admin-panel/printer-settings/save/', {'kitchen_printer': 'B Kitchen'})
        self.r_b.refresh_from_db(); self.r_main.refresh_from_db()
        self.assertEqual(self.r_b.kitchen_printer_name, 'B Kitchen')
        self.assertNotEqual(self.r_main.kitchen_printer_name, 'B Kitchen')


class BranchDeleteTests(PanelBase):
    """Bug 2."""

    def _delete(self, r):
        return self.client.post(f'/admin-panel/branches/{r.id}/delete/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()

    def test_delete_branch_with_menu(self):
        self.login(self.main)
        res = self._delete(self.r_a)
        self.assertTrue(res['success'], res)
        self.assertFalse(Restaurant.objects.filter(pk=self.r_a.pk).exists())
        self.assertFalse(User.objects.filter(username__in=['pbo_a', 'pmgr_a', 'pcash_a']).exists())
        self.assertTrue(Product.objects.filter(pk=self.prod['main'].pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.prod['b'].pk).exists())

    def test_branch_with_orders_is_refused(self):
        o = self.order(self.t['a'], [(self.prod['a'], 1)])
        self.login(self.main)
        res = self._delete(self.r_a)
        self.assertFalse(res['success'])
        self.assertIn('order', res['error'])
        self.assertTrue(Order.objects.filter(pk=o.pk).exists())
        self.assertTrue(Restaurant.objects.filter(pk=self.r_a.pk).exists())

    def test_self_managed_branch_keeps_main_data(self):
        br = self.self_managed_branch()
        TableInfo.objects.create(restaurant=br, tbl_no='S1')
        main_order = self.order(self.t['main'], [(self.prod['main'], 1)])
        self.login(self.main)
        res = self._delete(br)
        self.assertTrue(res['success'], res)
        self.assertFalse(Restaurant.objects.filter(pk=br.pk).exists())
        self.assertTrue(TableInfo.objects.filter(pk=self.t['main'].pk).exists())
        self.assertTrue(MainCategory.objects.filter(pk=self.cat['main'].pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.prod['main'].pk).exists())
        self.assertTrue(Order.objects.filter(pk=main_order.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.main.pk).exists())

    def test_other_tenant_denied(self):
        self.login(self.other)
        self.assertFalse(self._delete(self.r_a)['success'])
        self.assertTrue(Restaurant.objects.filter(pk=self.r_a.pk).exists())


class DashboardTests(PanelBase):
    """Bugs 3 and 4."""

    def setUp(self):
        super().setUp()
        self.order(self.t['main'], [(self.prod['main'], 1)])                    # 5,900
        self.order(self.t['a'], [(self.prod['a'], 2)], status='served')          # 11,800
        self.order(self.t['a'], [(self.prod['a'], 1)], status='cancelled')       # not revenue
        self.order(self.t['a'], [(self.prod['a'], 1)], status='wasted')          # not revenue
        self.order(None, [(self.prod['a'], 1)], order_type='pickup', restaurant_owner=self.bo_a)  # 5,900
        self.order(self.t['b'], [(self.prod['b'], 1)])                           # 5,900

    def _dash(self, user, restaurant=None, view_all=False):
        self.login(user, restaurant)
        if view_all:
            self.client.get('/admin-panel/set-view-all-restaurants/')
        from admin_panel import views
        with capture(views) as ctx:
            self.assertEqual(self.client.get('/admin-panel/').status_code, 200)
        return dict(ctx)

    def test_branch_owner_sees_only_branch_and_excludes_cancelled(self):
        ctx = self._dash(self.bo_a)
        self.assertEqual(ctx['today_revenue'], D('17700.00'))
        self.assertEqual(ctx['total_orders'], 4)
        self.assertEqual(ctx['pending_orders'], 1)

    def test_manager_matches_owner(self):
        a = self._dash(self.bo_a)
        m = self._dash(self.mgr_a)
        self.assertEqual((m['total_orders'], m['today_revenue']), (a['total_orders'], a['today_revenue']))

    def test_main_restaurant_excludes_branches(self):
        ctx = self._dash(self.main, self.r_main)
        self.assertEqual((ctx['total_orders'], ctx['today_revenue']), (1, D('5900.00')))

    def test_all_locations_excludes_cancelled(self):
        ctx = self._dash(self.main, view_all=True)
        self.assertEqual(ctx['today_revenue'], D('29500.00'))

    def test_main_owner_dashboard_per_branch(self):
        Product.objects.create(name='Chapati', description='x', main_category=self.cat['a'], price=D('1000'))
        self.login(self.main)
        from admin_panel import views_main_owner
        with capture(views_main_owner) as ctx:
            self.client.get('/admin-panel/main-owner-dashboard/')
        stat = {s['restaurant'].id: s for s in ctx['branch_stats']}
        self.assertEqual(stat[self.r_a.id]['orders_count'], 4)               # incl. pickup
        self.assertEqual(stat[self.r_a.id]['today_revenue'], D('17700.00'))  # no join duplication, no cancelled
        self.assertEqual(stat[self.r_a.id]['products_count'], 2)
        self.assertEqual(stat[self.r_main.id]['orders_count'], 1)
        self.assertEqual(ctx['total_revenue'], D('29500.00'))

    def test_branch_reports_date_to_today_includes_today(self):
        self.login(self.main)
        today = timezone.localdate().isoformat()
        from admin_panel import views_main_owner
        with capture(views_main_owner) as ctx:
            self.client.get('/admin-panel/branch-reports/', {'restaurant': self.r_b.id, 'date_from': today, 'date_to': today})
        self.assertEqual(ctx['total_orders'], 1)

    def test_switch_to_self_managed_branch(self):
        br = self.self_managed_branch()
        ctx = self._dash(self.main, br)
        self.assertEqual(ctx['current_restaurant'], br)
        self.assertEqual(ctx['total_orders'], 0)


class QRCodeTests(PanelBase):
    """Bug 5."""

    def test_regenerate_acts_on_selected_branch(self):
        self.login(self.main, self.r_b)
        old_b, old_main = self.r_b.qr_code, self.r_main.qr_code
        self.client.post('/admin-panel/qr-code/regenerate/')
        self.r_b.refresh_from_db(); self.r_main.refresh_from_db()
        self.assertNotEqual(self.r_b.qr_code, old_b)
        self.assertEqual(self.r_main.qr_code, old_main)

    def test_image_encodes_selected_branch(self):
        self.login(self.main, self.r_b)
        from admin_panel import views
        seen = []
        real = views.get_production_qr_url
        views.get_production_qr_url = lambda req, code: seen.append(code) or real(req, code)
        try:
            self.assertEqual(self.client.get('/admin-panel/qr-code/image/').status_code, 200)
        finally:
            views.get_production_qr_url = real
        self.assertEqual(seen, [self.r_b.qr_code])

    def test_regenerate_needs_manage_tables(self):
        self.login(self.bo_a)
        self.client.post('/admin-panel/roles-permissions/save-role/',
                         '{"role_name": "manager", "feature_slugs": ["view_orders"]}', content_type='application/json')
        self.login(self.mgr_a)
        old = self.r_a.qr_code
        self.client.post('/admin-panel/qr-code/regenerate/')
        self.r_a.refresh_from_db()
        self.assertEqual(self.r_a.qr_code, old)


class CancelFromPanelTests(PanelBase):
    """Bug 6 (and 21: moving an order between tables)."""

    def _status(self, order, status, **extra):
        return self.client.post('/admin-panel/orders/update-status/',
                                {'order_id': order.id, 'status': status, **extra}).json()

    def test_cancel_restores_stock_and_frees_table(self):
        o = self.order(self.t['a'], [(self.prod['a'], 3)], status='preparing')
        Product.objects.filter(pk=self.prod['a'].pk).update(available_in_stock=97)
        self.assertFalse(TableInfo.objects.get(pk=self.t['a'].pk).is_available)
        self.login(self.bo_a)
        self.assertTrue(self._status(o, 'cancelled')['success'])
        o.refresh_from_db()
        self.assertEqual(o.status, 'cancelled')
        self.assertEqual(Product.objects.get(pk=self.prod['a'].pk).available_in_stock, 100)
        self.assertTrue(TableInfo.objects.get(pk=self.t['a'].pk).is_available)

    def test_served_order_cancel_keeps_stock(self):
        o = self.order(self.t['a'], [(self.prod['a'], 3)], status='served')
        self.login(self.bo_a)
        self.assertTrue(self._status(o, 'cancelled')['success'])
        self.assertEqual(Product.objects.get(pk=self.prod['a'].pk).available_in_stock, 100)

    def test_paid_order_refused(self):
        from cashier.models import Payment
        o = self.order(self.t['a'], [(self.prod['a'], 1)], status='served')
        Payment.objects.create(order=o, amount=o.total_amount, payment_method='cash', processed_by=self.cash_a)
        self.login(self.bo_a)
        res = self._status(o, 'cancelled')
        self.assertFalse(res['success'])
        self.assertIn('Void the payment', res['message'])
        self.assertEqual(Order.objects.get(pk=o.pk).status, 'served')
        # edit_order path too
        res = self.client.post(f'/admin-panel/orders/edit/{o.id}/', {'status': 'cancelled'}).json()
        self.assertFalse(res['success'])
        self.assertEqual(Order.objects.get(pk=o.pk).status, 'served')

    def test_voided_payment_does_not_block(self):
        from cashier.models import Payment
        o = self.order(self.t['a'], [(self.prod['a'], 1)])
        Payment.objects.create(order=o, amount=o.total_amount, payment_method='cash', processed_by=self.cash_a,
                               is_voided=True)
        self.login(self.bo_a)
        self.assertTrue(self._status(o, 'cancelled')['success'])

    def test_requires_cancel_orders_feature(self):
        from accounts.permissions_defaults import DEFAULT_ROLE_FEATURES
        o = self.order(self.t['a'], [(self.prod['a'], 1)])
        feats = [f for f in DEFAULT_ROLE_FEATURES['manager'] if f != 'cancel_orders']
        self.login(self.bo_a)
        import json
        self.client.post('/admin-panel/roles-permissions/save-role/',
                         json.dumps({'role_name': 'manager', 'feature_slugs': feats}), content_type='application/json')
        self.login(self.mgr_a)
        self.assertFalse(self._status(o, 'cancelled')['success'])
        self.client.post(f'/admin-panel/orders/edit/{o.id}/', {'status': 'cancelled'})
        self.assertEqual(Order.objects.get(pk=o.pk).status, 'pending')

    def test_empty_reason_refused_when_sent(self):
        o = self.order(self.t['a'], [(self.prod['a'], 1)])
        self.login(self.bo_a)
        self.assertFalse(self._status(o, 'cancelled', reason='  ')['success'])
        self.assertTrue(self._status(o, 'cancelled', reason='Customer left')['success'])
        self.assertEqual(Order.objects.get(pk=o.pk).reason_if_cancelled, 'Customer left')

    def test_move_order_moves_table_occupancy(self):
        t2 = TableInfo.objects.create(restaurant=self.r_a, owner=self.bo_a, tbl_no='A2')
        o = self.order(self.t['a'], [(self.prod['a'], 1)])
        self.login(self.bo_a)
        self.assertTrue(self.client.post(f'/admin-panel/orders/edit/{o.id}/', {'table_id': t2.id}).json()['success'])
        self.assertFalse(TableInfo.objects.get(pk=t2.pk).is_available)
        self.assertTrue(TableInfo.objects.get(pk=self.t['a'].pk).is_available)

    def test_move_keeps_old_table_busy_with_other_order(self):
        t2 = TableInfo.objects.create(restaurant=self.r_a, owner=self.bo_a, tbl_no='A2')
        o = self.order(self.t['a'], [(self.prod['a'], 1)])
        self.order(self.t['a'], [(self.prod['a'], 1)])
        self.login(self.bo_a)
        self.client.post(f'/admin-panel/orders/edit/{o.id}/', {'table_id': t2.id})
        self.assertFalse(TableInfo.objects.get(pk=self.t['a'].pk).is_available)


class TableTests(PanelBase):
    """Bugs 9, 10, 20."""

    def test_delete_table_with_open_order_refused(self):
        o = self.order(self.t['a'], [(self.prod['a'], 1)], status='preparing')
        self.login(self.bo_a)
        res = self.client.post('/admin-panel/tables/delete/', {'table_id': self.t['a'].id}).json()
        self.assertFalse(res['success'])
        self.assertTrue(TableInfo.objects.filter(pk=self.t['a'].pk).exists())
        self.assertEqual(Order.objects.get(pk=o.pk).table_info_id, self.t['a'].id)

    def test_delete_table_with_finished_orders_ok(self):
        self.order(self.t['a'], [(self.prod['a'], 1)], status='cancelled')
        self.order(self.t['a'], [(self.prod['a'], 1)], status='served', payment_status='paid')
        self.login(self.bo_a)
        self.assertTrue(self.client.post('/admin-panel/tables/delete/', {'table_id': self.t['a'].id}).json()['success'])

    def test_self_managed_branch_may_reuse_main_table_number_but_not_its_own(self):
        # Owner decision 2026-11-09: table numbers are unique per restaurant
        br = self.self_managed_branch()
        self.login(self.main)
        add = lambda: self.client.post('/admin-panel/tables/add/',
                                       {'tbl_no': 'MAIN1', 'capacity': '4', 'restaurant_id': br.id}).json()
        self.assertTrue(add()['success'])                                  # same number as the main restaurant
        res = add()                                                        # twice in the same branch
        self.assertFalse(res['success'])
        self.assertIn('already exists', res['message'])

    def test_main_can_rename_table_to_number_used_only_in_branch(self):
        self.login(self.main)
        res = self.client.post('/admin-panel/tables/update/', {'table_id': self.t['main'].id, 'tbl_no': 'A1',
                                                               'capacity': '4', 'is_available': 'on'}).json()
        self.assertTrue(res['success'], res)


class ProfileTests(PanelBase):
    """Bugs 13, 14, 19."""

    def _profile(self, **extra):
        data = {'action': 'update_restaurant', 'restaurant_name': 'Main', 'tax_rate_percentage': '18'}
        data.update(extra)
        return self.client.post('/admin-panel/profile/', data)

    def test_main_owner_save_leaves_branches_alone(self):
        Restaurant.objects.filter(pk=self.r_a.pk).update(tax_rate=D('0.1000'), wifi_ssid='BranchWifi',
                                                          allow_remote_orders=True)
        self.login(self.main)
        self._profile(tax_rate_percentage='15', wifi_ssid='MainWifi')
        self.r_main.refresh_from_db(); self.r_a.refresh_from_db()
        self.assertEqual(self.r_main.tax_rate, D('0.1500'))
        self.assertEqual(self.r_main.wifi_ssid, 'MainWifi')
        self.assertFalse(self.r_main.allow_remote_orders)
        self.assertEqual((self.r_a.tax_rate, self.r_a.wifi_ssid, self.r_a.allow_remote_orders),
                         (D('0.1000'), 'BranchWifi', True))

    def test_empty_tax_keeps_current(self):
        self.login(self.bo_a)
        self._profile(tax_rate_percentage='', restaurant_name='Branch A')
        self.r_a.refresh_from_db()
        self.assertEqual(self.r_a.tax_rate, D('0.1800'))

    def test_invalid_tax_rejected(self):
        self.login(self.bo_a)
        for bad in ('nan', 'inf', '-1', '100', 'abc'):
            self._profile(tax_rate_percentage=bad, restaurant_name='Branch A')
            self.r_a.refresh_from_db()
            self.assertEqual(self.r_a.tax_rate, D('0.1800'), bad)

    def test_edit_branch_tax(self):
        self.login(self.main)
        url = f'/admin-panel/branches/{self.r_a.id}/edit/'
        self.client.post(url, {'name': 'Branch A', 'address': 'x'})                       # missing → keep
        self.client.post(url, {'name': 'Branch A', 'address': 'x', 'tax_rate': ''})       # empty → keep
        self.client.post(url, {'name': 'Branch A', 'address': 'x', 'tax_rate': 'nan'})    # rejected
        self.r_a.refresh_from_db()
        self.assertEqual(self.r_a.tax_rate, D('0.1800'))
        self.client.post(url, {'name': 'Branch A', 'address': 'x', 'tax_rate': '16.5'})
        self.r_a.refresh_from_db()
        self.assertEqual(self.r_a.tax_rate, D('0.1650'))

    def test_manager_told_clearly_nothing_changes(self):
        self.login(self.mgr_a)
        r = self._profile(tax_rate_percentage='12', restaurant_name='Branch A')
        self.r_a.refresh_from_db()
        self.assertEqual(self.r_a.tax_rate, D('0.1800'))
        msgs = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any('owner' in m for m in msgs), msgs)
        self.assertFalse(any('successfully' in m for m in msgs), msgs)


class ProductTests(PanelBase):
    """Bugs 15, 17."""

    def _data(self, **kw):
        d = {'name': 'Mishkaki', 'description': 'x', 'main_category': self.cat['a'].id,
             'sub_category': self.cat['a'].subcategories.first().id, 'price': '2500', 'available_in_stock': '10',
             'preparation_time': '10', 'is_available': 'on', 'station': 'kitchen'}
        d.update(kw)
        return d

    def test_add_rejects_bad_prices(self):
        self.login(self.bo_a)
        for bad in ('0', '0.001', '-5', 'nan', 'inf', 'abc'):
            res = self.client.post('/admin-panel/products/add/', self._data(price=bad)).json()
            self.assertFalse(res['success'], bad)
        self.assertFalse(Product.objects.filter(name='Mishkaki').exists())
        res = self.client.post('/admin-panel/products/add/', self._data(price='0.01')).json()
        self.assertTrue(res['success'], res)
        self.assertEqual(Product.objects.get(name='Mishkaki').price, D('0.01'))

    def test_update_rejects_bad_price(self):
        self.login(self.bo_a)
        p = self.prod['a']
        for bad in ('-100', '0', 'nan'):
            self.client.post(f'/admin-panel/products/{p.id}/update/', {'price': bad, 'is_available': 'on'},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            p.refresh_from_db()
            self.assertEqual(p.price, D('5000.00'), bad)

    def test_station_validated(self):
        self.login(self.bo_a)
        res = self.client.post('/admin-panel/products/add/', self._data(station='garage')).json()
        self.assertFalse(res['success'])
        res = self.client.post('/admin-panel/products/add/', self._data(station='bar')).json()
        self.assertTrue(res['success'])


class StaffTests(PanelBase):
    """Coordinator items A, B, C and bug 8."""

    def _add(self, username, role_name, **extra):
        data = {'first_name': 'Juma', 'last_name': 'Hassan', 'username': username, 'email': f'{username}@t.tz',
                'password': 'Staff2026!x', 'role': role_name, 'is_active': 'on'}
        data.update(extra)
        return self.client.post('/admin-panel/users/add/', data).json()

    def _upd(self, user, **changes):
        data = {'first_name': user.first_name or 'X', 'last_name': user.last_name or 'Y', 'username': user.username,
                'email': user.email, 'role': user.role.name, 'is_active': 'on'}
        data.update(changes)
        return self.client.post(f'/admin-panel/users/{user.id}/update/', data).json()

    def test_system_roles_never_creatable(self):
        role('admin_staff')
        for u in (self.main, self.bo_a, self.mgr_a):
            self.login(u)
            for rn in ('admin_staff', 'administrator', 'main_owner', 'owner'):
                self.assertFalse(self._add(f'x_{u.id}_{rn}', rn)['success'], (u.username, rn))
        self.assertFalse(User.objects.filter(username__startswith='x_').exists())

    def test_staff_roles_still_creatable(self):
        self.login(self.bo_a)
        for rn in ('manager', 'cashier', 'kitchen', 'delivery_rider'):
            self.assertTrue(self._add(f'ok_{rn}', rn)['success'], rn)
        self.login(self.mgr_a)
        self.assertFalse(self._add('mgr_makes_mgr', 'manager')['success'])
        self.assertTrue(self._add('mgr_makes_cash', 'cashier')['success'])

    def test_update_cannot_grant_system_role_or_change_own_role(self):
        role('admin_staff')
        self.login(self.bo_a)
        self.assertFalse(self._upd(self.cash_a, role='admin_staff')['success'])
        self.assertEqual(User.objects.get(pk=self.cash_a.pk).role.name, 'cashier')
        self.login(self.main)
        self.assertFalse(self._upd(self.main, role='cashier')['success'])
        self.assertEqual(User.objects.get(pk=self.main.pk).role.name, 'main_owner')

    def test_weak_passwords_rejected(self):
        self.login(self.bo_a)
        self.assertFalse(self._add('weak', 'cashier', password='1')['success'])
        self.assertFalse(self._add('weak2', 'cashier', password='short7!')['success'])
        self.assertFalse(User.objects.filter(username__startswith='weak').exists())
        res = self._upd(self.cash_a, password='123')
        self.assertFalse(res['success'])
        self.assertTrue(User.objects.get(pk=self.cash_a.pk).check_password(PW))

    def test_no_orphan_branch_owner(self):
        self.login(self.main)       # main-restaurant context
        self.assertFalse(self._add('orphan_bo', 'branch_owner')['success'])
        self.assertFalse(self._add('orphan_bo2', 'branch_owner', restaurant_id=self.r_a.id)['success'])  # has owner
        self.assertFalse(User.objects.filter(username__startswith='orphan').exists())
        br = self.self_managed_branch()
        # (the existing plan check reads the branch's own subscription_plan)
        Restaurant.objects.filter(pk=br.pk).update(subscription_plan='PRO')
        res = self._add('real_bo', 'branch_owner', restaurant_id=br.id)
        self.assertTrue(res['success'], res)
        br.refresh_from_db()
        self.assertEqual(br.branch_owner.username, 'real_bo')

    def test_main_owner_manages_branch_staff(self):
        self.login(self.main)
        res = self.client.post(f'/admin-panel/users/{self.cash_a.id}/toggle/').json()
        self.assertTrue(res['success'], res)
        self.login(self.other)
        self.assertFalse(self.client.post(f'/admin-panel/users/{self.cash_a.id}/toggle/').json()['success'])
