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
]
