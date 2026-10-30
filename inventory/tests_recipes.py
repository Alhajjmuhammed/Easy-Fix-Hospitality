import sys
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from accounts.models import Feature, Role, RolePermissionSet, User
from inventory.models import InventoryItem, InventoryRecord, RecipeIngredient
from orders.models import Order, OrderItem
from restaurant.models import MainCategory, Product
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class RecipeTests(TestCase):
    def setUp(self):
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.manager = mk('mgr', 'manager', owner=self.main)
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.other = mk('oth', 'main_owner', restaurant_name='Other R')
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRMAIN')
        other_r = Restaurant.objects.create(name='Other R', address='o', main_owner=self.other,
                                            branch_owner=self.other, is_main_restaurant=True, qr_code='QROTH')
        food = MainCategory.objects.create(restaurant=self.r, name='Food')
        self.pilau = Product.objects.create(name='Pilau', description='', main_category=food, price=Decimal('5000'))
        self.chips = Product.objects.create(name='Chips', description='', main_category=food, price=Decimal('3000'))
        self.their_dish = Product.objects.create(name='Theirs', description='',
                                                 main_category=MainCategory.objects.create(restaurant=other_r, name='F'),
                                                 price=Decimal('10'))
        self.rice = InventoryItem.objects.create(owner=self.main, name='Rice', unit='kg', unit_price=Decimal('3000'))
        self.beef = InventoryItem.objects.create(owner=self.main, name='Beef', unit='kg', unit_price=Decimal('12000'))
        self.salt = InventoryItem.objects.create(owner=self.other, name='Salt', unit='kg')
        RecipeIngredient.objects.create(product=self.pilau, item=self.rice, quantity=Decimal('0.25'))
        RecipeIngredient.objects.create(product=self.pilau, item=self.beef, quantity=Decimal('0.15'))
        InventoryRecord.objects.create(item=self.rice, record_type='received', quantity_change=Decimal('10'),
                                       unit_price=Decimal('3000'))
        self._n = 0

    # ---------- helpers ----------
    def _order(self, items=None, status='pending'):
        self._n += 1
        with self.captureOnCommitCallbacks(execute=True):   # like the request committing
            o = Order.objects.create(order_number=f'T{self._n}', ordered_by=self.cashier,
                                     restaurant_owner=self.main, order_type='pickup', status=status)
            for product, qty in (items or [(self.pilau, 2)]):
                OrderItem.objects.create(order=o, product=product, quantity=qty, unit_price=product.price)
        return o

    def _set(self, order, status):
        order.status = status
        order.save()

    def _stock(self, item):
        return InventoryItem.objects.get(pk=item.pk).current_stock

    # ---------- deduction ----------
    def test_nothing_taken_until_kitchen_starts_then_once(self):
        o = self._order()
        self._set(o, 'confirmed')
        self.assertEqual(self._stock(self.rice), Decimal('10'))
        self._set(o, 'preparing')
        self.assertEqual((self._stock(self.rice), self._stock(self.beef)), (Decimal('9.50'), Decimal('-0.30')))
        for s in ('ready', 'served'):
            self._set(o, s)
        self.assertEqual(self._stock(self.rice), Decimal('9.50'))          # never twice
        rec = InventoryRecord.objects.filter(source_order=o, item=self.rice).get()
        self.assertEqual((rec.record_type, rec.unit_price), ('used', None))
        self.assertIn(f'Order #{o.order_number}', rec.notes)

    def test_skipped_steps_still_deduct(self):
        o = self._order(status='pending')
        self._set(o, 'delivered')
        self.assertEqual(self._stock(self.rice), Decimal('9.50'))

    def test_cancel_puts_back_waste_keeps_out(self):
        o = self._order()
        self._set(o, 'preparing')
        self._set(o, 'cancelled')
        self.assertEqual(self._stock(self.rice), Decimal('10.00'))
        o2 = self._order()
        self._set(o2, 'preparing')
        self._set(o2, 'kitchen_error')
        self.assertEqual(self._stock(self.rice), Decimal('9.50'))
        self.assertEqual(set(InventoryRecord.objects.filter(source_order=o2).values_list('record_type', flat=True)),
                         {'waste'})
        o3 = self._order()
        self._set(o3, 'wasted')                                             # straight from pending
        self.assertEqual(self._stock(self.rice), Decimal('9.00'))
        self.assertEqual(set(InventoryRecord.objects.filter(source_order=o3).values_list('record_type', flat=True)),
                         {'waste'})

    def test_items_changed_after_cooking_started(self):
        o = self._order()
        self._set(o, 'preparing')
        with self.captureOnCommitCallbacks(execute=True):
            OrderItem.objects.create(order=o, product=self.pilau, quantity=1, unit_price=self.pilau.price)
        self.assertEqual(self._stock(self.rice), Decimal('9.25'))
        item = o.order_items.first()
        with self.captureOnCommitCallbacks(execute=True):
            item.delete()
        self.assertEqual(self._stock(self.rice), Decimal('9.75'))
        with self.captureOnCommitCallbacks(execute=True):
            OrderItem.objects.create(order=o, product=self.chips, quantity=3, unit_price=self.chips.price)  # no recipe
        self.assertEqual(self._stock(self.rice), Decimal('9.75'))

    def test_items_before_cooking_do_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._order()
        self.assertFalse(InventoryRecord.objects.filter(source_order__isnull=False).exists())

    def test_order_without_recipes_untouched(self):
        o = self._order(items=[(self.chips, 2)])
        self._set(o, 'served')
        self.assertFalse(InventoryRecord.objects.filter(source_order=o).exists())

    def test_stock_problem_never_blocks_the_order(self):
        o = self._order()
        with mock.patch('inventory.recipes._wanted_usage', side_effect=RuntimeError('boom')):
            self._set(o, 'preparing')
        self.assertEqual(Order.objects.get(pk=o.pk).status, 'preparing')
        self.assertFalse(InventoryRecord.objects.filter(source_order=o).exists())
        with self.captureOnCommitCallbacks(execute=True):                   # the next item change catches up
            OrderItem.objects.create(order=o, product=self.chips, quantity=1, unit_price=self.chips.price)
        self.assertEqual(self._stock(self.rice), Decimal('9.50'))

    def test_deleting_an_order_with_stock_taken(self):
        o = self._order()
        self._set(o, 'preparing')
        with self.captureOnCommitCallbacks(execute=True):
            o.delete()
        self.assertEqual(self._stock(self.rice), Decimal('9.50'))          # what was used stays used
        self.assertTrue(InventoryRecord.objects.filter(item=self.rice, source_order__isnull=True,
                                                       record_type='used').exists())

    def test_spend_report_not_double_counted(self):
        o = self._order()
        self._set(o, 'served')
        self.client.force_login(self.main)
        page = self.client.get('/inventory/history/').content.decode()
        self.assertIn('30,000.00' if '30,000.00' in page else '30000.00', page)  # only the purchase counts

    # ---------- review fixes ----------
    def test_recipe_edits_do_not_touch_orders_already_cooking(self):
        o = self._order()
        self._set(o, 'preparing')
        RecipeIngredient.objects.filter(product=self.pilau, item=self.rice).update(quantity=Decimal('1'))
        for s in ('ready', 'served', 'delivered'):
            self._set(o, s)
        self.assertEqual(self._stock(self.rice), Decimal('9.50'))
        self.pilau.delete()                                                  # dish removed from the menu
        o.refresh_from_db()
        self._set(o, 'served')
        self.assertEqual(self._stock(self.rice), Decimal('9.50'))

    def test_normal_kitchen_steps_do_no_stock_work(self):
        o = self._order()
        self._set(o, 'preparing')
        with mock.patch('inventory.recipes.sync_order_stock') as sync:
            for s in ('ready', 'served', 'out_for_delivery', 'delivered'):
                self._set(o, s)
        sync.assert_not_called()

    def test_many_items_one_sync_and_failures_are_contained(self):
        o = self._order()
        self._set(o, 'preparing')
        with mock.patch('inventory.recipes.sync_order_stock') as sync:
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(5):
                    OrderItem.objects.create(order=o, product=self.pilau, quantity=1, unit_price=self.pilau.price)
        self.assertEqual(sync.call_count, 1)
        with mock.patch('inventory.recipes.sync_order_stock', side_effect=RuntimeError('db blip')):
            with self.captureOnCommitCallbacks(execute=True):           # must not raise
                OrderItem.objects.create(order=o, product=self.pilau, quantity=1, unit_price=self.pilau.price)

    def test_never_touches_another_restaurants_stock(self):
        RecipeIngredient.objects.create(product=self.pilau, item=self.salt, quantity=Decimal('1'))  # bad old data
        o = self._order()
        self._set(o, 'preparing')
        self.assertEqual(InventoryItem.objects.get(pk=self.salt.pk).current_stock, 0)
        self.assertEqual(self._stock(self.rice), Decimal('9.50'))

    def test_waste_then_cancel_keeps_waste_label(self):
        o = self._order()
        self._set(o, 'wasted')
        self._set(o, 'cancelled')
        self.assertEqual(self._stock(self.rice), Decimal('10.00'))
        self.assertFalse(InventoryRecord.objects.filter(source_order=o, record_type='used').exists())

    # ---------- recipe pages ----------
    def test_recipe_page_cost_margin_and_stock_warning(self):
        self.client.force_login(self.manager)
        page = self.client.get('/inventory/recipes/').content.decode()
        self.assertIn('Pilau', page)
        self.assertIn('2550.00', page)                 # 0.25×3000 + 0.15×12000
        self.assertIn('49%', page)                     # (5000-2550)/5000
        self.assertIn('Out of stock: Beef', page)
        self.assertNotIn('Theirs', page)

    def test_save_recipe_and_validation(self):
        self.client.force_login(self.manager)
        url = f'/inventory/recipes/{self.chips.id}/'
        bad = [
            ([self.salt.id], ['1']),                    # another restaurant's item
            ([self.rice.id, self.rice.id], ['1', '2']),  # listed twice
            ([self.rice.id], ['0']), ([self.rice.id], ['-1']), ([self.rice.id], ['abc']),
            ([self.rice.id], ['0.0001']), ([self.rice.id], ['NaN']), (['x'], ['1']),
        ]
        for ids, qtys in bad:
            r = self.client.post(url, {'item_id': ids, 'quantity': qtys})
            self.assertEqual(r.status_code, 200, (ids, qtys))
            self.assertFalse(RecipeIngredient.objects.filter(product=self.chips).exists(), (ids, qtys))
        self.client.post(url, {'item_id': [self.rice.id, ''], 'quantity': ['0.125', '']})
        self.assertEqual(RecipeIngredient.objects.get(product=self.chips).quantity, Decimal('0.13'))  # stock precision
        self.client.post(url, {'item_id': [''], 'quantity': ['']})              # clear
        self.assertFalse(RecipeIngredient.objects.filter(product=self.chips).exists())
        self.assertEqual(self.client.get(f'/inventory/recipes/{self.their_dish.id}/').status_code, 404)

    def test_permissions(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get('/inventory/recipes/').status_code, 302)
        rps = RolePermissionSet.objects.create(owner=self.main, role_name='manager')
        rps.features.set([Feature.objects.get_or_create(slug='view_inventory', defaults={'name': 'View Inventory'})[0]])
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get('/inventory/recipes/').status_code, 200)
        self.client.post(f'/inventory/recipes/{self.chips.id}/', {'item_id': [self.rice.id], 'quantity': ['1']})
        self.assertFalse(RecipeIngredient.objects.filter(product=self.chips).exists())
