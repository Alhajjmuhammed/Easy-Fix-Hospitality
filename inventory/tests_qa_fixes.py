"""Regression tests for the stock / waste / reports QA fixes."""
import csv
import datetime
import io
import json
import sys
from decimal import Decimal as D
from unittest import mock

from django.http import HttpResponse
from django.test import TestCase
from django.utils import timezone

from accounts.models import Feature, Role, RolePermissionSet, RestaurantSubscription, User
from cashier.models import Payment
from inventory.models import InventoryItem, InventoryRecord, RecipeIngredient
from orders.models import Order, OrderItem
from restaurant.models import MainCategory, Product, TableInfo
from restaurant.models_restaurant import Restaurant
from waste_management.models import FoodWasteLog, ProductCostSettings

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


def restrict(owner, role_name, *slugs):
    rps, _ = RolePermissionSet.objects.get_or_create(owner=owner, role_name=role_name)
    rps.features.set([Feature.objects.get_or_create(slug=s, defaults={'name': s})[0] for s in slugs])


class Base(TestCase):
    def setUp(self):
        for target in ('orders.push.send_push', 'orders.push.notify_customer_status'):
            p = mock.patch(target)
            p.start()
            self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.bown = mk('bown', 'branch_owner', owner=self.main, restaurant_name='Branch R')
        self.manager = mk('mgr', 'manager', owner=self.main)
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.cash2 = mk('cash2', 'cashier', owner=self.bown)
        self.cust = mk('cust', 'customer')
        self.other = mk('oth', 'main_owner', restaurant_name='Other R')
        today = datetime.date.today()
        for o in (self.main, self.bown, self.other):
            RestaurantSubscription.objects.get_or_create(restaurant_owner=o, defaults={
                'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        self.r1 = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                            is_main_restaurant=True, qr_code='QR1', tax_rate=D('0.1000'))
        self.r2 = Restaurant.objects.create(name='Branch R', address='b', main_owner=self.main, branch_owner=self.bown,
                                            is_main_restaurant=False, parent_restaurant=self.r1, qr_code='QR2',
                                            tax_rate=D('0.1000'))
        self.r3 = Restaurant.objects.create(name='Other R', address='c', main_owner=self.other, branch_owner=self.other,
                                            is_main_restaurant=True, qr_code='QR3')
        self.t1 = TableInfo.objects.create(restaurant=self.r1, owner=self.main, tbl_no='T1')
        self.t2 = TableInfo.objects.create(restaurant=self.r2, owner=self.bown, tbl_no='B1')
        food = MainCategory.objects.create(restaurant=self.r1, owner=self.main, name='Food')
        bfood = MainCategory.objects.create(restaurant=self.r2, owner=self.bown, name='BFood')
        ofood = MainCategory.objects.create(restaurant=self.r3, owner=self.other, name='OFood')
        self.pilau = Product.objects.create(name='Pilau', description='', main_category=food, price=D('10.00'))
        self.juice = Product.objects.create(name='Juice', description='', main_category=food, price=D('2.00'))
        self.biry = Product.objects.create(name='Biryani', description='', main_category=bfood, price=D('10.00'))
        self.theirs = Product.objects.create(name='Theirs', description='', main_category=ofood, price=D('7.00'))
        self.rice = InventoryItem.objects.create(owner=self.main, name='Rice', unit='kg', unit_price=D('2.50'))
        self._n = 0

    def stock(self, item):
        return InventoryItem.objects.get(pk=item.pk).current_stock

    def rec(self, user, item, rtype, qty, price=''):
        self.client.force_login(user)
        return self.client.post('/inventory/record/', {'item_id': item.id, 'record_type': rtype,
                                                         'quantity': qty, 'unit_price': price})

    def ctx(self, user, url, module, session=None):
        self.client.force_login(user)
        if session:
            s = self.client.session
            s.update(session)
            s.save()
        box = {}

        def fake(request, template, context=None, *a, **k):
            box['ctx'] = context
            return HttpResponse('ok')
        with mock.patch(f'{module}.render', side_effect=fake):
            self.client.get(url)
        return box.get('ctx')


# ---------------------------------------------------------------------------
# Inventory records
# ---------------------------------------------------------------------------
class RecordTests(Base):
    def test_1_1_closing_count_sets_the_level(self):
        self.rec(self.manager, self.rice, 'received', '10')
        self.assertEqual(self.rec(self.manager, self.rice, 'closing', '8').status_code, 302)
        self.assertEqual(self.stock(self.rice), D('8'))
        rec = InventoryRecord.objects.filter(record_type='closing').get()
        self.assertEqual(rec.quantity_change, D('-2'))
        self.assertIn('Counted 8', rec.notes)
        self.rec(self.manager, self.rice, 'closing', '0')                 # empty shelf is a valid count
        self.assertEqual(self.stock(self.rice), D('0'))
        self.rec(self.manager, self.rice, 'closing', '12.5')
        self.assertEqual(self.stock(self.rice), D('12.5'))
        r = self.rec(self.manager, self.rice, 'closing', '-1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.stock(self.rice), D('12.5'))

    def test_1_2_amount_paid_is_a_total(self):
        self.rec(self.manager, self.rice, 'received', '10', '50')
        self.assertEqual(InventoryRecord.objects.get().unit_price, D('5.00'))
        self.rec(self.manager, self.rice, 'returned', '2', '10')
        self.rec(self.manager, self.rice, 'received', '3', '10')          # 3.333.. -> 3.33 per unit
        self.assertEqual(InventoryRecord.objects.get(quantity_change=D('3')).unit_price, D('3.33'))
        self.client.force_login(self.manager)
        rows = list(csv.reader(io.StringIO(self.client.get('/inventory/history/?export=csv').content.decode())))
        self.assertEqual(rows[1], ['Total Spent', '$59.99'])               # 50 + 3 x 3.33
        self.assertEqual(rows[2], ['Total Refunds', '$10.00'])
        costs = sorted(r[5] for r in rows if len(r) > 5 and r[1] == 'Rice')
        # 1.3: the row shows what the movement cost, not the unit price
        self.assertEqual(costs, ['+$10.00 (Refund)', '-$50.00', '-$9.99'])
        page = self.client.get('/inventory/history/').content.decode()
        self.assertIn('50.00', page)

    def test_1_5_and_1_7_bad_quantities_rejected(self):
        for q in ['0', 'abc', '', '0.001', 'nan', 'inf', '-inf', '1e20', '123456789', '-4']:
            r = self.rec(self.manager, self.rice, 'received', q)
            self.assertEqual(r.status_code, 200, q)
        for t in ('opening', 'used', 'waste', 'returned'):
            self.assertEqual(self.rec(self.manager, self.rice, t, '-1').status_code, 200, t)
        self.assertEqual(self.rec(self.manager, self.rice, 'received', '1', 'nan').status_code, 200)
        self.assertFalse(InventoryRecord.objects.exists())
        self.assertEqual(self.rec(self.manager, self.rice, 'adjustment', '-0.3').status_code, 302)
        self.assertEqual(self.stock(self.rice), D('-0.30'))

    def test_1_6_bad_values_no_500(self):
        self.client.force_login(self.manager)
        r = self.client.post('/inventory/items/', {'action': 'add', 'name': 'Sugar', 'low_stock_threshold': 'abc'})
        self.assertFalse(r.json()['success'])
        InventoryItem.objects.create(owner=self.main, name='Oil')
        r = self.client.post('/inventory/items/', {'action': 'edit', 'item_id': self.rice.id, 'name': 'oil'})
        self.assertFalse(r.json()['success'])
        r = self.client.post('/inventory/settings/', {'kind': 'unit', 'action': 'delete', 'id': 'abc'})
        self.assertEqual(r.status_code, 200)

    def test_6_1_view_only_cannot_archive_and_6_2_item_api(self):
        restrict(self.main, 'manager', 'view_inventory')
        self.client.force_login(self.manager)
        r = self.client.post('/inventory/items/', {'action': 'deactivate', 'item_id': self.rice.id})
        self.assertFalse(r.json()['success'])
        self.assertTrue(InventoryItem.objects.get(pk=self.rice.pk).is_active)
        self.client.force_login(self.main)
        self.client.post('/inventory/items/', {'action': 'deactivate', 'item_id': self.rice.id})
        self.assertFalse(InventoryItem.objects.get(pk=self.rice.pk).is_active)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(f'/inventory/api/item/{self.rice.id}/').status_code, 403)


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------
class RecipeTests(Base):
    def setUp(self):
        super().setUp()
        RecipeIngredient.objects.create(product=self.pilau, item=self.rice, quantity=D('0.33'))
        InventoryRecord.objects.create(item=self.rice, record_type='received', quantity_change=D('10'))

    def order(self, items=None):
        self._n += 1
        with self.captureOnCommitCallbacks(execute=True):
            o = Order.objects.create(order_number=f'R{self._n}', ordered_by=self.cashier,
                                     restaurant_owner=self.main, order_type='pickup', status='pending')
            for product, qty in (items or [(self.pilau, 3)]):
                OrderItem.objects.create(order=o, product=product, quantity=qty, unit_price=product.price)
        return o

    def set(self, o, status):
        o = Order.objects.get(pk=o.pk)
        o.status = status
        with self.captureOnCommitCallbacks(execute=True):
            o.save()
        return o

    def test_3_1_cancel_after_served_keeps_ingredients(self):
        o = self.order()
        for s in ('preparing', 'ready', 'served'):
            self.set(o, s)
        self.assertEqual(self.stock(self.rice), D('9.01'))
        self.set(o, 'cancelled')
        self.assertEqual(self.stock(self.rice), D('9.01'))
        o2 = self.order()
        self.set(o2, 'preparing')
        self.set(o2, 'out_for_delivery')
        self.set(o2, 'cancelled')
        self.assertEqual(self.stock(self.rice), D('8.02'))

    def test_3_1_cancel_before_served_puts_back(self):
        o = self.order()
        self.set(o, 'preparing')
        self.set(o, 'ready')
        self.set(o, 'cancelled')
        self.assertEqual(self.stock(self.rice), D('10.00'))

    def test_3_1_web_status_endpoint(self):
        o = self.order()
        for s in ('preparing', 'ready', 'served'):
            self.set(o, s)
        self.client.force_login(self.main)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(f'/orders/update-status/{o.id}/', data=json.dumps({'status': 'cancelled',
                                                                                    'cancel_reason': 'x'}),
                                 content_type='application/json')
        self.assertTrue(r.json().get('success'), r.content)
        self.assertEqual(self.stock(self.rice), D('9.01'))

    def test_3_2_recipe_edit_only_applies_to_changed_lines(self):
        o = self.order(items=[(self.pilau, 1)])
        self.set(o, 'preparing')                                           # rice -0.33
        RecipeIngredient.objects.filter(product=self.pilau, item=self.rice).update(quantity=D('0.50'))
        with self.captureOnCommitCallbacks(execute=True):
            OrderItem.objects.create(order=o, product=self.juice, quantity=1, unit_price=self.juice.price)
        self.assertEqual(self.stock(self.rice), D('9.67'))                 # pilau not re-costed
        self.set(o, 'wasted')                                              # label only
        self.assertEqual(self.stock(self.rice), D('9.67'))
        with self.captureOnCommitCallbacks(execute=True):                  # a new pilau line uses the new recipe
            OrderItem.objects.create(order=o, product=self.pilau, quantity=1, unit_price=self.pilau.price)
        self.assertEqual(self.stock(self.rice), D('9.00'))                 # pilau line changed: 2 x 0.50


# ---------------------------------------------------------------------------
# Waste
# ---------------------------------------------------------------------------
class WasteTests(Base):
    def old_order(self, owner, product, n, order_type='pickup', pay='unpaid', by=None):
        o = Order.objects.create(order_number=f'W{n}', ordered_by=by or self.cashier, restaurant_owner=owner,
                                 order_type=order_type, status='confirmed')
        OrderItem.objects.create(order=o, product=product, quantity=2, unit_price=product.price)
        Order.objects.filter(pk=o.pk).update(created_at=timezone.now() - datetime.timedelta(hours=3),
                                             payment_status=pay)
        return o

    def test_w1_dashboard_get_writes_nothing_and_detect_is_scoped(self):
        mine = self.old_order(self.main, self.pilau, 1)
        self.old_order(self.other, self.theirs, 2, by=self.cust)
        self.client.force_login(self.main)
        self.assertEqual(self.client.get('/waste-management/').status_code, 200)
        self.assertFalse(FoodWasteLog.objects.exists())
        r = self.client.post('/waste-management/auto-detect/')
        self.assertEqual(r.json()['detected_count'], 1)
        log = FoodWasteLog.objects.get()
        self.assertEqual((log.order_id, log.recorded_by), (mine.id, self.main))

    def test_w2_paid_or_dine_in_orders_are_not_abandoned(self):
        self.old_order(self.main, self.pilau, 1, pay='paid')
        self.old_order(self.main, self.pilau, 2, pay='partial')
        self.old_order(None, self.pilau, 3, order_type='dine-in')
        self.client.force_login(self.main)
        self.assertEqual(self.client.post('/waste-management/auto-detect/').json()['detected_count'], 0)
        self.assertFalse(FoodWasteLog.objects.exists())

    def test_w3_cost_settings_page_writes_nothing_and_shows_defaults(self):
        c = self.ctx(self.main, '/waste-management/cost-settings/', 'waste_management.views')
        self.assertFalse(ProductCostSettings.objects.exists())
        cs = c['current_settings']
        self.assertEqual((cs.ingredient_cost_percentage, cs.labor_cost_percentage, cs.overhead_cost_percentage),
                         (30, 25, 15))
        self.client.force_login(self.main)
        r = self.client.post('/waste-management/update-cost-settings/', json.dumps({
            'product_id': self.pilau.id, 'ingredient_cost': '1.10', 'labor_cost': '0.20', 'overhead_cost': '0'}),
            content_type='application/json')
        self.assertEqual(r.json()['total_cost'], 1.30)
        r = self.client.post('/waste-management/update-cost-settings/', json.dumps({
            'product_id': self.pilau.id, 'ingredient_cost': '-5'}), content_type='application/json')
        self.assertEqual(r.status_code, 400)                               # W7
        self.assertEqual(ProductCostSettings.objects.get().ingredient_cost_per_unit, D('1.10'))

    def test_w6_reason_and_method_validated_and_exports_tolerant(self):
        self.client.force_login(self.manager)
        post = lambda **d: self.client.post('/waste-management/record-waste/', json.dumps({
            'product_id': self.pilau.id, 'quantity_wasted': 1, 'waste_reason': 'kitchen_error',
            'disposal_method': 'waste_bin', **d}), content_type='application/json')
        self.assertEqual(post(waste_reason='hacked').status_code, 400)
        self.assertEqual(post(disposal_method='flushed').status_code, 400)
        self.assertEqual(post(quantity_wasted='2.5').status_code, 400)     # W10
        self.assertEqual(post(product_id=self.theirs.id).status_code, 404)  # W11
        self.assertEqual(post().status_code, 200)
        log = FoodWasteLog.objects.get()
        self.assertEqual(log.ingredient_cost + log.labor_cost + log.overhead_cost, log.total_cost)  # W8
        FoodWasteLog.objects.create(product=self.pilau, quantity_wasted=1, waste_reason='bogus',
                                    recorded_by=self.manager)               # bad old data
        self.client.force_login(self.main)
        for fmt in ('csv', 'excel', 'pdf'):
            self.assertEqual(self.client.get(f'/waste-management/export-report/?format={fmt}').status_code, 200, fmt)
        self.assertEqual(self.client.get('/waste-management/?period=all&from_date=nope').status_code, 200)  # W9


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ReportTests(Base):
    def order(self, items, total, status='served', pay='unpaid', table=None, by=None, otype='dine-in',
              rowner=None, fee=D('0'), payments=()):
        self._n += 1
        o = Order.objects.create(order_number=f'Q{self._n}', table_info=table, ordered_by=by or self.cashier,
                                 order_type=otype, restaurant_owner=rowner, status='pending',
                                 total_amount=D(total), delivery_fee=fee, payment_status='unpaid')
        for p, q in items:
            OrderItem.objects.create(order=o, product=p, quantity=q, unit_price=p.price)
        for amt, voided in payments:
            Payment.objects.create(order=o, amount=D(amt), payment_method='cash', processed_by=self.cashier,
                                   is_voided=voided)
        Order.objects.filter(pk=o.pk).update(status=status, payment_status=pay)
        return o

    def setUp(self):
        super().setUp()
        self.A = self.order([(self.pilau, 2)], '22.00', pay='paid', table=self.t1, payments=[('22.00', False)])
        self.B = self.order([(self.pilau, 1)], '11.00', pay='partial', table=self.t1,
                            payments=[('5.00', False), ('6.00', True)])
        self.C = self.order([(self.pilau, 3)], '33.00', status='cancelled', table=self.t1)
        self.K = self.order([(self.pilau, 1)], '11.00', status='kitchen_error', table=self.t1)
        self.E = self.order([(self.pilau, 1)], '14.00', status='delivered', pay='paid', by=self.cust,
                            otype='delivery', rowner=self.main, fee=D('3.00'), payments=[('14.00', False)])
        self.G = self.order([(self.biry, 1)], '11.00', pay='paid', table=self.t2, by=self.cash2,
                            payments=[('11.00', False)])

    def test_rp1_lost_orders_are_not_sales(self):
        c = self.ctx(self.main, f'/reports/?period=today&restaurant={self.r1.id}', 'reports.views')
        self.assertEqual(c['total_orders'], 3)                              # A, B, E
        self.assertEqual(D(c['total_revenue']).quantize(D('0.01')), D('43.00'))  # 20 + 10 + 13 (food + fee)
        self.client.force_login(self.main)
        body = self.client.get(f'/reports/export/?period=today&restaurant={self.r1.id}').content.decode()
        self.assertNotIn(self.C.order_number, body)
        self.assertIn('$14.00', body)                                       # RP7: charged total
        self.assertEqual(self.client.get('/reports/?restaurant=abc').status_code, 200)   # RP8

    def test_rp2_money_in_and_outstanding(self):
        c = self.ctx(self.main, '/reports/money-flow/?period=today', 'reports.views')
        self.assertEqual(D(c['sales_revenue']), D('47.00'))                 # paid: A + E + G
        self.assertEqual(c['sales_total_orders'], 4)
        self.assertEqual(D(c['sales_collected']), D('52.00'))               # 22 + 5 + 14 + 11 (void excluded)
        self.assertEqual(D(c['total_outstanding']), D('6.00'))              # B: 11 - 5; cancelled not owed

    def test_rp3_self_run_branch_not_doubled(self):
        Restaurant.objects.create(name='Branch 2', address='d', main_owner=self.main, branch_owner=self.main,
                                  is_main_restaurant=False, parent_restaurant=self.r1, qr_code='QR4')
        c = self.ctx(self.main, '/reports/money-flow/?period=today', 'reports.views')
        self.assertEqual(D(c['sales_revenue']), D('47.00'))
        self.assertEqual(D(c['sales_collected']), D('52.00'))

    def test_rp4_branch_does_not_show_main_delivery_orders(self):
        c = self.ctx(self.main, f'/reports/?period=today&restaurant={self.r2.id}', 'reports.views')
        self.assertEqual(c['total_orders'], 1)                              # G only, not E
        c = self.ctx(self.main, '/reports/money-flow/?period=today', 'reports.views',
                     session={'selected_restaurant_id': self.bown.id})
        self.assertEqual(D(c['sales_revenue']), D('11.00'))                 # RP5: follows the selected branch

    def test_rp6_csv_locations_add_up(self):
        self.client.force_login(self.main)
        s = self.client.session
        s['view_all_restaurants'] = True
        s.save()
        rows = list(csv.reader(io.StringIO(self.client.get('/reports/export/?period=today').content.decode())))
        row = lambda label: next(r for r in rows if r and r[0] == label)
        main, br = row('Main R'), row('Branch R (Branch)')
        self.assertEqual(int(main[1]) + int(br[1]), int(row('Total Orders:')[1]))
        total = D(main[3].lstrip('$').replace(',', '')) + D(br[3].lstrip('$').replace(',', ''))
        self.assertEqual(f'${total:,.2f}', row('Revenue:')[1])
