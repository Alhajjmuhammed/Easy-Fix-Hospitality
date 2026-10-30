import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, RestaurantSubscription, User
from orders import i18n
from orders.models import Order
from orders.models_sms import SmsAccount
from restaurant.models_restaurant import Restaurant


def role(name):
    return Role.objects.get_or_create(name=name)[0]


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
