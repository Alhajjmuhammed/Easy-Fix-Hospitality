from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('items/', views.manage_items, name='items'),
    path('record/', views.add_record, name='add_record'),
    path('history/', views.history, name='history'),
    path('settings/', views.manage_settings, name='settings'),
    path('api/item/<int:item_id>/', views.item_detail_ajax, name='item_detail'),
]
