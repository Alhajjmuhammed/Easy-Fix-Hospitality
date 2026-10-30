from django.urls import path
from . import views, views_purchasing, views_recipes

app_name = 'inventory'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('items/', views.manage_items, name='items'),
    path('record/', views.add_record, name='add_record'),
    path('history/', views.history, name='history'),
    path('settings/', views.manage_settings, name='settings'),
    path('api/item/<int:item_id>/', views.item_detail_ajax, name='item_detail'),
    path('recipes/', views_recipes.recipe_list, name='recipes'),
    path('recipes/<int:product_id>/', views_recipes.recipe_edit, name='recipe_edit'),
    path('suppliers/', views_purchasing.suppliers, name='suppliers'),
    path('purchase-orders/', views_purchasing.po_list, name='po_list'),
    path('purchase-orders/new/', views_purchasing.po_form, name='po_new'),
    path('purchase-orders/<int:pk>/', views_purchasing.po_detail, name='po_detail'),
    path('purchase-orders/<int:pk>/edit/', views_purchasing.po_form, name='po_edit'),
    path('purchase-orders/<int:pk>/action/', views_purchasing.po_action, name='po_action'),
    path('purchase-orders/<int:pk>/pdf/', views_purchasing.po_pdf, name='po_pdf'),
]
