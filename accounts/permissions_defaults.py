"""
Default feature sets per built-in role.
Used as fallback when no RolePermissionSet exists for a restaurant,
preserving the system's current hardcoded behavior exactly.
"""

DEFAULT_ROLE_FEATURES = {
    'manager': [
        'place_orders', 'manage_orders', 'cancel_orders', 'transfer_orders',
        'process_payments', 'void_payments',
        'view_receipts', 'kitchen_dashboard', 'bar_dashboard', 'buffet_dashboard',
        'service_dashboard', 'manage_menu', 'manage_categories', 'manage_promotions',
        'manage_events', 'manage_staff', 'view_reports', 'export_reports',
        'manage_waste', 'manage_inventory', 'view_attendance', 'manage_attendance',
        'manage_tables', 'manage_delivery',
    ],
    'customer_care': [
        'place_orders', 'manage_orders', 'cancel_orders', 'transfer_orders',
        'process_payments', 'view_receipts',
        'manage_waste', 'view_reports', 'view_attendance',
    ],
    'kitchen': ['kitchen_dashboard'],
    'bar': ['bar_dashboard'],
    'buffet': ['buffet_dashboard'],
    'service': ['service_dashboard'],
    'cashier': [
        'place_orders', 'manage_orders', 'cancel_orders', 'transfer_orders',
        'process_payments', 'void_payments',
        'view_receipts', 'manage_waste', 'view_reports', 'export_reports',
    ],
    'delivery_rider': ['manage_delivery'],
}

# (slug, display_name, description, category)
ALL_FEATURES = [
    ('place_orders',      'Place Orders',            'Place new orders for customers at the table, delivery or pickup', 'orders'),
    ('manage_orders',     'Manage Orders',            'Edit and update existing orders', 'orders'),
    ('cancel_orders',     'Cancel Orders',            'Cancel pending orders before payment', 'orders'),
    ('transfer_orders',   'Transfer Table',           'Transfer orders between tables', 'orders'),
    ('manage_delivery',   'Manage Delivery',          'Assign riders and manage delivery order lifecycle', 'orders'),
    ('process_payments',  'Process Payments',         'Accept cash, card, digital and voucher payments', 'payments'),
    ('void_payments',     'Void Payments',            'Void and reverse processed payments with audit trail', 'payments'),
    ('view_receipts',     'View & Print Receipts',    'View order receipts and reprint them on demand', 'payments'),
    ('kitchen_dashboard', 'Kitchen Dashboard',        'Access the kitchen order display and advance order status', 'station'),
    ('bar_dashboard',     'Bar Dashboard',            'Access the bar order display and advance order status', 'station'),
    ('buffet_dashboard',  'Buffet Dashboard',         'Access the buffet order display and advance order status', 'station'),
    ('service_dashboard', 'Service Dashboard',        'Access the service order display and advance order status', 'station'),
    ('manage_menu',       'Manage Menu Items',        'Add, edit and delete products from the menu', 'menu'),
    ('manage_categories', 'Manage Categories',        'Add, edit and delete menu categories and subcategories', 'menu'),
    ('manage_promotions', 'Manage Promotions',        'Create and manage happy hour discount promotions', 'menu'),
    ('manage_events',     'Manage Events',            'Create and manage banqueting and event bookings', 'menu'),
    ('manage_staff',      'Manage Staff',             'Add, edit and remove staff accounts', 'staff'),
    ('view_reports',      'View Reports',             'Access sales, cashier and performance reports', 'reports'),
    ('export_reports',    'Export Reports',           'Export reports as CSV or PDF files', 'reports'),
    ('manage_waste',      'Manage Waste',             'Log food waste incidents and view waste records', 'operations'),
    ('manage_inventory',  'Manage Inventory',         'Track, add and adjust stock levels', 'operations'),
    ('view_attendance',   'View Attendance',          'View staff attendance and shift records', 'operations'),
    ('manage_attendance', 'Manage Attendance',        'Manage shifts, QR codes and attendance policies', 'operations'),
    ('manage_tables',     'Manage Tables',            'Add, edit and remove tables', 'operations'),
]
