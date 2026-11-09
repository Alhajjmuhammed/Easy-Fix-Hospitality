"""
Offline / online regression tests for the mobile API:
add-items idempotency (client_id), payment offline_id replay, offline payments capped
after a price change at sync, sync batch limits, old payloads still accepted, and the
station cancel re-check under the row lock.

Run:  python manage.py test mobile_api.tests_offline
"""
import sys
from decimal import Decimal
from unittest import mock

import django.test.client as _dtc

from cashier.models import Payment
from orders.models import Order, OrderItem
from mobile_api.tests_qa_fixes import Base

if sys.version_info >= (3, 14):
    # Django 4.2's test client crashes copying template contexts on Python 3.14.
    _dtc.store_rendered_templates = lambda *a, **k: None


def app_order(offline_id, table_id, items, **kw):
    """Same shape as useSyncStore's payload.orders[]."""
    d = {
        'offline_id': offline_id, 'existing_order_id': None, 'local_print': False,
        'table_id': table_id, 'items': items, 'special_instructions': '',
        'restaurant_id': None, 'order_type': 'dine-in', 'delivery_address': '',
        'delivery_phone': '', 'delivery_lat': None, 'delivery_lng': None,
    }
    d.update(kw)
    return d


def app_payment(offline_id, order_id, amount):
    return {'offline_id': offline_id, 'order_id': order_id, 'amount': amount,
            'payment_method': 'cash', 'reference_number': '', 'notes': ''}


