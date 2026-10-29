"""
Default feature sets per built-in role.
Used as fallback when no RolePermissionSet exists for a restaurant,
preserving the system's current hardcoded behavior exactly.
"""

DEFAULT_ROLE_FEATURES = {
    'manager': [
        # Orders
        'view_orders', 'place_orders', 'manage_orders', 'cancel_orders', 'transfer_orders',
        'request_bill',
        # Delivery
        'view_delivery', 'manage_delivery',
        # Reservations
        'view_reservations', 'manage_reservations',
        # Payments
        'process_payments', 'void_payments', 'view_receipts',
        # Station
        'kitchen_dashboard', 'bar_dashboard', 'buffet_dashboard', 'service_dashboard',
        # Menu
        'view_menu', 'add_menu_items', 'manage_menu',
        'view_categories', 'add_categories', 'manage_categories',
        'view_promotions', 'add_promotions', 'manage_promotions',
        'view_events', 'add_events', 'manage_events',
        # Staff
        'view_staff', 'manage_staff',
        # Reports
        'view_reports', 'export_reports',
        # Operations
        'view_waste', 'log_waste', 'manage_waste',
        'view_inventory', 'add_inventory', 'manage_inventory',
        'view_attendance', 'manage_attendance',
        'view_tables', 'add_tables', 'manage_tables',
    ],
    'customer_care': [
        'view_orders', 'place_orders', 'manage_orders', 'cancel_orders', 'transfer_orders',
        'request_bill', 'process_payments', 'view_receipts',
        'view_waste', 'log_waste', 'view_reports', 'view_attendance',
        'view_reservations', 'manage_reservations',
    ],
    'kitchen': ['kitchen_dashboard'],
    'bar': ['bar_dashboard'],
    'buffet': ['buffet_dashboard'],
    'service': ['service_dashboard', 'request_bill'],
    'cashier': [
        'view_orders', 'place_orders', 'manage_orders', 'cancel_orders', 'transfer_orders',
        'request_bill', 'process_payments', 'void_payments', 'view_receipts',
        'view_waste', 'log_waste', 'view_reports', 'export_reports',
        'view_inventory',
        'view_reservations', 'manage_reservations',
    ],
    'delivery_rider': ['view_delivery', 'manage_delivery'],
}

# (slug, display_name, description, category)
# Hierarchy: manage_X implies add_X implies view_X — enforced in view guards.
ALL_FEATURES = [
    # Orders
    ('view_orders',       'View Orders',              'View and monitor all active orders', 'orders'),
    ('place_orders',      'Place Orders',             'Place new orders for customers at the table, delivery or pickup', 'orders'),
    ('manage_orders',     'Manage Orders',            'Edit, update and modify existing orders', 'orders'),
    ('cancel_orders',     'Cancel Orders',            'Cancel pending orders before payment', 'orders'),
    ('transfer_orders',   'Transfer Table',           'Transfer orders between tables', 'orders'),
    ('request_bill',      'Request Bill',             'Request the bill on behalf of customers at a table', 'orders'),
    # Delivery
    ('view_delivery',     'View Delivery',            'View delivery orders and rider assignments', 'orders'),
    ('manage_delivery',   'Manage Delivery',          'Assign riders and manage delivery order lifecycle', 'orders'),
    # Reservations
    ('view_reservations',   'View Reservations',      'View table reservations (read-only)', 'orders'),
    ('manage_reservations', 'Manage Reservations',    'Create, confirm, decline, assign tables and update reservations (includes view)', 'orders'),
    # Payments
    ('process_payments',  'Process Payments',         'Accept cash, card, digital and voucher payments', 'payments'),
    ('void_payments',     'Void Payments',            'Void and reverse processed payments with audit trail', 'payments'),
    ('view_receipts',     'View & Print Receipts',    'View order receipts and reprint them on demand', 'payments'),
    # Station
    ('kitchen_dashboard', 'Kitchen Dashboard',        'Access the kitchen order display and advance order status', 'station'),
    ('bar_dashboard',     'Bar Dashboard',            'Access the bar order display and advance order status', 'station'),
    ('buffet_dashboard',  'Buffet Dashboard',         'Access the buffet order display and advance order status', 'station'),
    ('service_dashboard', 'Service Dashboard',        'Access the service order display and advance order status', 'station'),
    # Menu
    ('view_menu',         'View Menu Items',          'View products and menu items (read-only)', 'menu'),
    ('add_menu_items',    'Add Menu Items',           'Add new products to the menu', 'menu'),
    ('manage_menu',       'Manage Menu Items',        'Edit and delete existing menu products (includes view + add)', 'menu'),
    ('view_categories',   'View Categories',          'View menu categories and subcategories (read-only)', 'menu'),
    ('add_categories',    'Add Categories',           'Add new menu categories and subcategories', 'menu'),
    ('manage_categories', 'Manage Categories',        'Edit and delete categories (includes view + add)', 'menu'),
    ('view_promotions',   'View Promotions',          'View happy hour promotions (read-only)', 'menu'),
    ('add_promotions',    'Add Promotions',           'Create new happy hour promotions', 'menu'),
    ('manage_promotions', 'Manage Promotions',        'Edit and delete promotions (includes view + add)', 'menu'),
    ('view_events',       'View Events',              'View banqueting and event bookings (read-only)', 'menu'),
    ('add_events',        'Add Events',               'Create new event bookings', 'menu'),
    ('manage_events',     'Manage Events',            'Edit and delete events (includes view + add)', 'menu'),
    # Staff
    ('view_staff',        'View Staff',               'View staff accounts and profiles (read-only)', 'staff'),
    ('manage_staff',      'Manage Staff',             'Add, edit and remove staff accounts (includes view)', 'staff'),
    # Reports
    ('view_reports',      'View Reports',             'Access sales, cashier and performance reports', 'reports'),
    ('export_reports',    'Export Reports',           'Export reports as CSV or PDF files', 'reports'),
    # Operations
    ('view_waste',        'View Waste Records',       'View food waste reports and incident history', 'operations'),
    ('log_waste',         'Log Waste',                'Record new food waste incidents', 'operations'),
    ('manage_waste',      'Manage Waste',             'Edit, delete waste records and manage settings (includes view + log)', 'operations'),
    ('view_inventory',    'View Inventory',           'View stock levels and inventory (read-only)', 'operations'),
    ('add_inventory',     'Add / Adjust Inventory',   'Add stock and record inventory adjustments', 'operations'),
    ('manage_inventory',  'Manage Inventory',         'Edit and delete inventory records (includes view + add)', 'operations'),
    ('view_attendance',   'View Attendance',          'View staff attendance and shift records', 'operations'),
    ('manage_attendance', 'Manage Attendance',        'Manage shifts, QR codes and attendance policies', 'operations'),
    ('view_tables',       'View Tables',              'View table layout and status (read-only)', 'operations'),
    ('add_tables',        'Add Tables',               'Add new tables to the layout', 'operations'),
    ('manage_tables',     'Manage Tables',            'Edit and remove tables (includes view + add)', 'operations'),
]
