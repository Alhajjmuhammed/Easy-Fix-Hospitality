import sys
if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None

import datetime
import json
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts.models import Role, User, RestaurantSubscription
from restaurant.models_restaurant import Restaurant
from restaurant.models import TableInfo, MainCategory, Product
from orders.models import Order, OrderItem
from cashier.models import Payment

D = Decimal


def role(name):
    return Role.objects.get_or_create(name=name)[0]


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class Base(TestCase):
    """Two restaurants, every staff role, products for each station (18% tax)."""
    PATCH_PRINT = True

    def setUp(self):
        cache.clear()
        targets = ['orders.push.send_push']
        if self.PATCH_PRINT:
            targets += ['cashier.views.auto_print_receipt', 'orders.printing.auto_print_receipt',
                        'orders.views.auto_print_order', 'orders.views.auto_print_new_items']
        for t in targets:
            p = mock.patch(t, return_value={'receipt_printed': False, 'errors': []})
            p.start()
            self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.other = mk('other', 'main_owner', restaurant_name='Other R')
        self.cashier = mk('cash', 'cashier', owner=self.main, first_name='Cash')
        self.kitchen = mk('kit', 'kitchen', owner=self.main)
        self.cc = mk('cc', 'customer_care', owner=self.main)
        self.cc2 = mk('cc2', 'customer_care', owner=self.main)
        self.manager = mk('mgr', 'manager', owner=self.main)
        self.cust = mk('cust', 'customer', phone_number='0712 345 678', first_name='Asha')
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRM', tax_rate=D('0.1800'),
                                           allow_remote_orders=True)
        today = datetime.date.today()
        for o in (self.main, self.other):
            RestaurantSubscription.objects.get_or_create(restaurant_owner=o, defaults={
                'subscription_start_date': today, 'subscription_end_date': today + datetime.timedelta(days=30)})
        self.t1 = TableInfo.objects.create(restaurant=self.r, owner=self.main, tbl_no='T1')
        cat = MainCategory.objects.create(restaurant=self.r, owner=self.main, name='Food')
        P = lambda n, price, st: Product.objects.create(name=n, description='d', main_category=cat,
                                                        price=D(price), available_in_stock=50, station=st)
        self.pk_ = P('Pilau', '1234.56', 'kitchen')
        self.pb = P('Soda', '1500.50', 'bar')
        self._n = 0

    def order(self, items, table=None, status='pending', by=None, otype='dine-in', **kw):
        self._n += 1
        table = self.t1 if table is None and otype == 'dine-in' else table
        o = Order.objects.create(order_number=f'Q{self._n}', table_info=table, ordered_by=by or self.cashier,
                                 status=status, order_type=otype, **kw)
        for p, q in items:
            OrderItem.objects.create(order=o, product=p, quantity=q, unit_price=p.price)
        o.calculate_total()
        o.save()
        o.refresh_from_db()
        return o

    def pay(self, order, amount, method='cash', user=None, **extra):
        self.client.force_login(user or self.cashier)
        return self.client.post(f'/cashier/process-payment/{order.id}/', json.dumps(
            {'amount': str(amount), 'payment_method': method, **extra}), content_type='application/json')

    def status(self, order, new, user=None, **extra):
        self.client.force_login(user or self.kitchen)
        r = self.client.post(f'/orders/update-status/{order.id}/', json.dumps({'status': new, **extra}),
                             content_type='application/json')
        return r.json()


