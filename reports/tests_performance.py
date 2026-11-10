"""Query-count guards for the heavy pages (review 2026-11: N+1 and unbounded lists).

Each test renders a page with a few rows, adds many more rows, and checks that the
number of SQL queries stays the same (it must not grow with the row count) and under
a fixed upper bound. Plus: PDF row cap, streamed CSV content, and the kitchen
dashboard's local-day boundary.
"""
import csv
import datetime
import io
import sys
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Role, RestaurantSubscription, User
from cashier.models import Payment
from orders.models import Order, OrderItem
from restaurant.models import MainCategory, Product, SubCategory, TableInfo
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class PerfBase(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        p = mock.patch('orders.push.send_push')
        p.start()
        self.addCleanup(p.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.admin = mk('sysadm', 'administrator')
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.cashiers = [mk(f'cash{i}', 'cashier', owner=self.main, first_name=f'C{i}') for i in range(3)]
        self.cashier = self.cashiers[0]
        self.kitchen = mk('kit', 'kitchen', owner=self.main)
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main,
                                           branch_owner=self.main, is_main_restaurant=True, qr_code='QRPERF')
        today = datetime.date.today()
        RestaurantSubscription.objects.get_or_create(restaurant_owner=self.main, defaults={
            'subscription_start_date': today - datetime.timedelta(days=1),
            'subscription_end_date': today + datetime.timedelta(days=30)})
        self.cats, self.products = [], []
        for c in range(4):
            cat = MainCategory.objects.create(restaurant=self.r, owner=self.main, name=f'Cat{c}')
            sub = SubCategory.objects.create(main_category=cat, name=f'Sub{c}')
            self.cats.append(cat)
            for j, st in enumerate(('kitchen', 'bar', 'kitchen')):
                self.products.append(Product.objects.create(
                    name=f'P{c}{j}', description='', main_category=cat, sub_category=sub,
                    price=Decimal('100') + j, station=st))
        self.tables = [TableInfo.objects.create(restaurant=self.r, owner=self.main, tbl_no=f'T{i}', capacity=4)
                       for i in range(6)]
        self._n = 0

    def make_orders(self, n, *, at=None, status='pending', by=None, pay=True):
        """n orders today (or at `at`), 3 items each, half of them paid in cash."""
        made = []
        for _ in range(n):
            self._n += 1
            i = self._n
            staff = by or self.cashiers[i % len(self.cashiers)]
            o = Order.objects.create(order_number=f'PF{i:05d}', table_info=self.tables[i % len(self.tables)],
                                     ordered_by=staff, status=status, total_amount=Decimal('0'))
            total = Decimal('0')
            for k in range(3):
                prod = self.products[(i + k) % len(self.products)]
                OrderItem.objects.create(order=o, product=prod, quantity=1 + k % 2, unit_price=prod.price)
                total += prod.price * (1 + k % 2)
            total = (total * Decimal('1.16')).quantize(Decimal('0.01'))
            fields = {'total_amount': total}
            if pay and i % 2 == 0:
                Payment.objects.create(order=o, amount=total, payment_method='cash', processed_by=staff)
                fields['payment_status'] = 'paid'
            if at is not None:
                fields['created_at'] = at
            Order.objects.filter(pk=o.pk).update(**fields)
            made.append(o)
        return made

    def queries_for(self, client, url, **params):
        with CaptureQueriesContext(connection) as cq:
            r = client.get(url, params)
            if getattr(r, 'streaming', False):
                b''.join(r.streaming_content)
        self.assertIn(r.status_code, (200,), f'{url}: {r.status_code} {r.get("Location")}')
        return len(cq)

    def assert_flat(self, user, url, bound, small=5, big=40, **params):
        """Query count with `small` rows == with `big` rows, and <= bound."""
        c = self.client_class()
        c.force_login(user)
        self.make_orders(small)
        c.get(url, params)  # warm per-process caches (content types, features...)
        n_small = self.queries_for(c, url, **params)
        self.make_orders(big - small)
        n_big = self.queries_for(c, url, **params)
        self.assertEqual(n_small, n_big, f'{url}: {n_small} queries with {small} orders, {n_big} with {big}')
        self.assertLessEqual(n_big, bound, f'{url}: {n_big} queries')
        return n_big


class QueryCountTests(PerfBase):
    def test_system_admin_all_orders(self):
        self.assert_flat(self.admin, '/system-admin/orders/', bound=25, big=60)

    def test_cashier_my_orders(self):
        # all orders by one cashier so every row is on the page
        c = self.client_class()
        c.force_login(self.cashier)
        self.make_orders(3, by=self.cashier)
        c.get('/cashier/my-orders/')
        n_small = self.queries_for(c, '/cashier/my-orders/')
        self.make_orders(40, by=self.cashier)
        n_big = self.queries_for(c, '/cashier/my-orders/')
        self.assertEqual(n_small, n_big)
        self.assertLessEqual(n_big, 30)

    def test_cashier_dashboard(self):
        self.assert_flat(self.cashier, '/cashier/', bound=40)

    def test_kitchen_dashboard(self):
        self.assert_flat(self.kitchen, '/orders/kitchen/', bound=45)

    def test_reports_dashboard(self):
        self.assert_flat(self.main, '/reports/', bound=70, period='today')

    def test_csv_export_50_vs_200_orders(self):
        c = self.client_class()
        c.force_login(self.main)
        self.make_orders(50)
        c.get('/reports/export/', {'period': 'today'}).content
        n50 = self.queries_for(c, '/reports/export/', period='today')
        self.make_orders(150)
        n200 = self.queries_for(c, '/reports/export/', period='today')
        self.assertEqual(n50, n200)
        self.assertLessEqual(n200, 45)


class ExportTests(PerfBase):
    def test_pdf_caps_detail_rows_but_totals_cover_all(self):
        from reports import views as rviews
        orders = self.make_orders(7)
        tables, paragraphs = [], []
        real_table, real_par = rviews.Table, rviews.Paragraph

        def _table(data, *a, **k):
            tables.append(data)
            return real_table(data, *a, **k)

        def _par(text, *a, **k):
            paragraphs.append(str(text))
            return real_par(text, *a, **k)

        self.client.force_login(self.main)
        with mock.patch.object(rviews, 'PDF_MAX_ORDER_ROWS', 3), \
                mock.patch.object(rviews, 'Table', _table), mock.patch.object(rviews, 'Paragraph', _par):
            r = self.client.get('/reports/export-pdf/', {'period': 'today'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        detail = [t for t in tables if t and t[0] and t[0][0] == 'Order #'][0]
        self.assertEqual(len(detail) - 1, 3)                       # capped
        newest = sorted(orders, key=lambda o: Order.objects.get(pk=o.pk).created_at, reverse=True)[:3]
        self.assertEqual([row[0] for row in detail[1:]], [o.order_number for o in newest])
        summary = [t for t in tables if t and t[0] and t[0][0] == 'Revenue:'][0]
        self.assertEqual(dict((row[0], row[1]) for row in summary)['Total Orders:'], '7')   # all orders
        self.assertTrue(any('3 of 7 orders' in p and 'CSV' in p for p in paragraphs), paragraphs)

    def test_pdf_has_no_note_under_the_cap(self):
        from reports import views as rviews
        self.make_orders(3)
        paragraphs = []
        real_par = rviews.Paragraph

        def _par(text, *a, **k):
            paragraphs.append(str(text))
            return real_par(text, *a, **k)

        self.client.force_login(self.main)
        with mock.patch.object(rviews, 'Paragraph', _par):
            self.client.get('/reports/export-pdf/', {'period': 'today'})
        self.assertFalse(any('CSV export' in p for p in paragraphs))

    def test_csv_is_streamed_and_complete(self):
        from reports import views as rviews
        made = self.make_orders(9)
        # formula injection in names
        self.cashiers[1].first_name = '=HYPERLINK("x")'
        self.cashiers[1].save()
        self.client.force_login(self.main)
        with mock.patch.object(rviews, 'CSV_CHUNK_SIZE', 2):     # several chunks
            r = self.client.get('/reports/export/', {'period': 'today'})
            self.assertTrue(r.streaming)
            streamed = b''.join(r.streaming_content).decode()
            r2 = self.client.get('/reports/export/', {'period': 'today'})
            whole = r2.content.decode()                            # .content still works
        drop_ts = lambda t: '\n'.join(l for l in t.replace('\r\n', '\n').split('\n') if not l.startswith('Generated on:'))
        self.assertEqual(drop_ts(streamed), drop_ts(whole))
        rows = list(csv.reader(io.StringIO(streamed)))
        hdr = next(i for i, row in enumerate(rows) if row and row[0] == 'Order ID')
        detail = [row for row in rows[hdr + 1:] if row]
        expected = Order.objects.filter(pk__in=[o.pk for o in made]).order_by('-created_at')
        self.assertEqual([row[0] for row in detail], [o.order_number for o in expected])
        self.assertEqual([row[9] for row in detail], [f'${o.total_amount:.2f}' for o in expected])
        self.assertIn(['Total Orders:', '9'], rows)
        # names starting with '=' are neutralised; '-' placeholders are kept
        injected = [row for row in detail if 'HYPERLINK' in row[1]]
        self.assertTrue(injected)
        for row in injected:
            self.assertTrue(row[1].startswith('\t='), row[1])
            self.assertTrue(row[13].startswith('\t='), row[13])
        self.assertTrue(any(row[14] == '-' for row in detail))     # unpaid orders: no "Paid By"


class KitchenDayRangeTests(PerfBase):
    def test_local_day_boundary(self):
        from orders.views import _local_day_range
        local_now = timezone.localtime(timezone.now())
        midnight = timezone.make_aware(datetime.datetime.combine(local_now.date(), datetime.time.min))
        start, end = _local_day_range()
        self.assertEqual(start, midnight)
        self.assertEqual(end, timezone.make_aware(datetime.datetime.combine(
            local_now.date() + datetime.timedelta(days=1), datetime.time.min)))

        late_yesterday = self.make_orders(1, at=midnight - datetime.timedelta(minutes=1))[0]
        early_today = self.make_orders(1, at=midnight + datetime.timedelta(minutes=1))[0]
        exact_midnight = self.make_orders(1, at=midnight)[0]
        # same rows as the old created_at__date=today filter
        old = set(Order.objects.filter(created_at__date=local_now.date()).values_list('pk', flat=True))
        new = set(Order.objects.filter(created_at__gte=start, created_at__lt=end).values_list('pk', flat=True))
        self.assertEqual(old, new)

        self.client.force_login(self.kitchen)
        r = self.client.get('/orders/kitchen/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn(late_yesterday.order_number, body)     # 23:59 yesterday (local)
        self.assertIn(early_today.order_number, body)           # 00:01 today (local)
        self.assertIn(exact_midnight.order_number, body)


class WebSocketOnCommitTests(PerfBase):
    def test_kitchen_notification_waits_for_commit(self):
        """group_send runs only after the transaction commits (not while rows are locked)."""
        from orders import views as oviews
        sent = []
        with mock.patch.object(oviews, 'get_channel_layer') as gcl, \
                mock.patch.object(oviews, 'async_to_sync', lambda f: (lambda *a, **k: sent.append(a))):
            gcl.return_value = mock.Mock()
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                oviews._ws_send_on_commit('restaurant_1', {'type': 'new_order'})
                self.assertEqual(sent, [])            # nothing sent inside the transaction
            self.assertEqual(len(callbacks), 1)
        self.assertEqual(sent, [('restaurant_1', {'type': 'new_order'})])

    def test_send_failure_never_raises(self):
        from orders import views as oviews
        with mock.patch.object(oviews, 'get_channel_layer', side_effect=RuntimeError('redis down')):
            with self.captureOnCommitCallbacks(execute=True):
                oviews._ws_send_on_commit('restaurant_1', {'type': 'new_order'})   # no exception


class MyOrdersPeriodTests(PerfBase):
    def test_default_today_and_pagination(self):
        old = timezone.now() - datetime.timedelta(days=3)
        old_order = self.make_orders(1, at=old, by=self.cashier)[0]
        self.make_orders(55, by=self.cashier)
        self.client.force_login(self.cashier)
        body = self.client.get('/cashier/my-orders/').content.decode()
        self.assertNotIn(old_order.order_number, body)              # default: today only
        self.assertIn('1 / 2', body)                                # 55 today -> 2 pages of 50
        body = self.client.get('/cashier/my-orders/', {'period': '7d', 'page': 2}).content.decode()
        self.assertIn(old_order.order_number, body)                 # oldest is on the last page


class VisibleFeaturesCacheTests(PerfBase):
    def test_computed_once_per_instance(self):
        u = User.objects.get(pk=self.cashier.pk)
        first = u.visible_features
        with self.assertNumQueries(0):
            self.assertEqual(u.visible_features, first)
        self.assertIn('cancel_orders', first)


class SysadminOrdersFilterTests(PerfBase):
    def test_period_default_and_filters_kept_across_pages(self):
        old = self.make_orders(1, at=timezone.now() - datetime.timedelta(days=10))[0]
        self.make_orders(55)
        self.client.force_login(self.admin)
        body = self.client.get('/system-admin/orders/').content.decode()
        self.assertNotIn(old.order_number, body)                    # default: last 7 days
        self.assertIn('Orders (55)', body)
        body = self.client.get('/system-admin/orders/', {'status': 'pending', 'period': '30d'}).content.decode()
        self.assertIn('Orders (56)', body)
        self.assertIn('status=pending&amp;restaurant=all&amp;period=30d&amp;page=2', body)


class PaymentReferenceCapTests(PerfBase):
    def test_long_reference_number_is_capped_not_a_500(self):
        import json
        o = self.make_orders(1, by=self.cashier, pay=False)[0]
        o.refresh_from_db()
        self.client.force_login(self.cashier)
        r = self.client.post(f'/cashier/process-payment/{o.id}/', json.dumps({
            'amount': str(o.total_amount), 'payment_method': 'card',
            'reference_number': 'R' * 80, 'notes': '<b>hi</b>'}), content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        p = Payment.objects.get(order=o)
        self.assertEqual(p.reference_number, 'R' * 50)
        self.assertNotIn('<b>', p.notes or '')
