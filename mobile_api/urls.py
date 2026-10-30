from django.urls import path
from .views import auth, menu, tables, orders, payments, bill_requests, sync, reports, waste, restaurants, delivery, reservations, feedback
from attendance import views_mobile as attendance
from cashier import views_loyalty as loyalty
from cashier import views_mobile_money as mobile_money

app_name = 'mobile_api'

urlpatterns = [
    # ── Authentication ─────────────────────────────────────────────────────
    path('auth/login/',       auth.login,           name='login'),
    path('auth/logout/',      auth.logout,          name='logout'),
    path('auth/me/',          auth.me,              name='me'),
    path('auth/register/',    auth.register,        name='register'),
    path('auth/push-token/',  auth.save_push_token, name='save_push_token'),
    path('auth/language/',    auth.save_language,   name='save_language'),

    # ── Menu ───────────────────────────────────────────────────────────────
    path('menu/',         menu.menu,          name='menu'),
    path('menu/changes/', menu.menu_changes,  name='menu_changes'),

    # ── Tables ─────────────────────────────────────────────────────────────
    path('tables/',              tables.tables,       name='tables'),
    path('tables/<int:table_id>/', tables.table_detail, name='table_detail'),
    path('tables/<int:table_id>/active-order/',  orders.active_order_for_table,  name='active_order_for_table'),
    path('tables/<int:table_id>/active-orders/', orders.active_orders_for_table, name='active_orders_for_table'),

    # ── Orders ─────────────────────────────────────────────────────────────
    path('orders/',                                   orders.orders,               name='orders'),
    path('orders/<int:order_id>/',                    orders.order_detail,         name='order_detail'),
    path('orders/<int:order_id>/status/',             orders.update_order_status,  name='update_order_status'),
    path('orders/<int:order_id>/print-bill/',           orders.print_bill,            name='print_bill'),
    path('orders/<int:order_id>/print-station-ticket/', orders.print_station_ticket, name='print_station_ticket'),
    path('orders/<int:order_id>/transfer/',           orders.transfer_table,       name='transfer_table'),
    path('orders/<int:order_id>/cancel/',             orders.cancel_order,         name='cancel_order'),
    path('orders/<int:order_id>/add-items/',          orders.add_items_to_order,   name='add_items_to_order'),
    path('orders/items/<int:item_id>/cancel/',        orders.cancel_order_item,    name='cancel_order_item'),

    # ── Payments ───────────────────────────────────────────────────────────
    path('payments/',                              payments.payments,        name='payments'),
    path('payments/<int:payment_id>/void/',        payments.void_payment,    name='void_payment'),
    path('payments/<int:payment_id>/receipt/',     payments.payment_receipt, name='payment_receipt'),
    path('payments/<int:payment_id>/reprint/',     payments.reprint_receipt, name='reprint_receipt'),

    # ── Bill Requests ──────────────────────────────────────────────────────
    path('bill-requests/',                              bill_requests.bill_requests,        name='bill_requests'),
    path('bill-requests/<int:request_id>/complete/',    bill_requests.complete_bill_request, name='complete_bill_request'),

    # ── Offline Sync ───────────────────────────────────────────────────────
    path('sync/push/', sync.sync_push, name='sync_push'),
    path('sync/pull/', sync.sync_pull, name='sync_pull'),

    # ── Reports ───────────────────────────────────────────────────────────
    path('reports/cc/',      reports.cc_reports,      name='cc_reports'),
    path('reports/revenue/', reports.owner_reports,   name='owner_reports'),
    path('reports/cashier/', reports.cashier_reports, name='cashier_reports'),

    # ── Waste Management ─────────────────────────────────────────────────
    path('waste/', waste.waste, name='waste'),

    # ── Restaurants (customer discovery) ─────────────────────────────────
    path('restaurants/',      restaurants.restaurants_list, name='restaurants_list'),
    path('restaurants/scan/', restaurants.restaurant_by_qr, name='restaurant_by_qr'),

    # ── Delivery ──────────────────────────────────────────────────────────
    path('delivery/riders/',                       delivery.riders_list,         name='delivery_riders'),
    path('delivery/assign/',                       delivery.assign_rider,        name='delivery_assign'),
    path('delivery/auto-assign/',                  delivery.auto_assign_rider,   name='delivery_auto_assign'),
    path('delivery/location/',                     delivery.update_location,     name='delivery_location'),
    path('delivery/assignments/',                  delivery.my_assignments,      name='delivery_assignments'),
    path('delivery/availability/',                 delivery.toggle_availability, name='delivery_availability'),
    path('delivery/<int:order_id>/track/',         delivery.track_order,         name='delivery_track'),
    path('delivery/<int:order_id>/pickup/',        delivery.mark_picked_up,      name='delivery_pickup'),
    path('delivery/<int:order_id>/complete/',      delivery.mark_delivered,      name='delivery_complete'),

    # ── Reservations ──────────────────────────────────────────────────────
    path('reservations/',                       reservations.reservations,       name='reservations'),
    path('reservations/<int:pk>/status/',       reservations.reservation_status, name='reservation_status'),
    path('reservations/<int:pk>/table/',        reservations.reservation_table,  name='reservation_table'),
    path('reservations/<int:pk>/cancel/',       reservations.reservation_cancel, name='reservation_cancel'),
    path('orders/<int:order_id>/rating/',       feedback.order_rating,           name='order_rating'),
    path('orders/<int:order_id>/loyalty/',      loyalty.order_loyalty_api,       name='order_loyalty'),
    path('loyalty/me/',                         loyalty.my_points_api,           name='my_loyalty_points'),
    path('orders/<int:order_id>/mobile-money/', mobile_money.start_api,          name='mobile_money_start'),
    path('mobile-money/<int:charge_id>/',       mobile_money.charge_status_api,  name='mobile_money_status'),

    # ── Attendance ────────────────────────────────────────────────────────
    path('attendance/scan/',    attendance.attendance_scan,    name='attendance_scan'),
    path('attendance/confirm/', attendance.attendance_confirm, name='attendance_confirm'),
    path('attendance/my/',      attendance.attendance_my,      name='attendance_my'),
    path('attendance/status/',  attendance.attendance_status,  name='attendance_status'),
    path('attendance/roster/my/', attendance.roster_my,        name='attendance_roster_my'),
]
