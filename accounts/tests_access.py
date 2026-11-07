"""
Regression tests for access control around subscriptions, customer ordering at closed
restaurants, login messages, rate limits, session timeout and a few customer-site fixes.

Run:  python manage.py test accounts.tests_access
"""
import datetime
import json
import sys
import time
from decimal import Decimal
from unittest import mock

import django.test.client as _dtc
from django.core.cache import cache
from django.test import TestCase, Client

from accounts.models import Role, User, RestaurantSubscription, Feature
from restaurant.models_restaurant import Restaurant
from restaurant.models import TableInfo, MainCategory, SubCategory, Product, HappyHourPromotion, Event
from orders.models import Order

if sys.version_info >= (3, 14):
    # Django 4.2's test client crashes copying template contexts on Python 3.14.
    _dtc.store_rendered_templates = lambda *a, **k: None

PW = 'Access-Strong-pw-4821!'


def role(name):
    return Role.objects.get_or_create(name=name)[0]


def expire(sub, days_ago=30):
    today = datetime.date.today()
    sub.subscription_start_date = today - datetime.timedelta(days=days_ago + 30)
    sub.subscription_end_date = today - datetime.timedelta(days=days_ago)
    sub.save()


class Tenant:
    """A main restaurant with one branch, staff on both, and a subscription on the main owner."""

    def __init__(self, tag):
        mk = lambda u, r, **kw: User.objects.create_user(f'{tag}_{u}', password=PW, role=role(r),
                                                         email=f'{tag}_{u}@x.test', **kw)
        self.main = mk('main', 'main_owner', restaurant_name=f'{tag} Main R')
        self.branch_owner = mk('bown', 'branch_owner', restaurant_name=f'{tag} Branch R')
        self.manager = mk('mgr', 'manager', owner=self.main)
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.kitchen = mk('kit', 'kitchen', owner=self.main)
        self.rider = mk('rider', 'delivery_rider', owner=self.main)
        self.branch_cashier = mk('bcash', 'cashier', owner=self.branch_owner)
        self.r_main = Restaurant.objects.create(
            name=f'{tag} Main R', address='a', main_owner=self.main, branch_owner=self.main,
            is_main_restaurant=True, qr_code=f'AQR{tag}MAIN', menu_qr_code=f'AMENU{tag}MAIN',
            allow_remote_orders=True, subscription_plan='PRO')
        self.r_branch = Restaurant.objects.create(
            name=f'{tag} Branch R', address='b', main_owner=self.main, branch_owner=self.branch_owner,
            is_main_restaurant=False, parent_restaurant=self.r_main, qr_code=f'AQR{tag}BR',
            menu_qr_code=f'AMENU{tag}BR', allow_remote_orders=True, subscription_plan='PRO')
        today = datetime.date.today()
        self.sub = RestaurantSubscription.objects.create(
            restaurant_owner=self.main, subscription_start_date=today - datetime.timedelta(days=1),
            subscription_end_date=today + datetime.timedelta(days=30))
        self.table = TableInfo.objects.create(restaurant=self.r_main, owner=self.main, tbl_no=f'T{tag}1')
        self.cat = MainCategory.objects.create(restaurant=self.r_main, owner=self.main, name=f'{tag}Cat')
        self.sub_cat = SubCategory.objects.create(main_category=self.cat, name=f'{tag}Sub')
        self.product = Product.objects.create(name=f'{tag}Dish', description='d', main_category=self.cat,
                                              sub_category=self.sub_cat, price=Decimal('100.00'),
                                              available_in_stock=50)


class AccessBase(TestCase):
    def setUp(self):
        cache.clear()
        self._p = [mock.patch('orders.push.send_push'),
                   mock.patch('orders.push._in_background', lambda fn, *a: None)]
        for p in self._p:
            p.start()
        self.A = Tenant('ta')
        self.B = Tenant('tb')
        self.admin = User.objects.create_user('ta_admin', password=PW, role=role('administrator'),
                                              is_staff=True, is_superuser=True)
        self.customer = User.objects.create_user('ta_customer', password=PW, role=role('customer'),
                                                 email='cust@x.test')

    def tearDown(self):
        for p in self._p:
            p.stop()
        cache.clear()

    def as_(self, user):
        c = Client()
        if user is not None:
            c.force_login(user)
        return c

    def login(self, username, password, ip='10.1.1.1'):
        c = Client()
        return c, c.post('/accounts/login/', {'username': username, 'password': password}, REMOTE_ADDR=ip)

    def process_expiry(self):
        expire(self.A.sub)
        self.A.sub.update_subscription_status()

    def refresh(self, *users):
        for u in users:
            u.refresh_from_db()


