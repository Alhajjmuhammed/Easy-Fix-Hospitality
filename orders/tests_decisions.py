"""The owner's six decisions (2026-11-09): kitchen cancel with a reason, cashiers assign riders,
auto-assign uses own riders only, payment-method totals, table numbers per restaurant, stock never
below 0 (with a kitchen warning)."""
import importlib
import json
from decimal import Decimal as D

from django.apps import apps as django_apps
from rest_framework.test import APIClient

from accounts.models import Feature, RolePermissionSet, User
from cashier.models import Payment
from cashier.tests_qa_fixes import Base, role
from orders.models import DeliveryRider, Order, OrderItem
from restaurant.models import MainCategory, Product, TableInfo
from restaurant.models_restaurant import Restaurant


def api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class KitchenCancelTests(Base):
    def test_kitchen_cancels_own_unpaid_order_with_reason_on_web(self):
        o = self.order([(self.pk_, 1)], status='preparing')
        self.client.force_login(self.kitchen)
        r = self.client.post(f'/orders/cancel-order/{o.id}/', json.dumps({'reason': 'Out of ingredients'}),
                             content_type='application/json')
        self.assertTrue(r.json()['success'], r.content)
        o.refresh_from_db()
        self.assertEqual((o.status, o.reason_if_cancelled), ('cancelled', 'Out of ingredients'))

    def test_kitchen_refused_for_paid_or_other_station_orders(self):
        paid = self.order([(self.pk_, 1)], status='preparing')
        self.pay(paid, paid.total_amount)
        drinks = self.order([(self.pb, 1)], status='preparing')            # bar items only
        self.client.force_login(self.kitchen)
        for o in (paid, drinks):
            r = self.client.post(f'/orders/cancel-order/{o.id}/', json.dumps({'reason': 'x'}),
                                 content_type='application/json')
            self.assertFalse(r.json()['success'])
            o.refresh_from_db()
            self.assertEqual(o.status, 'preparing')

    def test_station_status_cancel_needs_a_reason(self):
        o = self.order([(self.pk_, 1)], status='preparing')
        self.assertFalse(self.status(o, 'cancelled')['success'])
        self.assertTrue(self.status(o, 'cancelled', cancel_reason='Kitchen mistake')['success'])

    def test_app_station_cancel_with_reason(self):
        o = self.order([(self.pk_, 1)], status='confirmed')
        c = api(self.kitchen)
        self.assertEqual(c.post(f'/api/v1/orders/{o.id}/cancel/', {}, format='json').status_code, 400)
        r = c.post(f'/api/v1/orders/{o.id}/cancel/', {'reason': 'Customer left'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.status, 'cancelled')
        paid = self.order([(self.pk_, 1)], status='confirmed')
        self.pay(paid, paid.total_amount)
        self.assertEqual(c.post(f'/api/v1/orders/{paid.id}/cancel/', {'reason': 'x'}, format='json').status_code, 400)


class RiderTests(Base):
    def setUp(self):
        super().setUp()
        mk = lambda u, owner: DeliveryRider.objects.create(
            user=User.objects.create_user(u, password='pw12345!x', role=role('delivery_rider'), owner=owner),
            owner=owner)
        self.own_rider = mk('ownrider', self.main)
        self.other_rider = mk('otherrider', self.other)
        self.delivery = self.order([(self.pk_, 1)], table=None, otype='delivery', status='ready',
                                   restaurant_owner=self.main, delivery_phone='0712', delivery_address='x')

    def test_cashier_can_assign_an_own_rider(self):
        r = api(self.cashier).post('/api/v1/delivery/assign/',
                                   {'order_id': self.delivery.id, 'rider_id': self.own_rider.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_riders_cannot_assign_and_lists_never_show_other_restaurants(self):
        rider_user = self.own_rider.user
        r = api(rider_user).post('/api/v1/delivery/assign/',
                                 {'order_id': self.delivery.id, 'rider_id': self.own_rider.id}, format='json')
        self.assertEqual(r.status_code, 403)
        ids = {x['id'] for x in api(self.cashier).get('/api/v1/delivery/riders/?scope=global').json()['riders']}
        self.assertIn(self.own_rider.id, ids)
        self.assertNotIn(self.other_rider.id, ids)

    def test_auto_assign_never_uses_another_restaurants_rider(self):
        DeliveryRider.objects.filter(pk=self.own_rider.pk).update(is_available=False)
        r = api(self.cashier).post('/api/v1/delivery/auto-assign/', {'order_id': self.delivery.id}, format='json')
        self.assertEqual(r.status_code, 503)
        self.other_rider.refresh_from_db()
        self.assertTrue(self.other_rider.is_available)                          # untouched

    def test_migration_gives_saved_cashier_roles_the_permission(self):
        Feature.objects.filter(slug='assign_riders').delete()
        rps = RolePermissionSet.objects.create(owner=self.main, role_name='cashier')
        mig = importlib.import_module('accounts.migrations.0032_assign_riders_feature')
        mig.add_feature(django_apps, None)
        self.assertTrue(rps.features.filter(slug='assign_riders').exists())


class MethodTotalsTests(Base):
    def test_cashier_report_splits_paid_amount_by_method(self):
        o1 = self.order([(self.pk_, 1)])
        t2 = TableInfo.objects.create(restaurant=self.r, owner=self.main, tbl_no='T2')
        o2 = self.order([(self.pb, 1)], table=t2)
        self.pay(o1, '1000.00', 'cash')
        self.pay(o1, o1.total_amount - D('1000.00'), 'card')
        self.pay(o2, o2.total_amount, 'cash')
        self.client.force_login(self.cashier)
        r = self.client.get('/cashier/reports/')
        totals = {m['method']: m['total'] for m in r.context['payment_method_totals']} if r.context else None
        page = r.content.decode()
        self.assertIn('By payment method', page)
        if totals is not None:
            self.assertEqual(sum(totals.values()), r.context['paid_amount'])
        csv = self.client.get('/cashier/reports/?export=csv').content.decode()
        self.assertIn('Payment Method,Payments,Amount', csv)


class TableNumberTests(Base):
    def test_main_and_self_run_branch_can_both_have_t1_but_not_twice_in_one(self):
        branch = Restaurant.objects.create(name='Self run', address='s', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=False, parent_restaurant=self.r, qr_code='QRSR')
        TableInfo.objects.create(restaurant=branch, owner=self.main, tbl_no='T1')     # same owner, same number
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableInfo.objects.create(restaurant=branch, owner=self.main, tbl_no='T1')


class StockNeverBelowZeroTests(Base):
    def test_order_takes_only_what_is_left_and_cancel_gives_exactly_that_back(self):
        Product.objects.filter(pk=self.pk_.pk).update(available_in_stock=1)
        r = api(self.cashier).post('/api/v1/orders/', {'table_id': self.t1.id, 'order_type': 'dine-in',
                                                     'items': [{'product_id': self.pk_.id, 'quantity': 3,
                                                                'price': float(self.pk_.price)}]}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        line = OrderItem.objects.get(order__ordered_by=self.cashier, product=self.pk_)
        self.pk_.refresh_from_db()
        self.assertEqual((self.pk_.available_in_stock, line.stock_taken, line.stock_short), (0, 1, 2))
        self.client.force_login(self.kitchen)
        page = self.client.get('/orders/kitchen/').content.decode()
        self.assertIn('Only 1 in stock', page)
        self.assertTrue(self.status(line.order, 'cancelled', cancel_reason='Out of ingredients')['success'])
        self.pk_.refresh_from_db()
        self.assertEqual(self.pk_.available_in_stock, 1)                       # back to what was there

    def test_old_lines_give_back_their_full_quantity(self):
        o = self.order([(self.pk_, 2)], status='preparing')                    # made like a pre-rule line
        self.assertIsNone(o.order_items.get().stock_taken)
        self.assertTrue(self.status(o, 'cancelled', cancel_reason='x')['success'])
        self.pk_.refresh_from_db()
        self.assertEqual(self.pk_.available_in_stock, 52)

    def test_negative_stock_migration_and_app_field(self):
        Product.objects.filter(pk=self.pk_.pk).update(available_in_stock=-4)
        mig = importlib.import_module('restaurant.migrations.0030_no_negative_stock')
        mig.clamp(django_apps, None)
        self.pk_.refresh_from_db()
        self.assertEqual(self.pk_.available_in_stock, 0)
        o = self.order([(self.pk_, 1)])
        data = api(self.cashier).get(f'/api/v1/orders/{o.id}/').json()
        items = (data.get('order') or data).get('items') or (data.get('order') or data).get('order_items')
        self.assertIn('stock_short', items[0])


class ReviewFixTests(Base):
    def test_station_cannot_cancel_a_served_order_through_the_status_endpoint(self):
        o = self.order([(self.pk_, 1)], status='served')
        self.assertFalse(self.status(o, 'cancelled', cancel_reason='x')['success'])
        o.refresh_from_db()
        self.assertEqual(o.status, 'served')

    def test_give_back_happens_once_even_from_two_copies_of_a_line(self):
        from orders.stock import give_back, take_for_item
        Product.objects.filter(pk=self.pk_.pk).update(available_in_stock=2)
        o = self.order([], status='preparing')
        line = OrderItem.objects.create(order=o, product=self.pk_, quantity=3, unit_price=self.pk_.price)
        take_for_item(line)
        a, b = OrderItem.objects.get(pk=line.pk), OrderItem.objects.get(pk=line.pk)
        give_back(a)
        give_back(b)                                                          # stale copy: nothing more
        self.pk_.refresh_from_db()
        self.assertEqual(self.pk_.available_in_stock, 2)

    def test_deleting_an_order_still_in_the_kitchen_gives_stock_back(self):
        from orders.stock import give_back_order
        o = self.order([(self.pk_, 2)], status='preparing')
        give_back_order(o)
        self.pk_.refresh_from_db()
        self.assertEqual(self.pk_.available_in_stock, 52)
        s = self.order([(self.pk_, 2)], status='served')
        give_back_order(s)                                                    # served: food is gone
        self.pk_.refresh_from_db()
        self.assertEqual(self.pk_.available_in_stock, 52)
