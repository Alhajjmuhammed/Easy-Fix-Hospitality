import datetime
import sys
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Feature, Role, RolePermissionSet, User
from orders.models import Order
from orders.models_feedback import OrderRating
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


def tok(name):
    return f'ExponentPushToken[{name}]'


class FeedbackTests(TestCase):
    def setUp(self):
        self.push = mock.patch('orders.push.send_push')
        self.sent = self.push.start()
        self.addCleanup(self.push.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R', expo_push_token=tok('main'))
        self.manager = mk('mgr', 'manager', owner=self.main, expo_push_token=tok('mgr'))
        self.cashier = mk('cash', 'cashier', owner=self.main, expo_push_token=tok('cash'))
        self.cc = mk('cc', 'customer_care', owner=self.main, expo_push_token=tok('cc'))
        self.cust = mk('cust', 'customer', expo_push_token=tok('cust'))
        self.cust2 = mk('cust2', 'customer')
        self.other = mk('oth', 'main_owner', restaurant_name='Other R')
        Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                  is_main_restaurant=True, qr_code='QRMAIN')
        from accounts.models import RestaurantSubscription
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.main, defaults={
            'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        self._n = 0

    def _order(self, status='delivered', order_type='delivery', customer=None, owner=None):
        self._n += 1
        return Order.objects.create(order_number=f'F{self._n}', ordered_by=customer or self.cust,
                                    restaurant_owner=owner or self.main, order_type=order_type, status=status,
                                    total_amount=Decimal('100'))

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _rate(self, order, user=None, **body):
        return self._api(user or self.cust).post(f'/api/v1/orders/{order.id}/rating/', body, format='json')

    # ---------- rating ----------
    def test_rate_via_app_and_once_only(self):
        o = self._order()
        info = self._api(self.cust).get(f'/api/v1/orders/{o.id}/rating/').json()
        self.assertEqual(info, {'can_rate': True, 'rating': None})
        r = self._rate(o, food_stars=5, delivery_stars=4, comment='  Lovely  ')
        self.assertEqual(r.status_code, 201)
        rating = OrderRating.objects.get()
        self.assertEqual((rating.food_stars, rating.delivery_stars, rating.comment, rating.restaurant_owner),
                         (5, 4, 'Lovely', self.main))
        self.assertEqual(self._rate(o, food_stars=1).status_code, 400)            # only once
        self.assertEqual(OrderRating.objects.count(), 1)
        self.sent.assert_not_called()                                             # 5 stars: no alert
        info = self._api(self.cust).get(f'/api/v1/orders/{o.id}/rating/').json()
        self.assertEqual((info['can_rate'], info['rating']['food_stars']), (False, 5))

    def test_who_and_when_can_rate(self):
        self.assertEqual(self._rate(self._order(status='preparing'), food_stars=5).status_code, 400)
        self.assertEqual(self._rate(self._order(status='cancelled'), food_stars=5).status_code, 400)
        self.assertEqual(self._rate(self._order(), user=self.cust2, food_stars=5).status_code, 404)  # not theirs
        staff_order = self._order(customer=self.cashier)
        self.assertEqual(self._rate(staff_order, user=self.cashier, food_stars=5).status_code, 400)  # staff
        old = self._order()
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - datetime.timedelta(days=8))
        self.assertEqual(self._rate(old, food_stars=5).status_code, 400)       # too late
        for bad in (0, 6, 'x', None, 2.5):
            self.assertEqual(self._rate(self._order(), food_stars=bad).status_code, 400, bad)
        self.assertFalse(OrderRating.objects.exists())

    def test_pickup_served_and_delivery_stars_ignored_for_non_delivery(self):
        o = self._order(status='served', order_type='pickup')
        self._rate(o, food_stars=4, delivery_stars=1)
        self.assertIsNone(OrderRating.objects.get().delivery_stars)
        self.sent.assert_not_called()

    def test_low_rating_alerts_staff_with_permission(self):
        self._rate(self._order(), food_stars=2, comment='Cold food')
        tokens = sorted(self.sent.call_args.args[0])
        # owner + manager + customer care (have view_feedback); cashier doesn't by default
        self.assertEqual(tokens, sorted([tok('main'), tok('mgr'), tok('cc')]))
        self.assertIn('Cold food', self.sent.call_args.args[2])
        self.sent.reset_mock()
        self._rate(self._order(), food_stars=5, delivery_stars=1)                # bad delivery also alerts
        self.assertEqual(self.sent.call_count, 1)

    def test_web_rating_flow(self):
        o = self._order()
        self.client.force_login(self.cust)
        page = self.client.get(f'/orders/order/{o.id}/').content.decode()
        self.assertIn('Rate your order', page)
        self.client.post(f'/orders/order/{o.id}/rate/', {'food': '7'})                # invalid
        self.assertFalse(OrderRating.objects.exists())
        self.client.post(f'/orders/order/{o.id}/rate/', {'food': '4', 'comment': '<b>ok</b>'})
        self.assertEqual(OrderRating.objects.get().food_stars, 4)
        page = self.client.get(f'/orders/order/{o.id}/').content.decode()
        self.assertIn('Your rating', page)
        self.assertIn('&lt;b&gt;ok&lt;/b&gt;', page)
        self.client.force_login(self.cust2)
        self.assertEqual(self.client.get(f'/orders/order/{o.id}/rate/').status_code, 404)

    # ---------- staff side ----------
    def test_feedback_page_reply_and_customer_notified(self):
        self._rate(self._order(), food_stars=1, comment='Bad')
        rating = OrderRating.objects.get()
        other_rating_order = self._order(owner=self.other)
        OrderRating.objects.create(order=other_rating_order, customer=self.cust, restaurant_owner=self.other,
                                   food_stars=1, comment='Theirs')
        self.client.force_login(self.manager)
        page = self.client.get('/orders/feedback/').content.decode()
        self.assertIn('Bad', page)
        self.assertNotIn('Theirs', page)
        self.assertEqual(self.client.get('/orders/feedback/?show=low').status_code, 200)
        self.assertEqual(self.client.get('/orders/feedback/?show=unreplied&page=abc').status_code, 200)
        self.sent.reset_mock()
        self.client.post(f'/orders/feedback/{rating.id}/reply/', {'reply': 'Sorry, next meal is on us'})
        rating.refresh_from_db()
        self.assertEqual((rating.reply, rating.replied_by), ('Sorry, next meal is on us', self.manager))
        self.assertEqual(self.sent.call_args.args[0], [tok('cust')])
        self.assertEqual(self.sent.call_args.args[3]['kind'], 'rating_reply')
        other = OrderRating.objects.get(comment='Theirs')
        self.assertEqual(self.client.post(f'/orders/feedback/{other.id}/reply/', {'reply': 'x'}).status_code, 404)
        self.client.post(f'/orders/feedback/{rating.id}/reply/', {'reply': '   '})         # empty
        rating.refresh_from_db()
        self.assertEqual(rating.reply, 'Sorry, next meal is on us')
        info = self._api(self.cust).get(f'/api/v1/orders/{rating.order_id}/rating/').json()
        self.assertEqual(info['rating']['reply'], 'Sorry, next meal is on us')

    # ---------- review fixes ----------
    def test_alerts_never_reach_branch_owners_or_customers(self):
        bown = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'), owner=self.main,
                                        expo_push_token=tok('bown'))
        linked_customer = User.objects.create_user('lc', password='pw12345!x', role=role('customer'),
                                                   owner=self.main, expo_push_token=tok('lc'))
        self._rate(self._order(), food_stars=1)
        tokens = self.sent.call_args.args[0]
        self.assertNotIn(tok('bown'), tokens)
        self.assertNotIn(tok('lc'), tokens)
        self.assertIn(tok('main'), tokens)

    def test_module_switched_off_hides_rating_everywhere(self):
        self.main.subscription.disabled_features.add(Feature.objects.get(slug='view_feedback'))
        o = self._order()
        self.assertEqual(self._api(self.cust).get(f'/api/v1/orders/{o.id}/rating/').json()['can_rate'], False)
        self.assertEqual(self._rate(o, food_stars=1).status_code, 400)
        self.client.force_login(self.cust)
        self.assertNotIn('Rate your order', self.client.get(f'/orders/order/{o.id}/').content.decode())
        self.sent.assert_not_called()

    def test_odd_input_is_refused_not_crashing(self):
        for body in ({'food_stars': '²'}, {'food_stars': '1' * 5000}, {'food_stars': True},
                     {'food_stars': [5]}, {'food_stars': {'a': 1}}):
            self.assertEqual(self._rate(self._order(), **body).status_code, 400, str(body)[:40])
        for comment in (5, ['x'], {'a': 'b'}):
            self.assertEqual(self._rate(self._order(), food_stars=4, comment=comment).status_code, 201)
        self.assertTrue(all(r.comment == '' for r in OrderRating.objects.all()))
        self._rate(self._order(), food_stars=4, comment='ok\x00then')
        self.assertTrue(OrderRating.objects.filter(comment='okthen').exists())
        self.client.force_login(self.cust)
        self.assertEqual(self.client.post(f'/orders/order/{self._order().id}/rate/', {'food': '²'}).status_code, 200)

    def test_reply_only_once(self):
        self._rate(self._order(), food_stars=1)
        rating = OrderRating.objects.get()
        self.client.force_login(self.manager)
        self.sent.reset_mock()
        self.client.post(f'/orders/feedback/{rating.id}/reply/', {'reply': 'First'})
        self.client.post(f'/orders/feedback/{rating.id}/reply/', {'reply': 'Second'})   # double click / direct POST
        rating.refresh_from_db()
        self.assertEqual(rating.reply, 'First')
        self.assertEqual(self.sent.call_count, 1)

    def test_feedback_permissions(self):
        self.client.force_login(self.cashier)                  # no view_feedback by default
        self.assertEqual(self.client.get('/orders/feedback/').status_code, 302)
        self.client.force_login(self.cust)
        self.assertEqual(self.client.get('/orders/feedback/').status_code, 302)
        rps = RolePermissionSet.objects.create(owner=self.main, role_name='manager')
        rps.features.set([Feature.objects.get(slug='view_feedback')])
        self._rate(self._order(), food_stars=1)
        rating = OrderRating.objects.get()
        self.client.force_login(self.manager)                  # view only
        page = self.client.get('/orders/feedback/').content.decode()
        self.assertNotIn('Send reply', page)
        self.client.post(f'/orders/feedback/{rating.id}/reply/', {'reply': 'hi'})
        rating.refresh_from_db()
        self.assertEqual(rating.reply, '')
        self.main.subscription.disabled_features.add(Feature.objects.get(slug='view_feedback'))
        self.client.force_login(self.main)                     # Module Access switch
        self.assertEqual(self.client.get('/orders/feedback/').status_code, 302)