# ---------------------------------------------------------------- bug 2 / 9 / 7 / 8 / 19
class RenewalReactivationTests(AccessBase):
    def test_extend_reactivates_owner_and_staff_but_not_deliberately_disabled(self):
        self.A.kitchen.is_active = False          # owner disabled this account on purpose
        self.A.kitchen.save()
        self.process_expiry()
        self.refresh(self.A.main, self.A.cashier)
        self.assertFalse(self.A.main.is_active)
        self.assertFalse(self.A.cashier.is_active)

        self.as_(self.admin).post(f'/system-admin/extend-subscription/{self.A.main.id}/', {'days': 30})
        self.A.sub.refresh_from_db()
        self.assertTrue(self.A.sub.is_active)
        self.refresh(self.A.main, self.A.cashier, self.A.manager, self.A.kitchen)
        self.assertTrue(self.A.main.is_active)
        self.assertTrue(self.A.cashier.is_active)
        self.assertTrue(self.A.manager.is_active)
        self.assertFalse(self.A.kitchen.is_active, 'renewal re-enabled a staff account the owner disabled')
        _, r = self.login(self.A.main.username, PW)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].startswith('/admin-panel/'))

    def test_extend_legacy_suspension_without_record(self):
        """Expired before suspensions were recorded: owner and staff all come back."""
        expire(self.A.sub)
        RestaurantSubscription.objects.filter(pk=self.A.sub.pk).update(subscription_status='expired')
        User.objects.filter(pk__in=[self.A.main.pk, self.A.cashier.pk]).update(is_active=False)
        self.as_(self.admin).post(f'/system-admin/extend-subscription/{self.A.main.id}/', {'days': 30})
        self.refresh(self.A.main, self.A.cashier)
        self.assertTrue(self.A.main.is_active)
        self.assertTrue(self.A.cashier.is_active)

    def test_extend_other_tenant_untouched(self):
        self.process_expiry()
        self.B.cashier.is_active = False
        self.B.cashier.save()
        self.as_(self.admin).post(f'/system-admin/extend-subscription/{self.A.main.id}/', {'days': 30})
        self.B.cashier.refresh_from_db()
        self.assertFalse(self.B.cashier.is_active)

    def test_model_unblock_keeps_deliberately_disabled_staff_off(self):
        self.A.kitchen.is_active = False
        self.A.kitchen.save()
        self.A.sub.block_restaurant('unpaid')
        self.refresh(self.A.main, self.A.cashier)
        self.assertFalse(self.A.main.is_active)
        self.assertFalse(self.A.cashier.is_active)
        self.A.sub.refresh_from_db()
        self.A.sub.unblock_restaurant()
        self.refresh(self.A.main, self.A.cashier, self.A.kitchen)
        self.assertTrue(self.A.main.is_active)
        self.assertTrue(self.A.cashier.is_active)
        self.assertFalse(self.A.kitchen.is_active)

    def test_view_unblock_after_model_block(self):
        self.A.sub.block_restaurant('unpaid', blocked_by=self.admin)
        self.as_(self.admin).post(f'/system-admin/unblock-restaurant/{self.A.main.id}/')
        self.A.sub.refresh_from_db()
        self.refresh(self.A.main, self.A.cashier)
        self.assertFalse(self.A.sub.is_blocked_by_admin)
        self.assertTrue(self.A.sub.is_active)
        self.assertTrue(self.A.main.is_active)
        self.assertTrue(self.A.cashier.is_active)

    def test_view_unblock_during_grace_period(self):
        self.A.sub.subscription_end_date = datetime.date.today() - datetime.timedelta(days=2)
        self.A.sub.save()
        c = self.as_(self.admin)
        c.post(f'/system-admin/block-restaurant/{self.A.main.id}/')
        c.post(f'/system-admin/unblock-restaurant/{self.A.main.id}/')
        self.A.sub.refresh_from_db()
        self.assertEqual(self.A.sub.subscription_status, 'active')
        self.assertTrue(self.A.sub.is_active)

    def test_view_unblock_after_grace_stays_expired(self):
        expire(self.A.sub)
        c = self.as_(self.admin)
        c.post(f'/system-admin/block-restaurant/{self.A.main.id}/')
        c.post(f'/system-admin/unblock-restaurant/{self.A.main.id}/')
        self.A.sub.refresh_from_db()
        self.assertEqual(self.A.sub.subscription_status, 'expired')

    def test_extend_days_clamped(self):
        old = self.A.sub.subscription_end_date
        c = self.as_(self.admin)
        c.post(f'/system-admin/extend-subscription/{self.A.main.id}/', {'days': -400})
        self.A.sub.refresh_from_db()
        self.assertEqual(self.A.sub.subscription_end_date, old + datetime.timedelta(days=1))
        r = c.post(f'/system-admin/extend-subscription/{self.A.main.id}/', {'days': 10 ** 9})
        self.assertEqual(r.status_code, 302)
        self.A.sub.refresh_from_db()
        self.assertEqual(self.A.sub.subscription_end_date, old + datetime.timedelta(days=1 + 3650))

    def test_admin_orders_bad_filter(self):
        c = self.as_(self.admin)
        for url in ('/system-admin/orders/?restaurant=abc', '/system-admin/users/?restaurant=abc',
                    '/system-admin/products/?restaurant=abc'):
            self.assertEqual(c.get(url).status_code, 200, url)


