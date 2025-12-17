from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.core.paginator import Paginator
from orders.models import Order, OrderItem
from cashier.models import Payment
from restaurant.models import MainCategory, SubCategory
from accounts.models import get_owner_filter
from django.db.models import Sum, Count
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
            request.user.is_main_owner() or request.user.is_branch_owner()):
        from django.shortcuts import redirect
        from django.contrib import messages
        messages.error(request, "Access denied. Owner privileges required.")
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
    period = request.GET.get('period', 'today')  # Default to 'today' instead of 'all'
    category_id = request.GET.get('category_id', 'all')
    subcategory_id = request.GET.get('subcategory_id', 'all')
    station_filter = request.GET.get('station_filter', 'all')  # NEW: Kitchen/Bar filtering
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
                    Q(table_info__owner=target_restaurant.main_owner, table_info__restaurant__isnull=True)
                )
        else:
            # Branch restaurant: only show orders from tables specifically assigned to this branch
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.branch_owner, table_info__restaurant__isnull=True)
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
                    Q(table_info__owner=restaurant.branch_owner, table_info__restaurant__isnull=True)
                )
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(order_query)
        else:
            orders = Order.objects.none()
    
    # Apply period filter
    today = timezone.now().date()
    if period == 'today':
        orders = orders.filter(created_at__date=today)
    elif period == 'weekly':
        week_start = today - timedelta(days=today.weekday())
        orders = orders.filter(created_at__date__gte=week_start)
    elif period == 'monthly':
        month_start = today.replace(day=1)
        orders = orders.filter(created_at__date__gte=month_start)
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        orders = orders.filter(created_at__date__gte=year_start)
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
            orders = orders.filter(created_at__date__gte=from_date)
        if to_date:
            orders = orders.filter(created_at__date__lte=to_date)
    
    # Apply station filtering (Kitchen/Bar/All)
    if station_filter == 'kitchen':
        # Filter orders that have kitchen items
        orders = orders.filter(order_items__product__station='kitchen').distinct()
    elif station_filter == 'bar':
        # Filter orders that have bar items
        orders = orders.filter(order_items__product__station='bar').distinct()
    # 'all' means no station filter
    
    # Helper functions for station detection
    # Helper functions for station analysis
    def has_kitchen_items(order):
        return any(item.product.station == 'kitchen' for item in order.order_items.all())
    
    def has_bar_items(order):
        return any(item.product.station == 'bar' for item in order.order_items.all())

    # Calculate summary data with optimized queries
    total_orders = orders.count()
    total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    total_items = OrderItem.objects.filter(order__in=orders).aggregate(total=Sum('quantity'))['total'] or 0
    avg_order_value = (total_revenue / total_orders) if total_orders > 0 else 0
    
    # Calculate station-specific metrics
    kitchen_orders_count = len([o for o in orders if has_kitchen_items(o)]) if station_filter == 'all' else (total_orders if station_filter == 'kitchen' else 0)
    bar_orders_count = len([o for o in orders if has_bar_items(o)]) if station_filter == 'all' else (total_orders if station_filter == 'bar' else 0)
    mixed_orders_count = len([o for o in orders if has_kitchen_items(o) and has_bar_items(o)]) if station_filter == 'all' else 0
    
    # Top selling products analysis
    top_products = OrderItem.objects.filter(order__in=orders)\
        .values('product__name', 'product__station')\
        .annotate(total_quantity=Sum('quantity'), total_revenue=Sum('unit_price'))\
        .order_by('-total_quantity')[:5]
    
    # Get orders for table with pagination
    orders_list = orders.order_by('-created_at')
    
    # Pagination
    page_number = request.GET.get('page', 1)
    paginator = Paginator(orders_list, 10)  # Show 10 orders per page
    page_obj = paginator.get_page(page_number)
    
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
    
    # Filter subcategories by selected category if applicable
    if category_id != 'all':
        subcategories = subcategories.filter(main_category_id=category_id)
    
    # Get selected category/subcategory names for template display
    selected_category_name = None
    selected_subcategory_name = None
    if category_id != 'all':
        try:
            selected_category_name = MainCategory.objects.get(id=category_id).name
        except MainCategory.DoesNotExist:
            pass
    if subcategory_id != 'all':
        try:
            selected_subcategory_name = SubCategory.objects.get(id=subcategory_id).name
        except SubCategory.DoesNotExist:
            pass
    
    # Today's date for template defaults
    today_str = timezone.now().date().strftime('%Y-%m-%d')
    
    context = {
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'total_items': total_items,
        'avg_order_value': avg_order_value,
        'page_obj': page_obj,
        'orders': page_obj,
        'payment_status': payment_status,
        'period': period,
        'categories': categories,
        'subcategories': subcategories,
        'selected_category': category_id,
        'selected_subcategory': subcategory_id,
        'selected_category_name': selected_category_name,
        'selected_subcategory_name': selected_subcategory_name,
        'station_filter': station_filter,  # NEW: Station filter value
        'kitchen_orders_count': kitchen_orders_count,
        'bar_orders_count': bar_orders_count,
        'mixed_orders_count': mixed_orders_count,
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
    period = request.GET.get('period', 'today')  # Default to 'today' same as dashboard
    category_id = request.GET.get('category_id', 'all')
    subcategory_id = request.GET.get('subcategory_id', 'all')
    station_filter = request.GET.get('station_filter', 'all')  # NEW: Station filtering
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
                    Q(table_info__owner=target_restaurant.main_owner, table_info__restaurant__isnull=True)
                )
        else:
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.branch_owner, table_info__restaurant__isnull=True)
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
                    Q(table_info__owner=restaurant.branch_owner, table_info__restaurant__isnull=True)
                )
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(order_query)
        else:
            orders = Order.objects.none()
    
    # Apply period filter
    today = timezone.now().date()
    if period == 'today':
        orders = orders.filter(created_at__date=today)
    elif period == 'weekly':
        week_start = today - timedelta(days=today.weekday())
        orders = orders.filter(created_at__date__gte=week_start)
    elif period == 'monthly':
        month_start = today.replace(day=1)
        orders = orders.filter(created_at__date__gte=month_start)
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        orders = orders.filter(created_at__date__gte=year_start)
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
    
    # Calculate summary data for the export
    total_orders = orders.count()
    total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    total_items = OrderItem.objects.filter(order__in=orders).aggregate(total=Sum('quantity'))['total'] or 0
    avg_order_value = (total_revenue / total_orders) if total_orders > 0 else 0
    
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
    
    # Add station filter to period description
    if station_filter != 'all':
        period_desc += f" (Station: {station_filter.title()})"
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="sales_report_{payment_status}_{period}_{datetime.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    
    # Write summary header
    writer.writerow(['SALES REPORT SUMMARY'])
    writer.writerow(['Generated on:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow(['Period:', period_desc])
    writer.writerow(['Payment Status Filter:', payment_status.title()])
    writer.writerow(['Station Filter:', station_filter.title()])
    if target_restaurant:
        writer.writerow(['Restaurant:', target_restaurant.name])
    if category_id != 'all':
        try:
            category_name = MainCategory.objects.get(id=category_id).name
            writer.writerow(['Category Filter:', category_name])
        except:
            writer.writerow(['Category Filter:', f'Category ID {category_id}'])
    if subcategory_id != 'all':
        try:
            subcategory_name = SubCategory.objects.get(id=subcategory_id).name
            writer.writerow(['Sub Category Filter:', subcategory_name])
        except:
            writer.writerow(['Sub Category Filter:', f'Sub Category ID {subcategory_id}'])
    writer.writerow([])  # Empty row
    
    # Write summary statistics
    writer.writerow(['SUMMARY STATISTICS'])
    writer.writerow(['Total Revenue:', f'${total_revenue:,.2f}'])
    writer.writerow(['Total Orders:', f'{total_orders:,}'])
    writer.writerow(['Items Sold:', f'{total_items:,}'])
    writer.writerow(['Average Order Value:', f'${avg_order_value:,.2f}'])
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
                    f'${location_revenue:,.2f}',
                    f'{revenue_percentage:.1f}%',
                    f'${location_avg:.2f}'
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
                            total_revenue=Sum('unit_price')
                        )\
                        .order_by('-total_quantity')[:5]
                    
                    location_label = f"{restaurant.name}"
                    if not restaurant.is_main_restaurant:
                        location_label += " (Branch)"
                    
                    for idx, product in enumerate(top_products):
                        product_percentage = (product['total_revenue'] / location_revenue * 100) if location_revenue > 0 else 0
                        
                        writer.writerow([
                            location_label if idx == 0 else '',  # Only show location name on first row
                            product['product__name'],
                            f"{product['total_quantity']:,}",
                            f"${product['total_revenue']:,.2f}",
                            f"{product_percentage:.1f}%"
                        ])
                    
                    if not top_products:
                        writer.writerow([location_label, 'No products sold', '-', '-', '-'])
            
            writer.writerow([])  # Empty row
    
    writer.writerow([])  # Empty row
    
    # Write detailed data header
    writer.writerow(['DETAILED SALES DATA'])
    writer.writerow(['Order ID', 'Customer', 'Date', 'Table', 'Restaurant/Branch', 'Items', 'Categories', 'Sub Categories', 'Stations', 'Total Amount', 'Payment Status', 'Order Status', 'Cashier'])
    
    # Get selected category/subcategory names for display (same as web)
    selected_category_name = None
    selected_subcategory_name = None
    if category_id != 'all':
        try:
            selected_category_name = MainCategory.objects.get(id=category_id).name
        except:
            pass
    if subcategory_id != 'all':
        try:
            selected_subcategory_name = SubCategory.objects.get(id=subcategory_id).name
        except:
            pass
    
    for order in orders.order_by('-created_at'):
        all_items = list(order.order_items.all())
        
        # Filter items for Items column based on active filter (same logic as web template)
        # Web uses: if category -> elif subcategory -> elif station -> else all
        filtered_items = []
        if category_id != 'all':
            # Filter by category
            for item in all_items:
                if str(item.product.main_category_id) == str(category_id):
                    filtered_items.append(item)
        elif subcategory_id != 'all':
            # Filter by subcategory
            for item in all_items:
                if item.product.sub_category and str(item.product.sub_category_id) == str(subcategory_id):
                    filtered_items.append(item)
        elif station_filter != 'all':
            # Filter by station
            for item in all_items:
                if item.product.station == station_filter:
                    filtered_items.append(item)
        else:
            # No filter - show all items
            filtered_items = all_items
        
        # Items column: shows filtered items
        items_list = ', '.join([f"{item.product.name} x{item.quantity}" for item in filtered_items])
        
        # Categories column: if filter active show filter name, else show ALL categories from ALL items
        if selected_category_name:
            categories_list = selected_category_name
        else:
            categories_list = ', '.join(set([item.product.main_category.name for item in all_items])) if all_items else ''
        
        # SubCategories column: if filter active show filter name, else show ALL subcategories from ALL items
        if selected_subcategory_name:
            subcategories_list = selected_subcategory_name
        else:
            subcategories_list = ', '.join(set([item.product.sub_category.name if item.product.sub_category else '-' for item in all_items])) if all_items else ''
        
        # Stations column: if filter active show filter name, else show ALL stations from ALL items
        if station_filter != 'all':
            stations_list = station_filter.title()
        else:
            stations_list = ', '.join(set([item.product.station.title() for item in all_items])) if all_items else ''
        
        table_number = order.table_info.tbl_no if order.table_info else '-'
        customer_name = f"{order.ordered_by.first_name} {order.ordered_by.last_name}" if order.ordered_by else 'Walk-in Customer'
        cashier_name = f"{order.confirmed_by.first_name} {order.confirmed_by.last_name}" if order.confirmed_by else f"{order.ordered_by.first_name} {order.ordered_by.last_name} (Self)" if order.ordered_by else 'System'
        
        # Get restaurant/branch name for this order
        order_restaurant = order.table_info.restaurant.name if order.table_info and order.table_info.restaurant else 'Legacy'
        if order.table_info and order.table_info.restaurant and not order.table_info.restaurant.is_main_restaurant:
            order_restaurant += ' (Branch)'
        
        writer.writerow([
            f"ORD-{order.id:08d}",
            customer_name,
            order.created_at.strftime('%Y-%m-%d %H:%M'),
            table_number,
            order_restaurant,
            items_list,
            categories_list,
            subcategories_list,
            stations_list,
            order.total_amount,
            order.payment_status,
            order.status,
            cashier_name
        ])
    
    return response

@login_required
def export_pdf(request):
    """Export filtered data to PDF with station filtering"""
    
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
    period = request.GET.get('period', 'today')  # Default to 'today' same as dashboard
    category_id = request.GET.get('category_id', 'all')
    subcategory_id = request.GET.get('subcategory_id', 'all')
    station_filter = request.GET.get('station_filter', 'all')  # NEW: Station filtering
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
                    Q(table_info__owner=target_restaurant.main_owner, table_info__restaurant__isnull=True)
                )
        else:
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(
                    Q(table_info__restaurant=target_restaurant) |
                    Q(table_info__owner=target_restaurant.branch_owner, table_info__restaurant__isnull=True)
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
                    Q(table_info__owner=restaurant.branch_owner, table_info__restaurant__isnull=True)
                )
            orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by')\
                .prefetch_related('order_items__product__main_category', 'order_items__product__sub_category')\
                .filter(order_query)
        else:
            orders = Order.objects.none()
    
    # Apply period filter
    today = timezone.now().date()
    if period == 'today':
        orders = orders.filter(created_at__date=today)
    elif period == 'weekly':
        week_start = today - timedelta(days=today.weekday())
        orders = orders.filter(created_at__date__gte=week_start)
    elif period == 'monthly':
        month_start = today.replace(day=1)
        orders = orders.filter(created_at__date__gte=month_start)
    elif period == 'yearly':
        year_start = today.replace(month=1, day=1)
        orders = orders.filter(created_at__date__gte=year_start)
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
    
    # Calculate summary data for the export
    total_orders = orders.count()
    total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    total_items = OrderItem.objects.filter(order__in=orders).aggregate(total=Sum('quantity'))['total'] or 0
    avg_order_value = (total_revenue / total_orders) if total_orders > 0 else 0
    
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
    
    # Add station filter to period description for PDF
    if station_filter != 'all':
        period_desc += f" (Station: {station_filter.title()})"
    
    # Create PDF response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="sales_report_{payment_status}_{period}_{datetime.now().strftime("%Y%m%d")}.pdf"'
    
    # Create PDF document
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    
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
        ['Station Filter:', station_filter.title()],
    ]
    
    if target_restaurant:
        report_info.append(['Restaurant:', target_restaurant.name])
    
    if category_id != 'all':
        try:
            category_name = MainCategory.objects.get(id=category_id).name
            report_info.append(['Category Filter:', category_name])
        except:
            report_info.append(['Category Filter:', f'Category ID {category_id}'])
    
    if subcategory_id != 'all':
        try:
            subcategory_name = SubCategory.objects.get(id=subcategory_id).name
            report_info.append(['Sub Category Filter:', subcategory_name])
        except:
            report_info.append(['Sub Category Filter:', f'Sub Category ID {subcategory_id}'])
    
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
        ['Total Revenue:', f'${total_revenue:,.2f}'],
        ['Total Orders:', f'{total_orders:,}'],
        ['Items Sold:', f'{total_items:,}'],
        ['Average Order Value:', f'${avg_order_value:,.2f}']
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
                    f'${location_revenue:,.2f}',
                    f'{revenue_percentage:.1f}%',
                    f'${location_avg:.2f}'
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
                            total_revenue=Sum('unit_price')
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
    headers = ['Order #', 'Date', 'Customer', 'Location', 'Items', 'Total', 'Payment', 'Status']
    data = [headers]
    
    # Table data
    for order in orders.order_by('-created_at'):
        all_items = list(order.order_items.all())
        
        # Filter items for Items column based on active filter (same logic as web template)
        # Web uses: if category -> elif subcategory -> elif station -> else all
        filtered_items = []
        if category_id != 'all':
            # Filter by category
            for item in all_items:
                if str(item.product.main_category_id) == str(category_id):
                    filtered_items.append(item)
        elif subcategory_id != 'all':
            # Filter by subcategory
            for item in all_items:
                if item.product.sub_category and str(item.product.sub_category_id) == str(subcategory_id):
                    filtered_items.append(item)
        elif station_filter != 'all':
            # Filter by station
            for item in all_items:
                if item.product.station == station_filter:
                    filtered_items.append(item)
        else:
            # No filter - show all items
            filtered_items = all_items
        
        items_list = ', '.join([f"{item.product.name} x{item.quantity}" for item in filtered_items][:3])  # Limit items for PDF
        if len(filtered_items) > 3:
            items_list += "..."
        
        customer_name = f"{order.ordered_by.first_name} {order.ordered_by.last_name}" if order.ordered_by else 'Walk-in'
        
        # Get restaurant/branch name for this order
        order_restaurant = order.table_info.restaurant.name if order.table_info and order.table_info.restaurant else 'Legacy'
        if order.table_info and order.table_info.restaurant and not order.table_info.restaurant.is_main_restaurant:
            order_restaurant += ' (Branch)'
        
        data.append([
            f"ORD-{order.id:08d}",
            order.created_at.strftime('%m/%d/%Y'),
            customer_name[:12],  # Limit length
            order_restaurant[:15],  # Limit length
            items_list[:20],  # Limit length
            f"${order.total_amount:.2f}",
            order.payment_status.title(),
            order.status.title()
        ])
    
    # Create table with adjusted column widths to accommodate Restaurant/Branch column
    table = Table(data, colWidths=[0.8*inch, 0.7*inch, 0.8*inch, 0.9*inch, 1.5*inch, 0.7*inch, 0.7*inch, 0.7*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    
    # Get the value of the BytesIO buffer and write it to the response
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    
    return response