class CashierStationFixTests(Base):
    """Regression tests for the section-by-section QA run (stations, cashier, receipts)."""

    def test_cancelled_orders_cannot_be_paid(self):
        for st in ('cancelled', 'kitchen_error', 'wasted'):
            o = self.order([(self.pk_, 1)], status=st)
            self.assertEqual(self.pay(o, '100').status_code, 400, st)
        self.assertFalse(Payment.objects.exists())

    def test_amounts_are_rounded_to_the_cent(self):
        o = self.order([(self.pk_, 1)])
        self.assertEqual(self.pay(o, '0.004').status_code, 400)          # rounds to 0.00
        self.assertEqual(self.pay(o, 'Infinity').status_code, 400)
        self.assertEqual(self.pay(o, '10.004').status_code, 200)
        self.assertEqual(Payment.objects.get().amount, D('10.00'))

    def test_paid_order_cannot_be_cancelled_from_station_or_cancel_page(self):
        o = self.order([(self.pk_, 1)], status='preparing')
        self.pay(o, o.total_amount)
        self.assertFalse(self.status(o, 'cancelled')['success'])
        self.client.force_login(self.manager)
        r = self.client.post(f'/orders/cancel-order/{o.id}/', json.dumps({'reason': 'kitchen_error'}),
                             content_type='application/json')
        self.assertFalse(r.json()['success'])
        o.refresh_from_db()
        self.assertEqual(o.status, 'preparing')

    def test_unpaid_order_still_cancels_and_served_food_is_not_restocked(self):
        o = self.order([(self.pk_, 2)], status='preparing')
        self.assertTrue(self.status(o, 'cancelled')['success'])
        self.pk_.refresh_from_db()
        self.assertEqual(self.pk_.available_in_stock, 52)                  # not served yet: back in stock
        s = self.order([(self.pb, 1)], status='served')
        self.status(s, 'cancelled', user=self.manager)
        self.pb.refresh_from_db()
        self.assertEqual(self.pb.available_in_stock, 50)                   # served: the food is gone

    def test_split_bill_cannot_pay_more_of_an_item_than_is_left(self):
        o = self.order([(self.pb, 1), (self.pk_, 3)])
        soda = o.order_items.get(product=self.pb)
        self.assertEqual(self.pay(o, '3001.00', selected_items=[{'id': soda.id, 'quantity': 2}]).status_code, 400)
        self.assertEqual(self.pay(o, '1500.50', selected_items=[{'id': soda.id, 'quantity': 1}]).status_code, 200)
        self.assertEqual(self.pay(o, '1500.50', selected_items=[{'id': soda.id, 'quantity': 1}]).status_code, 400)
        self.assertEqual(Payment.objects.count(), 1)

    def test_receipt_uses_charged_prices_and_shows_paid_and_balance(self):
        o = self.order([(self.pk_, 3)])
        self.pay(o, '1000.00')
        Product.objects.filter(pk=self.pk_.pk).update(price=D('2000.00'))    # menu price changed later
        p = Payment.objects.get()
        self.client.force_login(self.cashier)
        page = self.client.get(f'/cashier/receipt/{p.id}/').content.decode()
        self.assertIn('3703.68', page)                                       # 3 x 1234.56 as charged
        self.assertNotIn('6000.00', page)
        self.assertIn('1000.00', page)                                       # paid
        self.assertIn(f'{o.total_amount - D("1000.00"):.2f}', page)          # balance due

    def test_bad_report_filters_do_not_crash(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get('/cashier/receipts/?date_from=garbage&date_to=x').status_code, 200)
        self.assertEqual(self.client.get('/cashier/reports/?category_id=abc&subcategory_id=x').status_code, 200)

    def test_kot_for_customers_own_pickup_order(self):
        o = self.order([(self.pk_, 1)], by=self.cust, otype='pickup', restaurant_owner=self.main)
        self.client.force_login(self.kitchen)
        self.assertEqual(self.client.get(f'/orders/kot/{o.id}/').status_code, 200)

    def test_removing_item_keeps_the_charged_tax_and_never_goes_below_paid(self):
        o = self.order([(self.pk_, 1), (self.pb, 1)])
        Restaurant.objects.filter(pk=self.r.pk).update(tax_rate=D('0.1000'))   # tax changed afterwards
        self.client.force_login(self.manager)
        soda = o.order_items.get(product=self.pb)
        self.client.post(f'/orders/cancel-item/{soda.id}/', json.dumps({'reason': 'mistake'}),
                         content_type='application/json')
        o.refresh_from_db()
        self.assertEqual(o.total_amount, D('1456.78'))                       # 1234.56 x 1.18, not x 1.10
        o2 = self.order([(self.pk_, 1), (self.pb, 1)])
        self.pay(o2, '2000.00')
        soda2 = o2.order_items.get(product=self.pb)
        self.client.force_login(self.manager)
        r = self.client.post(f'/orders/cancel-item/{soda2.id}/', json.dumps({'reason': 'mistake'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)                                 # 2000 paid > new total
        self.assertTrue(o2.order_items.filter(pk=soda2.pk).exists())


class CustomerSiteFixTests(Base):
    """Customer website and customer-care fixes from the QA run."""

    def setUp(self):
        super().setUp()
        self.bown = self.main          # a branch the main owner's restaurant network also has
        self.branch_owner = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'),
                                                     owner=self.main)
        self.branch = Restaurant.objects.create(name='Branch R', address='b', main_owner=self.main,
                                                branch_owner=self.branch_owner, is_main_restaurant=False,
                                                parent_restaurant=self.r, qr_code='QRB', tax_rate=D('0.1800'),
                                                allow_remote_orders=True)
        bcat = MainCategory.objects.create(restaurant=self.branch, owner=self.branch_owner, name='BFood')
        self.branch_dish = Product.objects.create(name='BranchDish', description='d', main_category=bcat,
                                                  price=D('5000.00'), available_in_stock=50, station='kitchen')

    def _pickup_session(self):
        self.client.force_login(self.cust)
        s = self.client.session
        s['selected_restaurant_id'] = self.main.id
        s['order_type'] = 'pickup'
        s.save()

    def test_main_restaurant_cart_refuses_a_branch_product(self):
        self._pickup_session()
        add = lambda pid: self.client.post('/orders/cart/add/', json.dumps({'product_id': pid, 'quantity': 1}),
                                           content_type='application/json').json()
        self.assertFalse(add(self.branch_dish.id)['success'])
        self.assertTrue(add(self.pk_.id)['success'])

    def test_customer_care_only_handles_own_orders(self):
        mine = self.order([(self.pk_, 1)], by=self.cc)
        theirs = self.order([(self.pk_, 1)], by=self.cc2)
        self.assertEqual(self.pay(theirs, '100', user=self.cc).status_code, 403)
        self.assertEqual(self.pay(mine, '100', user=self.cc).status_code, 200)
        self.pay(theirs, '100', user=self.cashier)
        other_payment = Payment.objects.get(order=theirs)
        self.client.force_login(self.cc)
        self.assertEqual(self.client.get(f'/orders/customer-care/receipt/{other_payment.id}/').status_code, 404)

    def test_empty_json_cancel_reason_gets_the_default(self):
        o = self.order([(self.pk_, 1)], by=self.cust, otype='pickup', table=None, restaurant_owner=self.main)
        self.client.force_login(self.cust)
        self.client.post(f'/orders/customer-cancel/{o.id}/', json.dumps({'reason': ''}),
                         content_type='application/json')
        o.refresh_from_db()
        if o.status == 'cancelled':
            self.assertEqual(o.reason_if_cancelled, 'Cancelled by customer')

    def test_promotion_price_is_rounded_to_the_cent(self):
        from restaurant.models import HappyHourPromotion
        import datetime as _dt
        promo = HappyHourPromotion.objects.create(
            owner=self.main, name='Happy', discount_percentage=D('33'), is_active=True,
            days_of_week='1,2,3,4,5,6,7', start_time=_dt.time(0, 0), end_time=_dt.time(23, 59))
        promo.products.add(self.pk_)
        p = Product.objects.get(pk=self.pk_.pk)
        price = p.get_current_price()
        self.assertEqual(price, D('827.16'))                                 # 1234.56 x 0.67, to the cent
        self.assertEqual(price.as_tuple().exponent, -2)


class SecondReviewFixTests(Base):
    """Fixes from the independent review of the QA fixes."""

    def test_locked_get_survives_duplicate_join_rows_and_404s(self):
        from django.db.models import Q
        from django.http import Http404
        from restaurant_system.db_utils import locked_get
        o = self.order([(self.pk_, 1)])
        dup = Q(table_info__restaurant__main_owner=self.main) | Q(table_info__owner=self.main)
        self.assertEqual(locked_get(Order.objects.filter(dup), id=o.id), o)
        with self.assertRaises(Http404):
            locked_get(Order.objects.filter(dup), id=999999)

    def test_cancelling_a_delivered_order_keeps_stock_out(self):
        o = self.order([(self.pk_, 3)], otype='delivery', table=None, status='delivered',
                       restaurant_owner=self.main, delivery_phone='0712', delivery_address='x')
        self.client.force_login(self.manager)
        self.client.post(f'/orders/cancel-order/{o.id}/', json.dumps({'reason': 'customer_refused'}),
                         content_type='application/json')
        self.pk_.refresh_from_db()
        self.assertEqual(self.pk_.available_in_stock, 50)

    def test_app_payment_refuses_wasted_orders(self):
        from rest_framework.test import APIClient
        o = self.order([(self.pk_, 1)], status='wasted')
        api = APIClient()
        api.force_authenticate(self.cashier)
        r = api.post('/api/v1/payments/', {'order_id': o.id, 'amount': '100', 'payment_method': 'cash'},
                     format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Payment.objects.exists())

    def test_customer_care_cannot_open_other_staff_receipts_anywhere(self):
        theirs = self.order([(self.pk_, 1)], by=self.cc2)
        self.pay(theirs, '100', user=self.cashier)
        p = Payment.objects.get(order=theirs)
        self.client.force_login(self.cc)
        for url in (f'/cashier/receipt/{p.id}/', f'/cashier/reprint/{p.id}/', f'/orders/receipt/{theirs.id}/'):
            self.assertNotEqual(self.client.get(url).status_code, 200, url)


class PrintJobFixTests(Base):
    PATCH_PRINT = False

    def _job(self, **kw):
        from orders.models_printjob import PrintJob
        return PrintJob.objects.create(restaurant=self.main, job_type='receipt', content='x', **kw)

    def test_print_job_api_is_read_only_and_claims_atomically(self):
        job = self._job()
        self.client.force_login(self.kitchen)
        base = f'/orders/api/print-jobs/{job.id}/'
        self.assertEqual(self.client.patch(base, json.dumps({'content': 'PAID 0.00'}),
                                           content_type='application/json').status_code, 405)
        self.assertEqual(self.client.delete(base).status_code, 405)
        self.assertEqual(self.client.post(base + 'start_printing/', {'client_id': 'a'}).status_code, 200)
        self.assertEqual(self.client.post(base + 'start_printing/', {'client_id': 'b'}).status_code, 400)

    def test_stale_reset_counts_from_printing_start_and_error_text_kept(self):
        from django.utils import timezone
        from orders.models_printjob import PrintJob
        job = self._job()
        PrintJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - datetime.timedelta(hours=1))
        self.client.force_login(self.kitchen)
        self.client.post(f'/orders/api/print-jobs/{job.id}/start_printing/', {'client_id': 'a'})
        self.client.get('/orders/api/print-jobs/pending/')
        self.assertEqual(PrintJob.objects.get(pk=job.pk).status, 'printing')   # just picked up: not reset
        self.client.post(f'/orders/api/print-jobs/{job.id}/mark_failed/', {'error_message': 'Paper out'})
        self.assertEqual(PrintJob.objects.get(pk=job.pk).error_message, 'Paper out')

    def test_print_job_failure_never_loses_the_payment(self):
        o = self.order([(self.pk_, 1)])
        with mock.patch('orders.models_printjob.PrintJob.objects.create', side_effect=Exception('db')):
            r = self.pay(o, o.total_amount)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Payment.objects.filter(order=o).count(), 1)
