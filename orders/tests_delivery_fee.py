"""
Delivery fee tests: every place that creates, changes, charges, prints or reports an
order total must include the fee exactly once and never count it as tax.

Setup: tax 18%, Pilau 5,000, delivery fee 3,000 (unless a test changes it).

Run:  python manage.py test orders.tests_delivery_fee
"""
import datetime
import sys
from decimal import Decimal
from unittest import mock

import django.test.client as _dtc
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User, RestaurantSubscription
from restaurant.models_restaurant import Restaurant
from restaurant.models import TableInfo, MainCategory, Product
from orders.models import Order

if sys.version_info >= (3, 14):
    _dtc.store_rendered_templates = lambda *a, **k: None

D = Decimal


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class DeliveryFeeTests(TestCase):
    def setUp(self):
        p = mock.patch('orders.push.send_push')  # no push side effects
        p.start(); self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.branch_owner = mk('bown', 'branch_owner', owner=self.main, restaurant_name='Branch R')
        self.cust = mk('cust', 'customer')
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.r = Restaurant.objects.create(
            name='Main R', address='a', main_owner=self.main, branch_owner=self.main, is_main_restaurant=True,
            qr_code='QRMAIN', allow_remote_orders=True, tax_rate=D('0.1800'), delivery_fee=D('3000.00'))
        self.branch = Restaurant.objects.create(
            name='Branch R', address='b', main_owner=self.main, branch_owner=self.branch_owner,
            is_main_restaurant=False, parent_restaurant=self.r, qr_code='QRBR', allow_remote_orders=True,
            tax_rate=D('0.1800'), delivery_fee=D('1000.00'))
        today = datetime.date.today()
        RestaurantSubscription.objects.create(restaurant_owner=self.main, subscription_start_date=today,
                                              subscription_end_date=today + datetime.timedelta(days=30))
        self.table = TableInfo.objects.create(restaurant=self.r, owner=self.main, tbl_no='T1')
        cat = MainCategory.objects.create(restaurant=self.r, owner=self.main, name='Food')
        self.food = Product.objects.create(name='Pilau', description='d', main_category=cat,
                                           price=D('5000.00'), available_in_stock=500)
        self.chips = Product.objects.create(name='Chips', description='d', main_category=cat,
                                            price=D('2000.00'), available_in_stock=500)

    # ---------- helpers ----------
    def _api(self, user, rid=None):
        c = APIClient()
        c.force_authenticate(user)
        if rid:
            c.credentials(HTTP_X_RESTAURANT_ID=str(rid))
        return c

    def _items(self, *pairs):
        return [{'product_id': p.id, 'quantity': q, 'price': float(p.price)} for p, q in pairs]

    def _mobile_delivery(self, *pairs, order_type='delivery'):
        r = self._api(self.cust, self.r.id).post('/api/v1/orders/', {
            'order_type': order_type, 'delivery_address': 'Stone Town', 'delivery_phone': '0777000000',
            'items': self._items(*pairs)}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        return Order.objects.get(id=r.json()['order']['id'])

    def _set(self, **kw):
        Restaurant.objects.filter(pk=self.r.pk).update(**kw)

    # ---------- the formula ----------
    def test_fee_not_taxed(self):
        o = self._mobile_delivery((self.food, 2))
        self.assertEqual((o.delivery_fee, o.delivery_fee_taxed), (D('3000.00'), False))
        self.assertEqual(o.total_amount, D('14800.00'))          # 10,000 + 1,800 tax + 3,000 fee
        self.assertEqual(o.get_tax_amount(), D('1800.00'))
        self.assertEqual(o.get_total(), D('14800.00'))
        self.assertEqual(o.get_subtotal(), D('10000.00'))

    def test_fee_taxed_when_restaurant_chooses(self):
        self._set(delivery_fee_taxable=True)
        o = self._mobile_delivery((self.food, 2))
        self.assertTrue(o.delivery_fee_taxed)
        self.assertEqual(o.total_amount, D('15340.00'))          # (10,000 + 3,000) x 1.18
        self.assertEqual(o.get_tax_amount(), D('2340.00'))
        self.assertEqual(o.get_total(), D('15340.00'))

    def test_free_delivery_minimum(self):
        self._set(free_delivery_minimum=D('10000.00'))
        o = self._mobile_delivery((self.food, 2))                # food 10,000 → free
        self.assertEqual((o.delivery_fee, o.total_amount), (D('0.00'), D('11800.00')))
        o2 = self._mobile_delivery((self.food, 1))               # food 5,000 → fee
        self.assertEqual((o2.delivery_fee, o2.total_amount), (D('3000.00'), D('8900.00')))

    def test_no_fee_for_pickup_dine_in_or_zero_setting(self):
        o = self._mobile_delivery((self.food, 1), order_type='pickup')
        self.assertEqual((o.delivery_fee, o.total_amount), (D('0.00'), D('5900.00')))
        r = self._api(self.cashier).post('/api/v1/orders/', {'table_id': self.table.id, 'items': self._items((self.food, 1))}, format='json')
        d = Order.objects.get(id=r.json()['order']['id'])
        self.assertEqual((d.delivery_fee, d.total_amount), (D('0.00'), D('5900.00')))
        self._set(delivery_fee=D('0'))
        z = self._mobile_delivery((self.food, 1))
        self.assertEqual((z.delivery_fee, z.total_amount), (D('0.00'), D('5900.00')))

    def test_branch_uses_its_own_fee(self):
        r = self._api(self.cust, self.branch.id)
        bcat = MainCategory.objects.create(restaurant=self.branch, owner=self.branch_owner, name='BFood')
        bp = Product.objects.create(name='B', description='d', main_category=bcat, price=D('5000.00'))
        resp = r.post('/api/v1/orders/', {'order_type': 'delivery', 'delivery_phone': '0777', 'delivery_address': 'x',
                                          'items': [{'product_id': bp.id, 'quantity': 1, 'price': 5000}]}, format='json')
        o = Order.objects.get(id=resp.json()['order']['id'])
        self.assertEqual((o.delivery_fee, o.total_amount), (D('1000.00'), D('6900.00')))

    # ---------- other creation paths ----------
    def test_web_delivery_order(self):
        self.client.force_login(self.cust)
        self.client.post(f'/restaurant/browse/{self.r.id}/delivery/', {'delivery_address': 'x', 'delivery_phone': '0777'})
        s = self.client.session
        s['cart'] = {str(self.food.id): {'name': 'Pilau', 'price': '5000.00', 'quantity': 2}}
        s.save()
        cart = self.client.get('/orders/cart/').content.decode()
        self.assertIn('Delivery fee:', cart)
        self.assertIn('14800.00', cart)
        self.assertIn('const FEE_SETTING = 3000.000000', cart)
        checkout = self.client.get('/orders/place-order/').content.decode()
        self.assertIn('Delivery fee:', checkout)
        self.assertIn('14800.00', checkout)
        self.client.post('/orders/place-order/', {'special_instructions': ''})
        o = Order.objects.get(ordered_by=self.cust)
        self.assertEqual((o.delivery_fee, o.total_amount), (D('3000.00'), D('14800.00')))

    def test_web_pickup_cart_shows_no_fee(self):
        self.client.force_login(self.cust)
        self.client.post(f'/restaurant/browse/{self.r.id}/order-type/', {'order_type': 'pickup'})
        s = self.client.session
        s['cart'] = {str(self.food.id): {'name': 'Pilau', 'price': '5000.00', 'quantity': 1}}
        s.save()
        self.assertNotIn('Delivery fee:', self.client.get('/orders/cart/').content.decode())

    def test_offline_sync_delivery(self):
        from mobile_api.views.sync import _sync_order
        res = _sync_order(self.cust, self.main, {'offline_id': 'off-1', 'order_type': 'delivery',
                                                 'delivery_phone': '0777', 'restaurant_id': self.r.id,
                                                 'items': self._items((self.food, 2))})
        o = Order.objects.get(id=res['order_id'])
        self.assertEqual((o.delivery_fee, o.total_amount), (D('3000.00'), D('14800.00')))

    # ---------- changing items keeps the fee and the tax rate ----------
    def test_add_and_cancel_items_keep_fee(self):
        self._set(delivery_fee_taxable=True)
        o = self._mobile_delivery((self.food, 2))                       # 15,340
        staff = self._api(self.main)
        r = staff.post(f'/api/v1/orders/{o.id}/add-items/', {'items': self._items((self.chips, 1))}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.total_amount, D('17700.00'))                 # (12,000 + 3,000) x 1.18
        self.assertEqual(o.get_tax_amount(), D('2700.00'))
        chips_item = o.order_items.get(product=self.chips)
        r = staff.post(f'/api/v1/orders/items/{chips_item.id}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.total_amount, D('15340.00'))                 # back to the original
        self.assertEqual(o.delivery_fee, D('3000.00'))

    def test_offline_append_keeps_fee(self):
        from mobile_api.views.sync import _sync_order
        o = self._mobile_delivery((self.food, 2))                       # 14,800
        res = _sync_order(self.main, self.main, {'offline_id': 'app-1', 'existing_order_id': o.id,
                                                 'items': self._items((self.chips, 1))})
        self.assertEqual(res.get('status'), 'created', res)
        o.refresh_from_db()
        self.assertEqual(o.total_amount, D('17160.00'))                 # 12,000 x 1.18 + 3,000

    def test_web_cancel_item_keeps_fee(self):
        o = self._mobile_delivery((self.food, 2), )
        from orders.models import OrderItem
        OrderItem.objects.create(order=o, product=self.chips, quantity=1, unit_price=D('2000.00'))
        Order.objects.filter(pk=o.pk).update(total_amount=D('17160.00'))
        item = o.order_items.get(product=self.chips)
        self.client.force_login(self.main)
        r = self.client.post(f'/orders/cancel-item/{item.id}/', data='{"reason": "test"}', content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertFalse(o.order_items.filter(product=self.chips).exists())
        self.assertEqual(o.total_amount, D('14800.00'))

    # ---------- money in / out ----------
    def test_payment_balance_includes_fee(self):
        o = self._mobile_delivery((self.food, 2))                       # 14,800
        data = self._api(self.main).get(f'/api/v1/orders/{o.id}/').json()['order']
        self.assertEqual((data['delivery_fee'], data['total'], data['balance_due']), (3000.0, 14800.0, 14800.0))
        r = self._api(self.main).post('/api/v1/payments/', {'order_id': o.id, 'amount': '14800.00', 'payment_method': 'cash'}, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        o.refresh_from_db()
        self.assertEqual(o.payment_status, 'paid')

    def test_printed_bill_shows_fee(self):
        from orders.printing import _generate_bill_content
        o = self._mobile_delivery((self.food, 2))
        bill = _generate_bill_content(o)
        self.assertIn('Delivery fee:', bill)
        self.assertIn('3000.00', bill)
        self.assertIn('1800.00', bill)      # tax excludes the fee
        self.assertIn('14800.00', bill)

    def test_report_tax_excludes_fee(self):
        self._mobile_delivery((self.food, 2))
        self.client.force_login(self.main)
        page = self.client.get('/reports/').content.decode()
        self.assertRegex(page, r'Tax \(18\.0%\): \$1800\.00')   # fee not counted as tax (would be 4800)
        self.assertIn('$13000.00', page)                         # revenue before tax = food 10,000 + fee 3,000

    # ---------- settings ----------
    def test_owner_profile_saves_own_restaurant_only(self):
        self.client.force_login(self.main)
        self.client.post('/admin-panel/profile/', {
            'action': 'update_restaurant', 'restaurant_name': 'Main R', 'restaurant_description': '',
            'tax_rate': '18', 'allow_remote_orders': 'on',
            'delivery_fee': '2500', 'free_delivery_minimum': '40000', 'delivery_fee_taxable': 'on'})
        self.r.refresh_from_db(); self.branch.refresh_from_db()
        self.assertEqual((self.r.delivery_fee, self.r.free_delivery_minimum, self.r.delivery_fee_taxable),
                         (D('2500.00'), D('40000.00'), True))
        self.assertEqual(self.branch.delivery_fee, D('1000.00'))   # branch untouched

    def test_owner_profile_rejects_invalid_fee(self):
        self.client.force_login(self.main)
        for bad in ('-5', 'abc', '1e12'):
            self.client.post('/admin-panel/profile/', {
                'action': 'update_restaurant', 'restaurant_name': 'Main R', 'restaurant_description': '',
                'tax_rate': '18', 'delivery_fee': bad})
            self.r.refresh_from_db()
            self.assertEqual(self.r.delivery_fee, D('3000.00'), bad)

    def test_empty_free_minimum_means_always_charge(self):
        self.client.force_login(self.main)
        self.client.post('/admin-panel/profile/', {
            'action': 'update_restaurant', 'restaurant_name': 'Main R', 'restaurant_description': '',
            'tax_rate': '18', 'delivery_fee': '3000', 'free_delivery_minimum': ''})
        self.r.refresh_from_db()
        self.assertIsNone(self.r.free_delivery_minimum)

    def test_app_sees_delivery_settings(self):
        self._set(free_delivery_minimum=D('50000'), delivery_fee_taxable=True)
        me = self._api(self.cust, self.r.id).get('/api/v1/auth/me/').json()
        self.assertEqual((me['delivery_fee'], me['delivery_fee_taxable'], me['free_delivery_minimum']), (3000.0, True, 50000.0))
        lst = {x['id']: x for x in self._api(self.cust).get('/api/v1/restaurants/').json()['restaurants']}
        self.assertEqual(lst[self.branch.id]['delivery_fee'], 1000.0)

    # ---------- WhatsApp share ----------
    def test_whatsapp_receipt_text_and_link(self):
        from urllib.parse import unquote
        from cashier.models import Payment
        from orders.share import receipt_share_text, whatsapp_url
        o = self._mobile_delivery((self.food, 2))
        Payment.objects.create(order=o, amount=D('10000.00'), payment_method='cash', processed_by=self.main)
        text = receipt_share_text(o, 'TSh', use_decimals=False)
        for expected in ('*Main R*', f'Order #{o.order_number}', '2 x Pilau - TSh10,000', 'Subtotal: TSh10,000',
                         'Tax: TSh1,800', 'Delivery fee: TSh3,000', '*Total: TSh14,800*',
                         'Paid: TSh10,000', 'Balance due: TSh4,800'):
            self.assertIn(expected, text)
        self.assertTrue(whatsapp_url(text, '0777000000').startswith('https://wa.me/?text='))      # local number → user picks
        self.assertTrue(whatsapp_url(text, '+255 777 000 000').startswith('https://wa.me/255777000000?text='))
        self.assertEqual(unquote(whatsapp_url(text).split('text=', 1)[1]), text)

    def test_receipt_pages_show_whatsapp_button(self):
        from cashier.models import Payment
        o = self._mobile_delivery((self.food, 1))
        pay = Payment.objects.create(order=o, amount=o.total_amount, payment_method='cash', processed_by=self.main)
        Order.objects.filter(pk=o.pk).update(payment_status='paid')
        self.client.force_login(self.main)
        page = self.client.get(f'/cashier/receipt/{pay.id}/').content.decode()
        self.assertIn('https://wa.me/?text=', page)
        self.assertIn('Share on WhatsApp', page)
        self.assertNotIn('your-font-awesome-kit', page)
        self.client.force_login(self.cust)
        self.assertIn('https://wa.me/?text=', self.client.get(f'/orders/receipt/{o.id}/').content.decode())

    # ---------- existing orders unaffected ----------
    def test_existing_orders_without_fee_unchanged(self):
        from orders.models import OrderItem
        o = Order.objects.create(order_number='ORD-OLD', ordered_by=self.cust, order_type='pickup',
                                 restaurant_owner=self.main, total_amount=D('5900.00'))
        OrderItem.objects.create(order=o, product=self.food, quantity=1, unit_price=D('5000.00'))
        self.assertEqual((o.get_tax_amount(), o.get_total()), (D('900.00'), D('5900.00')))
        self.assertEqual(o.charged_tax_rate().quantize(D('0.0001')), D('0.1800'))
