"""
Views for main owner monitoring of branch restaurants
Main owners can only VIEW data from branches, not manage them
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
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
    
    print(f"DEBUG: main_owner_dashboard - selected_restaurant_id={selected_restaurant_id}, view_all_restaurants={view_all_restaurants}")
    
    # Get base queryset of restaurants owned by this main owner
    base_restaurants = Restaurant.objects.filter(main_owner=request.user)
    print(f"DEBUG: base_restaurants count={base_restaurants.count()}")
    
    if selected_restaurant_id and not view_all_restaurants:
        # Viewing a specific restaurant
        try:
            current_restaurant = base_restaurants.get(id=selected_restaurant_id)
            restaurants = [current_restaurant]  # Only show selected restaurant
            print(f"DEBUG: Found current_restaurant={current_restaurant.name}")
        except Restaurant.DoesNotExist:
            # Invalid restaurant, clear session and show all
            print(f"DEBUG: Restaurant not found, clearing session")
            if 'selected_restaurant_id' in request.session:
                del request.session['selected_restaurant_id']
            restaurants = base_restaurants.order_by('-is_main_restaurant', 'name')
    else:
        # Viewing all restaurants
        print(f"DEBUG: Viewing all restaurants")
        restaurants = base_restaurants.order_by('-is_main_restaurant', 'name')
    
    print(f"DEBUG: Final restaurants count={len(restaurants)}")
    
    # Get main restaurant for context
    main_restaurant = base_restaurants.filter(is_main_restaurant=True).first()
    
    # Aggregate statistics
    total_orders = 0
    total_revenue = 0
    active_branches = 0  # Will count active restaurants
    total_staff = 0
    
    branch_stats = []
    
    for restaurant in restaurants:
        # Orders for this restaurant
        restaurant_orders = Order.objects.filter(
            Q(table_info__restaurant=restaurant) |
            Q(table_info__owner=restaurant.branch_owner)
        )
        
        orders_count = restaurant_orders.count()
        
        # Revenue calculation
        today = timezone.now().date()
        today_revenue = restaurant_orders.filter(
            created_at__date=today
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        # Staff count
        staff_count = User.objects.filter(owner=restaurant.branch_owner).count()
        
        # Tables count
        tables_count = TableInfo.objects.filter(
            Q(restaurant=restaurant) | Q(owner=restaurant.branch_owner)
        ).count()
        
        # Products count
        products_count = Product.objects.filter(
            Q(main_category__restaurant=restaurant) |
            Q(main_category__owner=restaurant.branch_owner)
        ).count()
        
        # Pending orders
        pending_orders = restaurant_orders.filter(status='pending').count()
        
        branch_stat = {
            'restaurant': restaurant,
            'orders_count': orders_count,
            'today_revenue': today_revenue,
            'staff_count': staff_count,
            'tables_count': tables_count,
            'products_count': products_count,
            'pending_orders': pending_orders,
            'is_active': restaurant.is_active,  # Use actual database field
        }
        branch_stats.append(branch_stat)
        
        # Add to totals
        total_orders += orders_count
        total_revenue += today_revenue
        total_staff += staff_count
        if restaurant.is_active:  # Count active restaurants based on database field
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
    
    restaurants = Restaurant.objects.filter(main_owner=request.user).order_by('name')
    
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
            query = Q(table_info__restaurant=selected_rest) | Q(table_info__owner=selected_rest.branch_owner)
            restaurant_filter = restaurants.filter(id=selected_restaurant)
        except Restaurant.DoesNotExist:
            pass
    else:
        # All restaurants
        for restaurant in restaurants:
            restaurant_query = Q(table_info__restaurant=restaurant) | Q(table_info__owner=restaurant.branch_owner)
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
    restaurant_revenue = []
    for restaurant in restaurant_filter:
        rest_orders = orders.filter(
            Q(table_info__restaurant=restaurant) | Q(table_info__owner=restaurant.branch_owner)
        )
        rest_revenue = rest_orders.aggregate(total=Sum('total_amount'))['total'] or 0
        rest_count = rest_orders.count()
        
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
    
    restaurants = Restaurant.objects.filter(main_owner=request.user)
    
    # Build query for all orders from owned restaurants
    query = Q()
    for restaurant in restaurants:
        restaurant_query = Q(table_info__restaurant=restaurant) | Q(table_info__owner=restaurant.branch_owner)
        if query:
            query |= restaurant_query
        else:
            query = restaurant_query
    
    orders = Order.objects.filter(query).order_by('-created_at')
    
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
                Q(table_info__owner=selected_restaurant.branch_owner)
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
        Q(table_info__restaurant=restaurant) | Q(table_info__owner=restaurant.branch_owner)
    )
    
    total_orders = orders.count()
    total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Today's stats
    today = timezone.now().date()
    today_orders = orders.filter(created_at__date=today)
    today_revenue = today_orders.aggregate(total=Sum('total_amount'))['total'] or 0
    today_order_count = today_orders.count()
    
    # This week's stats
    week_start = timezone.now() - timedelta(days=7)
    week_orders = orders.filter(created_at__gte=week_start).count()
    week_revenue = orders.filter(created_at__gte=week_start).aggregate(total=Sum('total_amount'))['total'] or 0
    
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
    recent_orders = orders.order_by('-created_at')[:10]
    
    context = {
        'restaurant': restaurant,
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