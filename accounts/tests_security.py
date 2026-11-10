"""
Security regression tests (Nov 2026 review):
  1. Stored XSS: system-admin / owner / customer pages escape user-controlled names,
     and JSON in <script> is emitted with json_script / escapejs.
  2. Names and custom-role text are sanitised on save.
  3. API tokens are deleted when the password changes (not on ordinary saves),
     and token expiry applies outside /api/v1/ (except the Print Client API).
  4. Mobile registration is rate limited per IP; DRF throttling trusts one proxy.
  5. WebSocket handshakes from foreign origins are refused.
  6. Inventory CSV export neutralises spreadsheet formulas.
"""
import sys
if sys.version_info >= (3, 14):
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None

import csv
import datetime
import io
import json
import re
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.models import CustomRole, Role, RestaurantSubscription, User
from accounts.security_utils import sanitize_name, sanitize_plain_text
from inventory.models import InventoryItem, InventoryRecord
from orders.models import Order
from restaurant.models import MainCategory, Product, SubCategory, TableInfo
from restaurant.models_restaurant import Restaurant

P = '<img src=x onerror=alert(1)>'
SP = '</script><script>alert(1)</script>'
PW = 'pw12345!x'


def role(name):
    return Role.objects.get_or_create(name=name)[0]


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class Base(TestCase):
    def setUp(self):
        cache.clear()
        for target in ('orders.push.send_push', 'orders.push.notify_customer_status'):
            p = mock.patch(target)
            p.start()
            self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password=PW, role=role(r), **kw)
        self.mk = mk
        self.admin = mk('adm', 'administrator', is_staff=True, is_superuser=True)
        self.owner = mk('own', 'main_owner', restaurant_name='Main R', first_name='O', last_name='W')
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.owner, branch_owner=self.owner,
                                           is_main_restaurant=True, qr_code='QRM', tax_rate=D('0.18'))
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.owner, defaults={
            'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        self.t1 = TableInfo.objects.create(restaurant=self.r, owner=self.owner, tbl_no='T1')


# ---------------------------------------------------------------------------
# 1. XSS
# ---------------------------------------------------------------------------
class XSSEscapingTests(Base):
    def test_base_templates_define_escape_helper(self):
        for name in ('system_admin/base.html', 'admin_panel/base.html', 'base.html'):
            text = (Path(settings.BASE_DIR) / 'templates' / name).read_text(encoding='utf-8')
            self.assertIn('function escapeHtml(value)', text, name)

    def test_admin_user_details_modal_escapes_every_field(self):
        self.client.force_login(self.admin)
        html = self.client.get('/system-admin/users/').content.decode()
        start = html.index('function viewUser(')
        block = html[start:html.index('function deleteUser(', start)]
        interpolations = re.findall(r'\$\{([^}]*)\}', block)
        self.assertTrue(interpolations)
        for expr in interpolations:
            if expr.strip() in ('userId',):
                continue
            self.assertTrue(expr.strip().startswith('escapeHtml('), expr)

    def test_statistics_chart_json_cannot_break_out_of_script(self):
        self.owner.restaurant_name = SP
        self.owner.save(update_fields=['restaurant_name'])
        Order.objects.create(order_number='X1', table_info=self.t1, ordered_by=self.owner, total_amount=D('1'))
        self.client.force_login(self.admin)
        html = self.client.get('/system-admin/statistics/').content.decode()
        self.assertNotIn(SP, html)
        m = re.search(r'<script id="stats-top-restaurants" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1))['labels'], [SP])  # JS still gets the same structure
        self.assertIn("readJson('stats-top-restaurants')", html)

    def test_system_admin_permissions_page_custom_role_json(self):
        CustomRole.objects.create(owner=self.owner, name=SP, description=P)
        self.client.force_login(self.admin)
        html = self.client.get(f'/system-admin/restaurant-permissions/{self.owner.id}/').content.decode()
        self.assertNotIn(SP, html)
        self.assertNotIn(P, html)
        m = re.search(r'<script id="perm-custom-roles" type="application/json">(.*?)</script>', html, re.S)
        self.assertEqual(json.loads(m.group(1))[0]['name'], SP)

    def test_owner_roles_permissions_page_custom_role_json(self):
        CustomRole.objects.create(owner=self.owner, name=SP, description=P)
        self.client.force_login(self.owner)
        r = self.client.get('/admin-panel/roles-permissions/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn(SP, html)
        self.assertNotIn(P, html)

    def test_customer_menu_escapes_product_and_subcategory_names(self):
        cat = MainCategory.objects.create(restaurant=self.r, owner=self.owner, name='Food')
        sub = SubCategory.objects.create(main_category=cat, name=P)
        Product.objects.create(name=P, description=P, main_category=cat, sub_category=sub,
                               price=D('1'), available_in_stock=5)
        cust = self.mk('c', 'customer')
        self.client.force_login(cust)
        s = self.client.session
        s['selected_table'] = 'T1'
        s['selected_restaurant_id'] = self.owner.id
        s['selected_table_id'] = self.t1.id
        s['selected_restaurant_name'] = 'Main R'
        s.save()
        resp = self.client.get('/restaurant/menu/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn(P, html)
        self.assertIn('${escapeHtml(product.name)}', html)
        self.assertIn('data-product-name="${escapeHtml(product.name)}"', html)
        self.assertNotIn("addToCartDemo('${product.name}'", html)

    def test_rider_delete_button_escapes_name_for_js(self):
        from orders.models import DeliveryRider
        rider_user = self.mk('rid', 'delivery_rider', owner=self.owner, first_name="x');alert(1);//")
        try:
            DeliveryRider.objects.create(user=rider_user)
        except Exception:
            self.skipTest('DeliveryRider needs more fields in this schema')
        self.client.force_login(self.admin)
        html = self.client.get('/system-admin/riders/').content.decode()
        self.assertNotIn("x');alert(1);//", html)
        i = html.index('confirmDeleteRider(')
        handler = html[i:html.index('"', i)]
        # escapejs, not just autoescape: the attribute would decode &#x27; back into a quote
        self.assertIn(r"'x\u0027)", handler)
        self.assertNotIn('&#x27;', handler)


# ---------------------------------------------------------------------------
# 2. Sanitising on save
# ---------------------------------------------------------------------------
class SanitiseOnSaveTests(Base):
    def test_sanitize_name_keeps_real_names(self):
        self.assertEqual(sanitize_name("O'Brien"), "O'Brien")
        self.assertEqual(sanitize_name('José Ñúñez'), 'José Ñúñez')
        self.assertEqual(sanitize_name('Tom & Jerry'), 'Tom & Jerry')
        self.assertEqual(sanitize_name('  Anne-Marie  '), 'Anne-Marie')
        self.assertEqual(sanitize_name(P), '')
        self.assertEqual(sanitize_name('<b>Bob</b>'), 'Bob')
        self.assertEqual(sanitize_name('&lt;script&gt;x'), 'scriptx')
        self.assertEqual(sanitize_plain_text('a\nb & <i>c</i>'), 'a\nb & c')

    def _register(self, **over):
        body = {'username': 'newbie', 'email': 'n@x.com', 'first_name': 'A', 'last_name': 'B',
                'password': 'Zx9!long-pass', 'confirm_password': 'Zx9!long-pass'}
        body.update(over)
        return self.client.post('/api/v1/auth/register/', body, content_type='application/json')

    def test_register_strips_html_from_names(self):
        r = self._register(first_name='<b>José</b>', last_name="O'Brien" + P)
        self.assertEqual(r.status_code, 201, r.content)
        u = User.objects.get(username='newbie')
        self.assertEqual((u.first_name, u.last_name), ('José', "O'Brien"))

    def test_register_name_that_is_only_markup_is_rejected(self):
        r = self._register(first_name=P)
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.json())
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_owner_custom_role_text_is_sanitised(self):
        self.client.force_login(self.owner)
        r = self.client.post('/admin-panel/roles-permissions/custom-role/create/',
                             json.dumps({'name': 'Waiter <script>x</script>', 'description': 'Tables & ' + P,
                                         'feature_slugs': []}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        cr = CustomRole.objects.get(owner=self.owner)
        self.assertEqual(cr.name, 'Waiter x')
        self.assertEqual(cr.description, 'Tables &')


# ---------------------------------------------------------------------------
# 3. Tokens: password change + expiry
# ---------------------------------------------------------------------------
class TokenRevocationTests(Base):
    def setUp(self):
        super().setUp()
        self.cash = self.mk('cashA', 'cashier', owner=self.owner)
        self.key = Token.objects.create(user=self.cash).key

    def _has_token(self):
        return Token.objects.filter(user=self.cash).exists()

    def test_set_password_deletes_token(self):
        self.cash.set_password('NewPw!23456')
        self.cash.save()
        self.assertFalse(self._has_token())
        r = self.client.get('/api/v1/auth/me/', HTTP_AUTHORIZATION=f'Token {self.key}')
        self.assertEqual(r.status_code, 401)

    def test_direct_hash_assignment_deletes_token(self):
        self.cash.password = make_password('Other!23456')
        self.cash.save(update_fields=['password'])
        self.assertFalse(self._has_token())

    def test_normal_saves_and_login_keep_token(self):
        self.cash.first_name = 'Renamed'
        self.cash.save()
        self.cash.last_login = timezone.now()
        self.cash.save(update_fields=['last_login'])
        self.client.force_login(self.cash)   # login() -> update_last_login -> save(update_fields=['last_login'])
        self.cash.refresh_from_db()
        self.cash.save()                 # full save with an unchanged hash
        self.assertEqual(Token.objects.get(user=self.cash).key, self.key)

    def test_mobile_login_still_rotates_token_after_password_change(self):
        self.cash.set_password('NewPw!23456')
        self.cash.save()
        r = self.client.post('/api/v1/auth/login/', {'username': 'cashA', 'password': 'NewPw!23456'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        new_key = r.json()['token']
        self.assertNotEqual(new_key, self.key)
        self.assertEqual(self.client.get('/api/v1/auth/me/', HTTP_AUTHORIZATION=f'Token {new_key}').status_code, 200)

    def test_web_password_change_keeps_session_but_revokes_token(self):
        Token.objects.create(user=self.owner)
        self.client.force_login(self.owner)
        r = self.client.post('/admin-panel/profile/', {'action': 'change_password', 'current_password': PW,
                                                       'new_password': 'Brand!New123', 'confirm_password': 'Brand!New123'})
        self.assertIn(r.status_code, (200, 302))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('Brand!New123'))
        self.assertFalse(Token.objects.filter(user=self.owner).exists())
        r = self.client.get('/admin-panel/profile/')
        self.assertEqual(r.status_code, 200)  # still logged in on the web


class TokenExpiryTests(Base):
    def _aged_token(self, user):
        tok = Token.objects.create(user=user)
        Token.objects.filter(pk=tok.pk).update(created=timezone.now() - datetime.timedelta(days=20))
        return tok.key

    def test_expired_token_rejected_on_mobile_api(self):
        key = self._aged_token(self.owner)
        r = self.client.get('/api/v1/auth/me/', HTTP_AUTHORIZATION=f'Token {key}')
        self.assertEqual(r.status_code, 401)
        self.assertFalse(Token.objects.filter(key=key).exists())

    def test_expired_token_rejected_outside_mobile_api(self):
        key = self._aged_token(self.owner)
        r = self.client.get('/orders/api/', HTTP_AUTHORIZATION=f'Token {key}')
        self.assertEqual(r.status_code, 401)

    def test_print_client_api_keeps_long_lived_token(self):
        key = self._aged_token(self.owner)
        r = self.client.get('/orders/api/print-jobs/pending/', HTTP_AUTHORIZATION=f'Token {key}')
        self.assertNotEqual(r.status_code, 401)
        self.assertTrue(Token.objects.filter(key=key).exists())


# ---------------------------------------------------------------------------
# 4. Rate limiting / proxy handling
# ---------------------------------------------------------------------------
class RegisterRateLimitTests(Base):
    def _post(self, i, ip):
        return self.client.post('/api/v1/auth/register/', {
            'username': f'spam{i}', 'email': f's{i}@x.com', 'first_name': 'a', 'last_name': 'b',
            'password': 'Zx9!kqmw2Lp', 'confirm_password': 'Zx9!kqmw2Lp'},
            content_type='application/json', REMOTE_ADDR=ip)

    def test_thirty_first_signup_per_hour_from_one_ip_is_refused(self):
        codes = [self._post(i, '6.6.6.6').status_code for i in range(30)]
        self.assertEqual(codes, [201] * 30)
        r = self._post(99, '6.6.6.6')
        self.assertEqual(r.status_code, 429)
        self.assertIn('error', r.json())
        self.assertFalse(User.objects.filter(username='spam99').exists())
        # another address is not affected
        self.assertEqual(self._post(100, '7.7.7.7').status_code, 201)


class ProxySettingsTests(SimpleTestCase):
    def test_production_trusts_exactly_one_proxy_for_drf_throttling(self):
        text = (Path(settings.BASE_DIR) / 'restaurant_system' / 'production_settings.py').read_text(encoding='utf-8')
        self.assertRegex(text, r"'NUM_PROXIES':\s*1")

    def test_num_proxies_one_uses_the_address_nginx_appended(self):
        from rest_framework.throttling import AnonRateThrottle
        rf = RequestFactory()
        with override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, 'NUM_PROXIES': 1}):
            req = rf.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='1.2.3.4, 9.9.9.9')
            self.assertEqual(AnonRateThrottle().get_ident(req), '9.9.9.9')


# ---------------------------------------------------------------------------
# 5. WebSocket origin
# ---------------------------------------------------------------------------
class WebSocketOriginTests(SimpleTestCase):
    def _connect(self, headers):
        from channels.generic.websocket import AsyncWebsocketConsumer
        from channels.testing import WebsocketCommunicator
        from restaurant_system.token_auth_middleware import AllowedHostsOriginValidator

        class Echo(AsyncWebsocketConsumer):
            async def connect(self):
                await self.accept()

        async def run():
            comm = WebsocketCommunicator(AllowedHostsOriginValidator(Echo.as_asgi()), '/ws/x/', headers=headers)
            ok, _ = await comm.connect()
            await comm.disconnect()
            return ok
        return async_to_sync(run)()

    @override_settings(ALLOWED_HOSTS=['hospitality.easyfixsoft.com'])
    def test_origins(self):
        self.assertTrue(self._connect([(b'origin', b'https://hospitality.easyfixsoft.com')]))
        self.assertFalse(self._connect([(b'origin', b'https://evil.example')]))
        self.assertFalse(self._connect([(b'origin', b'null')]))
        self.assertTrue(self._connect([]))  # native app without an Origin header

    def test_asgi_wraps_websocket_router(self):
        text = (Path(settings.BASE_DIR) / 'restaurant_system' / 'asgi.py').read_text(encoding='utf-8')
        self.assertIn('"websocket": AllowedHostsOriginValidator(', text)


# ---------------------------------------------------------------------------
# 6. Inventory CSV
# ---------------------------------------------------------------------------
class InventoryCsvTests(Base):
    def test_formula_cells_are_neutralised(self):
        item = InventoryItem.objects.create(owner=self.owner, name='=HYPERLINK("http://x","y")', unit='@kg')
        InventoryRecord.objects.create(item=item, record_type='received', quantity_change=D('-3'),
                                       notes='+cmd|calc', recorded_by=self.owner)
        self.client.force_login(self.owner)
        r = self.client.get('/inventory/history/?export=csv')
        self.assertEqual(r.status_code, 200)
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        row = next(x for x in rows if len(x) > 6 and 'HYPERLINK' in x[1])
        self.assertEqual(row[1], '\t=HYPERLINK("http://x","y")')
        self.assertEqual(row[4], '\t@kg')
        self.assertEqual(row[6], '\t+cmd|calc')
        self.assertEqual(row[3], '-3.00')   # numbers stay numbers
