from django.urls import path
from rest_framework.decorators import authentication_classes
from .authentication import ExpiringTokenAuthentication
from rest_framework.authentication import SessionAuthentication
from .views import auth, menu, tables, orders, payments, bill_requests, sync, reports, waste, restaurants

app_name = 'mobile_api'

# Apply ExpiringTokenAuthentication to every mobile API view without touching
# the global REST_FRAMEWORK default (which must stay as standard TokenAuthentication
# so the print client's long-lived service token is never rejected).
def _mobile(view_func):
    return authentication_classes([ExpiringTokenAuthentication, SessionAuthentication])(view_func)

urlpatterns = [
    # ── Authentication ─────────────────────────────────────────────────────
    path('auth/login/',       _mobile(auth.login),           name='login'),
    path('auth/logout/',      _mobile(auth.logout),          name='logout'),
    path('auth/me/',          _mobile(auth.me),              name='me'),
    path('auth/register/',    _mobile(auth.register),        name='register'),
    path('auth/push-token/',  _mobile(auth.save_push_token), name='save_push_token'),

    # ── Menu ───────────────────────────────────────────────────────────────
    path('menu/',         _mobile(menu.menu),          name='menu'),
    path('menu/changes/', _mobile(menu.menu_changes),  name='menu_changes'),

    # ── Tables ─────────────────────────────────────────────────────────────
    path('tables/',              _mobile(tables.tables),       name='tables'),
    path('tables/<int:table_id>/', _mobile(tables.table_detail), name='table_detail'),
    path('tables/<int:table_id>/active-order/',  _mobile(orders.active_order_for_table),  name='active_order_for_table'),
    path('tables/<int:table_id>/active-orders/', _mobile(orders.active_orders_for_table), name='active_orders_for_table'),

    # ── Orders ─────────────────────────────────────────────────────────────
    path('orders/',                                   _mobile(orders.orders),               name='orders'),
    path('orders/<int:order_id>/',                    _mobile(orders.order_detail),         name='order_detail'),
    path('orders/<int:order_id>/status/',             _mobile(orders.update_order_status),  name='update_order_status'),
    path('orders/<int:order_id>/print-bill/',         _mobile(orders.print_bill),           name='print_bill'),
    path('orders/<int:order_id>/transfer/',           _mobile(orders.transfer_table),       name='transfer_table'),
    path('orders/<int:order_id>/cancel/',             _mobile(orders.cancel_order),         name='cancel_order'),
    path('orders/<int:order_id>/add-items/',          _mobile(orders.add_items_to_order),   name='add_items_to_order'),
    path('orders/items/<int:item_id>/cancel/',        _mobile(orders.cancel_order_item),    name='cancel_order_item'),

    # ── Payments ───────────────────────────────────────────────────────────
    path('payments/',                              _mobile(payments.payments),        name='payments'),
    path('payments/<int:payment_id>/void/',        _mobile(payments.void_payment),    name='void_payment'),
    path('payments/<int:payment_id>/receipt/',     _mobile(payments.payment_receipt), name='payment_receipt'),
    path('payments/<int:payment_id>/reprint/',     _mobile(payments.reprint_receipt), name='reprint_receipt'),

    # ── Bill Requests ──────────────────────────────────────────────────────
    path('bill-requests/',                              _mobile(bill_requests.bill_requests),        name='bill_requests'),
    path('bill-requests/<int:request_id>/complete/',    _mobile(bill_requests.complete_bill_request), name='complete_bill_request'),

    # ── Offline Sync ───────────────────────────────────────────────────────
    path('sync/push/', _mobile(sync.sync_push), name='sync_push'),
    path('sync/pull/', _mobile(sync.sync_pull), name='sync_pull'),

    # ── Reports ───────────────────────────────────────────────────────────
    path('reports/cc/',      _mobile(reports.cc_reports),      name='cc_reports'),
    path('reports/revenue/', _mobile(reports.owner_reports),   name='owner_reports'),
    path('reports/cashier/', _mobile(reports.cashier_reports), name='cashier_reports'),

    # ── Waste Management ─────────────────────────────────────────────────
    path('waste/', _mobile(waste.waste), name='waste'),

    # ── Restaurants (customer discovery) ─────────────────────────────────
    path('restaurants/',      _mobile(restaurants.restaurants_list), name='restaurants_list'),
    path('restaurants/scan/', _mobile(restaurants.restaurant_by_qr), name='restaurant_by_qr'),
]