class StationCancelLockTests(Base):
    """The station check must be repeated under the row lock: the order may have moved on
    (cashier assigned a rider → out_for_delivery) after the station loaded it."""

    def test_station_cancel_refused_when_order_left_the_kitchen_meanwhile(self):
        o = self.place_ok(self.cashier, {'order_type': 'delivery', 'items': [self.item()],
                                         'delivery_address': 'x', 'delivery_phone': '0712'})
        Order.objects.filter(pk=o.pk).update(status='ready')
        stale = Order.objects.get(pk=o.pk)                      # what the station saw
        Order.objects.filter(pk=o.pk).update(status='out_for_delivery')  # rider assigned meanwhile
        with mock.patch('mobile_api.views.orders.get_object_or_404', return_value=stale):
            r = self.api(self.kitchen).post(f'/api/v1/orders/{o.id}/cancel/', {'reason': 'no rice'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        o.refresh_from_db()
        self.assertEqual(o.status, 'out_for_delivery')

    def test_station_cancel_still_works_for_kitchen_order(self):
        o = self.dinein()
        r = self.api(self.kitchen).post(f'/api/v1/orders/{o.id}/cancel/', {'reason': 'no rice'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.status, 'cancelled')

    def test_station_cannot_cancel_order_without_its_items(self):
        o = self.dinein(items=[self.item(self.drink)])
        r = self.api(self.kitchen).post(f'/api/v1/orders/{o.id}/cancel/', {'reason': 'x'}, format='json')
        self.assertIn(r.status_code, (400, 403))
        o.refresh_from_db()
        self.assertEqual(o.status, 'pending')


class AddItemsIdempotencyTests(Base):
    """MEDIUM 4: add-items accepts a client_id; a replay (online retry or the queued
    append synced with the same id) adds nothing twice."""

    def add(self, order, items, **extra):
        return self.api(self.cashier).post(f'/api/v1/orders/{order.id}/add-items/',
                                           {'items': items, **extra}, format='json')

    def test_same_client_id_twice_adds_once(self):
        o = self.dinein()
        r1 = self.add(o, [self.item(self.drink, 2)], client_id='chk-add-1')
        self.assertEqual(r1.status_code, 200, r1.content)
        total_after_first = Order.objects.get(pk=o.pk).total_amount
        r2 = self.add(o, [self.item(self.drink, 2)], client_id='chk-add-1')
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertTrue(r2.json()['already_applied'])
        self.assertEqual(r2.json()['order']['id'], o.id)
        o.refresh_from_db()
        self.assertEqual(o.order_items.count(), 2)
        self.assertEqual(o.total_amount, total_after_first)
        self.drink.refresh_from_db()
        self.assertEqual(self.drink.available_in_stock, 48)       # taken once

    def test_queued_append_with_same_id_is_duplicate_at_sync(self):
        o = self.dinein()
        self.assertEqual(self.add(o, [self.item(self.drink)], client_id='chk-add-2').status_code, 200)
        res = self.sync(self.cashier, {'orders': [app_order('chk-add-2', self.tM.id, [self.item(self.drink)],
                                                            existing_order_id=o.id)]})
        self.assertEqual(res['orders'][0]['status'], 'duplicate')
        self.assertEqual(o.order_items.count(), 2)

    def test_replay_after_order_was_paid_returns_earlier_result(self):
        o = self.dinein()
        self.assertEqual(self.add(o, [self.item(self.drink)], client_id='chk-add-3').status_code, 200)
        o.refresh_from_db()
        self.assertEqual(self.pay(o, o.total_amount).status_code, 201)
        r = self.add(o, [self.item(self.drink)], client_id='chk-add-3')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['already_applied'])
        self.assertEqual(o.order_items.count(), 2)

    def test_old_payload_without_client_id_still_adds(self):
        o = self.dinein()
        self.assertEqual(self.add(o, [self.item(self.drink)]).status_code, 200)
        self.assertEqual(self.add(o, [self.item(self.drink)]).status_code, 200)
        self.assertEqual(o.order_items.count(), 3)
        self.assertNotIn('offline-append', Order.objects.get(pk=o.pk).special_instructions)


class PaymentReplayTests(Base):
    """MEDIUM 4: the app now sends offline_id on POST /payments/; a replay (online retry
    or the queued copy synced with the same id) returns the earlier payment."""

    def post_pay(self, order, amount, **extra):
        return self.api(self.cashier).post('/api/v1/payments/', {
            'order_id': order.id, 'amount': str(amount), 'payment_method': 'cash', **extra}, format='json')

    def test_online_replay_returns_earlier_payment_not_400(self):
        o = self.dinein()
        r1 = self.post_pay(o, o.total_amount, offline_id='pay-1')
        self.assertEqual(r1.status_code, 201, r1.content)
        r2 = self.post_pay(o, o.total_amount, offline_id='pay-1')       # full amount again
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertTrue(r2.json()['already_synced'])
        self.assertEqual(r2.json()['payment']['id'], r1.json()['payment']['id'])
        self.assertEqual(Payment.objects.filter(order=o).count(), 1)

    def test_queued_copy_with_same_id_is_duplicate_at_sync(self):
        o = self.dinein()
        self.assertEqual(self.post_pay(o, o.total_amount, offline_id='pay-2').status_code, 201)
        res = self.sync(self.cashier, {'payments': [app_payment('pay-2', o.id, float(o.total_amount))]})
        self.assertEqual(res['payments'][0]['status'], 'duplicate')
        self.assertEqual(Payment.objects.filter(order=o).count(), 1)

    def test_online_overpayment_still_refused_even_with_offline_id(self):
        o = self.dinein()
        r = self.post_pay(o, o.total_amount + 1, offline_id='pay-3')
        self.assertEqual(r.status_code, 400)
        self.assertIn('exceeds remaining balance', r.json()['error'])
        self.assertEqual(Payment.objects.filter(order=o).count(), 0)

    def test_old_payload_without_offline_id_still_works(self):
        o = self.dinein()
        self.assertEqual(self.pay(o, o.total_amount).status_code, 201)
        o.refresh_from_db()
        self.assertEqual(o.payment_status, 'paid')


class PriceChangeAtSyncTests(Base):
    """MEDIUM 5: server prices win; an offline payment that no longer fits the order total
    is recorded capped with a note and a warning instead of failing on every sync."""

    def test_price_drop_offline_full_payment_is_capped_with_note(self):
        self.food.price = Decimal('4500.00')            # client still had 5000 → 5900 incl. 18% tax
        self.food.save()
        res = self.sync(self.cashier, {'orders': [app_order('o-drop', self.tM.id, [self.item(q=1) | {'price': 5000.0}])]})
        r = res['orders'][0]
        self.assertEqual(r['status'], 'created')
        self.assertEqual(Decimal(r['total_amount']), Decimal('5310.00'))
        self.assertEqual(len(r['price_changes']), 1)
        self.assertIn('price', r['warning'])

        res2 = self.sync(self.cashier, {'payments': [app_payment('p-drop', r['order_id'], 5900.0)]})
        p = res2['payments'][0]
        self.assertEqual(p['status'], 'created', p)
        self.assertEqual(Decimal(p['amount_recorded']), Decimal('5310.00'))
        self.assertEqual(Decimal(p['difference']), Decimal('590.00'))
        self.assertIn('Check the order before settling', p['warning'])
        self.assertIn('recorded as 5310.00', p['warning'])
        pay = Payment.objects.get(pk=p['payment_id'])
        self.assertEqual(pay.amount, Decimal('5310.00'))
        self.assertIn('[offline:p-drop]', pay.notes)
        self.assertIn('Offline payment 5900', pay.notes)
        self.assertIn('590', pay.notes)
        o = Order.objects.get(pk=r['order_id'])
        self.assertEqual(o.payment_status, 'paid')
        # replay of the capped payment: duplicate, nothing recorded twice
        res3 = self.sync(self.cashier, {'payments': [app_payment('p-drop', r['order_id'], 5900.0)]})
        self.assertEqual(res3['payments'][0]['status'], 'duplicate')
        self.assertEqual(Payment.objects.filter(order=o).count(), 1)

    def test_price_rise_reports_change_and_new_total(self):
        self.food.price = Decimal('5500.00')
        self.food.save()
        res = self.sync(self.cashier, {'orders': [app_order('o-rise', self.tM.id, [self.item(q=1) | {'price': 5000.0}])]})
        r = res['orders'][0]
        self.assertEqual(Decimal(r['total_amount']), Decimal('6490.00'))
        self.assertEqual(r['price_changes'][0]['server_price'], 5500.0)
        res2 = self.sync(self.cashier, {'payments': [app_payment('p-rise', r['order_id'], 5900.0)]})
        self.assertEqual(res2['payments'][0]['status'], 'created')
        self.assertNotIn('warning', res2['payments'][0])       # fits: no cap
        self.assertEqual(Order.objects.get(pk=r['order_id']).payment_status, 'partial')

    def test_no_warning_when_prices_unchanged(self):
        res = self.sync(self.cashier, {'orders': [app_order('o-same', self.tM.id, [self.item(q=1)])]})
        self.assertNotIn('warning', res['orders'][0])
        self.assertNotIn('price_changes', res['orders'][0])

    def test_offline_payment_on_order_already_paid_is_still_refused(self):
        o = self.dinein()
        self.assertEqual(self.pay(o, o.total_amount).status_code, 201)
        res = self.sync(self.cashier, {'payments': [app_payment('p-paid', o.id, float(o.total_amount))]})
        self.assertEqual(res['payments'][0]['status'], 'error')
        self.assertEqual(Payment.objects.filter(order=o).count(), 1)

    def test_sync_payment_without_offline_id_keeps_strict_check(self):
        o = self.dinein()
        body = app_payment('', o.id, float(o.total_amount) + 10)
        res = self.sync(self.cashier, {'payments': [body]})
        self.assertEqual(res['payments'][0]['status'], 'error')
        self.assertEqual(Payment.objects.filter(order=o).count(), 0)

    def test_offline_append_reports_unavailable_item(self):
        o = self.dinein()
        self.drink.is_available = False
        self.drink.save()
        res = self.sync(self.cashier, {'orders': [app_order('o-app', self.tM.id,
                                                            [self.item(q=1), self.item(self.drink, 1)],
                                                            existing_order_id=o.id)]})
        r = res['orders'][0]
        self.assertEqual(r['status'], 'created')
        self.assertEqual(r['dropped_item_ids'], [self.drink.id])
        self.assertIn('unavailable', r['warning'])


class SyncBatchLimitTests(Base):
    """HIGH 2: the app pushes in chunks within these limits; each full chunk is accepted."""

    def test_full_chunks_are_accepted(self):
        orders = [app_order(f'lim-{i}', self.tM.id, [self.item()]) for i in range(50)]
        res = self.sync(self.cashier, {'orders': orders, 'payments': [], 'bill_requests': []})
        self.assertEqual(len(res['orders']), 50)
        self.assertTrue(all(r['status'] == 'created' for r in res['orders']))

        o = self.dinein(table=self.tM2)
        payments = [app_payment(f'limp-{i}', o.id, 1.0) for i in range(100)]
        bills = [{'offline_id': f'limb-{i}', 'table_id': self.tM2.id} for i in range(20)]
        res = self.sync(self.cashier, {'orders': [], 'payments': payments, 'bill_requests': bills})
        self.assertEqual(sum(r['status'] == 'created' for r in res['payments']), 100)
        self.assertEqual(len(res['bill_requests']), 20)

    def test_over_the_limit_is_refused_whole(self):
        orders = [app_order(f'big-{i}', self.tM.id, [self.item()]) for i in range(51)]
        r = self.api(self.cashier).post('/api/v1/sync/push/', {'orders': orders}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_old_app_payload_shape_still_accepted(self):
        # Older builds: no prices in items, no client totals, payments without notes.
        res = self.sync(self.cashier, {'orders': [{'offline_id': 'old-1', 'table_id': self.tM.id,
                                                   'items': [{'product_id': self.food.id, 'quantity': 1}]}]})
        self.assertEqual(res['orders'][0]['status'], 'created')
        self.assertNotIn('price_changes', res['orders'][0])
        oid = res['orders'][0]['order_id']
        res = self.sync(self.cashier, {'payments': [{'offline_id': 'old-p', 'order_id': oid,
                                                     'amount': 100, 'payment_method': 'cash'}]})
        self.assertEqual(res['payments'][0]['status'], 'created')
        self.assertEqual(OrderItem.objects.filter(order_id=oid).count(), 1)


class CrossChunkOrderingTests(Base):
    """rv_chunk_order.py scenario: a queued add-items for order X and the cash payment for X's
    new total. A paid order refuses sync add-items; the app therefore pushes every order
    (and append) BEFORE any payment, so the items are billed and the payment fits in full."""

    def test_paid_order_refuses_sync_append_even_with_capped_payment(self):
        o = self.dinein()
        o.refresh_from_db()
        p = self.sync(self.cashier, {'payments': [app_payment('p-x', o.id, float(o.total_amount) + 1770.0)]})['payments'][0]
        self.assertIn('amount_recorded', p)                     # capped: order now paid
        res = self.sync(self.cashier, {'orders': [app_order('a-x', self.tM.id, [self.item(self.drink)],
                                                            existing_order_id=o.id)]})
        self.assertEqual(res['orders'][0]['status'], 'error')
        self.assertIn('fully paid', res['orders'][0]['error'])
        o.refresh_from_db()
        self.assertEqual(o.order_items.count(), 1)
        self.assertEqual(o.payment_status, 'paid')

    def test_paid_order_refuses_sync_append(self):
        o = self.dinein()
        self.assertEqual(self.pay(o, o.total_amount).status_code, 201)
        res = self.sync(self.cashier, {'orders': [app_order('a-y', self.tM.id, [self.item(self.drink)],
                                                            existing_order_id=o.id)]})
        self.assertEqual(res['orders'][0]['status'], 'error')
        self.assertEqual(o.order_items.count(), 1)

    def test_new_push_order_bills_items_and_records_payment_in_full(self):
        # The app's order: all order requests (incl. the append) first, then payments.
        o = self.dinein()
        o.refresh_from_db()
        new_total = o.total_amount + Decimal('1770.00')         # what the phone showed
        res1 = self.sync(self.cashier, {'orders': [app_order('a-z', self.tM.id, [self.item(self.drink)],
                                                             existing_order_id=o.id)]})
        self.assertEqual(res1['orders'][0]['status'], 'created')
        res2 = self.sync(self.cashier, {'payments': [app_payment('p-z', o.id, float(new_total))]})
        p = res2['payments'][0]
        self.assertEqual(p['status'], 'created')
        self.assertNotIn('amount_recorded', p)                  # NOT capped
        o.refresh_from_db()
        self.assertEqual(o.total_amount, new_total)
        self.assertEqual(o.order_items.count(), 2)              # items billed
        self.assertEqual(Payment.objects.get(pk=p['payment_id']).amount, new_total)
        self.assertEqual(o.payment_status, 'paid')


class AppendDedupUnderLockTests(Base):
    """Review 2, item 3: an online add-items with the same client_id may stamp the dedup tag
    after the sync's unlocked check; the check is repeated on the locked row."""

    def test_tag_written_between_check_and_lock_is_seen(self):
        o = self.dinein()
        tag = '[offline-append:race-1]'
        manager_cls = type(Order.objects)
        orig = manager_cls.select_for_update

        def sfu(mgr, *a, **k):
            if mgr.model is Order:   # the concurrent online request commits just before the lock
                Order.objects.filter(pk=o.pk).update(special_instructions=f'x {tag}')
            return orig(mgr, *a, **k)

        with mock.patch.object(manager_cls, 'select_for_update', sfu):
            res = self.sync(self.cashier, {'orders': [app_order('race-1', self.tM.id, [self.item(self.drink)],
                                                                existing_order_id=o.id)]})
        self.assertEqual(res['orders'][0]['status'], 'duplicate', res)
        self.assertEqual(o.order_items.count(), 1)


class NotRecordedPaymentTests(Base):
    """Review 2, item 8: an offline payment when nothing is owed any more."""

    def pay_body(self, oid, amount, offline_id, new_app=True):
        body = app_payment(offline_id, oid, amount)
        if new_app:
            body['accepts_not_recorded'] = True
        return body

    def test_second_split_payment_after_capped_one_is_not_recorded(self):
        self.food.price = Decimal('4500.00')
        self.food.save()
        r = self.sync(self.cashier, {'orders': [app_order('o-sp', self.tM.id, [self.item(q=1) | {'price': 5000.0}])]})['orders'][0]
        p1 = self.sync(self.cashier, {'payments': [self.pay_body(r['order_id'], 5000.0, 'sp-1')]})['payments'][0]
        self.assertEqual(p1['status'], 'created')               # 5000 of 5310: fits, recorded in full
        self.assertNotIn('amount_recorded', p1)
        p2 = self.sync(self.cashier, {'payments': [self.pay_body(r['order_id'], 900.0, 'sp-2')]})['payments'][0]
        self.assertEqual(p2['status'], 'created')               # 310 still owed → capped
        self.assertEqual(Decimal(p2['amount_recorded']), Decimal('310.00'))
        p3 = self.sync(self.cashier, {'payments': [self.pay_body(r['order_id'], 100.0, 'sp-3')]})['payments'][0]
        self.assertEqual(p3['status'], 'not_recorded', p3)
        self.assertIn('could not be recorded', p3['warning'])
        self.assertIn('settle/refund', p3['warning'])
        self.assertEqual(p3['order_number'], Order.objects.get(pk=r['order_id']).order_number)
        self.assertEqual(Payment.objects.filter(order_id=r['order_id']).count(), 2)

    def test_old_app_without_flag_keeps_old_error_shape(self):
        o = self.dinein()
        self.assertEqual(self.pay(o, o.total_amount).status_code, 201)
        res = self.sync(self.cashier, {'payments': [self.pay_body(o.id, 50.0, 'old-x', new_app=False)]})
        self.assertEqual(res['payments'][0]['status'], 'error')
        self.assertIn('exceeds remaining balance', res['payments'][0]['error'])

    def test_online_payment_keeps_strict_refusal(self):
        o = self.dinein()
        self.assertEqual(self.pay(o, o.total_amount).status_code, 201)
        r = self.api(self.cashier).post('/api/v1/payments/', {
            'order_id': o.id, 'amount': '50', 'payment_method': 'cash', 'offline_id': 'on-1',
            'accepts_not_recorded': True}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Payment.objects.filter(order=o).count(), 1)
