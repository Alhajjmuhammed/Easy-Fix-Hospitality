import sys
if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None

import datetime
import importlib
import json
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase

from accounts.models import Role, RestaurantSubscription, User
from orders.models import Order
from restaurant.models_restaurant import Restaurant


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class SelfRunBranchTests(TestCase):
    """A main owner who also runs a branch himself (branch_owner == main_owner)."""

    def setUp(self):
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRM', tax_rate=Decimal('0.18'))
        self.self_run = Restaurant.objects.create(name='Self Run', address='b', main_owner=self.main,
                                                  branch_owner=self.main, is_main_restaurant=False,
                                                  parent_restaurant=self.r, qr_code='QRS', tax_rate=Decimal('0.16'))
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.main, defaults={
            'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})

    def test_for_owner_is_the_main_restaurant(self):
        self.assertEqual(Restaurant.for_owner(self.main), self.r)

    def test_closing_the_self_run_branch_keeps_the_main_restaurant_open(self):
        from accounts.security_utils import validate_session_restaurant_id
        Restaurant.objects.filter(pk=self.self_run.pk).update(is_active=False)
        self.assertEqual(validate_session_restaurant_id({'selected_restaurant_id': self.main.id}), self.main)

    def test_pickup_orders_counted_once(self):
        from admin_panel.restaurant_utils import restaurant_orders_q
        Order.objects.create(order_number='P1', ordered_by=self.main, restaurant_owner=self.main,
                             order_type='pickup', total_amount=Decimal('100'))
        n_main = Order.objects.filter(restaurant_orders_q(self.r)).distinct().count()
        n_branch = Order.objects.filter(restaurant_orders_q(self.self_run)).distinct().count()
        self.assertEqual((n_main, n_branch), (1, 0))

    def test_owner_tax_form_changes_only_the_own_restaurant(self):
        self.client.force_login(self.main)
        self.client.post('/accounts/update-tax-rate/', json.dumps({'tax_rate': 10}),
                         content_type='application/json')
        self.r.refresh_from_db()
        self.self_run.refresh_from_db()
        self.assertEqual(self.self_run.tax_rate, Decimal('0.1600'))       # the branch keeps its own rate


class InventoryPricePerUnitMigrationTests(TestCase):
    def test_hand_entered_totals_become_per_unit_and_po_rows_are_untouched(self):
        from inventory.models import InventoryItem, InventoryRecord
        owner = User.objects.create_user('o', password='pw12345!x', role=role('main_owner'))
        item = InventoryItem.objects.create(owner=owner, name='Rice', unit='kg')
        hand = InventoryRecord.objects.create(item=item, record_type='received', quantity_change=Decimal('10'),
                                              unit_price=Decimal('50000'))
        no_price = InventoryRecord.objects.create(item=item, record_type='opening', quantity_change=Decimal('3'))
        mig = importlib.import_module('inventory.migrations.0008_record_price_per_unit')
        mig.to_per_unit(django_apps, None)
        hand.refresh_from_db()
        no_price.refresh_from_db()
        self.assertEqual(hand.unit_price, Decimal('5000.00'))
        self.assertEqual(hand.transaction_cost, Decimal('50000.00'))
        self.assertIsNone(no_price.unit_price)
