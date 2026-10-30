import datetime
import sys
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, RestaurantSubscription, User
from inventory.models import InventoryItem, InventoryRecord, RecipeIngredient
from orders.models import Order, OrderItem
from reports import forecast as svc
from restaurant.models import MainCategory, Product
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class ForecastTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        for target in ('orders.push.send_push',):
            p = mock.patch(target)
            p.start()
            self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.manager = mk('mgr', 'manager', owner=self.main)
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.cust = mk('cust', 'customer')
        self.other = mk('oth', 'main_owner', restaurant_name='Other R')
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRMAIN')
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.main, defaults={
            'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        cat = MainCategory.objects.create(restaurant=self.r, name='Food')
        self.pilau = Product.objects.create(name='Pilau', description='', main_category=cat, price=Decimal('5000'))
        self.chips = Product.objects.create(name='Chips', description='', main_category=cat, price=Decimal('3000'))
        self.rice = InventoryItem.objects.create(owner=self.main, name='Rice', unit='kg', unit_price=Decimal('3000'),
                                                 low_stock_threshold=Decimal('2'))
        RecipeIngredient.objects.create(product=self.pilau, item=self.rice, quantity=Decimal('0.25'))
        InventoryRecord.objects.create(item=self.rice, record_type='received', quantity_change=Decimal('3'))
        self.today = timezone.localdate()
        self._n = 0

    def _order(self, day, hour=13, total='10000', items=((None, 2),), owner=None, status='served'):
        self._n += 1
        o = Order.objects.create(order_number=f'F{self._n}', ordered_by=self.cust, restaurant_owner=owner or self.main,
                                 order_type='pickup', status='pending', total_amount=Decimal(total))
        for product, qty in items:
            OrderItem.objects.create(order=o, product=product or self.pilau, quantity=qty,
                                     unit_price=(product or self.pilau).price)
        at = timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, 15)))
        Order.objects.filter(pk=o.pk).update(created_at=at, status=status)
        return o

    def _history(self):
        """Every day for 8 weeks: one 10,000 order at 13:00; Fridays an extra 20,000 order at 19:00."""
        for back in range(1, 57):
            day = self.today - datetime.timedelta(days=back)
            self._order(day)
            if day.weekday() == 4:
                self._order(day, hour=19, total='20000', items=((self.chips, 4),))

    def test_daily_forecast_follows_weekdays(self):
        self._history()
        data = svc.build(self.main)
        by_weekday = {f['date'].weekday(): f for f in data['forecast']}
        self.assertEqual(by_weekday[4]['revenue'], Decimal('30000'))          # Friday: 10k + 20k
        self.assertEqual(by_weekday[4]['orders'], 2)
        self.assertEqual(by_weekday[(4 + 1) % 7]['revenue'], Decimal('10000'))
        self.assertEqual(data['week_total'], Decimal('90000'))
        self.assertEqual(data['trend_percent'], 0)
        self.assertTrue(data['enough_history'])

    def test_cancelled_and_other_restaurants_are_ignored(self):
        self._history()
        yesterday = self.today - datetime.timedelta(days=7)
        self._order(yesterday, total='999999', status='cancelled')
        self._order(yesterday, total='999999', owner=self.other)
        data = svc.build(self.main)
        self.assertLess(max(f['revenue'] for f in data['forecast']), Decimal('100000'))

    def test_busy_hours_and_dish_trends(self):
        self._history()
        data = svc.build(self.main)
        self.assertEqual(data['active_hours'], [13, 19])
        friday = [r for r in data['heatmap'] if r['weekday'] == 'Fri'][0]
        self.assertEqual([c['avg'] for c in friday['cells']], [1.0, 1.0])
        self.assertEqual(data['rising'], [])                                   # flat history
        for back in range(1, 15):                                             # chips boom recently
            self._order(self.today - datetime.timedelta(days=back), items=((self.chips, 5),), total='15000')
        self.assertEqual(svc.build(self.main)['rising'][0]['name'], 'Chips')

    def test_shopping_list_from_recipes(self):
        self._history()
        data = svc.build(self.main)
        row = svc.shopping_list(self.main, data['expected_qty'])[0]
        # 2 pilau a day × 7 days × 0.25 kg = 3.5 kg; stock 3; keep 2 → buy 2.5
        self.assertEqual((row['item'], row['need'], row['stock'], row['buy']), (self.rice, 3.5, 3.0, 2.5))
        self.assertEqual(row['cost'], Decimal('7500.00'))

    def test_page_permissions_and_po_prefill(self):
        self._history()
        from inventory.models import Supplier
        Supplier.objects.create(owner=self.main, name='Mama Mboga')
        self.client.force_login(self.manager)
        page = self.client.get('/reports/forecast/').content.decode()
        self.assertIn('Expected sales', page)
        self.assertIn(f'prefill={self.rice.id}%3A2.5', page)
        po = self.client.get(f'/inventory/purchase-orders/new/?prefill={self.rice.id}:2.5,999:1,abc,{self.rice.id}:-1')
        html = po.content.decode()
        self.assertIn('value="2.5"', html)
        self.assertEqual(html.count('class="po-line"'), 1)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get('/reports/forecast/').status_code, 302)

    # ---------- review fixes ----------
    def test_no_fake_trend_with_six_weeks_of_flat_sales(self):
        for back in range(1, 43):
            self._order(self.today - datetime.timedelta(days=back))
        data = svc.build(self.main)
        self.assertEqual(data['trend_percent'], 0)
        self.assertEqual({f['revenue'] for f in data['forecast']}, {Decimal('10000')})

    def test_trend_applies_to_old_restaurant_closed_on_one_day(self):
        self._order(self.today - datetime.timedelta(days=200))              # open for months
        for back in range(1, 57):
            if back == 56:
                continue                                                    # closed that one day
            self._order(self.today - datetime.timedelta(days=back), total='20000' if back <= 28 else '10000')
        data = svc.build(self.main)
        self.assertEqual(data['trend_percent'], 25)                         # sales doubled → capped at +25%

    def test_owner_of_two_branches_not_double_counted(self):
        second = Restaurant.objects.create(name='Second', address='s', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=False, parent_restaurant=self.r, qr_code='QR2')
        self.assertTrue(second.pk)
        for back in range(1, 57):
            self._order(self.today - datetime.timedelta(days=back))
        data = svc.build(self.main)
        self.assertEqual({f['revenue'] for f in data['forecast']}, {Decimal('10000')})

    def test_young_restaurant_counts_each_weekday_correctly(self):
        for back in range(1, 11):                          # 10 days, 1 order a day with 2 pilau
            self._order(self.today - datetime.timedelta(days=back))
        data = svc.build(self.main)
        self.assertEqual({c['avg'] for row in data['heatmap'] for c in row['cells']}, {1.0})
        self.assertAlmostEqual(data['expected_qty'][self.pilau.id], 14.0)

    def test_crafted_prefill_links_are_harmless(self):
        from inventory.models import Supplier
        Supplier.objects.create(owner=self.main, name='Mama Mboga')
        self.client.force_login(self.manager)
        for raw in (f'{self.rice.id}:1e999999999', f'{self.rice.id}:1E+999998', 'x' * 10000, f'{self.rice.id}:NaN'):
            r = self.client.get('/inventory/purchase-orders/new/', {'prefill': raw})
            self.assertEqual(r.status_code, 200, raw[:30])
            self.assertLess(len(r.content), 500000)
        html = self.client.get('/inventory/purchase-orders/new/',
                               {'prefill': f'{self.rice.id}:2.5,{self.rice.id}:9'}).content.decode()
        self.assertEqual(html.count('class="po-line"'), 1)     # the same item once

    def test_page_cache_keeps_stock_live(self):
        self._history()
        self.client.force_login(self.main)
        self.assertIn('Rice', self.client.get('/reports/forecast/').content.decode())
        InventoryRecord.objects.create(item=self.rice, record_type='received', quantity_change=Decimal('50'))
        self.assertNotIn('>Rice<', self.client.get('/reports/forecast/').content.decode())

    def test_new_restaurant_without_history(self):
        data = svc.build(self.main)
        self.assertEqual(data['week_total'], Decimal('0'))
        self.assertFalse(data['enough_history'])
        self.client.force_login(self.main)
        self.assertEqual(self.client.get('/reports/forecast/').status_code, 200)
