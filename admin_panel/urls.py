from django.urls import path
from . import views
from . import views_branches
from . import views_main_owner

app_name = 'admin_panel'

urlpatterns = [
    path('', views.admin_dashboard, name='admin_dashboard'),
    
    # Main Owner Monitoring Views (Read-only)
    path('main-owner-dashboard/', views_main_owner.main_owner_dashboard, name='main_owner_dashboard'),
    path('branch-reports/', views_main_owner.branch_reports, name='branch_reports'),
    path('view-all-orders/', views_main_owner.view_all_orders, name='view_all_orders'),
    path('branch/<int:restaurant_id>/detail/', views_main_owner.branch_detail, name='branch_detail'),
    
    # Branch management URLs
    path('branches/', views_branches.manage_branches, name='manage_branches'),
    path('branches/add/', views_branches.add_branch, name='add_branch'),
    path('branches/<int:restaurant_id>/edit/', views_branches.edit_branch, name='edit_branch'),
    path('branches/<int:restaurant_id>/delete/', views_branches.delete_branch, name='delete_branch'),
    path('branches/<int:restaurant_id>/toggle-status/', views_branches.toggle_restaurant_status, name='toggle_restaurant_status'),
    path('restaurant-selection/', views_branches.restaurant_selection, name='restaurant_selection'),
    path('switch-restaurant/', views_branches.switch_restaurant, name='switch_restaurant'),
    path('set-view-all-restaurants/', views_branches.set_view_all_restaurants, name='set_view_all_restaurants'),
    
    # Subscription management
    path('upgrade-to-pro/', views_branches.upgrade_to_pro, name='upgrade_to_pro'),
    path('downgrade-to-single/', views_branches.downgrade_to_single, name='downgrade_to_single'),
    path('setup-main-restaurant/', views_branches.setup_main_restaurant, name='setup_main_restaurant'),
    
    # Temporary placeholder for reports - redirect to existing reports
    path('consolidated-reports/', views.admin_dashboard, {'template': 'reports'}, name='consolidated_reports'),
    
    # Existing URLs continue below...
    path('profile/', views.profile, name='profile'),
    path('users/', views.manage_users, name='manage_users'),
    path('products/', views.manage_products, name='manage_products'),
    path('orders/', views.manage_orders, name='manage_orders'),
    path('tables/', views.manage_tables, name='manage_tables'),
    path('categories/', views.manage_categories, name='manage_categories'),
    
    # Category Management
    path('categories/add-main/', views.add_main_category, name='add_main_category'),
    path('categories/edit-main/<int:category_id>/', views.edit_main_category, name='edit_main_category'),
    path('categories/delete-main/<int:category_id>/', views.delete_main_category, name='delete_main_category'),
    path('categories/toggle-main/<int:category_id>/', views.toggle_main_category, name='toggle_main_category'),
    path('categories/add-sub/', views.add_subcategory, name='add_subcategory'),
    path('categories/edit-sub/<int:subcategory_id>/', views.edit_subcategory, name='edit_subcategory'),
    path('categories/delete-sub/<int:subcategory_id>/', views.delete_subcategory, name='delete_subcategory'),
    path('categories/toggle-sub/<int:subcategory_id>/', views.toggle_subcategory, name='toggle_subcategory'),
    path('categories/bulk-delete-main/', views.bulk_delete_main_categories, name='bulk_delete_main_categories'),
    path('categories/bulk-delete-sub/', views.bulk_delete_subcategories, name='bulk_delete_subcategories'),
    
    # User Management
    path('users/add/', views.add_user, name='add_user'),
    path('users/<int:user_id>/edit/', views.edit_user, name='edit_user'),
    path('users/<int:user_id>/update/', views.update_user, name='update_user'),
    path('users/<int:user_id>/toggle/', views.toggle_user_status, name='toggle_user_status'),
    path('users/<int:user_id>/delete/', views.delete_user, name='delete_user'),
    path('users/<int:user_id>/get/', views.get_user_data, name='get_user_data'),
    
    # Role Management
    path('roles/add/', views.add_role, name='add_role'),
    path('roles/<int:role_id>/edit/', views.edit_role, name='edit_role'),
    path('roles/<int:role_id>/update/', views.update_role, name='update_role'),
    path('roles/<int:role_id>/delete/', views.delete_role, name='delete_role'),
    path('roles/<int:role_id>/get/', views.get_role_data, name='get_role_data'),
    
    # Table Management
    path('tables/add/', views.add_table, name='add_table'),
    path('tables/get/', views.get_table, name='get_table'),
    path('tables/update/', views.update_table, name='update_table'),
    path('tables/toggle-status/', views.toggle_table_status, name='toggle_table_status'),
    path('tables/delete/', views.delete_table, name='delete_table'),
    
    # Order Management
    path('orders/view/<int:order_id>/', views.view_order, name='view_order'),
    path('orders/update-status/', views.update_order_status, name='update_order_status'),
    path('orders/add/', views.add_order, name='add_order'),
    path('orders/edit/<int:order_id>/', views.edit_order, name='edit_order'),
    path('orders/delete/<int:order_id>/', views.delete_order, name='delete_order'),
    
    # Product Management API
    path('get-subcategories/<int:main_category_id>/', views.get_subcategories, name='get_subcategories'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/<int:product_id>/', views.view_product, name='view_product'),
    path('products/<int:product_id>/edit/', views.edit_product, name='edit_product'),
    path('products/<int:product_id>/update/', views.update_product, name='update_product'),
    path('products/<int:product_id>/toggle-availability/', views.toggle_product_availability, name='toggle_product_availability'),
    path('products/<int:product_id>/delete/', views.delete_product, name='delete_product'),
    path('products/bulk-delete/', views.bulk_delete_products, name='bulk_delete_products'),
    
    # Product Import/Export
    path('products/import-csv/', views.import_products_csv, name='import_products_csv'),
    path('products/import-excel/', views.import_products_excel, name='import_products_excel'),
    path('products/export-csv/', views.export_products_csv, name='export_products_csv'),
    path('products/export-excel/', views.export_products_excel, name='export_products_excel'),
    path('products/export-pdf/', views.export_products_pdf, name='export_products_pdf'),
    path('products/template-csv/', views.download_template_csv, name='download_template_csv'),
    path('products/template-excel/', views.download_template_excel, name='download_template_excel'),
    
    # QR Code Management
    path('qr-code/', views.manage_qr_code, name='manage_qr_code'),
    path('qr-code/regenerate/', views.regenerate_qr_code, name='regenerate_qr_code'),
    path('qr-code/image/', views.generate_qr_image, name='generate_qr_image'),
    path('qr-code/debug/', views.debug_qr_code, name='debug_qr_code'),
    
    # Printer Configuration
    path('printer-settings/', views.printer_settings, name='printer_settings'),
    path('printer-settings/save/', views.save_printer_settings, name='save_printer_settings'),
    path('printer-settings/detect/', views.detect_printers, name='detect_printers'),
]
