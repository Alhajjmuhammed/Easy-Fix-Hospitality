from django.urls import path
from . import views

app_name = 'restaurant'

urlpatterns = [
    path('', views.home, name='home'),
    path('menu/', views.menu, name='menu'),
    
    # Happy Hour Management
    path('promotions/', views.manage_promotions, name='manage_promotions'),
    path('promotions/add/', views.add_promotion, name='add_promotion'),
    path('promotions/<int:promotion_id>/edit/', views.edit_promotion, name='edit_promotion'),
    path('promotions/<int:promotion_id>/delete/', views.delete_promotion, name='delete_promotion'),
    path('promotions/<int:promotion_id>/toggle/', views.toggle_promotion, name='toggle_promotion'),
    path('promotions/<int:promotion_id>/preview/', views.promotion_preview, name='promotion_preview'),
    path('ajax/get-restaurant-products/', views.get_restaurant_products, name='get_restaurant_products'),
    
    # Event Management
    path('events/', views.manage_events, name='manage_events'),
    path('events/add/', views.add_event, name='add_event'),
    path('events/export/csv/', views.export_events_csv, name='export_events_csv'),
    path('events/export/pdf/', views.export_events_pdf, name='export_events_pdf'),
    path('events/<int:event_id>/', views.view_event, name='view_event'),
    path('events/<int:event_id>/edit/', views.edit_event, name='edit_event'),
    path('events/<int:event_id>/delete/', views.delete_event, name='delete_event'),
    path('events/<int:event_id>/update-status/', views.update_event_status, name='update_event_status'),
    path('events/<int:event_id>/record-payment/', views.record_event_payment, name='record_event_payment'),
    path('events/<int:event_id>/approve-payment/', views.approve_event_payment, name='approve_event_payment'),
    path('events/reports/', views.event_reports, name='event_reports'),
]
