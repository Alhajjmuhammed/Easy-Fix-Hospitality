"""
Table reservation tests (web + API).

Run:  python manage.py test restaurant.tests_reservations
"""
import datetime
import sys
from unittest import mock

import django.test.client as _dtc
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User, RestaurantSubscription, Feature, RolePermissionSet
from restaurant.models import TableInfo
from restaurant.models_reservation import Reservation
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


def local_parts(dt):
    dt = timezone.localtime(dt)
    return dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M')


class ReservationTests(TestCase):
    def setUp(self):
        self.push = mock.patch('orders.push.send_push')
        self.sent = self.push.start()
        self.addCleanup(self.push.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.other_owner = mk('oth', 'main_owner', restaurant_name='Other R')
        self.cust = mk('cust', 'customer', expo_push_token='ExponentPushToken[cust]', phone_number='0777')
        self.cust2 = mk('cust2', 'customer')
        self.cashier = mk('cash', 'cashier', owner=self.main, expo_push_token='ExponentPushToken[cash]')
        self.kitchen = mk('kit', 'kitchen', owner=self.main)
        self.other_cashier = mk('ocash', 'cashier', owner=self.other_owner)
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRMAIN', reservations_enabled=True)
        self.other = Restaurant.objects.create(name='Other R', address='o', main_owner=self.other_owner,
                                               branch_owner=self.other_owner, is_main_restaurant=True, qr_code='QROTH',
                                               reservations_enabled=True)
        today = datetime.date.today()
        for o in (self.main, self.other_owner):
            RestaurantSubscription.objects.create(restaurant_owner=o, subscription_start_date=today,
                                                  subscription_end_date=today + datetime.timedelta(days=30))
        self.t1 = TableInfo.objects.create(restaurant=self.r, owner=self.main, tbl_no='T1', capacity=4)
        self.when = timezone.now() + datetime.timedelta(days=2)
        self.when = self.when.replace(minute=0, second=0, microsecond=0)

    def _api(self, user, rid=None):
        c = APIClient()
        c.force_authenticate(user)
        if rid:
            c.credentials(HTTP_X_RESTAURANT_ID=str(rid))
        return c

    def _web_book(self, **over):
        d, t = local_parts(self.when)
        data = {'name': 'Asha', 'phone': '0777', 'party_size': '4', 'date': d, 'time': t, 'notes': 'window'}
        data.update(over)
        self.client.force_login(self.cust)
        return self.client.post(f'/restaurant/browse/{self.r.id}/book/', data)

    def _kinds(self):
        return [c.args[3].get('kind') for c in self.sent.call_args_list]

    # ---------- customer booking ----------
    def test_customer_booking_pending_when_staff_must_confirm(self):
        r = self._web_book()
        self.assertEqual(r.status_code, 302)
        res = Reservation.objects.get()
        self.assertEqual((res.status, res.party_size, res.source, res.customer), ('pending', 4, 'web', self.cust))
        self.assertEqual(res.duration_minutes, 120)
        tokens = self.sent.call_args_list[0].args[0]
        self.assertEqual(tokens, ['ExponentPushToken[cash]'])          # staff told, customer not yet

    def test_auto_confirm_confirms_and_tells_customer(self):
        Restaurant.objects.filter(pk=self.r.pk).update(reservations_auto_confirm=True)
        self._web_book()
        self.assertEqual(Reservation.objects.get().status, 'confirmed')
        self.assertIn(['ExponentPushToken[cust]'], [c.args[0] for c in self.sent.call_args_list])

    def test_disabled_restaurant_cannot_be_booked(self):
        Restaurant.objects.filter(pk=self.r.pk).update(reservations_enabled=False)
        self.assertEqual(self._web_book().status_code, 404)
        d, t = local_parts(self.when)
        r = self._api(self.cust, self.r.id).post('/api/v1/reservations/', {'party_size': 2, 'date': d, 'time': t}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Reservation.objects.exists())

    def test_validation(self):
        past = timezone.now() - datetime.timedelta(hours=1)
        far = timezone.now() + datetime.timedelta(days=120)
        for over in ({'party_size': '0'}, {'party_size': '101'}, {'phone': ''}, {'name': ''},
                     dict(zip(('date', 'time'), local_parts(past))), dict(zip(('date', 'time'), local_parts(far))),
                     {'date': 'nope'}):
            self._web_book(**over)
        self.assertFalse(Reservation.objects.exists())

    def test_customer_cancel_rules(self):
        self._web_book()
        res = Reservation.objects.get()
        self.client.force_login(self.cust2)
        self.assertEqual(self.client.post(f'/restaurant/my-reservations/{res.pk}/cancel/').status_code, 404)
        self.client.force_login(self.cust)
        self.client.post(f'/restaurant/my-reservations/{res.pk}/cancel/')
        res.refresh_from_db()
        self.assertEqual(res.status, 'cancelled')
        page = self.client.get('/restaurant/my-reservations/').content.decode()
        self.assertIn('Main R', page)

    # ---------- staff ----------
    def test_staff_page_and_permissions(self):
        self._web_book()
        self.client.force_login(self.cashier)
        page = self.client.get(f'/restaurant/reservations/?date={local_parts(self.when)[0]}').content.decode()
        self.assertIn('Asha', page)
        self.assertIn('waiting for confirmation', page)
        self.client.force_login(self.kitchen)
        self.assertEqual(self.client.get('/restaurant/reservations/').status_code, 302)   # no permission
        self.client.force_login(self.other_cashier)
        self.assertNotIn('Asha', self.client.get(f'/restaurant/reservations/?date={local_parts(self.when)[0]}').content.decode())

    def test_staff_actions_and_customer_notifications(self):
        self._web_book()
        res = Reservation.objects.get()
        self.sent.reset_mock()
        self.client.force_login(self.cashier)
        self.client.post(f'/restaurant/reservations/{res.pk}/action/', {'action': 'status', 'status': 'confirmed'})
        res.refresh_from_db()
        self.assertEqual((res.status, res.status_changed_by), ('confirmed', self.cashier))
        self.assertEqual(self.sent.call_args_list[-1].args[3]['status'], 'confirmed')
        self.client.post(f'/restaurant/reservations/{res.pk}/action/', {'action': 'status', 'status': 'completed'})
        res.refresh_from_db()
        self.assertEqual(res.status, 'confirmed')                                       # invalid jump refused
        for s in ('seated', 'completed'):
            self.client.post(f'/restaurant/reservations/{res.pk}/action/', {'action': 'status', 'status': s})
        res.refresh_from_db()
        self.assertEqual(res.status, 'completed')
        self.client.force_login(self.other_cashier)
        self.assertEqual(self.client.post(f'/restaurant/reservations/{res.pk}/action/',
                                          {'action': 'status', 'status': 'cancelled'}).status_code, 404)

    def test_staff_booking_double_booking_and_capacity_warnings(self):
        d, t = local_parts(self.when)
        self.client.force_login(self.cashier)
        self.client.post('/restaurant/reservations/', {'name': 'A', 'phone': '1', 'party_size': '2', 'date': d, 'time': t,
                                                     'table_id': self.t1.id})
        a = Reservation.objects.get(name='A')
        self.assertEqual((a.status, a.source, a.table), ('confirmed', 'staff', self.t1))
        later = self.when + datetime.timedelta(hours=1)                         # overlaps A (2h booking)
        d2, t2 = local_parts(later)
        self.client.post('/restaurant/reservations/', {'name': 'B', 'phone': '2', 'party_size': '6', 'date': d2, 'time': t2,
                                                     'table_id': self.t1.id})
        b = Reservation.objects.get(name='B')                                   # warned, not blocked
        warnings = b.warnings()
        self.assertTrue(any('already booked for A' in w for w in warnings))
        self.assertTrue(any('larger than table T1' in w for w in warnings))
        far = self.when + datetime.timedelta(hours=3)                           # no overlap
        d3, t3 = local_parts(far)
        self.client.post('/restaurant/reservations/', {'name': 'C', 'phone': '3', 'party_size': '2', 'date': d3, 'time': t3,
                                                     'table_id': self.t1.id})
        self.assertEqual(Reservation.objects.get(name='C').warnings(), [])

    def test_assign_table_from_other_restaurant_rejected(self):
        self._web_book()
        res = Reservation.objects.get()
        other_table = TableInfo.objects.create(restaurant=self.other, owner=self.other_owner, tbl_no='X1')
        self.client.force_login(self.cashier)
        r = self.client.post(f'/restaurant/reservations/{res.pk}/action/', {'action': 'table', 'table_id': other_table.id})
        self.assertEqual(r.status_code, 404)
        res.refresh_from_db()
        self.assertIsNone(res.table_id)

    def test_module_access_can_disable_reservations(self):
        self.main.subscription.disabled_features.add(Feature.objects.get(slug='view_reservations'),
                                                     Feature.objects.get(slug='manage_reservations'))
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get('/restaurant/reservations/').status_code, 302)
        self.assertEqual(self._api(self.cashier).get('/api/v1/reservations/').status_code, 403)

    # ---------- entry points ----------
    def test_booking_only_restaurant_is_listed_and_cannot_take_pickup(self):
        self.client.force_login(self.cust)
        self.assertIn('Main R', self.client.get('/restaurant/browse/').content.decode())
        page = self.client.get(f'/restaurant/browse/{self.r.id}/order-type/').content.decode()
        self.assertIn('Book a table', page)
        self.assertNotIn('value="pickup"', page)
        self.client.post(f'/restaurant/browse/{self.r.id}/order-type/', {'order_type': 'pickup'})
        self.assertNotEqual(self.client.session.get('order_type'), 'pickup')

    # ---------- API ----------
    def test_api_customer_and_staff_flow(self):
        d, t = local_parts(self.when)
        r = self._api(self.cust, self.r.id).post('/api/v1/reservations/', {'party_size': 3, 'date': d, 'time': t,
                                                                          'notes': 'quiet'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        rid = r.json()['reservation']['id']
        self.assertEqual(r.json()['reservation']['status'], 'pending')
        self.assertEqual(Reservation.objects.get(pk=rid).source, 'app')
        mine = self._api(self.cust).get('/api/v1/reservations/').json()['reservations']
        self.assertEqual([x['id'] for x in mine], [rid])
        self.assertEqual(self._api(self.cust2).get('/api/v1/reservations/').json()['reservations'], [])
        staff = self._api(self.cashier).get(f'/api/v1/reservations/?date={d}').json()
        self.assertEqual([x['id'] for x in staff['reservations']], [rid])
        self.assertEqual(self._api(self.other_cashier).get(f'/api/v1/reservations/?date={d}').json()['reservations'], [])
        r = self._api(self.cashier).post(f'/api/v1/reservations/{rid}/table/', {'table_id': self.t1.id}, format='json')
        self.assertEqual(r.json()['reservation']['table_number'], 'T1')
        r = self._api(self.cashier).post(f'/api/v1/reservations/{rid}/status/', {'status': 'confirmed'}, format='json')
        self.assertEqual(r.json()['reservation']['status'], 'confirmed')
        self.assertEqual(self._api(self.other_cashier).post(f'/api/v1/reservations/{rid}/status/',
                                                            {'status': 'cancelled'}, format='json').status_code, 404)
        self.assertEqual(self._api(self.cust2).post(f'/api/v1/reservations/{rid}/cancel/').status_code, 404)
        r = self._api(self.cust).post(f'/api/v1/reservations/{rid}/cancel/')
        self.assertEqual(r.json()['reservation']['status'], 'cancelled')

    def test_api_blocked_restaurant(self):
        self.main.subscription.block_restaurant(reason='t')
        d, t = local_parts(self.when)
        r = self._api(self.cust, self.r.id).post('/api/v1/reservations/', {'party_size': 2, 'date': d, 'time': t}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_restaurant_payload_has_reservation_flags(self):
        lst = {x['id']: x for x in self._api(self.cust).get('/api/v1/restaurants/').json()['restaurants']}
        self.assertTrue(lst[self.r.id]['reservations_enabled'])

    # ---------- settings & permissions ----------
    def test_owner_settings_saved_and_validated(self):
        self.client.force_login(self.main)
        base = {'action': 'update_restaurant', 'restaurant_name': 'Main R', 'restaurant_description': '', 'tax_rate': '8'}
        self.client.post('/admin-panel/profile/', {**base, 'reservations_auto_confirm': 'on', 'reservation_duration_minutes': '90'})
        self.r.refresh_from_db()
        self.assertEqual((self.r.reservations_enabled, self.r.reservations_auto_confirm, self.r.reservation_duration_minutes),
                         (False, True, 90))
        self.client.post('/admin-panel/profile/', {**base, 'reservations_enabled': 'on', 'reservation_duration_minutes': '5'})
        self.r.refresh_from_db()
        self.assertEqual((self.r.reservations_enabled, self.r.reservation_duration_minutes), (False, 90))   # rejected

    def test_permissions_migration_grants_existing_role_sets(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module('accounts.migrations.0029_reservation_features')
        rps = RolePermissionSet.objects.create(owner=self.main, role_name='cashier')
        kitchen_rps = RolePermissionSet.objects.create(owner=self.main, role_name='kitchen')
        mig.add_features(apps, None)
        self.assertEqual(set(rps.features.values_list('slug', flat=True)), {'view_reservations', 'manage_reservations'})
        self.assertEqual(kitchen_rps.features.count(), 0)
        self.assertTrue(self.cashier.has_feature('manage_reservations'))
        self.assertFalse(self.kitchen.has_feature('view_reservations'))
