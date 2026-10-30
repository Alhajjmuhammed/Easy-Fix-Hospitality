import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, RestaurantSubscription, User
from orders import i18n
from orders.models import Order
from orders.models_sms import SmsAccount
from restaurant.models_restaurant import Restaurant


def role(name):
    return Role.objects.get_or_create(name=name)[0]


@override_settings(SMS_ENABLED=True)
class LanguageTests(TestCase):
    def setUp(self):
        self.push = mock.patch('orders.push.send_push')
        self.sent_push = self.push.start()
        self.addCleanup(self.push.stop)
        self.sms = []
        p = mock.patch('orders.sms._post', side_effect=lambda acc, to, msg: (self.sms.append(msg), {
            'SMSMessageData': {'Recipients': [{'statusCode': 101}]}})[1])
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch('orders.push._in_background', lambda fn, *args: fn(*args))
        p2.start()
        self.addCleanup(p2.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Mama Lishe')
        self.cust = mk('cust', 'customer', phone_number='0712345678', expo_push_token='ExponentPushToken[c]')
        Restaurant.objects.create(name='Mama Lishe', address='a', main_owner=self.main, branch_owner=self.main,
                                  is_main_restaurant=True, qr_code='QRMAIN', currency_code='KES')
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.main, defaults={
            'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        acc = SmsAccount(owner=self.main, enabled=True, events=['order_confirmed'])
        acc.credentials = {'username': 'sandbox', 'api_key': 'k'}
        acc.save()

    def test_save_language_endpoint(self):
        api = APIClient()
        api.force_authenticate(self.cust)
        self.assertEqual(api.post('/api/v1/auth/language/', {'language': 'sw'}, format='json').status_code, 200)
        self.assertEqual(User.objects.get(pk=self.cust.pk).language, 'sw')
        self.assertEqual(api.post('/api/v1/auth/language/', {'language': 'fr'}, format='json').status_code, 400)
        self.assertEqual(APIClient().post('/api/v1/auth/language/', {'language': 'sw'}, format='json').status_code, 401)

    def test_push_and_sms_follow_customer_language(self):
        User.objects.filter(pk=self.cust.pk).update(language='sw')
        self.cust.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            o = Order.objects.create(order_number='K1', ordered_by=self.cust, restaurant_owner=self.main,
                                     order_type='delivery', delivery_phone='0712345678', total_amount=Decimal('100'))
        with self.captureOnCommitCallbacks(execute=True):
            o.status = 'confirmed'
            o.save()
        self.assertEqual(self.sent_push.call_args.args[1], 'Oda Imethibitishwa ✅')
        self.assertEqual(self.sms[-1], 'Mama Lishe: oda #K1 imethibitishwa.')

    def test_english_default_and_fallback(self):
        self.assertEqual(i18n.tr('en', 'Order Confirmed ✅'), 'Order Confirmed ✅')
        self.assertEqual(i18n.tr('sw', 'Not translated yet'), 'Not translated yet')
        self.assertEqual(i18n.tr('sw', '{n} people', n=4), 'watu 4')
        self.assertEqual(i18n.tr('sw', 'Bad {placeholder}'), 'Bad {placeholder}')
        self.assertEqual(i18n.when_text('sw', datetime.datetime(2026, 11, 6, 19, 0)), 'Ijumaa 06 Nov, 19:00')

    def test_website_language_switch_and_choice_before_login_is_kept(self):
        r = self.client.post('/language/', {'language': 'sw', 'next': 'https://evil.example/x'})
        self.assertEqual(r['Location'], '/')                              # no redirect to other sites
        self.assertEqual(self.client.session['site_language'], 'sw')
        r = self.client.post('/accounts/login/', {'username': 'cust', 'password': 'pw12345!x'})
        self.assertEqual(r.status_code, 302)                              # logged in through the real login page
        self.assertEqual(User.objects.get(pk=self.cust.pk).language, 'sw')
        page = self.client.get('/accounts/profile/')
        self.assertEqual(page['Content-Language'], 'sw')

    def test_sms_numbers_for_nigeria_and_retry_never_sends_twice(self):
        from orders import sms
        self.assertEqual(sms.to_international('0803 123 4567', 'NGN'), '+2348031234567')
        self.assertEqual(sms.to_international('+234 803 123 4567', 'NGN'), '+2348031234567')
        self.assertEqual(sms.to_international('0712 345 678', 'KES'), '+254712345678')
        self.assertEqual(sms.to_international('0803 123 456', 'NGN'), '')
        from orders.models_sms import SmsLog
        log = SmsLog.objects.create(account=SmsAccount.objects.get(), event='order_confirmed', to='+254712345678',
                                    message='hi')
        SmsLog.objects.filter(pk=log.pk).update(created_at=log.created_at - datetime.timedelta(minutes=10))
        real_deliver = sms._deliver

        def deliver_with_overlapping_run(log_id, acc=None):
            self.assertEqual(sms.retry_stuck(), 0)                       # a second run meanwhile: nothing to send
            real_deliver(log_id, acc)
        with mock.patch('orders.sms._deliver', side_effect=deliver_with_overlapping_run):
            self.assertEqual(sms.retry_stuck(), 1)
        self.assertEqual((len(self.sms), SmsLog.objects.get(pk=log.pk).status), (1, 'sent'))
