"""
Views for main owner monitoring of branch restaurants
Main owners can only VIEW data from branches, not manage them
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum, Count, Q, Subquery, OuterRef, Value
from django.utils import timezone
from datetime import timedelta
from django.core.paginator import Paginator
from accounts.models import User
from restaurant.models_restaurant import Restaurant
from restaurant.models import Product, MainCategory, SubCategory, TableInfo
from orders.models import Order, OrderItem


@login_required
def main_owner_dashboard(request):
    """Dashboard for main owners to monitor all their branches"""
    if not request.user.is_main_owner():
        messages.error(request, 'Only main owners can access this page.')
        return redirect('admin_panel:admin_dashboard')
    
    # Check PRO plan access for branch features
    if not request.user.can_access_branch_features():
        messages.error(request, 'Branch monitoring dashboard requires a PRO subscription. Please upgrade your plan.')
        return redirect('admin_panel:admin_dashboard')
    
    # Check if viewing a specific restaurant or all restaurants
    selected_restaurant_id = request.session.get('selected_restaurant_id')
    view_all_restaurants = request.session.get('view_all_restaurants', False)
    current_restaurant = None
    
    # Get base queryset of restaurants owned by this main owner
    base_restaurants = Restaurant.objects.filter(main_owner=request.user)
    
    if selected_restaurant_id and not view_all_restaurants:
        # Viewing a specific restaurant — session stores User (owner) ID, not Restaurant ID
        try:
            selected_user = User.objects.get(id=selected_restaurant_id)
            if selected_user.is_branch_owner():
                current_restaurant = base_restaurants.filter(
                    branch_owner=selected_user, is_main_restaurant=False
                ).first()
            else:
                current_restaurant = base_restaurants.filter(
                    main_owner=selected_user, is_main_restaurant=True
                ).first()
            if not current_restaurant:
                raise Restaurant.DoesNotExist
            restaurants = [current_restaurant]  # Only show selected restaurant
        except (User.DoesNotExist, Restaurant.DoesNotExist):
            # Invalid session value, clear it and show all
            if 'selected_restaurant_id' in request.session:
                del request.session['selected_restaurant_id']
            restaurants = base_restaurants.order_by('-is_main_restaurant', 'name')
    else:
        # Viewing all restaurants
        restaurants = base_restaurants.order_by('-is_main_restaurant', 'name')
    
    # Get main restaurant for context
    main_restaurant = base_restaurants.filter(is_main_restaurant=True).first()
    
    # Build per-restaurant stats using DB-level annotations — avoids 6 queries per restaurant
    from django.db.models import Case, When, DecimalField
    from django.utils.timezone import localtime
    today = localtime(timezone.now()).date()

    # Annotate directly on the restaurants queryset
    restaurant_ids = [r.id for r in restaurants]
    annotated = Restaurant.objects.filter(id__in=restaurant_ids).annotate(
        orders_count=Count(
            'tables__orders',
            filter=Q(tables__orders__isnull=False),
            distinct=True,
        ),
        today_revenue=Sum(
            'tables__orders__total_amount',
            filter=Q(tables__orders__created_at__date=today),
        ),
        tables_count=Count('tables', distinct=True),
        products_count=Count('main_categories__products', distinct=True),
        pending_orders=Count(
            'tables__orders',
            filter=Q(tables__orders__status='pending'),
            distinct=True,
        ),
        staff_count=Count('branch_owner__owned_users', distinct=True),
    ).in_bulk()  # dict keyed by pk for O(1) lookup

    # Aggregate statistics
    total_orders = 0
    total_revenue = 0
    active_branches = 0
    total_staff = 0

    branch_stats = []

    for restaurant in restaurants:
        ann = annotated.get(restaurant.id, restaurant)
        orders_count   = ann.orders_count   or 0
        today_rev      = ann.today_revenue  or 0
        staff_count    = ann.staff_count    or 0
        tables_count   = ann.tables_count   or 0
        products_count = ann.products_count or 0
        pending_count  = ann.pending_orders or 0

        branch_stat = {
            'restaurant': restaurant,
            'orders_count': orders_count,
            'today_revenue': today_rev,
            'staff_count': staff_count,
            'tables_count': tables_count,
            'products_count': products_count,
            'pending_orders': pending_count,
            'is_active': restaurant.is_active,
        }
        branch_stats.append(branch_stat)

        # Add to totals
        total_orders  += orders_count
        total_revenue += today_rev
        total_staff   += staff_count
        if restaurant.is_active:
            active_branches += 1
    
    context = {
        'restaurants': restaurants,
        'branch_stats': branch_stats,
        'total_restaurants': len(restaurants),
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'active_branches': active_branches,
        'total_staff': total_staff,
        'main_restaurant': main_restaurant,
        'current_restaurant': current_restaurant,
        'view_all_restaurants': view_all_restaurants,
        'selected_restaurant_id': selected_restaurant_id,
    }
    
    return render(request, 'admin_panel/main_owner_dashboard.html', context)


@login_required
def branch_reports(request):
    """Consolidated reports view for main owners"""
    if not request.user.is_main_owner():
        messages.error(request, 'Only main owners can access this page.')
        return redirect('admin_panel:admin_dashboard')
    
    # Check PRO plan access for branch features
    if not request.user.can_access_branch_features():
        messages.error(request, 'Branch reports require a PRO subscription. Please upgrade your plan.')
        return redirect('admin_panel:admin_dashboard')
    
    restaurants = Restaurant.objects.filter(main_owner=request.user).select_related('branch_owner').order_by('name')
    
    # Date range filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    selected_restaurant = request.GET.get('restaurant')
    
    # Build query
    query = Q()
    restaurant_filter = restaurants
    
    if selected_restaurant and selected_restaurant != 'all':
        try:
            selected_rest = restaurants.get(id=selected_restaurant)
            query = (
                Q(table_info__restaurant=selected_rest) |
                Q(table_info__owner=selected_rest.branch_owner) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=selected_rest.branch_owner) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=selected_rest.branch_owner)
            )
            restaurant_filter = restaurants.filter(id=selected_restaurant)
        except Restaurant.DoesNotExist:
            pass
    else:
        # All restaurants
        for restaurant in restaurants:
            restaurant_query = (
                Q(table_info__restaurant=restaurant) |
                Q(table_info__owner=restaurant.branch_owner) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=restaurant.branch_owner) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=restaurant.branch_owner)
            )
            if query:
                query |= restaurant_query
            else:
                query = restaurant_query

    orders = Order.objects.filter(query)
    
    # Apply date filters
    if date_from:
        orders = orders.filter(created_at__gte=date_from)
    if date_to:
        orders = orders.filter(created_at__lte=date_to)
    
    # Calculate metrics
    total_orders = orders.count()
    total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    average_order = total_revenue / total_orders if total_orders > 0 else 0
    
    # Orders by status
    status_breakdown = orders.values('status').annotate(count=Count('id'))
    
    # Revenue by restaurant
    # Correlated subquery annotations — 1 SQL statement instead of N round-trips
    _rev_sq = Subquery(
        orders.filter(
            Q(table_info__restaurant=OuterRef('pk')) |
            Q(table_info__owner=OuterRef('branch_owner'))
        ).annotate(_g=Value(1)).values('_g').annotate(s=Sum('total_amount')).values('s')[:1]
    )
    _cnt_sq = Subquery(
        orders.filter(
            Q(table_info__restaurant=OuterRef('pk')) |
            Q(table_info__owner=OuterRef('branch_owner'))
        ).annotate(_g=Value(1)).values('_g').annotate(s=Count('id')).values('s')[:1]
    )

    restaurant_revenue = []
    for restaurant in restaurant_filter.annotate(_rest_rev=_rev_sq, _rest_cnt=_cnt_sq):
        rest_revenue = restaurant._rest_rev or 0
        rest_count = restaurant._rest_cnt or 0
        restaurant_revenue.append({
            'restaurant': restaurant,
            'revenue': rest_revenue,
            'orders': rest_count,
            'percentage': (rest_revenue / total_revenue * 100) if total_revenue > 0 else 0
        })
    
    # Recent orders
    recent_orders = orders.order_by('-created_at')[:10]
    
    context = {
        'restaurants': restaurants,
        'selected_restaurant': selected_restaurant,
        'date_from': date_from,
        'date_to': date_to,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'average_order': average_order,
        'status_breakdown': status_breakdown,
        'restaurant_revenue': restaurant_revenue,
        'recent_orders': recent_orders,
    }
    
    return render(request, 'admin_panel/branch_reports.html', context)


@login_required
def view_all_orders(request):
    """View all orders from all branches (read-only for main owners)"""
    if not request.user.is_main_owner():
        messages.error(request, 'Only main owners can access this page.')
        return redirect('admin_panel:admin_dashboard')
    
    # Check PRO plan access for branch features
    if not request.user.can_access_branch_features():
        messages.error(request, 'All branch orders view requires a PRO subscription. Please upgrade your plan.')
        return redirect('admin_panel:admin_dashboard')
    
    restaurants = Restaurant.objects.filter(main_owner=request.user).select_related('branch_owner')
    
    # Build query for all orders from owned restaurants
    query = Q()
    for restaurant in restaurants:
        restaurant_query = (
            Q(table_info__restaurant=restaurant) |
            Q(table_info__owner=restaurant.branch_owner) |
            Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=restaurant.branch_owner) |
            Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=restaurant.branch_owner)
        )
        if query:
            query |= restaurant_query
        else:
            query = restaurant_query

    orders = Order.objects.filter(query).select_related('table_info', 'ordered_by').prefetch_related('order_items').order_by('-created_at')
    
    # Filters
    status_filter = request.GET.get('status')
    restaurant_filter = request.GET.get('restaurant')
    
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    if restaurant_filter and restaurant_filter != 'all':
        try:
            selected_restaurant = restaurants.get(id=restaurant_filter)
            orders = orders.filter(
                Q(table_info__restaurant=selected_restaurant) |
                Q(table_info__owner=selected_restaurant.branch_owner) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=selected_restaurant.branch_owner) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=selected_restaurant.branch_owner)
            )
        except Restaurant.DoesNotExist:
            pass
    
    # Pagination
    paginator = Paginator(orders, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Order statuses for filter
    order_statuses = Order.STATUS_CHOICES
    
    context = {
        'orders': page_obj,
        'restaurants': restaurants,
        'order_statuses': order_statuses,
        'current_status': status_filter,
        'current_restaurant': restaurant_filter,
        'total_orders': orders.count(),
    }
    
    return render(request, 'admin_panel/view_all_orders.html', context)


@login_required
def branch_detail(request, restaurant_id):
    """Detailed view of a specific branch (read-only for main owners)"""
    if not request.user.is_main_owner():
        messages.error(request, 'Only main owners can access this page.')
        return redirect('admin_panel:admin_dashboard')
    
    # Check PRO plan access for branch features
    if not request.user.can_access_branch_features():
        messages.error(request, 'Branch details require a PRO subscription. Please upgrade your plan.')
        return redirect('admin_panel:admin_dashboard')
    
    restaurant = get_object_or_404(Restaurant, id=restaurant_id, main_owner=request.user)
    
    # Branch statistics
    orders = Order.objects.filter(
        Q(table_info__restaurant=restaurant) |
        Q(table_info__owner=restaurant.branch_owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=restaurant.branch_owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=restaurant.branch_owner)
    )
    
    total_orders = orders.count()
    total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Today's stats
    from django.utils.timezone import localtime
    today = localtime(timezone.now()).date()
    today_orders = orders.filter(created_at__date=today)
    _today = today_orders.aggregate(total=Sum('total_amount'), count=Count('id'))
    today_revenue = _today['total'] or 0
    today_order_count = _today['count'] or 0
    
    # This week's stats
    week_start = timezone.now() - timedelta(days=7)
    _week = orders.filter(created_at__gte=week_start).aggregate(total=Sum('total_amount'), count=Count('id'))
    week_orders = _week['count'] or 0
    week_revenue = _week['total'] or 0
    
    # Staff information
    staff = User.objects.filter(owner=restaurant.branch_owner)
    
    # Tables
    tables = TableInfo.objects.filter(
        Q(restaurant=restaurant) | Q(owner=restaurant.branch_owner)
    )
    
    # Products
    products = Product.objects.filter(
        Q(main_category__restaurant=restaurant) |
        Q(main_category__owner=restaurant.branch_owner)
    )
    
    # Recent orders
    recent_orders = orders.prefetch_related('order_items').order_by('-created_at')[:10]
    
    context = {
        'restaurant': restaurant,
        'branch': restaurant,          # template uses {{ branch.* }} alias
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'today_revenue': today_revenue,
        'today_orders': today_order_count,
        'week_orders': week_orders,
        'week_revenue': week_revenue,
        'staff': staff,
        'staff_count': staff.count(),
        'tables': tables,
        'tables_count': tables.count(),
        'products_count': products.count(),
        'recent_orders': recent_orders,
    }
    
    return render(request, 'admin_panel/branch_detail.html', context)