# ---------------------------------------------------------------- bug 3 / 6
class ClosedRestaurantCustomerTests(AccessBase):
    def test_session_helper_refuses_expired_blocked_inactive(self):
        from accounts.security_utils import validate_session_restaurant_id
        self.assertEqual(validate_session_restaurant_id({'selected_restaurant_id': self.A.main.id}), self.A.main)
        expire(self.A.sub)
        session = {'selected_restaurant_id': self.A.main.id}
        self.assertIsNone(validate_session_restaurant_id(session))
        self.assertNotIn('selected_restaurant_id', session)
        # branch of an expired main restaurant
        self.assertIsNone(validate_session_restaurant_id({'selected_restaurant_id': self.A.branch_owner.id}))
        # other tenant unaffected
        self.assertEqual(validate_session_restaurant_id({'selected_restaurant_id': self.B.main.id}), self.B.main)
        # blocked / deactivated restaurant
        self.B.sub.block_restaurant('x')
        self.assertIsNone(validate_session_restaurant_id({'selected_restaurant_id': self.B.main.id}))

    def test_deactivated_branch_refused(self):
        from accounts.security_utils import validate_session_restaurant_id
        Restaurant.objects.filter(pk=self.A.r_branch.pk).update(is_active=False)
        self.assertIsNone(validate_session_restaurant_id({'selected_restaurant_id': self.A.branch_owner.id}))
        self.assertEqual(validate_session_restaurant_id({'selected_restaurant_id': self.A.main.id}), self.A.main)

    def test_cannot_place_web_order_after_expiry(self):
        c = self.as_(self.customer)
        c.get(f'/r/{self.A.r_main.qr_code}/')
        c.post('/orders/table/', {'table_id': self.A.table.id})
        s = c.session
        s['cart'] = {str(self.A.product.id): {'name': self.A.product.name, 'price': '100.00', 'quantity': 1}}
        s.save()
        expire(self.A.sub)
        before = Order.objects.count()
        c.post('/orders/place-order/', {'special_instructions': ''})
        self.assertEqual(Order.objects.count(), before)

    def test_browse_hides_expired_and_order_type_404(self):
        expire(self.A.sub)
        c = self.as_(self.customer)
        r = c.get('/restaurant/browse/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, self.A.r_main.name)
        self.assertNotContains(r, self.A.r_branch.name)
        self.assertContains(r, self.B.r_main.name)
        self.assertEqual(c.get(f'/restaurant/browse/{self.A.r_main.id}/order-type/').status_code, 404)
        self.assertEqual(c.get(f'/restaurant/browse/{self.A.r_main.id}/delivery/').status_code, 404)
        self.assertEqual(c.get(f'/restaurant/browse/{self.B.r_main.id}/order-type/').status_code, 200)


# ---------------------------------------------------------------- bug 4 / 5
class QrUnavailableTests(AccessBase):
    def test_blocked_qr_shows_suspended(self):
        self.A.sub.block_restaurant('unpaid')
        r = Client().get(f'/r/{self.A.r_main.qr_code}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'suspended')

    def test_expired_processed_qr_shows_unavailable(self):
        self.process_expiry()
        for code in (self.A.r_main.qr_code, self.A.r_branch.qr_code):
            c = Client()
            r = c.get(f'/r/{code}/')
            self.assertEqual(r.status_code, 200, code)
            self.assertContains(r, 'unavailable')
            self.assertNotIn('selected_restaurant_id', c.session)

    def test_menu_view_blocked_and_expired(self):
        self.A.sub.block_restaurant('x')
        r = Client().get(f'/menu-view/{self.A.r_main.menu_qr_code}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'unavailable')
        self.assertNotContains(r, self.A.product.name)

    def test_deactivated_restaurant_qr_and_menu(self):
        Restaurant.objects.filter(pk=self.A.r_main.pk).update(is_active=False)
        c = self.as_(self.customer)
        r = c.get(f'/r/{self.A.r_main.qr_code}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'unavailable')
        self.assertNotIn('selected_restaurant_id', c.session)
        r = Client().get(f'/menu-view/{self.A.r_main.menu_qr_code}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'unavailable')
        self.assertNotContains(r, self.A.product.name)

    def test_manually_deactivated_owner_still_invalid(self):
        User.objects.filter(pk=self.A.main.pk).update(is_active=False)
        r = Client().get(f'/r/{self.A.r_main.qr_code}/')
        self.assertEqual(r.status_code, 302)

    def test_active_qr_still_works(self):
        c = self.as_(self.customer)
        r = c.get(f'/r/{self.A.r_main.qr_code}/')
        self.assertEqual(r.headers['Location'], '/orders/table/')
        self.assertEqual(c.session['selected_restaurant_id'], self.A.main.id)


# ---------------------------------------------------------------- bug 10
class BranchModuleRestrictionTests(AccessBase):
    def test_disabled_module_applies_to_branches(self):
        f, _ = Feature.objects.get_or_create(slug='process_payments',
                                             defaults={'name': 'Process Payments', 'category': 'payments'})
        self.A.sub.disabled_features.add(f)
        for u in (self.A.main, self.A.cashier, self.A.branch_owner, self.A.branch_cashier):
            fresh = User.objects.get(pk=u.pk)
            self.assertFalse(fresh.has_feature('process_payments'), u.username)
            self.assertNotIn('process_payments', fresh.visible_features, u.username)
        fresh = User.objects.get(pk=self.B.branch_cashier.pk)
        self.assertTrue(fresh.has_feature('process_payments'))


# ---------------------------------------------------------------- bug 11
class SessionTimeoutTests(AccessBase):
    def test_idle_timeout_logs_out_with_redirect(self):
        c = self.as_(self.A.cashier)
        self.assertEqual(c.get('/cashier/').status_code, 200)
        s = c.session
        s['last_activity'] = time.time() - 43201
        s.save()
        r = c.get('/cashier/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/accounts/login/', r.headers['Location'])
        self.assertNotIn('_auth_user_id', c.session)

    def test_message_middleware_before_custom_middleware(self):
        for module in ('restaurant_system.settings', 'restaurant_system.production_settings'):
            import importlib
            try:
                mw = importlib.import_module(module).MIDDLEWARE
            except Exception:
                continue  # production settings need the server environment
            msg = mw.index('django.contrib.messages.middleware.MessageMiddleware')
            self.assertLess(mw.index('django.contrib.auth.middleware.AuthenticationMiddleware'), msg, module)
            self.assertLess(msg, mw.index('restaurant_system.session_timeout_middleware.SessionTimeoutMiddleware'), module)
            self.assertLess(msg, mw.index('restaurant_system.subscription_middleware.SubscriptionAccessMiddleware'), module)


# ---------------------------------------------------------------- bug 12 / 15 / 16
class RateLimitAndRegistrationTests(AccessBase):
    def test_login_rate_limit_friendly_page(self):
        # 20/min per IP; fixed one-minute windows, so send enough to cross a window edge
        codes = [Client().post('/accounts/login/', {'username': f'nobody{i}', 'password': 'x'},
                               REMOTE_ADDR='10.5.5.5').status_code for i in range(45)]
        self.assertIn(429, codes)
        self.assertNotIn(403, codes)

    def _reg(self, **kw):
        d = dict(username='newcust1', email='newcust1@x.test', first_name='N', last_name='C',
                 phone_number='0712345678', address='addr', password='Very-Strong-pw-77',
                 confirm_password='Very-Strong-pw-77')
        d.update(kw)
        return d

    def test_registration_rate_limit_friendly_page(self):
        codes = [Client().post('/accounts/register/', self._reg(username=f'rl{i}', email=f'rl{i}@x.t'),
                               REMOTE_ADDR='9.9.9.9').status_code for i in range(4)]
        self.assertEqual(codes[3], 429)

    def test_blank_email_customers(self):
        Client().post('/accounts/register/', self._reg(username='noemail1', email=''), REMOTE_ADDR='1.1.1.1')
        Client().post('/accounts/register/', self._reg(username='noemail2', email=''), REMOTE_ADDR='1.1.1.2')
        self.assertTrue(User.objects.filter(username='noemail2').exists())

    def test_owner_registration_duplicate_email_and_honeypot(self):
        r = Client().post('/accounts/register-owner/', self._reg(username='o1', email=self.A.main.email,
                          restaurant_name='X', subscription_plan='SINGLE'), REMOTE_ADDR='2.2.2.1')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='o1').exists())
        Client().post('/accounts/register-owner/', self._reg(username='o2', email='o2@x.test',
                      restaurant_name='X', subscription_plan='SINGLE', website='spam'), REMOTE_ADDR='2.2.2.2')
        self.assertFalse(User.objects.filter(username='o2').exists())


# ---------------------------------------------------------------- bug 13 / 17 / 20
class LoginMessageTests(AccessBase):
    def test_expired_owner_and_staff_see_reason(self):
        from axes.models import AccessAttempt
        self.process_expiry()
        for u in (self.A.main, self.A.cashier):
            c, r = self.login(u.username, PW)
            self.assertEqual(r.status_code, 302, u.username)
            self.assertTrue(r.headers['Location'].startswith('/accounts/access-blocked/'), r.headers['Location'])
            self.assertIn('expired', r.headers['Location'])
            self.assertNotIn('_auth_user_id', c.session)
        self.assertFalse(AccessAttempt.objects.filter(username=self.A.main.username).exists(),
                         'correct password counted as a failed attempt')

    def test_blocked_reason_shown(self):
        self.A.sub.block_restaurant('Unpaid invoice')
        c, r = self.login(self.A.cashier.username, PW)
        r2 = c.get(r.headers['Location'])
        self.assertContains(r2, 'Unpaid invoice')

    def test_wrong_password_reveals_nothing(self):
        self.process_expiry()
        _, r = self.login(self.A.main.username, 'wrong-password')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Invalid username or password')

    def test_disabled_staff_with_active_subscription_gets_normal_message(self):
        self.A.kitchen.is_active = False
        self.A.kitchen.save()
        _, r = self.login(self.A.kitchen.username, PW)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Invalid username or password')

    def test_locked_out_account_stays_locked(self):
        self.process_expiry()
        for i in range(10):
            self.login(self.A.main.username, f'bad{i}', ip='10.7.7.7')
        _, r = self.login(self.A.main.username, PW, ip='10.7.7.7')
        self.assertIn(r.status_code, (403, 429))

    def test_manager_tax_update_refused(self):
        c = self.as_(self.A.manager)
        r = c.post('/accounts/update-tax-rate/', json.dumps({'tax_rate': '0.18'}), content_type='application/json')
        self.assertFalse(r.json()['success'])
        c = self.as_(self.A.main)
        r = c.post('/accounts/update-tax-rate/', json.dumps({'tax_rate': '0.18'}), content_type='application/json')
        self.assertTrue(r.json()['success'])
        self.A.r_main.refresh_from_db()
        self.assertEqual(self.A.r_main.tax_rate, Decimal('0.1800'))

    def test_rider_web_login_lands_on_app_page(self):
        c, r = self.login(self.A.rider.username, PW)
        self.assertEqual(r.headers['Location'], '/accounts/rider/')
        self.assertEqual(c.get('/accounts/rider/').status_code, 200)


# ---------------------------------------------------------------- customer site: B2 / B6 / B7 / B8 / B11
class CustomerSiteFixTests(AccessBase):
    def _cart(self, c, product):
        s = c.session
        s['cart'] = {str(product.id): {'name': product.name, 'price': str(product.price), 'quantity': 1}}
        s.save()

    def test_switching_restaurant_clears_cart(self):
        c = self.as_(self.customer)
        c.post(f'/restaurant/browse/{self.A.r_main.id}/order-type/', {'order_type': 'pickup'})
        self._cart(c, self.A.product)
        # same restaurant again keeps the cart
        c.post(f'/restaurant/browse/{self.A.r_main.id}/order-type/', {'order_type': 'pickup'})
        self.assertIn(str(self.A.product.id), c.session.get('cart', {}))
        # a different restaurant (delivery) empties it
        c.post(f'/restaurant/browse/{self.B.r_main.id}/delivery/',
               {'delivery_address': 'Stone Town', 'delivery_phone': '0777'})
        self.assertEqual(c.session.get('selected_restaurant_id'), self.B.main.id)
        self.assertNotIn(str(self.A.product.id), c.session.get('cart', {}))
        # QR scan of another restaurant empties it too
        self._cart(c, self.B.product)
        c.get(f'/r/{self.A.r_main.qr_code}/')
        self.assertNotIn(str(self.B.product.id), c.session.get('cart', {}))

    def test_menu_price_uses_highest_discount(self):
        now = datetime.datetime.now()
        common = dict(owner=self.A.main, is_active=True, days_of_week='1,2,3,4,5,6,7',
                      start_time=datetime.time(0, 0), end_time=datetime.time(23, 59, 59))
        p10 = HappyHourPromotion.objects.create(name='p10', discount_percentage=Decimal('10'), **common)
        p10.products.add(self.A.product)
        p30 = HappyHourPromotion.objects.create(name='p30', discount_percentage=Decimal('30'), **common)
        p30.main_categories.add(self.A.cat)
        charged = Product.objects.get(pk=self.A.product.pk).get_current_price()
        self.assertEqual(charged, Decimal('70.00'))
        c = self.as_(self.customer)
        c.post(f'/restaurant/browse/{self.A.r_main.id}/order-type/', {'order_type': 'pickup'})
        r = c.get('/restaurant/menu/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "'price': '70.00'")
        self.assertNotContains(r, "'price': '90.00'")

    def test_menu_lists_products_without_subcategory(self):
        Product.objects.create(name='LooseSamosa', description='d', main_category=self.A.cat,
                               price=Decimal('5.00'), available_in_stock=5)
        c = self.as_(self.customer)
        c.post(f'/restaurant/browse/{self.A.r_main.id}/order-type/', {'order_type': 'pickup'})
        r = c.get('/restaurant/menu/')
        self.assertContains(r, 'LooseSamosa')

    def _event(self):
        return Event.objects.create(owner=self.A.main, title='Wedding', event_date=datetime.date.today(),
                                    start_time=datetime.time(18, 0), total_pax=10,
                                    price_per_pax=Decimal('10.00'), contact_name='X', contact_phone='0777')

    def test_delete_event_requires_post(self):
        ev = self._event()
        c = self.as_(self.A.main)
        self.assertEqual(c.get(f'/restaurant/events/{ev.id}/delete/').status_code, 405)
        self.assertTrue(Event.objects.filter(pk=ev.pk).exists())
        c.post(f'/restaurant/events/{ev.id}/delete/')
        self.assertFalse(Event.objects.filter(pk=ev.pk).exists())

    def test_event_payment_bad_amount(self):
        ev = self._event()
        c = self.as_(self.A.main)
        for bad in ('abc', 'NaN', 'Infinity'):
            r = c.post(f'/restaurant/events/{ev.id}/record-payment/', json.dumps({'amount': bad}),
                       content_type='application/json')
            self.assertEqual(r.status_code, 200, bad)
            self.assertFalse(r.json()['success'], bad)
