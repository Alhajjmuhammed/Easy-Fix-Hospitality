import datetime
import sys
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, RestaurantSubscription, User
from cashier.models import Payment
from orders import sms
from orders.models import Order
from orders.models_sms import SmsAccount, SmsLog
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


@override_settings(SMS_ENABLED=True)
class SmsTests(TestCase):
    def setUp(self):
        self.sent = []
        self.reply = {'SMSMessageData': {'Message': 'Sent to 1/1', 'Recipients': [
            {'statusCode': 101, 'number': '+254712345678', 'status': 'Success', 'cost': 'KES 0.8000',
             'messageId': 'ATXid_1'}]}}
        p1 = mock.patch('orders.sms._post', side_effect=lambda acc, to, msg: (self.sent.append((to, msg)), self.reply)[1])
        p2 = mock.patch('orders.push._in_background', lambda fn, *args: fn(*args))
        p3 = mock.patch('orders.push.send_push')
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Mama Lishe')
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.cust = mk('cust', 'customer', phone_number='0712345678')
        self.r = Restaurant.objects.create(name='Mama Lishe', address='a', main_owner=self.main,
                                           branch_owner=self.main, is_main_restaurant=True, qr_code='QRMAIN',
                                           currency_code='KES', reservations_enabled=True)
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.main, defaults={
            'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        self.acc = SmsAccount(owner=self.main, enabled=True,
                              events=['order_confirmed', 'order_ready', 'out_for_delivery', 'order_delivered',
                                      'payment_receipt', 'reservation'])
        self.acc.credentials = {'username': 'sandbox', 'api_key': 'key123'}
        self.acc.save()
        self._n = 0

    def _order(self, order_type='delivery', phone='0712 345 678', status='pending'):
        self._n += 1
        with self.captureOnCommitCallbacks(execute=True):
            return Order.objects.create(order_number=f'S{self._n}', ordered_by=self.cust, restaurant_owner=self.main,
                                        order_type=order_type, status=status, delivery_phone=phone,
                                        total_amount=Decimal('2500'))

    def _status(self, order, status):
        with self.captureOnCommitCallbacks(execute=True):
            order.status = status
            order.save()

    # ---------- formatting ----------
    def test_phone_formats_only_own_country(self):
        self.assertEqual(sms.to_international('0712 345 678', 'KES'), '+254712345678')
        self.assertEqual(sms.to_international('712345678', 'KES'), '+254712345678')
        self.assertEqual(sms.to_international('+254 0712 345 678', 'KES'), '+254712345678')
        self.assertEqual(sms.to_international('0754111222', 'TZS'), '+255754111222')
        self.assertEqual(sms.to_international('+255 754 111 222', 'KES'), '')       # other country: refused
        self.assertEqual(sms.to_international('+44 7700 900123', 'KES'), '')
        self.assertEqual(sms.to_international('12', 'KES'), '')
        self.assertEqual(sms.to_international('0712345678', 'USD'), '')

    def test_texts_stay_one_cheap_part(self):
        self.assertEqual(sms.gsm_text('Mama’s Kitchen – Downtown “best” …'), 'Mama\'s Kitchen - Downtown "best" ...')
        self.assertEqual(sms.gsm_text('Café 🍕 Ñandu'), 'Café Ñandu')            # é and Ñ are GSM; emoji dropped
        self.assertTrue(all(c in sms._GSM for c in sms.gsm_text('Zürich ★ Łódź')))
        self.assertEqual(len(sms.gsm_text('x' * 400)), 160)
        self.assertEqual(sms.short_name('A' * 80), 'A' * 29 + '.')

    # ---------- hooks never work inside the request ----------
    def test_hooks_do_no_database_work_in_the_request(self):
        o = self._order()
        o.status = 'confirmed'
        with self.assertNumQueries(0):
            sms.order_status_changed(o)
            sms.order_paid(o)

    def test_missing_tables_or_errors_cannot_break_the_order(self):
        o = self._order()
        with mock.patch('orders.sms.account_for', side_effect=Exception('relation does not exist')):
            self._status(o, 'confirmed')
        self.assertEqual(Order.objects.get(pk=o.pk).status, 'confirmed')

    # ---------- orders ----------
    def test_delivery_order_texts_once_per_step(self):
        o = self._order()
        self._status(o, 'confirmed')
        self.assertEqual(self.sent, [('+254712345678', 'Mama Lishe: order #S1 confirmed.')])
        self._status(o, 'preparing')
        self._status(o, 'confirmed')                     # back and forth: no second text
        self._status(o, 'out_for_delivery')
        self._status(o, 'delivered')
        self.assertEqual(len(self.sent), 3)
        log = SmsLog.objects.filter(order=o, event='order_confirmed').get()
        self.assertEqual((log.status, log.cost, log.provider_message_id), ('sent', 'KES 0.8000', 'ATXid_1'))
        with self.assertRaises(IntegrityError), transaction.atomic():   # the database refuses a duplicate
            SmsLog.objects.create(account=self.acc, event='order_confirmed', to='+254712345678', message='x', order=o)

    def test_only_switched_on_events_and_right_order_types(self):
        self._status(self._order(order_type='dine-in'), 'confirmed')
        self.assertEqual(self.sent, [])                  # dine-in: customer is at the table
        pickup = self._order(order_type='pickup')
        self._status(pickup, 'ready')
        self.assertIn('ready for pickup', self.sent[-1][1])
        self._status(pickup, 'delivered')                # "delivered" is only for delivery orders
        self._status(self._order(), 'ready')             # "ready" is only for pickup
        self.assertEqual(len(self.sent), 1)
        SmsAccount.objects.filter(pk=self.acc.pk).update(events=['payment_receipt'])
        self._status(self._order(), 'confirmed')
        SmsAccount.objects.filter(pk=self.acc.pk).update(enabled=False, events=['order_confirmed'])
        self._status(self._order(), 'confirmed')
        self.assertEqual(len(self.sent), 1)

    def test_daily_limit_per_number(self):
        for _ in range(sms.MAX_PER_NUMBER_PER_DAY + 3):
            self._status(self._order(), 'confirmed')
        self.assertEqual(len(self.sent), sms.MAX_PER_NUMBER_PER_DAY)

    def test_payment_receipt(self):
        o = self._order()
        with self.captureOnCommitCallbacks(execute=True):
            Payment.objects.create(order=o, amount=Decimal('2500'), payment_method='cash', processed_by=self.cashier)
            o.payment_status = 'paid'
            o.save(update_fields=['payment_status'])
        self.assertEqual(self.sent[-1][1], 'Mama Lishe: received KES 2,500.00 for order #S1. Thank you!')

    def test_provider_failure_is_logged_and_harmless(self):
        self.reply = {'SMSMessageData': {'Message': 'InvalidSenderId', 'Recipients': []}}
        o = self._order()
        self._status(o, 'confirmed')
        self.assertEqual(Order.objects.get(pk=o.pk).status, 'confirmed')
        self.assertEqual(SmsLog.objects.get().status, 'failed')
        with mock.patch('orders.sms._post', side_effect=OSError('network down')):
            self._status(self._order(), 'confirmed')
        self.assertEqual(SmsLog.objects.filter(status='failed').count(), 2)

    def test_stuck_texts_are_retried(self):
        log = SmsLog.objects.create(account=self.acc, event='test', to='+254712345678', message='hello')
        SmsLog.objects.filter(pk=log.pk).update(created_at=timezone.now() - datetime.timedelta(minutes=10))
        self.assertEqual(sms.retry_stuck(), 1)
        self.assertEqual(SmsLog.objects.get(pk=log.pk).status, 'sent')

    # ---------- reservations ----------
    def test_staff_booking_texts_the_number_entered(self):
        from restaurant import reservations as res_svc
        with self.captureOnCommitCallbacks(execute=True):
            res_svc.create_reservation(self.r, name='Asha', phone='0733 000 111', email='', party_size=4,
                                       start=timezone.now() + datetime.timedelta(days=2), created_by=self.cashier,
                                       source='staff', staff=True)
        self.assertEqual(self.sent[-1][0], '+254733000111')
        self.assertIn('table for 4', self.sent[-1][1])

    def test_customer_booking_texts_only_their_own_number(self):
        from restaurant import reservations as res_svc
        Restaurant.objects.filter(pk=self.r.pk).update(reservations_auto_confirm=True)
        self.r.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            res_svc.create_reservation(self.r, name='X', phone='0799 999 999', email='', party_size=2,
                                       start=timezone.now() + datetime.timedelta(days=2), customer=self.cust,
                                       created_by=self.cust, source='web')
        self.assertEqual([to for to, _ in self.sent], ['+254712345678'])  # typed number is never texted

    # ---------- switched off by default (SMS costs money) ----------
    def test_everything_off_without_the_setting(self):
        with override_settings(SMS_ENABLED=False):
            self._status(self._order(), 'confirmed')
            self.assertEqual(self.sent, [])
            self.assertFalse(SmsLog.objects.exists())
            self.assertIsNone(sms.send(self.main, 'test', '0712345678', 'hi', force=True))
            self.client.force_login(self.main)
            self.assertEqual(self.client.get('/orders/sms-settings/').status_code, 302)
            self.assertNotIn('sms-settings', self.client.get('/admin-panel/profile/').content.decode())

    # ---------- settings ----------
    def test_settings_page(self):
        self.client.force_login(self.main)
        self.client.post('/orders/sms-settings/', {
            'username': 'mamalishe', 'api_key': '', 'sender_id': 'MAMALISHE', 'environment': 'live',
            'event_order_confirmed': 'on', 'enabled': 'on', 'action': 'test', 'test_phone': '0712345678'})
        acc = SmsAccount.objects.get(owner=self.main)
        self.assertEqual((acc.credentials['api_key'], acc.credentials['username']), ('key123', 'mamalishe'))
        self.assertNotIn('key123', acc.credentials_encrypted)
        self.assertEqual(acc.events, ['order_confirmed'])
        self.assertIn('SMS is working', self.sent[-1][1])
        page = self.client.get('/orders/sms-settings/').content.decode()
        self.assertNotIn('key123', page)
        self.assertIn('+254712345678', page)                        # owner sees the log
        bown = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'), owner=self.main)
        Restaurant.objects.create(name='Branch', address='b', main_owner=self.main, branch_owner=bown,
                                  is_main_restaurant=False, parent_restaurant=self.r, qr_code='QRBR')
        self.client.force_login(bown)
        self.assertNotIn('+254712345678', self.client.get('/orders/sms-settings/').content.decode())
        self.client.post('/orders/sms-settings/', {'username': 'x', 'enabled': ''})
        self.assertTrue(SmsAccount.objects.get(owner=self.main).enabled)        # read-only for branches
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get('/orders/sms-settings/').status_code, 302)
