from django.urls import path
from . import views

app_name = 'system_admin'

urlpatterns = [
    # Overview
    path('', views.system_dashboard, name='dashboard'),
    path('statistics/', views.system_statistics, name='statistics'),
    
    # Management
    path('users/', views.manage_all_users, name='manage_users'),
    path('categories/', views.manage_categories, name='manage_categories'),
    path('products/', views.manage_products, name='manage_products'),
    path('tables/', views.manage_tables, name='manage_tables'),
    
    # Operations
    path('orders/', views.view_all_orders, name='view_orders'),
    path('manage-orders/', views.manage_orders, name='manage_orders'),
    path('restaurants/', views.manage_all_restaurants, name='manage_restaurants'),
    
    # User Management (CRUD)
    path('create-user/', views.create_user, name='add_user'),
    path('user-details/<int:user_id>/', views.user_details, name='user_details'),
    path('edit-user/<int:user_id>/', views.edit_user, name='edit_user'),
    path('delete-user/<int:user_id>/', views.delete_user, name='delete_user'),
    
    # Restaurant Management (CRUD)
    path('create-restaurant/', views.create_restaurant_owner, name='create_restaurant'),
    path('restaurant-details/<int:restaurant_id>/', views.get_restaurant_details, name='restaurant_details'),
    path('edit-restaurant/<int:restaurant_id>/', views.edit_restaurant, name='edit_restaurant'),
    path('delete-restaurant/<int:restaurant_id>/', views.delete_restaurant, name='delete_restaurant'),
    
    # Subscription Management
    path('block-restaurant/<int:restaurant_id>/', views.block_restaurant, name='block_restaurant'),
    path('unblock-restaurant/<int:restaurant_id>/', views.unblock_restaurant, name='unblock_restaurant'),
    path('extend-subscription/<int:restaurant_id>/', views.extend_subscription, name='extend_subscription'),
    
    # New Admin Functions
    path('toggle-subscription-plan/', views.toggle_restaurant_subscription_plan, name='toggle_subscription_plan'),
    path('toggle-restaurant-status/', views.toggle_restaurant_status, name='toggle_restaurant_status'),
    path('delete-restaurant-admin/', views.delete_restaurant_admin, name='delete_restaurant_admin'),
    path('restaurant-details-admin/<int:restaurant_id>/', views.restaurant_details_admin, name='restaurant_details_admin'),
    
    # Categories Management (CRUD)
    path('create-category/', views.create_category, name='create_category'),
    path('create-subcategory/', views.create_subcategory, name='create_subcategory'),
    path('category-details/<int:category_id>/', views.category_details, name='category_details'),
    path('edit-category/<int:category_id>/', views.edit_category, name='edit_category'),
    path('edit-subcategory/<int:subcategory_id>/', views.edit_subcategory, name='edit_subcategory'),
    path('delete-category/<int:category_id>/', views.delete_category, name='delete_category'),
    path('delete-subcategory/<int:subcategory_id>/', views.delete_subcategory, name='delete_subcategory'),
    path('get-categories/<int:restaurant_id>/', views.get_categories, name='get_categories'),
    path('get-subcategories/<int:category_id>/', views.get_subcategories, name='get_subcategories'),
    
    # Products Management (CRUD)
    path('create-product/', views.create_product, name='create_product'),
    path('product-details/<int:product_id>/', views.product_details, name='product_details'),
    path('edit-product/<int:product_id>/', views.edit_product, name='edit_product'),
    path('delete-product/<int:product_id>/', views.delete_product, name='delete_product'),
    
    # Tables Management (CRUD)
    path('create-table/', views.create_table, name='create_table'),
    path('table-details/<int:table_id>/', views.table_details, name='table_details'),
    path('edit-table/<int:table_id>/', views.edit_table, name='edit_table'),
    path('delete-table/<int:table_id>/', views.delete_table, name='delete_table'),
    
    # Orders Management
    path('order-details/<int:order_id>/', views.order_details, name='order_details'),
    path('update-order-status/<int:order_id>/', views.update_order_status, name='update_order_status'),
    path('update-payment-status/<int:order_id>/', views.update_payment_status, name='update_payment_status'),
    path('cancel-order/<int:order_id>/', views.cancel_order, name='cancel_order'),
    path('get-order-status/<int:order_id>/', views.get_order_status, name='get_order_status'),
    path('get-payment-status/<int:order_id>/', views.get_payment_status, name='get_payment_status'),
]