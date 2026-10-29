"""
Push notification tests. Nothing is sent over the network: the Expo HTTP call is
replaced by a recorder, and background threads run inline.

Run:  python manage.py test orders.tests_push
"""
import datetime
import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User, RestaurantSubscription
from restaurant.models_restaurant import Restaurant
from restaurant.models import TableInfo, MainCategory, Product
from orders.models import Order, DeliveryRider
from orders import push


def role(name):
    return Role.objects.get_or_create(name=name)[0]


def tok(name):
    return f'ExponentPushToken[{name}]'


class PushTests(TestCase):
    def setUp(self):
        self.sent = []
        p1 = mock.patch('orders.push._post', side_effect=lambda msgs: self.sent.extend(msgs))
        p2 = mock.patch('orders.push._in_background', lambda fn, *args: fn(*args))
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.other_owner = mk('oth', 'main_owner', restaurant_name='Other R')
        self.cust = mk('cust', 'customer', expo_push_token=tok('cust'))
        self.cashier = mk('cash', 'cashier', owner=self.main, expo_push_token=tok('cash'))
        self.cc = mk('cc', 'customer_care', owner=self.main, expo_push_token=tok('cc'))
        self.kitchen = mk('kit', 'kitchen', owner=self.main, expo_push_token=tok('kit'))
        self.bar = mk('bar', 'bar', owner=self.main, expo_push_token=tok('bar'))
        self.other_kitchen = mk('okit', 'kitchen', owner=self.other_owner, expo_push_token=tok('okit'))
        self.rider_user = mk('rider', 'delivery_rider', owner=self.main, expo_push_token=tok('rider'))
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRMAIN', allow_remote_orders=True)
        today = datetime.date.today()
        RestaurantSubscription.objects.create(restaurant_owner=self.main, subscription_start_date=today,
                                              subscription_end_date=today + datetime.timedelta(days=30))
        self.table = TableInfo.objects.create(restaurant=self.r, owner=self.main, tbl_no='T1')
        cat = MainCategory.objects.create(restaurant=self.r, owner=self.main, name='Food')
        self.food = Product.objects.create(name='Pilau', description='d', main_category=cat,
                                           price=Decimal('5000.00'), available_in_stock=50, station='kitchen')

    def _api(self, user, rid=None):
        c = APIClient()
        c.force_authenticate(user)
        if rid:
            c.credentials(HTTP_X_RESTAURANT_ID=str(rid))
        return c

    def _to(self):
        return sorted(m['to'] for m in self.sent)

    def _customer_pickup(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self._api(self.cust, self.r.id).post('/api/v1/orders/', {
                'order_type': 'pickup', 'items': [{'product_id': self.food.id, 'quantity': 1, 'price': 5000}]},
                format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        return Order.objects.get(ordered_by=self.cust)

    # ---------- new order alerts ----------
    def test_remote_order_alerts_front_staff_and_kitchen_only(self):
        self._customer_pickup()
        self.assertEqual(self._to(), sorted([tok('cash'), tok('cc'), tok('kit')]))
        self.assertTrue(all(m['data']['kind'] == 'new_order' for m in self.sent))
        self.assertTrue(all(m['channelId'] == 'orders' for m in self.sent))

    def test_dine_in_alerts_station_but_not_the_person_who_ordered(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self._api(self.cashier).post('/api/v1/orders/', {
                'table_id': self.table.id, 'items': [{'product_id': self.food.id, 'quantity': 1, 'price': 5000}]},
                format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(self._to(), [tok('kit')])

    def test_web_order_alerts_staff(self):
        self.client.force_login(self.cust)
        self.client.post(f'/restaurant/browse/{self.r.id}/order-type/', {'order_type': 'pickup'})
        s = self.client.session
        s['cart'] = {str(self.food.id): {'name': 'Pilau', 'price': '5000.00', 'quantity': 1}}
        s.save()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post('/orders/place-order/', {'special_instructions': ''})
        self.assertEqual(self._to(), sorted([tok('cash'), tok('cc'), tok('kit')]))

    # ---------- customer status alerts ----------
    def test_status_change_from_app_notifies_customer_once(self):
        order = self._customer_pickup()
        self.sent.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self._api(self.cashier).patch(f'/api/v1/orders/{order.id}/status/', {'status': 'confirmed'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._to(), [tok('cust')])
        self.assertEqual(self.sent[0]['data'], {'kind': 'order_status', 'orderId': order.id, 'status': 'confirmed'})

    def test_status_change_anywhere_notifies_customer(self):
        order = self._customer_pickup()
        self.sent.clear()
        order = Order.objects.get(pk=order.pk)
        order.status = 'ready'
        with self.captureOnCommitCallbacks(execute=True):
            order.save(update_fields=['status', 'updated_at'])
        self.assertEqual(self._to(), [tok('cust')])
        self.assertEqual(self.sent[0]['body'], 'Your order is ready for pickup.')

    def test_no_alert_when_status_unchanged_or_not_saved(self):
        order = self._customer_pickup()
        self.sent.clear()
        order = Order.objects.get(pk=order.pk)
        with self.captureOnCommitCallbacks(execute=True):
            order.special_instructions = 'x'
            order.save(update_fields=['special_instructions'])
            order.save()
        self.assertEqual(self.sent, [])

    def test_partial_save_does_not_hide_later_status_change(self):
        order = self._customer_pickup()
        self.sent.clear()
        order = Order.objects.get(pk=order.pk)
        order.status = 'confirmed'                                     # changed in memory...
        with self.captureOnCommitCallbacks(execute=True):
            order.save(update_fields=['special_instructions'])         # ...but this save doesn't write it
            order.save(update_fields=['status'])                       # now it is written → must notify
        self.assertEqual([m['data'].get('status') for m in self.sent], ['confirmed'])

    def test_refresh_from_db_does_not_cause_duplicate(self):
        order = self._customer_pickup()
        stale = Order.objects.get(pk=order.pk)
        Order.objects.filter(pk=order.pk).update(status='confirmed')   # changed elsewhere (already notified there)
        stale.refresh_from_db()
        self.sent.clear()
        with self.captureOnCommitCallbacks(execute=True):
            stale.save()                                               # status unchanged → no push
        self.assertEqual(self.sent, [])

    def test_customer_own_cancellation_not_notified_but_staff_cancel_is(self):
        order = self._customer_pickup()
        self.sent.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self._api(self.cust, self.r.id).post(f'/api/v1/orders/{order.id}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([m for m in self.sent if m['data'].get('kind') == 'order_status'], [])
        Order.objects.filter(ordered_by=self.cust).delete()
        order2 = self._customer_pickup()
        self.sent.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self._api(self.main).post(f'/api/v1/orders/{order2.id}/cancel/', {'reason': 'out of stock'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([m['data'].get('status') for m in self.sent], ['cancelled'])

    def test_staff_who_placed_order_gets_no_customer_status_alert(self):
        order = Order.objects.create(order_number='ORD-STAFF', table_info=self.table, ordered_by=self.cashier)
        order = Order.objects.get(pk=order.pk)
        order.status = 'ready'
        with self.captureOnCommitCallbacks(execute=True):
            order.save()
        self.assertEqual(self.sent, [])

    def test_deferred_status_does_not_query_or_crash(self):
        order = Order.objects.create(order_number='ORD-DEF', table_info=self.table, ordered_by=self.cust)
        with self.assertNumQueries(1):
            list(Order.objects.only('id').filter(pk=order.pk))

    # ---------- rider ----------
    def test_rider_assignment_notifies_rider(self):
        order = Order.objects.create(order_number='ORD-DEL', ordered_by=self.cust, order_type='delivery',
                                     restaurant_owner=self.main, delivery_phone='0777', status='ready')
        rider = DeliveryRider.objects.create(user=self.rider_user, owner=self.main, is_available=True)
        self.sent.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self._api(self.main).post('/api/v1/delivery/assign/', {'order_id': order.id, 'rider_id': rider.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        kinds = {m['to']: m['data']['kind'] for m in self.sent}
        self.assertEqual(kinds.get(tok('rider')), 'delivery_assigned')
        self.assertEqual(kinds.get(tok('cust')), 'order_status')  # status became out_for_delivery

    # ---------- tokens ----------
    def test_token_moves_to_new_user_and_logout_clears_it(self):
        r = self._api(self.kitchen).post('/api/v1/auth/push-token/', {'token': tok('cash')}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.cashier.refresh_from_db(); self.kitchen.refresh_from_db()
        self.assertIsNone(self.cashier.expo_push_token)
        self.assertEqual(self.kitchen.expo_push_token, tok('cash'))
        self._api(self.kitchen).post('/api/v1/auth/logout/')
        self.kitchen.refresh_from_db()
        self.assertIsNone(self.kitchen.expo_push_token)

    def test_invalid_tokens_are_skipped(self):
        with self.captureOnCommitCallbacks(execute=True):
            push.send_push(['', None, 'not-a-token', tok('a'), tok('a')], 't', 'b')
        self.assertEqual(self._to(), [tok('a')])

    def test_push_failure_never_raises(self):
        with mock.patch('orders.push._post', side_effect=OSError('network down')):
            with self.captureOnCommitCallbacks(execute=True):
                push.send_push([tok('a')], 't', 'b')  # must not raise


class ExpoResponseTests(TestCase):
    def test_dead_tokens_are_cleared(self):
        u = User.objects.create_user('gone', password='pw12345!x', role=role('customer'), expo_push_token=tok('gone'))
        keep = User.objects.create_user('ok', password='pw12345!x', role=role('customer'), expo_push_token=tok('ok'))
        body = json.dumps({'data': [
            {'status': 'error', 'details': {'error': 'DeviceNotRegistered'}},
            {'status': 'ok', 'id': 'x'},
        ]}).encode()
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = body
        with mock.patch('orders.push.urllib.request.urlopen', return_value=fake):
            push._post([{'to': tok('gone')}, {'to': tok('ok')}])
        u.refresh_from_db(); keep.refresh_from_db()
        self.assertIsNone(u.expo_push_token)
        self.assertEqual(keep.expo_push_token, tok('ok'))

    def test_batches_of_100(self):
        calls = []
        with mock.patch('orders.push._post', side_effect=lambda msgs: calls.append(len(msgs))):
            push._deliver([{'to': tok(str(i))} for i in range(250)])
        self.assertEqual(calls, [100, 100, 50])
