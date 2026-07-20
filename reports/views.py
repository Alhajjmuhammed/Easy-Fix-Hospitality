from django.shortcuts import render
from django.contrib.auth.decorators import login_required


def _safe_csv(value):
    """Prevent CSV formula injection: prefix dangerous leading characters."""
    s = str(value) if value is not None else ''
    if s and s[0] in ('=', '+', '-', '@', '|', '%'):
        return '\t' + s
    return s
from django.http import HttpResponse
from django.core.paginator import Paginator
from orders.models import Order, OrderItem
from cashier.models import Payment
from restaurant.models import MainCategory, SubCategory
from accounts.models import get_owner_filter, User
from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField
from datetime import datetime, timedelta
from django.utils import timezone
import csv

# PDF export libraries
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO

@login_required
def dashboard(request):
    """Advanced sales reports dashboard with kitchen/bar filtering"""
    
    if not (request.user.is_administrator() or request.user.is_owner() or 
            request.user.is_main_owner() or request.user.is_branch_owner() or 
            request.user.is_customer_care()):
        from django.shortcuts import redirect
        from django.contrib import messages
        messages.error(request, "Access denied. Owner or Customer Care role required.")
        return redirect('restaurant:home')
    
    # Import restaurant context utilities
    from admin_panel.restaurant_utils import get_restaurant_context
    from django.db.models import Q
    
    # Get restaurant context
    session_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant_context = get_restaurant_context(request.user, session_restaurant_id, request)
    current_restaurant = restaurant_context['current_restaurant']
    view_all_restaurants = restaurant_context['view_all_restaurants']
    
    # Get filter parameters
    payment_status = request.GET.get('payment_status', 'all')
    payment_method = request.GET.get('payment_method', 'all')
    period = request.GET.get('period', 'today')  # Default to 'today' instead of 'all'
    category_id = request.GET.get('category_id', 'all')
    subcategory_id = request.GET.get('subcategory_id', 'all')
    station_filter = request.GET.get('station_filter', 'all')  # NEW: Kitchen/Bar filtering
    product_id = request.GET.get('product_id', 'all')
    table_id = request.GET.get('table_id', 'all')
    staff_filter = request.GET.get('staff_filter', 'all')  # NEW: Staff member filtering
    restaurant_filter = request.GET.get('restaurant', '').strip()

    # Get date filters (only use if no period is being used)
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # Determine which restaurant to filter by
    target_restaurant = None
    if restaurant_filter:
        try:
            from restaurant.models_restaurant import Restaurant
            target_restaurant = Restaurant.objects.get(id=restaurant_filter)
            # SECURITY: validate the requesting user has access to this restaurant (IDOR prevention)
            if not request.user.is_administrator():
                accessible_ids = set(restaurant_context['accessible_restaurants'].values_list('id', flat=True))
                if target_restaurant.id not in accessible_ids:
                    target_restaurant = current_restaurant  # fall back silently
        except Restaurant.DoesNotExist:
            target_restaurant = None
    elif current_restaurant and not view_all_restaurants:
        target_restaurant = current_restaurant
    
    # Base queryset - filter by restaurant with performance optimization
    if target_restaurant:
        # Filter orders by specific selected restaurant
        if target_restaurant.is_main_restaurant:
            # Main restaurant: show orders from tables assigned to it OR owned by main owner with no restaurant
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.main_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [target_restaurant.main_owner, target_restaurant.branch_owner] if o])
                )
        else:
            # Branch restaurant: only show orders from tables specifically assigned to this branch
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.branch_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [target_restaurant.main_owner, target_restaurant.branch_owner] if o])
                )
    elif request.user.is_administrator():
        # Administrator sees all orders
        orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
            .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category').all()
    else:
        # Get orders from all accessible restaurants
        accessible_restaurants = restaurant_context['accessible_restaurants']

        if accessible_restaurants.exists():
            order_query = Q()
            for restaurant in accessible_restaurants:
                order_query |= (
                    Q(table_info__restaurant=restaurant) |
                    Q(table_info__owner=restaurant.main_owner, table_info__restaurant__isnull=True) |
                    Q(table_info__owner=restaurant.branch_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [restaurant.main_owner, restaurant.branch_owner] if o])
                )
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(order_query)
        else:
            orders = Order.objects.none()
    
    # Customer care sees only their own orders
    if request.user.is_customer_care() and not (request.user.is_owner() or 
                                                  request.user.is_main_owner() or 
                                                  request.user.is_branch_owner()):
        orders = orders.filter(ordered_by=request.user)
    
    # Apply period filter using timezone-aware datetime boundaries.
    # PostgreSQL extracts __date in UTC; orders placed between midnight-3am local (UTC+3)
    # have a UTC date one day earlier, causing them to vanish from Today/Weekly filters.
    # Fix: use timezone.make_aware() with naive midnight datetimes - Django converts them
    # to UTC correctly using settings.TIME_ZONE (Africa/Nairobi).
    now_local = timezone.localtime(timezone.now())
    today = now_local.date()
    if period == 'today':
        start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        end = timezone.make_aware(datetime.combine(today + timedelta(days=1), datetime.min.time()))
        orders = orders.filter(created_at__gte=start, created_at__lt=end)
    elif period == 'weekly':
        week_start = today - timedelta(days=6)  # Last 7 days including today
        start = timezone.make_aware(datetime.combine(week_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    elif period == 'monthly':
        month_start = today.replace(day=1)
        start = timezone.make_aware(datetime.combine(month_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        start = timezone.make_aware(datetime.combine(year_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    # 'all' period means no date filter - show all orders
    
    # Apply category filter
    if category_id != 'all':
        orders = orders.filter(order_items__product__main_category_id=category_id).distinct()
    
    # Apply subcategory filter
    if subcategory_id != 'all':
        orders = orders.filter(order_items__product__sub_category_id=subcategory_id).distinct()
    
    # Apply payment status filter
    if payment_status == 'paid':
        orders = orders.filter(payment_status='paid')
    elif payment_status == 'unpaid':
        orders = orders.filter(payment_status='unpaid')
    elif payment_status == 'partial':
        orders = orders.filter(payment_status='partial')
    
    # Apply custom date filters (only when period allows custom dates)
    if (period == 'all' or period == 'custom') and (from_date or to_date):
        if from_date:
            try:
                from_dt = datetime.strptime(from_date, '%Y-%m-%d').date()
                orders = orders.filter(created_at__gte=timezone.make_aware(datetime.combine(from_dt, datetime.min.time())))
            except (ValueError, TypeError):
                pass
        if to_date:
            try:
                to_dt = datetime.strptime(to_date, '%Y-%m-%d').date()
                end_dt = timezone.make_aware(datetime.combine(to_dt + timedelta(days=1), datetime.min.time()))
                orders = orders.filter(created_at__lt=end_dt)
            except (ValueError, TypeError):
                pass
    
    # Apply station filtering (Kitchen/Bar/Buffet/Service/All)
    if station_filter == 'kitchen':
        # Filter orders that have kitchen items
        orders = orders.filter(order_items__product__station='kitchen').distinct()
    elif station_filter == 'bar':
        # Filter orders that have bar items
        orders = orders.filter(order_items__product__station='bar').distinct()
    elif station_filter == 'buffet':
        # Filter orders that have buffet items
        orders = orders.filter(order_items__product__station='buffet').distinct()
    elif station_filter == 'service':
        # Filter orders that have service items
        orders = orders.filter(order_items__product__station='service').distinct()
    # 'all' means no station filter
    
    # Apply staff filtering (filter by who created the order)
    if staff_filter != 'all':
        try:
            staff_id = int(staff_filter)
            orders = orders.filter(ordered_by_id=staff_id)
        except (ValueError, TypeError):
            pass  # Invalid staff_filter, ignore

    # Apply product filter (only orders containing this specific product)
    if product_id != 'all':
        orders = orders.filter(order_items__product_id=product_id).distinct()

    # Apply table filter (only orders from this specific table)
    if table_id != 'all':
        orders = orders.filter(table_info_id=table_id)

    # Apply payment method filter (cash/card/digital/voucher)
    if payment_method != 'all':
        orders = orders.filter(payments__payment_method=payment_method, payments__is_voided=False).distinct()

    # Helper functions for station detection
    # Helper functions for station analysis
    def has_kitchen_items(order):
        return any(item.product and item.product.station == 'kitchen' for item in order.order_items.all())

    def has_bar_items(order):
        return any(item.product and item.product.station == 'bar' for item in order.order_items.all())

    def has_buffet_items(order):
        return any(item.product and item.product.station == 'buffet' for item in order.order_items.all())

    def has_service_items(order):
        return any(item.product and item.product.station == 'service' for item in order.order_items.all())

    # Calculate summary data with optimized queries
    total_orders = orders.count()
    _item_filter_active = (product_id != 'all' or category_id != 'all' or subcategory_id != 'all' or station_filter != 'all')
    if _item_filter_active:
        _stats_items = OrderItem.objects.filter(order__in=orders)
        if category_id != 'all':
            _stats_items = _stats_items.filter(product__main_category_id=category_id)
        if subcategory_id != 'all':
            _stats_items = _stats_items.filter(product__sub_category_id=subcategory_id)
        if station_filter != 'all':
            _stats_items = _stats_items.filter(product__station=station_filter)
        if product_id != 'all':
            _stats_items = _stats_items.filter(product_id=product_id)
        total_revenue = sum(item.quantity * item.unit_price for item in _stats_items) or 0
        total_items = _stats_items.aggregate(total=Sum('quantity'))['total'] or 0
    else:
        _stats_items = None
        total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
        total_items = OrderItem.objects.filter(order__in=orders).aggregate(total=Sum('quantity'))['total'] or 0
    avg_order_value = (total_revenue / total_orders) if total_orders > 0 else 0
    
    from decimal import Decimal

    # Get tax rate for display (must come before any tax calculation)
    tax_rate_percentage = 0
    if orders.exists():
        first_order = orders.first()
        tax_rate_percentage = first_order.tax_rate
    elif target_restaurant and hasattr(target_restaurant, 'tax_rate'):
        tax_rate_percentage = float(target_restaurant.tax_rate * 100)
    elif request.user.tax_rate:
        tax_rate_percentage = float(request.user.tax_rate * 100)
    _tax_rate_decimal = Decimal(str(tax_rate_percentage)) / Decimal('100')

    # Calculate tax on the correct revenue base.
    # When a filter is active, tax must be on filtered items revenue only —
    # calling order.get_tax_amount() would use the full order subtotal and give wrong figures.
    if _item_filter_active:
        total_tax = (Decimal(str(total_revenue)) * _tax_rate_decimal).quantize(Decimal('0.01'))
    else:
        total_tax = Decimal('0.00')
        for order in orders:
            total_tax += order.get_tax_amount()
        # sum(total_amount) is tax-inclusive; derive pre-tax base to avoid double-counting
        _total_rev_with_tax = Decimal(str(total_revenue))
        total_revenue = _total_rev_with_tax - total_tax
        avg_order_value = (total_revenue / total_orders) if total_orders > 0 else 0
    total_revenue_with_tax = Decimal(str(total_revenue)) + total_tax
    avg_order_value_with_tax = (total_revenue_with_tax / total_orders) if total_orders > 0 else 0
    # Use effective tax rate for display when current rate is 0 but historical tax exists
    if tax_rate_percentage == 0 and total_tax > 0 and total_revenue > 0:
        tax_rate_percentage = round(float(total_tax / Decimal(str(total_revenue)) * 100), 1)
    
    # Calculate payment status counts and revenues
    paid_orders = orders.filter(payment_status='paid')
    paid_orders_count = paid_orders.count()
    if _item_filter_active and _stats_items is not None:
        paid_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='paid')) or 0
    else:
        paid_revenue = paid_orders.aggregate(total=Sum('total_amount'))['total'] or 0
    if _item_filter_active:
        paid_tax = (Decimal(str(paid_revenue)) * _tax_rate_decimal).quantize(Decimal('0.01'))
    else:
        paid_tax = Decimal('0.00')
        for order in paid_orders:
            paid_tax += order.get_tax_amount()
        paid_revenue = Decimal(str(paid_revenue)) - paid_tax
    paid_revenue_with_tax = Decimal(str(paid_revenue)) + paid_tax

    unpaid_orders = orders.filter(payment_status='unpaid')
    unpaid_orders_count = unpaid_orders.count()
    if _item_filter_active and _stats_items is not None:
        unpaid_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='unpaid')) or 0
    else:
        unpaid_revenue = unpaid_orders.aggregate(total=Sum('total_amount'))['total'] or 0
    if _item_filter_active:
        unpaid_tax = (Decimal(str(unpaid_revenue)) * _tax_rate_decimal).quantize(Decimal('0.01'))
    else:
        unpaid_tax = Decimal('0.00')
        for order in unpaid_orders:
            unpaid_tax += order.get_tax_amount()
        unpaid_revenue = Decimal(str(unpaid_revenue)) - unpaid_tax
    unpaid_revenue_with_tax = Decimal(str(unpaid_revenue)) + unpaid_tax

    partial_orders = orders.filter(payment_status='partial')
    partial_orders_count = partial_orders.count()
    if _item_filter_active and _stats_items is not None:
        partial_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='partial')) or 0
    else:
        partial_revenue = partial_orders.aggregate(total=Sum('total_amount'))['total'] or 0
    if _item_filter_active:
        partial_tax = (Decimal(str(partial_revenue)) * _tax_rate_decimal).quantize(Decimal('0.01'))
    else:
        partial_tax = Decimal('0.00')
        for order in partial_orders:
            partial_tax += order.get_tax_amount()
        partial_revenue = Decimal(str(partial_revenue)) - partial_tax
    partial_revenue_with_tax = Decimal(str(partial_revenue)) + partial_tax
    
    # Calculate station-specific metrics
    kitchen_orders_count = len([o for o in orders if has_kitchen_items(o)]) if station_filter == 'all' else (total_orders if station_filter == 'kitchen' else 0)
    bar_orders_count = len([o for o in orders if has_bar_items(o)]) if station_filter == 'all' else (total_orders if station_filter == 'bar' else 0)
    buffet_orders_count = len([o for o in orders if has_buffet_items(o)]) if station_filter == 'all' else (total_orders if station_filter == 'buffet' else 0)
    service_orders_count = len([o for o in orders if has_service_items(o)]) if station_filter == 'all' else (total_orders if station_filter == 'service' else 0)
    mixed_orders_count = len([o for o in orders if sum([has_kitchen_items(o), has_bar_items(o), has_buffet_items(o), has_service_items(o)]) > 1]) if station_filter == 'all' else 0
    
    # Top selling products analysis (moved after categories are defined — see below)
    
    # Get staff users for filtering - only those who can create orders
    # Get all staff from the current restaurant context
    if target_restaurant:
        # Get staff for specific restaurant
        if target_restaurant.is_main_restaurant:
            staff_users = User.objects.filter(
                Q(owner=target_restaurant.main_owner) |
                Q(id=target_restaurant.main_owner_id)
            ).filter(
                role__name__in=['customer_care', 'cashier']
            ).distinct().order_by('first_name', 'last_name')
        else:
            staff_users = User.objects.filter(
                Q(owner=target_restaurant.branch_owner) |
                Q(id=target_restaurant.branch_owner_id)
            ).filter(
                role__name__in=['customer_care', 'cashier']
            ).distinct().order_by('first_name', 'last_name')
    elif request.user.is_administrator():
        # Admin sees all staff
        staff_users = User.objects.filter(
            role__name__in=['customer_care', 'cashier']
        ).order_by('first_name', 'last_name')
    else:
        # Get staff from accessible restaurants
        accessible_restaurants = restaurant_context['accessible_restaurants']
        staff_query = Q()
        for restaurant in accessible_restaurants:
            if restaurant.main_owner:
                staff_query |= Q(owner=restaurant.main_owner) | Q(id=restaurant.main_owner_id)
            if restaurant.branch_owner:
                staff_query |= Q(owner=restaurant.branch_owner) | Q(id=restaurant.branch_owner_id)
        staff_users = User.objects.filter(staff_query).filter(
            role__name__in=['customer_care', 'cashier']
        ).distinct().order_by('first_name', 'last_name')
    
    # Get orders for table with pagination
    orders_list = orders.prefetch_related('payments__processed_by').order_by('-created_at')
    
    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(orders_list, 10)  # Show 10 orders per page
    page_obj = paginator.get_page(page_number)

    # Attach per-order display total for the template rows.
    # When a filter is active the row must show only filtered-item revenue,
    # not order.total_amount (which is the full-order subtotal).
    if _item_filter_active and _stats_items is not None:
        _filtered_totals_map = {}
        for _si in _stats_items:
            _filtered_totals_map[_si.order_id] = (
                _filtered_totals_map.get(_si.order_id, Decimal('0.00'))
                + _si.quantity * _si.unit_price
            )
        for _o in page_obj:
            _o.row_display_total = _filtered_totals_map.get(_o.id, Decimal('0.00'))
    else:
        for _o in page_obj:
            _o.row_display_total = _o.total_amount
    
    # Get categories and subcategories for the current restaurant context
    if target_restaurant:
        if target_restaurant.is_main_restaurant:
            categories = MainCategory.objects.filter(
                Q(restaurant=target_restaurant) |
                Q(owner=target_restaurant.main_owner, restaurant__isnull=True)
            )
        else:
            branch_query = Q(restaurant=target_restaurant)
            if target_restaurant.branch_owner:
                branch_query |= Q(owner=target_restaurant.branch_owner, restaurant__isnull=True)
            categories = MainCategory.objects.filter(branch_query)
    elif request.user.is_administrator():
        categories = MainCategory.objects.all()
    else:
        accessible_restaurants = restaurant_context['accessible_restaurants']
        if accessible_restaurants.exists():
            cat_query = Q()
            for restaurant in accessible_restaurants:
                cat_query |= Q(restaurant=restaurant)
                if restaurant.main_owner:
                    cat_query |= Q(owner=restaurant.main_owner, restaurant__isnull=True)
                if restaurant.branch_owner:
                    cat_query |= Q(owner=restaurant.branch_owner, restaurant__isnull=True)
            categories = MainCategory.objects.filter(cat_query)
        else:
            categories = MainCategory.objects.none()
    
    subcategories = SubCategory.objects.filter(main_category__in=categories)

    # Build products dropdown scoped to current category/subcategory selection
    from restaurant.models import Product as ProductModel, TableInfo as TableInfoModel
    products_qs = ProductModel.objects.filter(
        main_category__in=categories, is_available=True
    ).select_related('main_category', 'sub_category').order_by('main_category__name', 'name')
    if subcategory_id != 'all':
        products_qs = products_qs.filter(sub_category_id=subcategory_id)
    elif category_id != 'all':
        products_qs = products_qs.filter(main_category_id=category_id)

    # Build tables dropdown scoped to current restaurant context
    if target_restaurant:
        tables_qs = TableInfoModel.objects.filter(restaurant=target_restaurant).order_by('tbl_no')
    elif request.user.is_administrator():
        tables_qs = TableInfoModel.objects.all().select_related('restaurant').order_by('tbl_no')
    else:
        accessible_restaurants = restaurant_context['accessible_restaurants']
        if accessible_restaurants.exists():
            tables_qs = TableInfoModel.objects.filter(
                restaurant__in=accessible_restaurants
            ).select_related('restaurant').order_by('tbl_no')
        else:
            tables_qs = TableInfoModel.objects.none()

    # SECURITY: scope top products to this restaurant's own categories only
    top_products = OrderItem.objects.filter(order__in=orders, product__main_category__in=categories)\
        .values('product__name', 'product__station')\
        .annotate(
            total_quantity=Sum('quantity'),
            total_revenue=ExpressionWrapper(
                Sum(F('unit_price') * F('quantity')),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )\
        .order_by('-total_quantity')[:5]

    # Filter subcategories by selected category if applicable
    if category_id != 'all':
        subcategories = subcategories.filter(main_category_id=category_id)
    
    # Get selected category/subcategory names for template display
    selected_category_name = None
    selected_subcategory_name = None
    # SECURITY: validate against restaurant-scoped querysets — prevents cross-tenant name leakage
    if category_id != 'all':
        _cat = categories.filter(id=category_id).first()
        selected_category_name = _cat.name if _cat else None
    if subcategory_id != 'all':
        _subcat = subcategories.filter(id=subcategory_id).first()
        selected_subcategory_name = _subcat.name if _subcat else None

    # Resolve selected product and table display names
    # SECURITY: validate against restaurant-scoped querysets — prevents cross-tenant name leakage
    selected_product_name = None
    selected_table_name = None
    if product_id != 'all':
        try:
            _prod = ProductModel.objects.filter(id=product_id, main_category__in=categories).first()
            if _prod:
                selected_product_name = _prod.name
            else:
                product_id = 'all'
        except (ValueError, Exception):
            product_id = 'all'
    if table_id != 'all':
        try:
            _tbl = tables_qs.filter(id=table_id).first()
            if _tbl:
                selected_table_name = _tbl.tbl_no
            else:
                table_id = 'all'
        except (ValueError, Exception):
            table_id = 'all'

    # Payment method breakdown (cash/card/digital/voucher counts and totals)
    from cashier.models import Payment as PaymentModel
    _method_qs = PaymentModel.objects.filter(order__in=orders, is_voided=False)\
        .values('payment_method')\
        .annotate(count=Count('id'), total=Sum('amount'))\
        .order_by('payment_method')
    payment_method_stats = {row['payment_method']: row for row in _method_qs}
    cash_count    = payment_method_stats.get('cash',    {}).get('count', 0)
    cash_total    = payment_method_stats.get('cash',    {}).get('total', 0) or 0
    card_count    = payment_method_stats.get('card',    {}).get('count', 0)
    card_total    = payment_method_stats.get('card',    {}).get('total', 0) or 0
    digital_count = payment_method_stats.get('digital', {}).get('count', 0)
    digital_total = payment_method_stats.get('digital', {}).get('total', 0) or 0
    voucher_count = payment_method_stats.get('voucher', {}).get('count', 0)
    voucher_total = payment_method_stats.get('voucher', {}).get('total', 0) or 0

    # Today's date for template defaults
    today_str = timezone.now().date().strftime('%Y-%m-%d')

    context = {
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'total_revenue_with_tax': total_revenue_with_tax,
        'total_tax': total_tax,
        'tax_rate_percentage': tax_rate_percentage,
        'total_items': total_items,
        'avg_order_value': avg_order_value,
        'avg_order_value_with_tax': avg_order_value_with_tax,
        'page_obj': page_obj,
        'orders': page_obj,
        'payment_status': payment_status,
        'payment_method': payment_method,
        'cash_count': cash_count, 'cash_total': cash_total,
        'card_count': card_count, 'card_total': card_total,
        'digital_count': digital_count, 'digital_total': digital_total,
        'voucher_count': voucher_count, 'voucher_total': voucher_total,
        'period': period,
        'categories': categories,
        'subcategories': subcategories,
        'selected_category': category_id,
        'selected_subcategory': subcategory_id,
        'selected_category_name': selected_category_name,
        'selected_subcategory_name': selected_subcategory_name,
        'station_filter': station_filter,  # NEW: Station filter value
        'staff_filter': staff_filter,  # NEW: Staff filter value
        'staff_users': staff_users,  # NEW: Staff users list
        'paid_orders_count': paid_orders_count,
        'paid_revenue': paid_revenue,
        'paid_revenue_with_tax': paid_revenue_with_tax,
        'paid_tax': paid_tax,
        'unpaid_orders_count': unpaid_orders_count,
        'unpaid_revenue': unpaid_revenue,
        'unpaid_revenue_with_tax': unpaid_revenue_with_tax,
        'unpaid_tax': unpaid_tax,
        'partial_orders_count': partial_orders_count,
        'partial_revenue': partial_revenue,
        'partial_revenue_with_tax': partial_revenue_with_tax,
        'partial_tax': partial_tax,
        'kitchen_orders_count': kitchen_orders_count,
        'bar_orders_count': bar_orders_count,
        'buffet_orders_count': buffet_orders_count,
        'service_orders_count': service_orders_count,
        'mixed_orders_count': mixed_orders_count,
        'products': products_qs,
        'tables': tables_qs,
        'selected_product': product_id,
        'selected_table': table_id,
        'selected_product_name': selected_product_name,
        'selected_table_name': selected_table_name,
        'top_products': top_products,
        'from_date': from_date,  # Default date values for template
        'to_date': to_date,
        'today': today_str,  # Today's date for reference
        **restaurant_context,  # Include restaurant context for filters
    }
    
    return render(request, 'reports/dashboard.html', context)

@login_required
def export_csv(request):
    """Export filtered data to CSV with station filtering"""
    from django.shortcuts import redirect
    from django.contrib import messages as _messages
    if not (request.user.is_administrator() or request.user.is_owner() or
            request.user.is_main_owner() or request.user.is_branch_owner() or
            request.user.is_customer_care()):
        _messages.error(request, "Access denied. Owner or Customer Care role required.")
        return redirect('restaurant:home')
    
    # Import restaurant context utilities
    from admin_panel.restaurant_utils import get_restaurant_context
    from django.db.models import Q
    
    # Get restaurant context
    session_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant_context = get_restaurant_context(request.user, session_restaurant_id, request)
    current_restaurant = restaurant_context['current_restaurant']
    view_all_restaurants = restaurant_context['view_all_restaurants']
    
    # Get same filters as dashboard
    payment_status = request.GET.get('payment_status', 'all')
    payment_method = request.GET.get('payment_method', 'all')
    period = request.GET.get('period', 'today')  # Default to 'today' same as dashboard
    category_id = request.GET.get('category_id', 'all')
    subcategory_id = request.GET.get('subcategory_id', 'all')
    station_filter = request.GET.get('station_filter', 'all')  # NEW: Station filtering
    product_id = request.GET.get('product_id', 'all')
    table_id = request.GET.get('table_id', 'all')
    staff_filter = request.GET.get('staff_filter', 'all')  # NEW: Staff filtering
    restaurant_filter = request.GET.get('restaurant', '').strip()
    
    # Get date filters (only use if custom period)
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # Determine which restaurant to filter by
    target_restaurant = None
    if restaurant_filter:
        try:
            from restaurant.models_restaurant import Restaurant
            target_restaurant = Restaurant.objects.get(id=restaurant_filter)
            # SECURITY: validate the requesting user has access to this restaurant (IDOR prevention)
            if not request.user.is_administrator():
                accessible_ids = set(restaurant_context['accessible_restaurants'].values_list('id', flat=True))
                if target_restaurant.id not in accessible_ids:
                    target_restaurant = current_restaurant  # fall back silently
        except Restaurant.DoesNotExist:
            target_restaurant = None
    elif current_restaurant and not view_all_restaurants:
        target_restaurant = current_restaurant
    
    # Base queryset - filter by restaurant with optimization
    if target_restaurant:
        if target_restaurant.is_main_restaurant:
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.main_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [target_restaurant.main_owner, target_restaurant.branch_owner] if o])
                )
        else:
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.branch_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [target_restaurant.main_owner, target_restaurant.branch_owner] if o])
                )
    elif request.user.is_administrator():
        orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
            .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category').all()
    else:
        accessible_restaurants = restaurant_context['accessible_restaurants']
        if accessible_restaurants.exists():
            order_query = Q()
            for restaurant in accessible_restaurants:
                order_query |= (
                    Q(table_info__restaurant=restaurant) |
                    Q(table_info__owner=restaurant.main_owner, table_info__restaurant__isnull=True) |
                    Q(table_info__owner=restaurant.branch_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [restaurant.main_owner, restaurant.branch_owner] if o])
                )
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(order_query)
        else:
            orders = Order.objects.none()

    # Customer care sees only their own orders
    if request.user.is_customer_care() and not (request.user.is_owner() or
                                                  request.user.is_main_owner() or
                                                  request.user.is_branch_owner()):
        orders = orders.filter(ordered_by=request.user)
    
    # Apply period filter using timezone-aware datetime boundaries.
    # PostgreSQL extracts __date in UTC; orders placed between midnight-3am local (UTC+3)
    # have a UTC date one day earlier, causing them to vanish from Today/Weekly filters.
    # Fix: use timezone.make_aware() with naive midnight datetimes - Django converts them
    # to UTC correctly using settings.TIME_ZONE (Africa/Nairobi).
    now_local = timezone.localtime(timezone.now())
    today = now_local.date()
    if period == 'today':
        start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        end = timezone.make_aware(datetime.combine(today + timedelta(days=1), datetime.min.time()))
        orders = orders.filter(created_at__gte=start, created_at__lt=end)
    elif period == 'weekly':
        week_start = today - timedelta(days=6)  # Last 7 days including today
        start = timezone.make_aware(datetime.combine(week_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    elif period == 'monthly':
        month_start = today.replace(day=1)
        start = timezone.make_aware(datetime.combine(month_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        start = timezone.make_aware(datetime.combine(year_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    # 'all' period means no date filter - show all orders
    
    # Apply category filter
    if category_id != 'all':
        orders = orders.filter(order_items__product__main_category_id=category_id).distinct()
    
    # Apply subcategory filter
    if subcategory_id != 'all':
        orders = orders.filter(order_items__product__sub_category_id=subcategory_id).distinct()
    
    # Apply payment status filter
    if payment_status == 'paid':
        orders = orders.filter(payment_status='paid')
    elif payment_status == 'unpaid':
        orders = orders.filter(payment_status='unpaid')
    elif payment_status == 'partial':
        orders = orders.filter(payment_status='partial')
    
    # Apply date filters (these override period if specified)
    if from_date:
        orders = orders.filter(created_at__date__gte=from_date)
    if to_date:
        orders = orders.filter(created_at__date__lte=to_date)
    
    # Apply station filtering (Kitchen/Bar/All)
    if station_filter == 'kitchen':
        orders = orders.filter(order_items__product__station='kitchen').distinct()
    elif station_filter == 'bar':
        orders = orders.filter(order_items__product__station='bar').distinct()
    elif station_filter == 'buffet':
        orders = orders.filter(order_items__product__station='buffet').distinct()
    elif station_filter == 'service':
        orders = orders.filter(order_items__product__station='service').distinct()
    
    # Apply staff filtering (filter by who created the order)
    if staff_filter != 'all':
        try:
            staff_id = int(staff_filter)
            orders = orders.filter(ordered_by_id=staff_id)
        except (ValueError, TypeError):
            pass  # Invalid staff_filter, ignore

    # Apply product filter (only orders containing this specific product)
    if product_id != 'all':
        orders = orders.filter(order_items__product_id=product_id).distinct()

    # Apply table filter (only orders from this specific table)
    if table_id != 'all':
        orders = orders.filter(table_info_id=table_id)
    if payment_method != 'all':
        orders = orders.filter(payments__payment_method=payment_method, payments__is_voided=False).distinct()

    # Calculate summary data for the export
    total_orders = orders.count()
    _item_filter_active = (product_id != 'all' or category_id != 'all' or subcategory_id != 'all' or station_filter != 'all')
    if _item_filter_active:
        # AND-chain all active filters (same logic as dashboard) so combined filters are accurate
        _stats_items = OrderItem.objects.filter(order__in=orders)
        if category_id != 'all':
            _stats_items = _stats_items.filter(product__main_category_id=category_id)
        if subcategory_id != 'all':
            _stats_items = _stats_items.filter(product__sub_category_id=subcategory_id)
        if station_filter != 'all':
            _stats_items = _stats_items.filter(product__station=station_filter)
        if product_id != 'all':
            _stats_items = _stats_items.filter(product_id=product_id)
        total_revenue = sum(item.quantity * item.unit_price for item in _stats_items) or 0
        total_items = _stats_items.aggregate(total=Sum('quantity'))['total'] or 0
    else:
        total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
        total_items = OrderItem.objects.filter(order__in=orders).aggregate(total=Sum('quantity'))['total'] or 0
    avg_order_value = (total_revenue / total_orders) if total_orders > 0 else 0

    # Separate tax from revenue so CSV matches dashboard (total_amount is tax-inclusive)
    from decimal import Decimal as _D
    if not _item_filter_active:
        _csv_total_tax = sum(_o.get_tax_amount() for _o in orders)
        total_revenue = _D(str(orders.aggregate(total=Sum('total_amount'))['total'] or 0)) - _D(str(_csv_total_tax))
    else:
        _csv_total_tax = _D('0.00')

    # Calculate payment status breakdown
    paid_orders = orders.filter(payment_status='paid')
    paid_orders_count = paid_orders.count()
    if _item_filter_active:
        paid_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='paid')) or 0
    else:
        _pr_tax = sum(_o.get_tax_amount() for _o in paid_orders)
        paid_revenue = _D(str(paid_orders.aggregate(total=Sum('total_amount'))['total'] or 0)) - _D(str(_pr_tax))

    unpaid_orders = orders.filter(payment_status='unpaid')
    unpaid_orders_count = unpaid_orders.count()
    if _item_filter_active:
        unpaid_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='unpaid')) or 0
    else:
        _ur_tax = sum(_o.get_tax_amount() for _o in unpaid_orders)
        unpaid_revenue = _D(str(unpaid_orders.aggregate(total=Sum('total_amount'))['total'] or 0)) - _D(str(_ur_tax))

    partial_orders = orders.filter(payment_status='partial')
    partial_orders_count = partial_orders.count()
    if _item_filter_active:
        partial_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='partial')) or 0
    else:
        _par_tax = sum(_o.get_tax_amount() for _o in partial_orders)
        partial_revenue = _D(str(partial_orders.aggregate(total=Sum('total_amount'))['total'] or 0)) - _D(str(_par_tax))
    
    # Get currency symbol from user settings
    currency_symbol = User.CURRENCY_SYMBOLS.get(request.user.currency_code, '$')
    
    # Determine the period description for the report
    if from_date and to_date:
        period_desc = f"Custom Period: {from_date} to {to_date}"
    elif from_date:
        period_desc = f"From: {from_date}"
    elif to_date:
        period_desc = f"Until: {to_date}"
    elif period == 'today':
        period_desc = f"Today: {today}"
    elif period == 'weekly':
        week_start = today - timedelta(days=today.weekday())
        period_desc = f"This Week: {week_start} to {today}"
    elif period == 'monthly':
        month_start = today.replace(day=1)
        period_desc = f"This Month: {month_start} to {today}"
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        period_desc = f"This Year: {year_start} to {today}"
    else:
        period_desc = "All Time"
    
    # Add filters to period description
    if station_filter != 'all':
        period_desc += f" (Station: {station_filter.title()})"
    if staff_filter != 'all':
        try:
            # SECURITY: only resolve user if they have orders in the already-scoped queryset
            # prevents cross-tenant user name/role enumeration via arbitrary staff_filter IDs
            if orders.filter(ordered_by_id=int(staff_filter)).exists():
                staff_user = User.objects.get(id=int(staff_filter))
                period_desc += f" (Staff: {staff_user.first_name} {staff_user.last_name})"
        except (User.DoesNotExist, ValueError):
            pass
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="sales_report_{payment_status}_{period}_{datetime.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    
    # Write summary header
    writer.writerow(['SALES REPORT SUMMARY'])
    writer.writerow(['Generated on:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow(['Period:', period_desc])
    writer.writerow(['Payment Status Filter:', payment_status.title()])
    writer.writerow(['Payment Method Filter:', payment_method.title() if payment_method != 'all' else 'All'])
    writer.writerow(['Station Filter:', station_filter.title()])
    if staff_filter != 'all':
        try:
            # SECURITY: only resolve user if they have orders in the already-scoped queryset
            if orders.filter(ordered_by_id=int(staff_filter)).exists():
                staff_user = User.objects.get(id=int(staff_filter))
                writer.writerow(['Staff Filter:', f'{staff_user.first_name} {staff_user.last_name} ({staff_user.role.get_name_display()})'])
        except (User.DoesNotExist, ValueError):
            pass
    if target_restaurant:
        writer.writerow(['Restaurant:', target_restaurant.name])
    if category_id != 'all':
        # SECURITY: anchor lookup to already-scoped orders — prevents cross-tenant name leakage
        _cat = MainCategory.objects.filter(
            id=category_id
        ).values('name').first()
        writer.writerow(['Category Filter:', _cat['name'] if _cat else f'Category ID {category_id}'])
    if subcategory_id != 'all':
        _subcat = SubCategory.objects.filter(
            id=subcategory_id
        ).values('name').first()
        writer.writerow(['Sub Category Filter:', _subcat['name'] if _subcat else f'Sub Category ID {subcategory_id}'])
    if product_id != 'all':
        try:
            from restaurant.models import Product as ProductModel
            if target_restaurant:
                _valid_cats = MainCategory.objects.filter(
                    Q(restaurant=target_restaurant) |
                    Q(owner=target_restaurant.main_owner, restaurant__isnull=True)
                )
            elif not request.user.is_administrator():
                _accessible = restaurant_context['accessible_restaurants']
                _cat_q = Q()
                for _r in _accessible:
                    _cat_q |= Q(restaurant=_r)
                    if _r.main_owner: _cat_q |= Q(owner=_r.main_owner, restaurant__isnull=True)
                    if _r.branch_owner: _cat_q |= Q(owner=_r.branch_owner, restaurant__isnull=True)
                _valid_cats = MainCategory.objects.filter(_cat_q)
            else:
                _valid_cats = None
            _prod = (ProductModel.objects.filter(id=product_id, main_category__in=_valid_cats)
                     if _valid_cats is not None else ProductModel.objects.filter(id=product_id)).first()
            if _prod:
                writer.writerow(['Product Filter:', _prod.name])
            else:
                writer.writerow(['Product Filter:', f'Product ID {product_id}'])
        except Exception:
            writer.writerow(['Product Filter:', f'Product ID {product_id}'])
    if table_id != 'all':
        try:
            from restaurant.models import TableInfo as TableInfoModel
            if target_restaurant:
                _tbl = TableInfoModel.objects.filter(id=table_id, restaurant=target_restaurant).first()
            elif not request.user.is_administrator():
                _accessible = restaurant_context['accessible_restaurants']
                _tbl = TableInfoModel.objects.filter(id=table_id, restaurant__in=_accessible).first()
            else:
                _tbl = TableInfoModel.objects.filter(id=table_id).first()
            if _tbl:
                writer.writerow(['Table Filter:', f'Table {_tbl.tbl_no}'])
            else:
                writer.writerow(['Table Filter:', f'Table ID {table_id}'])
        except Exception:
            writer.writerow(['Table Filter:', f'Table ID {table_id}'])
    writer.writerow([])  # Empty row
    
    # Write summary statistics
    writer.writerow(['SUMMARY STATISTICS'])
    writer.writerow(['Revenue:', f'{currency_symbol}{total_revenue:,.2f}'])
    writer.writerow(['Total Orders:', f'{total_orders:,}'])
    writer.writerow(['Items Sold:', f'{total_items:,}'])
    writer.writerow([])  # Empty row
    
    # Write payment status breakdown
    writer.writerow(['PAYMENT STATUS BREAKDOWN'])
    writer.writerow(['Paid Orders:', f'{paid_orders_count:,}', f'{currency_symbol}{paid_revenue:,.2f}'])
    writer.writerow(['Unpaid Orders:', f'{unpaid_orders_count:,}', f'{currency_symbol}{unpaid_revenue:,.2f}'])
    writer.writerow(['Partial Payments:', f'{partial_orders_count:,}', f'{currency_symbol}{partial_revenue:,.2f}'])
    writer.writerow([])  # Empty row
    
    # Payment method breakdown
    from cashier.models import Payment as _CsvPaymentModel
    from django.db.models import Sum as _CsvSum, Count as _CsvCount
    _csv_method_qs = _CsvPaymentModel.objects.filter(order__in=orders, is_voided=False)\
        .values('payment_method').annotate(count=_CsvCount('id'), total=_CsvSum('amount')).order_by('payment_method')
    _csv_method_map = {r['payment_method']: r for r in _csv_method_qs}
    writer.writerow(['PAYMENT METHOD BREAKDOWN'])
    writer.writerow(['Method', 'Transactions', 'Total Amount'])
    for _method in ['cash', 'card', 'digital', 'voucher']:
        _row = _csv_method_map.get(_method, {})
        if _row:
            writer.writerow([_method.title(), f"{_row['count']:,}", f"{currency_symbol}{_row['total']:,.2f}"])
    writer.writerow([])  # Empty row
    
    # Branch Performance Analysis (only when viewing all restaurants for PRO plan)
    if not target_restaurant and not request.user.is_administrator():
        accessible_restaurants = restaurant_context['accessible_restaurants']
        
        # Check if user has multiple locations (main + branch, or multiple branches)
        has_multiple_locations = accessible_restaurants.count() > 1
        
        if has_multiple_locations:
            writer.writerow([])  # Empty row
            writer.writerow(['BRANCH/LOCATION PERFORMANCE ANALYSIS'])
            writer.writerow(['Location', 'Orders', '% of Total Orders', 'Revenue', '% of Total Revenue', 'Avg Order Value'])
            
            for restaurant in accessible_restaurants.order_by('name'):
                # Get orders for this specific location
                # CRITICAL FIX: Legacy orders (no restaurant) should ONLY count for MAIN restaurant
                if restaurant.is_main_restaurant:
                    restaurant_orders = orders.filter(
                        Q(table_info__restaurant=restaurant) |
                        Q(table_info__owner=restaurant.main_owner, table_info__restaurant__isnull=True)
                    )
                else:
                    # Branches: ONLY direct orders assigned to this branch, NO legacy orders
                    restaurant_orders = orders.filter(table_info__restaurant=restaurant)
                
                location_order_count = restaurant_orders.count()
                location_revenue = restaurant_orders.aggregate(total=Sum('total_amount'))['total'] or 0
                location_avg = (location_revenue / location_order_count) if location_order_count > 0 else 0
                
                order_percentage = (location_order_count / total_orders * 100) if total_orders > 0 else 0
                revenue_percentage = (location_revenue / total_revenue * 100) if total_revenue > 0 else 0
                
                location_label = f"{restaurant.name}"
                if not restaurant.is_main_restaurant:
                    location_label += " (Branch)"
                
                writer.writerow([
                    location_label,
                    f'{location_order_count:,}',
                    f'{order_percentage:.1f}%',
                    f'{currency_symbol}{location_revenue:,.2f}',
                    f'{revenue_percentage:.1f}%',
                    f'{currency_symbol}{location_avg:.2f}'
                ])
            
            writer.writerow([])  # Empty row
            
            # Top Products by Location
            writer.writerow(['TOP PRODUCTS BY LOCATION'])
            writer.writerow(['Location', 'Product', 'Quantity Sold', 'Revenue', '% of Location Revenue'])
            
            for restaurant in accessible_restaurants.order_by('name'):
                # Get orders for this location
                # CRITICAL FIX: Legacy orders (no restaurant) should ONLY count for MAIN restaurant
                if restaurant.is_main_restaurant:
                    restaurant_orders = orders.filter(
                        Q(table_info__restaurant=restaurant) |
                        Q(table_info__owner=restaurant.main_owner, table_info__restaurant__isnull=True)
                    )
                else:
                    # Branches: ONLY direct orders assigned to this branch, NO legacy orders
                    restaurant_orders = orders.filter(table_info__restaurant=restaurant)
                
                location_revenue = restaurant_orders.aggregate(total=Sum('total_amount'))['total'] or 0
                
                if restaurant_orders.exists():
                    # Get top 5 products for this location
                    top_products = OrderItem.objects.filter(order__in=restaurant_orders)\
                        .values('product__name')\
                        .annotate(
                            total_quantity=Sum('quantity'),
                            total_revenue=ExpressionWrapper(
                                Sum(F('unit_price') * F('quantity')),
                                output_field=DecimalField(max_digits=12, decimal_places=2)
                            )
                        )\
                        .order_by('-total_quantity')[:5]
                    
                    location_label = _safe_csv(restaurant.name)
                    if not restaurant.is_main_restaurant:
                        location_label += " (Branch)"
                    
                    for idx, product in enumerate(top_products):
                        product_percentage = (product['total_revenue'] / location_revenue * 100) if location_revenue > 0 else 0
                        
                        writer.writerow([
                            location_label if idx == 0 else '',  # Only show location name on first row
                            _safe_csv(product['product__name']),
                            f"{product['total_quantity']:,}",
                            f"{currency_symbol}{product['total_revenue']:,.2f}",
                            f"{product_percentage:.1f}%"
                        ])
                    
                    if not top_products:
                        writer.writerow([location_label, 'No products sold', '-', '-', '-'])
            
            writer.writerow([])  # Empty row
    
    writer.writerow([])  # Empty row
    
    # Write detailed data header
    writer.writerow(['DETAILED SALES DATA'])
    writer.writerow(['Order ID', 'Customer', 'Date', 'Table', 'Restaurant/Branch', 'Items', 'Categories', 'Sub Categories', 'Stations', 'Total Amount', 'Payment Status', 'Payment Method', 'Order Status', 'Order By', 'Paid By'])
    
    # Get selected category/subcategory names for display
    # SECURITY: anchor to already-scoped orders — prevents cross-tenant name leakage
    selected_category_name = None
    selected_subcategory_name = None
    if category_id != 'all':
        _cat = MainCategory.objects.filter(
            id=category_id
        ).values('name').first()
        selected_category_name = _cat['name'] if _cat else None
    if subcategory_id != 'all':
        _subcat = SubCategory.objects.filter(
            id=subcategory_id
        ).values('name').first()
        selected_subcategory_name = _subcat['name'] if _subcat else None
    
    for order in orders.order_by('-created_at'):
        all_items = list(order.order_items.all())
        
        # Filter items for Items column based on active filter.
        # Priority: product (most specific) > subcategory > category > station
        filtered_items = []
        if product_id != 'all':
            for item in all_items:
                if str(item.product_id) == str(product_id):
                    filtered_items.append(item)
        elif subcategory_id != 'all':
            # Filter by subcategory
            for item in all_items:
                if item.product and item.product.sub_category and str(item.product.sub_category_id) == str(subcategory_id):
                    filtered_items.append(item)
        elif category_id != 'all':
            # Filter by category
            for item in all_items:
                if item.product and str(item.product.main_category_id) == str(category_id):
                    filtered_items.append(item)
        elif station_filter != 'all':
            # Filter by station
            for item in all_items:
                if item.product and item.product.station == station_filter:
                    filtered_items.append(item)
        else:
            # No filter - show all items
            filtered_items = all_items
        
        # Items column: shows filtered items
        items_list = ', '.join([f"{(item.product.name if item.product else '[deleted]')} x{item.quantity}" for item in filtered_items])

        # Categories column: if filter active show filter name, else show ALL categories from ALL items
        if selected_category_name:
            categories_list = selected_category_name
        else:
            categories_list = ', '.join(set([item.product.main_category.name for item in all_items if item.product and item.product.main_category])) if all_items else ''

        # SubCategories column: if filter active show filter name, else show ALL subcategories from ALL items
        if selected_subcategory_name:
            subcategories_list = selected_subcategory_name
        else:
            subcategories_list = ', '.join(set([item.product.sub_category.name if item.product and item.product.sub_category else '-' for item in all_items])) if all_items else ''

        # Stations column: if filter active show filter name, else show ALL stations from ALL items
        if station_filter != 'all':
            stations_list = station_filter.title()
        else:
            stations_list = ', '.join(set([item.product.station.title() for item in all_items if item.product and item.product.station])) if all_items else ''
        
        table_number = order.table_info.tbl_no if order.table_info else '-'
        customer_name = f"{order.ordered_by.first_name} {order.ordered_by.last_name}" if order.ordered_by else 'Walk-in Customer'
        
        # Order By column
        order_by_name = f"{order.ordered_by.first_name} {order.ordered_by.last_name} ({order.ordered_by.role.get_name_display()})" if order.ordered_by else '-'
        
        # Paid By column - get all payments
        paid_by_names = []
        if hasattr(order, 'payments'):
            for payment in order.payments.all():
                if not payment.is_voided and payment.processed_by:
                    paid_by_names.append(f"{payment.processed_by.first_name} {payment.processed_by.last_name} ({payment.processed_by.role.get_name_display()})")
        paid_by_name = ', '.join(paid_by_names) if paid_by_names else '-'
        
        # Get restaurant/branch name for this order
        order_restaurant = order.table_info.restaurant.name if order.table_info and order.table_info.restaurant else 'Legacy'
        if order.table_info and order.table_info.restaurant and not order.table_info.restaurant.is_main_restaurant:
            order_restaurant += ' (Branch)'
        
        writer.writerow([
            order.order_number,
            customer_name,
            order.created_at.strftime('%Y-%m-%d %H:%M'),
            table_number,
            order_restaurant,
            items_list,
            categories_list,
            subcategories_list,
            stations_list,
            f"{currency_symbol}{sum(item.quantity * item.unit_price for item in filtered_items):.2f}",
            order.payment_status,
            ', '.join(sorted(set(p.payment_method.title() for p in order.payments.all() if not p.is_voided))) or '-',
            order.status,
            order_by_name,
            paid_by_name
        ])
    
    return response

@login_required
def export_pdf(request):
    """Export filtered data to PDF with station filtering"""
    from django.shortcuts import redirect
    from django.contrib import messages as _messages
    if not (request.user.is_administrator() or request.user.is_owner() or
            request.user.is_main_owner() or request.user.is_branch_owner() or
            request.user.is_customer_care()):
        _messages.error(request, "Access denied. Owner or Customer Care role required.")
        return redirect('restaurant:home')
    
    # Import restaurant context utilities
    from admin_panel.restaurant_utils import get_restaurant_context
    from django.db.models import Q
    
    # Get restaurant context
    session_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant_context = get_restaurant_context(request.user, session_restaurant_id, request)
    current_restaurant = restaurant_context['current_restaurant']
    view_all_restaurants = restaurant_context['view_all_restaurants']
    
    # Get same filters as dashboard
    payment_status = request.GET.get('payment_status', 'all')
    payment_method = request.GET.get('payment_method', 'all')
    period = request.GET.get('period', 'today')  # Default to 'today' same as dashboard
    category_id = request.GET.get('category_id', 'all')
    subcategory_id = request.GET.get('subcategory_id', 'all')
    station_filter = request.GET.get('station_filter', 'all')  # NEW: Station filtering
    product_id = request.GET.get('product_id', 'all')
    table_id = request.GET.get('table_id', 'all')
    staff_filter = request.GET.get('staff_filter', 'all')  # NEW: Staff filtering
    restaurant_filter = request.GET.get('restaurant', '').strip()
    
    # Get date filters (only use if custom period)
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    # Determine which restaurant to filter by
    target_restaurant = None
    if restaurant_filter:
        try:
            from restaurant.models_restaurant import Restaurant
            target_restaurant = Restaurant.objects.get(id=restaurant_filter)
            # SECURITY: validate the requesting user has access to this restaurant (IDOR prevention)
            if not request.user.is_administrator():
                accessible_ids = set(restaurant_context['accessible_restaurants'].values_list('id', flat=True))
                if target_restaurant.id not in accessible_ids:
                    target_restaurant = current_restaurant  # fall back silently
        except Restaurant.DoesNotExist:
            target_restaurant = None
    elif current_restaurant and not view_all_restaurants:
        target_restaurant = current_restaurant
    
    # Base queryset - filter by restaurant with optimization
    if target_restaurant:
        if target_restaurant.is_main_restaurant:
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.main_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [target_restaurant.main_owner, target_restaurant.branch_owner] if o])
                )
        else:
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.branch_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [target_restaurant.main_owner, target_restaurant.branch_owner] if o])
                )
    elif request.user.is_administrator():
        orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
            .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category').all()
    else:
        accessible_restaurants = restaurant_context['accessible_restaurants']
        if accessible_restaurants.exists():
            order_query = Q()
            for restaurant in accessible_restaurants:
                order_query |= (
                    Q(table_info__restaurant=restaurant) |
                    Q(table_info__owner=restaurant.main_owner, table_info__restaurant__isnull=True) |
                    Q(table_info__owner=restaurant.branch_owner, table_info__restaurant__isnull=True) |
                    Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__in=[o for o in [restaurant.main_owner, restaurant.branch_owner] if o])
                )
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(order_query)
        else:
            orders = Order.objects.none()

    # Customer care sees only their own orders
    if request.user.is_customer_care() and not (request.user.is_owner() or
                                                  request.user.is_main_owner() or
                                                  request.user.is_branch_owner()):
        orders = orders.filter(ordered_by=request.user)
    
    # Apply period filter using timezone-aware datetime boundaries.
    # PostgreSQL extracts __date in UTC; orders placed between midnight-3am local (UTC+3)
    # have a UTC date one day earlier, causing them to vanish from Today/Weekly filters.
    # Fix: use timezone.make_aware() with naive midnight datetimes - Django converts them
    # to UTC correctly using settings.TIME_ZONE (Africa/Nairobi).
    now_local = timezone.localtime(timezone.now())
    today = now_local.date()
    if period == 'today':
        start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        end = timezone.make_aware(datetime.combine(today + timedelta(days=1), datetime.min.time()))
        orders = orders.filter(created_at__gte=start, created_at__lt=end)
    elif period == 'weekly':
        week_start = today - timedelta(days=6)  # Last 7 days including today
        start = timezone.make_aware(datetime.combine(week_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    elif period == 'monthly':
        month_start = today.replace(day=1)
        start = timezone.make_aware(datetime.combine(month_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        start = timezone.make_aware(datetime.combine(year_start, datetime.min.time()))
        orders = orders.filter(created_at__gte=start)
    # 'all' period means no date filter - show all orders
    
    # Apply category filter
    if category_id != 'all':
        orders = orders.filter(order_items__product__main_category_id=category_id).distinct()
    
    # Apply subcategory filter
    if subcategory_id != 'all':
        orders = orders.filter(order_items__product__sub_category_id=subcategory_id).distinct()
    
    # Apply payment status filter
    if payment_status == 'paid':
        orders = orders.filter(payment_status='paid')
    elif payment_status == 'unpaid':
        orders = orders.filter(payment_status='unpaid')
    elif payment_status == 'partial':
        orders = orders.filter(payment_status='partial')
    
    # Apply date filters (these override period if specified)
    if from_date:
        orders = orders.filter(created_at__date__gte=from_date)
    if to_date:
        orders = orders.filter(created_at__date__lte=to_date)
    
    # Apply station filtering (Kitchen/Bar/All)
    if station_filter == 'kitchen':
        orders = orders.filter(order_items__product__station='kitchen').distinct()
    elif station_filter == 'bar':
        orders = orders.filter(order_items__product__station='bar').distinct()
    elif station_filter == 'buffet':
        orders = orders.filter(order_items__product__station='buffet').distinct()
    elif station_filter == 'service':
        orders = orders.filter(order_items__product__station='service').distinct()
    
    # Apply staff filtering (filter by who created the order)
    if staff_filter != 'all':
        try:
            staff_id = int(staff_filter)
            orders = orders.filter(ordered_by_id=staff_id)
        except (ValueError, TypeError):
            pass  # Invalid staff_filter, ignore

    # Apply product filter (only orders containing this specific product)
    if product_id != 'all':
        orders = orders.filter(order_items__product_id=product_id).distinct()

    # Apply table filter (only orders from this specific table)
    if table_id != 'all':
        orders = orders.filter(table_info_id=table_id)
    if payment_method != 'all':
        orders = orders.filter(payments__payment_method=payment_method, payments__is_voided=False).distinct()

    # Calculate summary data for the export
    total_orders = orders.count()
    _item_filter_active = (product_id != 'all' or category_id != 'all' or subcategory_id != 'all' or station_filter != 'all')
    if _item_filter_active:
        # AND-chain all active filters (same logic as dashboard) so combined filters are accurate
        _stats_items = OrderItem.objects.filter(order__in=orders)
        if category_id != 'all':
            _stats_items = _stats_items.filter(product__main_category_id=category_id)
        if subcategory_id != 'all':
            _stats_items = _stats_items.filter(product__sub_category_id=subcategory_id)
        if station_filter != 'all':
            _stats_items = _stats_items.filter(product__station=station_filter)
        if product_id != 'all':
            _stats_items = _stats_items.filter(product_id=product_id)
        total_revenue = sum(item.quantity * item.unit_price for item in _stats_items) or 0
        total_items = _stats_items.aggregate(total=Sum('quantity'))['total'] or 0
    else:
        total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
        total_items = OrderItem.objects.filter(order__in=orders).aggregate(total=Sum('quantity'))['total'] or 0
    avg_order_value = (total_revenue / total_orders) if total_orders > 0 else 0

    # Separate tax from revenue so PDF matches dashboard (total_amount is tax-inclusive)
    from decimal import Decimal as _D
    if not _item_filter_active:
        _pdf_total_tax = sum(_o.get_tax_amount() for _o in orders)
        total_revenue = _D(str(orders.aggregate(total=Sum('total_amount'))['total'] or 0)) - _D(str(_pdf_total_tax))
    else:
        _pdf_total_tax = _D('0.00')

    # Calculate payment status breakdown
    paid_orders = orders.filter(payment_status='paid')
    paid_orders_count = paid_orders.count()
    if _item_filter_active:
        paid_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='paid')) or 0
    else:
        _pdf_pr_tax = sum(_o.get_tax_amount() for _o in paid_orders)
        paid_revenue = _D(str(paid_orders.aggregate(total=Sum('total_amount'))['total'] or 0)) - _D(str(_pdf_pr_tax))

    unpaid_orders = orders.filter(payment_status='unpaid')
    unpaid_orders_count = unpaid_orders.count()
    if _item_filter_active:
        unpaid_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='unpaid')) or 0
    else:
        _pdf_ur_tax = sum(_o.get_tax_amount() for _o in unpaid_orders)
        unpaid_revenue = _D(str(unpaid_orders.aggregate(total=Sum('total_amount'))['total'] or 0)) - _D(str(_pdf_ur_tax))

    partial_orders = orders.filter(payment_status='partial')
    partial_orders_count = partial_orders.count()
    if _item_filter_active:
        partial_revenue = sum(item.quantity * item.unit_price for item in _stats_items.filter(order__payment_status='partial')) or 0
    else:
        _pdf_par_tax = sum(_o.get_tax_amount() for _o in partial_orders)
        partial_revenue = _D(str(partial_orders.aggregate(total=Sum('total_amount'))['total'] or 0)) - _D(str(_pdf_par_tax))
    
    # Get currency symbol from user settings
    currency_symbol = User.CURRENCY_SYMBOLS.get(request.user.currency_code, '$')
    
    # Determine the period description for the report
    if from_date and to_date:
        period_desc = f"Custom Period: {from_date} to {to_date}"
    elif from_date:
        period_desc = f"From: {from_date}"
    elif to_date:
        period_desc = f"Until: {to_date}"
    elif period == 'today':
        period_desc = f"Today: {today}"
    elif period == 'weekly':
        week_start = today - timedelta(days=today.weekday())
        period_desc = f"This Week: {week_start} to {today}"
    elif period == 'monthly':
        month_start = today.replace(day=1)
        period_desc = f"This Month: {month_start} to {today}"
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        period_desc = f"This Year: {year_start} to {today}"
    else:
        period_desc = "All Time"
    
    # Add filters to period description for PDF
    if station_filter != 'all':
        period_desc += f" (Station: {station_filter.title()})"
    if staff_filter != 'all':
        try:
            # SECURITY: only resolve user if they have orders in the already-scoped queryset
            if orders.filter(ordered_by_id=int(staff_filter)).exists():
                staff_user = User.objects.get(id=int(staff_filter))
                period_desc += f" (Staff: {staff_user.first_name} {staff_user.last_name})"
        except (User.DoesNotExist, ValueError):
            pass
    
    # Create PDF response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="sales_report_{payment_status}_{period}_{datetime.now().strftime("%Y%m%d")}.pdf"'
    
    # Create PDF document
    buffer = BytesIO()
    from reportlab.lib.pagesizes import landscape
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    
    # Container for the 'Flowable' objects
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1,  # Center alignment
        textColor=colors.darkblue
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=12,
        textColor=colors.darkblue
    )
    
    # Title
    restaurant_name = target_restaurant.name if target_restaurant else "All Restaurants"
    title = Paragraph(f"{restaurant_name}<br/>SALES REPORT", title_style)
    elements.append(title)
    elements.append(Spacer(1, 20))
    
    # Report Information
    report_info = [
        ['Generated on:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
        ['Period:', period_desc],
        ['Payment Status Filter:', payment_status.title()],
        ['Payment Method Filter:', payment_method.title() if payment_method != 'all' else 'All'],
        ['Station Filter:', station_filter.title()],
    ]
    
    if staff_filter != 'all':
        try:
            staff_user = User.objects.get(id=int(staff_filter))
            report_info.append(['Staff Filter:', f'{staff_user.first_name} {staff_user.last_name} ({staff_user.role.get_name_display()})'])
        except (User.DoesNotExist, ValueError):
            pass
    
    if target_restaurant:
        report_info.append(['Restaurant:', target_restaurant.name])
    
    if category_id != 'all':
        # SECURITY: anchor lookup to already-scoped orders — prevents cross-tenant name leakage
        _cat = MainCategory.objects.filter(
            id=category_id
        ).values('name').first()
        report_info.append(['Category Filter:', _cat['name'] if _cat else f'Category ID {category_id}'])
    
    if subcategory_id != 'all':
        _subcat = SubCategory.objects.filter(
            id=subcategory_id
        ).values('name').first()
        report_info.append(['Sub Category Filter:', _subcat['name'] if _subcat else f'Sub Category ID {subcategory_id}'])
    if product_id != 'all':
        try:
            from restaurant.models import Product as ProductModel
            if target_restaurant:
                _valid_cats = MainCategory.objects.filter(
                    Q(restaurant=target_restaurant) |
                    Q(owner=target_restaurant.main_owner, restaurant__isnull=True)
                )
            elif not request.user.is_administrator():
                _accessible = restaurant_context['accessible_restaurants']
                _cat_q = Q()
                for _r in _accessible:
                    _cat_q |= Q(restaurant=_r)
                    if _r.main_owner: _cat_q |= Q(owner=_r.main_owner, restaurant__isnull=True)
                    if _r.branch_owner: _cat_q |= Q(owner=_r.branch_owner, restaurant__isnull=True)
                _valid_cats = MainCategory.objects.filter(_cat_q)
            else:
                _valid_cats = None
            _prod = (ProductModel.objects.filter(id=product_id, main_category__in=_valid_cats)
                     if _valid_cats is not None else ProductModel.objects.filter(id=product_id)).first()
            if _prod:
                report_info.append(['Product Filter:', _prod.name])
            else:
                report_info.append(['Product Filter:', f'Product ID {product_id}'])
        except Exception:
            report_info.append(['Product Filter:', f'Product ID {product_id}'])
    if table_id != 'all':
        try:
            from restaurant.models import TableInfo as TableInfoModel
            if target_restaurant:
                _tbl = TableInfoModel.objects.filter(id=table_id, restaurant=target_restaurant).first()
            elif not request.user.is_administrator():
                _accessible = restaurant_context['accessible_restaurants']
                _tbl = TableInfoModel.objects.filter(id=table_id, restaurant__in=_accessible).first()
            else:
                _tbl = TableInfoModel.objects.filter(id=table_id).first()
            if _tbl:
                report_info.append(['Table Filter:', f'Table {_tbl.tbl_no}'])
            else:
                report_info.append(['Table Filter:', f'Table ID {table_id}'])
        except Exception:
            report_info.append(['Table Filter:', f'Table ID {table_id}'])
    
    info_table = Table(report_info, colWidths=[2*inch, 4*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(info_table)
    elements.append(Spacer(1, 20))
    
    # Summary Statistics
    summary_heading = Paragraph("SUMMARY STATISTICS", heading_style)
    elements.append(summary_heading)
    
    summary_data = [
        ['Revenue:', f'{currency_symbol}{total_revenue:,.2f}'],
        ['Total Orders:', f'{total_orders:,}'],
        ['Items Sold:', f'{total_items:,}'],
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(summary_table)
    elements.append(Spacer(1, 15))
    
    # Payment Status Breakdown
    payment_heading = Paragraph("PAYMENT STATUS BREAKDOWN", heading_style)
    elements.append(payment_heading)
    
    payment_data = [
        ['Paid Orders:', f'{paid_orders_count:,}', f'{currency_symbol}{paid_revenue:,.2f}'],
        ['Unpaid Orders:', f'{unpaid_orders_count:,}', f'{currency_symbol}{unpaid_revenue:,.2f}'],
        ['Partial Payments:', f'{partial_orders_count:,}', f'{currency_symbol}{partial_revenue:,.2f}']
    ]
    
    payment_table = Table(payment_data, colWidths=[2*inch, 1*inch, 2*inch])
    payment_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (1, 0), (2, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(payment_table)
    elements.append(Spacer(1, 30))
    
    # Branch Performance Analysis (only for PRO plans with multiple locations when viewing all)
    if not target_restaurant and not request.user.is_administrator():
        accessible_restaurants = restaurant_context['accessible_restaurants']
        has_multiple_locations = accessible_restaurants.count() > 1
        
        if has_multiple_locations:
            # Branch Performance Heading
            branch_heading = Paragraph("BRANCH/LOCATION PERFORMANCE ANALYSIS", heading_style)
            elements.append(branch_heading)
            
            # Branch performance data
            branch_data = [['Location', 'Orders', '% of Total', 'Revenue', '% of Total', 'Avg Order']]
            
            for restaurant in accessible_restaurants.order_by('name'):
                # Get orders for this location
                # CRITICAL FIX: Legacy orders (no restaurant) should ONLY count for MAIN restaurant
                if restaurant.is_main_restaurant:
                    restaurant_orders = orders.filter(
                        Q(table_info__restaurant=restaurant) |
                        Q(table_info__owner=restaurant.main_owner, table_info__restaurant__isnull=True)
                    )
                else:
                    # Branches: ONLY direct orders assigned to this branch, NO legacy orders
                    restaurant_orders = orders.filter(table_info__restaurant=restaurant)
                
                location_orders = restaurant_orders.count()
                location_revenue = restaurant_orders.aggregate(total=Sum('total_amount'))['total'] or 0
                location_avg = (location_revenue / location_orders) if location_orders > 0 else 0
                
                order_percentage = (location_orders / total_orders * 100) if total_orders > 0 else 0
                revenue_percentage = (location_revenue / total_revenue * 100) if total_revenue > 0 else 0
                
                location_label = restaurant.name
                if not restaurant.is_main_restaurant:
                    location_label += " (Branch)"
                
                branch_data.append([
                    location_label,
                    f'{location_orders:,}',
                    f'{order_percentage:.1f}%',
                    f'{currency_symbol}{location_revenue:,.2f}',
                    f'{revenue_percentage:.1f}%',
                    f'{currency_symbol}{location_avg:.2f}'
                ])
            
            branch_table = Table(branch_data, colWidths=[1.5*inch, 0.8*inch, 0.8*inch, 1.2*inch, 0.8*inch, 1*inch])
            branch_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightcyan),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            elements.append(branch_table)
            elements.append(Spacer(1, 20))
            
            # Top Products by Location
            products_heading = Paragraph("TOP PRODUCTS BY LOCATION", heading_style)
            elements.append(products_heading)
            
            # Create products data for all locations
            products_data = [['Location', 'Product', 'Qty', 'Revenue', '% of Loc']]
            
            for restaurant in accessible_restaurants.order_by('name'):
                # Get orders for this location
                # CRITICAL FIX: Legacy orders (no restaurant) should ONLY count for MAIN restaurant
                if restaurant.is_main_restaurant:
                    restaurant_orders = orders.filter(
                        Q(table_info__restaurant=restaurant) |
                        Q(table_info__owner=restaurant.main_owner, table_info__restaurant__isnull=True)
                    )
                else:
                    # Branches: ONLY direct orders assigned to this branch, NO legacy orders
                    restaurant_orders = orders.filter(table_info__restaurant=restaurant)
                
                location_revenue = restaurant_orders.aggregate(total=Sum('total_amount'))['total'] or 0
                
                if restaurant_orders.exists():
                    # Get top 5 products for this location
                    top_products = OrderItem.objects.filter(order__in=restaurant_orders)\
                        .values('product__name')\
                        .annotate(
                            total_quantity=Sum('quantity'),
                            total_revenue=ExpressionWrapper(
                                Sum(F('unit_price') * F('quantity')),
                                output_field=DecimalField(max_digits=12, decimal_places=2)
                            )
                        )\
                        .order_by('-total_quantity')[:5]
                    
                    location_label = restaurant.name
                    if not restaurant.is_main_restaurant:
                        location_label += " (Branch)"
                    
                    for idx, product in enumerate(top_products):
                        product_percentage = (product['total_revenue'] / location_revenue * 100) if location_revenue > 0 else 0
                        
                        products_data.append([
                            location_label if idx == 0 else '',  # Only show location name on first row
                            product['product__name'][:20],  # Limit product name length
                            f"{product['total_quantity']:,}",
                            f"${product['total_revenue']:,.2f}",
                            f"{product_percentage:.1f}%"
                        ])
                    
                    if not top_products:
                        products_data.append([location_label, 'No products sold', '-', '-', '-'])
            
            if len(products_data) > 1:  # If we have data beyond header
                products_table = Table(products_data, colWidths=[1.5*inch, 2*inch, 0.7*inch, 1*inch, 0.9*inch])
                products_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 9),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.lightgreen),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
                ]))
                
                elements.append(products_table)
                elements.append(Spacer(1, 30))
    
    # Detailed Sales Data
    detailed_heading = Paragraph("DETAILED SALES DATA", heading_style)
    elements.append(detailed_heading)
    
    # Table headers
    headers = ['Order #', 'Date', 'Customer', 'Location', 'Items', 'Total', 'Pay Status', 'Method', 'Status', 'Order By', 'Paid By']
    data = [headers]
    
    # Table data
    for order in orders.order_by('-created_at'):
        all_items = list(order.order_items.all())
        
        # Filter items for Items column based on active filter.
        # Priority: product (most specific) > subcategory > category > station
        filtered_items = []
        if product_id != 'all':
            for item in all_items:
                if str(item.product_id) == str(product_id):
                    filtered_items.append(item)
        elif subcategory_id != 'all':
            # Filter by subcategory
            for item in all_items:
                if item.product and item.product.sub_category and str(item.product.sub_category_id) == str(subcategory_id):
                    filtered_items.append(item)
        elif category_id != 'all':
            # Filter by category
            for item in all_items:
                if item.product and str(item.product.main_category_id) == str(category_id):
                    filtered_items.append(item)
        elif station_filter != 'all':
            # Filter by station
            for item in all_items:
                if item.product and item.product.station == station_filter:
                    filtered_items.append(item)
        else:
            # No filter - show all items
            filtered_items = all_items

        items_list = ', '.join([f"{item.product.name} x{item.quantity}" for item in filtered_items][:3])  # Limit items for PDF
        if len(filtered_items) > 3:
            items_list += "..."
        
        customer_name = f"{order.ordered_by.first_name} {order.ordered_by.last_name}" if order.ordered_by else 'Walk-in'
        
        # Order By column
        order_by_name = f"{order.ordered_by.first_name} {order.ordered_by.last_name}" if order.ordered_by else '-'
        
        # Paid By column - get first payment processor
        paid_by_name = '-'
        if hasattr(order, 'payments'):
            for payment in order.payments.all():
                if not payment.is_voided and payment.processed_by:
                    paid_by_name = f"{payment.processed_by.first_name} {payment.processed_by.last_name}"
                    break  # Just show first one for PDF space
        
        # Get restaurant/branch name for this order
        order_restaurant = order.table_info.restaurant.name if order.table_info and order.table_info.restaurant else 'Legacy'
        if order.table_info and order.table_info.restaurant and not order.table_info.restaurant.is_main_restaurant:
            order_restaurant += ' (Branch)'
        
        data.append([
            order.order_number,
            order.created_at.strftime('%m/%d/%Y'),
            customer_name[:12],  # Limit length
            order_restaurant[:12],  # Limit length
            items_list[:15],  # Limit length
            f"{currency_symbol}{sum(item.quantity * item.unit_price for item in filtered_items):.2f}",
            order.payment_status.title(),
            ', '.join(sorted(set(p.payment_method.title() for p in order.payments.all() if not p.is_voided))) or '-',
            order.status.title(),
            order_by_name[:12],  # Limit length
            paid_by_name[:12]  # Limit length
        ])
    
    # Create table with adjusted column widths to accommodate Order By and Paid By columns
    table = Table(data, colWidths=[0.95*inch, 0.75*inch, 0.85*inch, 0.85*inch, 1.5*inch, 0.75*inch, 0.75*inch, 0.75*inch, 0.75*inch, 0.85*inch, 0.85*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('WORDWRAP', (0, 0), (-1, -1), True)
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    
    # Get the value of the BytesIO buffer and write it to the response
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    
    return response


# ---------------------------------------------------------------------------
# Money Flow Dashboard
# ---------------------------------------------------------------------------

@login_required
def money_flow(request):
    """Unified money flow: Sales revenue + Event income vs Inventory costs."""
    from django.shortcuts import redirect
    from django.contrib import messages as _messages
    if not (request.user.is_administrator() or request.user.is_owner() or
            request.user.is_main_owner() or request.user.is_branch_owner() or
            request.user.is_manager() or request.user.is_customer_care()):
        _messages.error(request, "Access denied. Owner or Manager role required.")
        return redirect('restaurant:home')
    from inventory.models import InventoryRecord
    from restaurant.models import Event

    owner = get_owner_filter(request.user)
    currency_symbol = User.CURRENCY_SYMBOLS.get(request.user.currency_code, '$')

    # ── Period filter ────────────────────────────────────────────────────────
    period = request.GET.get('period', 'today')
    date_from_raw = request.GET.get('date_from', '')
    date_to_raw = request.GET.get('date_to', '')
    today = timezone.now().date()

    if period == 'today':
        date_from = date_to = today
    elif period == 'week':
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif period == 'month':
        date_from = today.replace(day=1)
        date_to = today
    elif period == 'custom' and date_from_raw and date_to_raw:
        try:
            date_from = datetime.strptime(date_from_raw, '%Y-%m-%d').date()
            date_to = datetime.strptime(date_to_raw, '%Y-%m-%d').date()
        except ValueError:
            date_from = date_to = today
    else:
        date_from = date_to = today

    # ── Orders / Sales ───────────────────────────────────────────────────────
    if owner:
        from django.db.models import Q as DQ
        orders_qs = Order.objects.filter(
            DQ(table_info__owner=owner) |
            DQ(table_info__restaurant__main_owner=owner) |
            DQ(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) |
            DQ(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
        )
    elif request.user.is_administrator():
        orders_qs = Order.objects.all()
    else:
        orders_qs = Order.objects.none()

    orders_qs = orders_qs.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)

    sales_revenue      = orders_qs.filter(payment_status='paid').aggregate(t=Sum('total_amount'))['t'] or 0
    sales_unpaid       = orders_qs.filter(payment_status='unpaid').aggregate(t=Sum('total_amount'))['t'] or 0
    sales_partial      = orders_qs.filter(payment_status='partial').aggregate(t=Sum('total_amount'))['t'] or 0
    sales_total_orders = orders_qs.count()
    sales_paid_orders  = orders_qs.filter(payment_status='paid').count()

    # ── Events ───────────────────────────────────────────────────────────────
    try:
        if owner:
            events_qs = Event.objects.filter(owner=owner)
        elif request.user.is_administrator():
            events_qs = Event.objects.all()
        else:
            events_qs = Event.objects.none()

        events_qs = events_qs.filter(event_date__gte=date_from, event_date__lte=date_to)

        event_collected   = events_qs.aggregate(t=Sum('amount_paid'))['t'] or 0
        event_outstanding = events_qs.exclude(payment_status='fully_paid').aggregate(
            t=Sum('balance_due'))['t'] or 0
        event_total_value = events_qs.aggregate(
            t=Sum('price_per_pax'))['t'] or 0   # rough; ideally price_per_pax * total_pax
        event_count       = events_qs.count()
    except Exception:
        event_collected = event_outstanding = event_total_value = 0
        event_count = 0

    # ── Inventory costs ──────────────────────────────────────────────────────
    if owner:
        inv_qs = InventoryRecord.objects.filter(item__owner=owner)
    elif request.user.is_administrator():
        inv_qs = InventoryRecord.objects.all()
    else:
        inv_qs = InventoryRecord.objects.none()

    inv_qs = inv_qs.filter(recorded_at__date__gte=date_from, recorded_at__date__lte=date_to)

    from django.db.models import ExpressionWrapper as _EW, DecimalField as _DF
    from django.db.models.functions import Abs as _Abs
    _inv_cost_expr = _EW(_Abs(F('quantity_change')) * F('unit_price'), output_field=_DF(max_digits=14, decimal_places=2))
    inv_spent   = inv_qs.exclude(record_type='returned').exclude(unit_price__isnull=True).aggregate(t=Sum(_inv_cost_expr))['t'] or 0
    inv_refunds = inv_qs.filter(record_type='returned').exclude(unit_price__isnull=True).aggregate(t=Sum(_inv_cost_expr))['t'] or 0
    inv_net     = inv_spent - inv_refunds

    # ── Totals ───────────────────────────────────────────────────────────────
    total_in         = sales_revenue + event_collected
    total_out        = inv_net          # net inventory spend (after refunds)
    total_outstanding = sales_unpaid + sales_partial + event_outstanding
    net_position     = total_in - total_out

    # ── Daily chart data (money in vs out per day in range) ──────────────────
    from collections import defaultdict
    delta = (date_to - date_from).days + 1
    chart_labels = []
    chart_in = []
    chart_out = []

    for i in range(delta):
        day = date_from + timedelta(days=i)
        label = day.strftime('%b %d') if delta <= 31 else day.strftime('%Y-%m-%d')
        chart_labels.append(label)

        day_orders_revenue = orders_qs.filter(
            created_at__date=day, payment_status='paid'
        ).aggregate(t=Sum('total_amount'))['t'] or 0

        try:
            day_event_collected = events_qs.filter(
                event_date=day
            ).aggregate(t=Sum('amount_paid'))['t'] or 0
        except Exception:
            day_event_collected = 0

        day_inv_spent = inv_qs.filter(
            recorded_at__date=day
        ).exclude(record_type='returned').exclude(unit_price__isnull=True).aggregate(t=Sum(_inv_cost_expr))['t'] or 0
        day_inv_refunds = inv_qs.filter(
            recorded_at__date=day, record_type='returned'
        ).exclude(unit_price__isnull=True).aggregate(t=Sum(_inv_cost_expr))['t'] or 0

        chart_in.append(float(day_orders_revenue + day_event_collected))
        chart_out.append(float(max(0, day_inv_spent - day_inv_refunds)))

    from admin_panel.restaurant_utils import get_restaurant_context as _get_rc
    _restaurant_context = _get_rc(request.user, request.session.get('current_restaurant_id'), request)

    import json
    context = {
        'currency_symbol': currency_symbol,
        'period': period,
        'date_from': date_from_raw or str(date_from),
        'date_to': date_to_raw or str(date_to),
        'date_from_display': date_from,
        'date_to_display': date_to,
        # Sales
        'sales_revenue': sales_revenue,
        'sales_unpaid': sales_unpaid,
        'sales_partial': sales_partial,
        'sales_total_orders': sales_total_orders,
        'sales_paid_orders': sales_paid_orders,
        # Events
        'event_collected': event_collected,
        'event_outstanding': event_outstanding,
        'event_count': event_count,
        # Inventory
        'inv_spent': inv_spent,
        'inv_refunds': inv_refunds,
        'inv_net': inv_net,
        # Totals
        'total_in': total_in,
        'total_out': total_out,
        'total_outstanding': total_outstanding,
        'net_position': net_position,
        # Chart
        'chart_labels': json.dumps(chart_labels),
        'chart_in': json.dumps(chart_in),
        'chart_out': json.dumps(chart_out),
        **_restaurant_context,
    }
    return render(request, 'reports/money_flow.html', context)


