import datetime
import sys
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Feature, Role, RolePermissionSet, User
from inventory.models import InventoryItem, InventoryRecord, PurchaseOrder, Supplier, SupplierPayment
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class PurchasingTests(TestCase):
    def setUp(self):
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R', email='boss@main.test')
        self.manager = mk('mgr', 'manager', owner=self.main)
        self.cashier = mk('cash', 'cashier', owner=self.main)
        self.other = mk('oth', 'main_owner', restaurant_name='Other R')
        Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                  is_main_restaurant=True, qr_code='QRMAIN')
        self.rice = InventoryItem.objects.create(owner=self.main, name='Rice', unit='kg', unit_price=Decimal('2.50'))
        self.oil = InventoryItem.objects.create(owner=self.main, name='Oil', unit='L', unit_price=Decimal('4.00'))
        self.their_item = InventoryItem.objects.create(owner=self.other, name='Salt', unit='kg')
        self.sup = Supplier.objects.create(owner=self.main, name='Mama Mboga', phone='+255 712 345 678',
                                           email='mboga@supplier.test')
        self.their_sup = Supplier.objects.create(owner=self.other, name='Theirs')

    # ---------- helpers ----------
    def _login(self, user):
        self.client.force_login(user)

    def _create(self, user=None, lines=None, **extra):
        self._login(user or self.manager)
        lines = lines or [(self.rice.id, '10', '2.50'), (self.oil.id, '5', '4')]
        data = {'supplier_id': self.sup.id, 'order_date': timezone.localdate().isoformat(),
                'item_id': [l[0] for l in lines], 'quantity': [l[1] for l in lines],
                'unit_price': [l[2] for l in lines]}
        data.update(extra)
        return self.client.post('/inventory/purchase-orders/new/', data)

    def _act(self, order, action, **data):
        return self.client.post(f'/inventory/purchase-orders/{order.pk}/action/', {'action': action, **data})

    def _stock(self, item):
        return InventoryItem.objects.get(pk=item.pk).current_stock

    # ---------- suppliers ----------
    def test_supplier_add_edit_duplicate_and_scope(self):
        self._login(self.manager)
        self.client.post('/inventory/suppliers/', {'action': 'add', 'name': 'Kariakoo Wholesale', 'phone': '0755'})
        self.assertTrue(Supplier.objects.filter(owner=self.main, name='Kariakoo Wholesale').exists())
        self.client.post('/inventory/suppliers/', {'action': 'add', 'name': 'mama mboga'})       # duplicate (case)
        self.assertEqual(Supplier.objects.filter(owner=self.main).count(), 2)
        self.client.post('/inventory/suppliers/', {'action': 'add', 'name': 'X', 'email': 'not-an-email'})
        self.assertFalse(Supplier.objects.filter(name='X').exists())
        r = self.client.post('/inventory/suppliers/', {'action': 'edit', 'supplier_id': self.their_sup.id, 'name': 'Hacked'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Supplier.objects.get(pk=self.their_sup.pk).name, 'Theirs')
        page = self.client.get('/inventory/suppliers/').content.decode()
        self.assertIn('Mama Mboga', page)
        self.assertNotIn('Theirs', page)

    # ---------- orders ----------
    def test_create_order_numbers_and_totals(self):
        self._create()
        self._create()
        o1, o2 = PurchaseOrder.objects.order_by('number')
        self.assertEqual((o1.code, o2.code), ('PO-00001', 'PO-00002'))
        self.assertEqual(o1.ordered_total, Decimal('45.00'))
        self.assertEqual((o1.status, o1.payment_status, o1.amount_owed), ('draft', 'unpaid', Decimal('0.00')))
        # numbering is per restaurant
        self.other_sup_order = self._create(user=self.other, lines=[(self.their_item.id, '1', '1')],
                                            supplier_id=self.their_sup.id)
        self.assertEqual(PurchaseOrder.objects.get(owner=self.other).number, 1)

    def test_order_validation(self):
        bad = [
            dict(lines=[(self.their_item.id, '1', '1')]),                  # another restaurant's item
            dict(supplier_id=self.their_sup.id),                           # another restaurant's supplier
            dict(lines=[(self.rice.id, '0', '1')]),                        # zero quantity
            dict(lines=[(self.rice.id, '-3', '1')]),
            dict(lines=[(self.rice.id, 'abc', '1')]),
            dict(lines=[(self.rice.id, '1', '-1')]),
            dict(lines=[(self.rice.id, 'NaN', '1')]),
            dict(lines=[(self.rice.id, '1e20', '1')]),
            dict(lines=[('', '', '')]),                                    # no lines
            dict(expected_date='2000-01-01'),                              # before order date
            dict(order_date='31-12-2026'),
        ]
        for kw in bad:
            r = self._create(**kw)
            self.assertEqual(r.status_code, 200, kw)    # form shown again with the error
            self.assertFalse(PurchaseOrder.objects.exists(), kw)

    def test_edit_only_while_nothing_received(self):
        self._create()
        o = PurchaseOrder.objects.get()
        self._login(self.manager)
        self.client.post(f'/inventory/purchase-orders/{o.pk}/edit/', {
            'supplier_id': self.sup.id, 'item_id': [self.rice.id], 'quantity': ['20'], 'unit_price': ['3']})
        o.refresh_from_db()
        self.assertEqual(o.ordered_total, Decimal('60.00'))
        self._act(o, 'receive', **{f'recv_{o.lines.get().id}': '5'})
        r = self.client.post(f'/inventory/purchase-orders/{o.pk}/edit/', {
            'supplier_id': self.sup.id, 'item_id': [self.rice.id], 'quantity': ['1'], 'unit_price': ['1']})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PurchaseOrder.objects.get().ordered_total, Decimal('60.00'))

    # ---------- receiving ----------
    def test_partial_then_full_delivery_adds_stock_at_order_price(self):
        self._create()
        o = PurchaseOrder.objects.get()
        rice, oil = o.lines.order_by('id')
        self._act(o, 'receive', **{f'recv_{rice.id}': '4', 'note': 'Invoice 77'})
        o.refresh_from_db()
        self.assertEqual(o.status, 'partial')
        self.assertEqual(self._stock(self.rice), Decimal('4'))
        rec = InventoryRecord.objects.get()
        self.assertEqual((rec.record_type, rec.unit_price, rec.purchase_line_id), ('received', Decimal('2.50'), rice.id))
        self.assertIn('PO-00001 from Mama Mboga', rec.notes)
        self.assertIn('Invoice 77', rec.notes)

        self._act(o, 'receive', **{f'recv_{rice.id}': '7'})                     # more than still due
        self.assertEqual(self._stock(self.rice), Decimal('4'))
        self._act(o, 'receive', **{f'recv_{rice.id}': '6', f'recv_{oil.id}': '5'})
        o.refresh_from_db()
        self.assertEqual(o.status, 'received')
        self.assertEqual((self._stock(self.rice), self._stock(self.oil)), (Decimal('10'), Decimal('5')))
        self.assertEqual(o.received_total, Decimal('45.00'))
        self._act(o, 'receive', **{f'recv_{rice.id}': '1'})                     # finished order
        self.assertEqual(self._stock(self.rice), Decimal('10'))

    def test_receive_bad_input(self):
        self._create()
        o = PurchaseOrder.objects.get()
        line = o.lines.first()
        for value in ('-1', 'abc', '', '0'):
            self._act(o, 'receive', **{f'recv_{line.id}': value})
        self.assertFalse(InventoryRecord.objects.exists())
        self.assertEqual(self._act(o, 'receive', **{'recv_abc': '1'}).status_code, 404)
        self.assertFalse(InventoryRecord.objects.exists())

    def test_close_and_cancel_rules(self):
        self._create()
        o = PurchaseOrder.objects.get()
        self._act(o, 'close')                                                   # not partial yet
        self.assertEqual(PurchaseOrder.objects.get().status, 'draft')
        self._act(o, 'receive', **{f'recv_{o.lines.first().id}': '1'})
        self._act(o, 'cancel')                                                  # something received
        self.assertEqual(PurchaseOrder.objects.get().status, 'partial')
        self._act(o, 'close')
        self.assertEqual(PurchaseOrder.objects.get().status, 'closed')
        self._create()
        o2 = PurchaseOrder.objects.get(number=2)
        self._act(o2, 'pay', amount='10')
        self._act(o2, 'cancel')                                                 # has payments
        self.assertEqual(PurchaseOrder.objects.get(pk=o2.pk).status, 'draft')
        self._act(o2, 'delete_payment', payment_id=SupplierPayment.objects.get().id)
        self._act(o2, 'cancel')
        self.assertEqual(PurchaseOrder.objects.get(pk=o2.pk).status, 'cancelled')

    # ---------- payments ----------
    def test_payments_and_amount_owed(self):
        self._create()
        o = PurchaseOrder.objects.get()
        self._act(o, 'receive', **{f'recv_{o.lines.order_by("id").first().id}': '10'})   # 25.00 delivered
        o = PurchaseOrder.objects.get()
        self.assertEqual((o.amount_owed, o.payment_status), (Decimal('25.00'), 'unpaid'))
        self._act(o, 'pay', amount='10', method='mobile_money', reference='MP123')
        o = PurchaseOrder.objects.get()
        self.assertEqual((o.amount_owed, o.payment_status), (Decimal('15.00'), 'partly_paid'))
        self._act(o, 'pay', amount='15')
        o = PurchaseOrder.objects.get()
        self.assertEqual((o.amount_owed, o.payment_status), (Decimal('0.00'), 'paid'))
        self._act(o, 'pay', amount='100')                                       # more than order total
        self._act(o, 'pay', amount='-5')
        self._act(o, 'pay', amount='5', method='bitcoin')
        future = (timezone.localdate() + datetime.timedelta(days=3)).isoformat()
        self._act(o, 'pay', amount='5', paid_on=future)
        self.assertEqual(SupplierPayment.objects.count(), 2)
        page = self.client.get('/inventory/purchase-orders/').content.decode()
        self.assertIn('PO-00001', page)

    # ---------- sending ----------
    def test_pdf_share_text_and_whatsapp(self):
        self._create(notes='Deliver to back door <b>')
        o = PurchaseOrder.objects.get()
        r = self.client.get(f'/inventory/purchase-orders/{o.pk}/pdf/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        page = self.client.get(f'/inventory/purchase-orders/{o.pk}/').content.decode()
        self.assertIn('Rice: 10 kg', page)
        self.assertIn('Total:', page)
        self.assertIn('&lt;b&gt;', page)          # notes are escaped

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_sends_pdf_and_marks_sent(self):
        self._create()
        o = PurchaseOrder.objects.get()
        self._act(o, 'email')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['mboga@supplier.test'])
        self.assertEqual(mail.outbox[0].attachments[0][0], 'PO-00001.pdf')
        self.assertEqual(PurchaseOrder.objects.get().status, 'sent')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST_USER='',
                       EMAIL_HOST_PASSWORD='')
    def test_email_not_configured_or_no_address(self):
        self._create()
        o = PurchaseOrder.objects.get()
        self._act(o, 'email')
        self.assertEqual(PurchaseOrder.objects.get().status, 'draft')
        Supplier.objects.filter(pk=self.sup.pk).update(email='')
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self._act(o, 'email')
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_failure_is_reported_not_crashed(self):
        self._create()
        o = PurchaseOrder.objects.get()
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=OSError('smtp down')):
            r = self._act(o, 'email')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PurchaseOrder.objects.get().status, 'draft')

    # ---------- permissions ----------
    def test_permissions_and_scope(self):
        self._create()
        o = PurchaseOrder.objects.get()
        self._login(self.other)                               # another restaurant
        self.assertEqual(self.client.get(f'/inventory/purchase-orders/{o.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'/inventory/purchase-orders/{o.pk}/pdf/').status_code, 404)
        self.assertEqual(self._act(o, 'pay', amount='5').status_code, 404)
        self._login(self.cashier)                             # not an inventory role
        self.assertEqual(self.client.get('/inventory/purchase-orders/').status_code, 302)
        self._act(o, 'pay', amount='5')
        self.assertFalse(SupplierPayment.objects.exists())

        rps = RolePermissionSet.objects.create(owner=self.main, role_name='manager')
        rps.features.set([Feature.objects.get_or_create(slug='view_inventory', defaults={'name': 'View Inventory'})[0]])
        self._login(self.manager)                             # view-only manager
        self.assertEqual(self.client.get(f'/inventory/purchase-orders/{o.pk}/').status_code, 200)
        self.assertNotIn('Record payment', self.client.get(f'/inventory/purchase-orders/{o.pk}/').content.decode())
        self.assertEqual(self.client.get('/inventory/purchase-orders/new/').status_code, 302)
        self._act(o, 'pay', amount='5')
        self.client.post('/inventory/suppliers/', {'action': 'add', 'name': 'Sneaky'})
        self.assertFalse(SupplierPayment.objects.exists())
        self.assertFalse(Supplier.objects.filter(name='Sneaky').exists())

    # ---------- review fixes ----------
    def test_item_on_order_cannot_be_deleted_but_owner_can(self):
        self._create()
        r = self.client.post('/inventory/items/', {'action': 'delete', 'item_id': self.rice.id})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['success'])
        self.assertTrue(InventoryItem.objects.filter(pk=self.rice.pk).exists())
        # Removing a (branch) owner account takes its purchasing data with it instead of being blocked
        self._create(user=self.other, lines=[(self.their_item.id, '1', '1')], supplier_id=self.their_sup.id)
        from accounts.models import RestaurantSubscription, SubscriptionLog
        SubscriptionLog.objects.filter(subscription__restaurant_owner=self.other).delete()
        RestaurantSubscription.objects.filter(restaurant_owner=self.other).delete()
        self.other.delete()
        self.assertFalse(PurchaseOrder.objects.filter(owner_id=self.other.id).exists())
        self.assertFalse(Supplier.objects.filter(pk=self.their_sup.pk).exists())
        self.assertTrue(PurchaseOrder.objects.filter(owner=self.main).exists())

    def test_cannot_edit_total_below_payments(self):
        self._create()
        o = PurchaseOrder.objects.get()
        self._act(o, 'pay', amount='45')
        self.assertEqual(PurchaseOrder.objects.get().payment_status, 'paid')     # prepaid in full
        self.client.post(f'/inventory/purchase-orders/{o.pk}/edit/', {
            'supplier_id': self.sup.id, 'item_id': [self.rice.id], 'quantity': ['2'], 'unit_price': ['1']})
        self.assertEqual(PurchaseOrder.objects.get().ordered_total, Decimal('45.00'))

    def test_closed_order_pays_only_delivered_value_and_shows_credit(self):
        self._create()
        o = PurchaseOrder.objects.get()
        self._act(o, 'pay', amount='45')                                          # prepaid
        self._act(o, 'receive', **{f'recv_{o.lines.order_by("id").first().id}': '10'})   # 25 delivered
        self._act(o, 'close')
        o = PurchaseOrder.objects.get()
        self.assertEqual((o.status, o.amount_owed, o.supplier_credit, o.payment_status),
                         ('closed', Decimal('0.00'), Decimal('20.00'), 'paid'))
        self.assertIn('Supplier owes us back', self.client.get(f'/inventory/purchase-orders/{o.pk}/').content.decode())
        self._act(o, 'pay', amount='1')                                           # nothing more is payable
        self.assertEqual(SupplierPayment.objects.count(), 1)

    def test_tiny_amounts_round_to_zero_and_are_refused(self):
        self.assertEqual(self._create(lines=[(self.rice.id, '0.001', '1')]).status_code, 200)
        self.assertFalse(PurchaseOrder.objects.exists())
        self._create()
        o = PurchaseOrder.objects.get()
        self._act(o, 'pay', amount='0.001')
        self.assertFalse(SupplierPayment.objects.exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_uses_short_timeout(self):
        self._create()
        o = PurchaseOrder.objects.get()
        with mock.patch('django.core.mail.get_connection', wraps=mail.get_connection) as conn:
            self._act(o, 'email')
        self.assertEqual(conn.call_args.kwargs.get('timeout'), 15)
        self.assertEqual(len(mail.outbox), 1)

    def test_list_filters_and_bad_params(self):
        self._create()
        self._login(self.manager)
        for qs in ('?status=open', '?status=junk', '?supplier=abc', '?supplier=999', '?payment=unpaid', '?payment=x'):
            self.assertEqual(self.client.get('/inventory/purchase-orders/' + qs).status_code, 200, qs)
        self.assertEqual(self.client.get('/inventory/purchase-orders/999/').status_code, 404)
