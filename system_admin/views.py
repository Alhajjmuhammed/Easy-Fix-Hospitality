from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Q
from django.utils import timezone
from django.core.paginator import Paginator
from accounts.models import User, Role, RestaurantSubscription, SubscriptionLog
from restaurant.models import MainCategory, SubCategory, Product, TableInfo
from restaurant.models_restaurant import Restaurant
from orders.models import Order, OrderItem
from django.contrib.auth.hashers import make_password
from datetime import date, timedelta, datetime
import json

def get_all_restaurants_for_admin():
    """
    Helper function to get all restaurants for admin filtering.
    Returns a list of dictionaries with id and name for both User and Restaurant models.
    Updated to show accurate subscription plan information after data cleanup.
    """
    # Priority: Get restaurants from Restaurant model first (more accurate)
    restaurants_from_model = Restaurant.objects.select_related('main_owner', 'main_owner__role').filter(
        is_main_restaurant=True,  # Only main restaurants for filtering
        main_owner__is_active=True  # Only active owners
    ).values(
        'main_owner__id', 'name', 'subscription_plan', 'main_owner__role__name'
    )
    
    # Get restaurants from User model that don't have Restaurant model entries
    restaurants_from_users = User.objects.filter(
        role__name__in=['owner', 'main_owner', 'branch_owner'], 
        restaurant_name__isnull=False,
        is_active=True
    ).exclude(restaurant_name='').exclude(
        id__in=[r['main_owner__id'] for r in restaurants_from_model]
    ).values(
        'id', 'restaurant_name', 'role__name'
    )
    
    # Build final restaurant list
    restaurant_list = []
    
    # Add from Restaurant model (most accurate)
    for resto in restaurants_from_model:
        plan_display = ""
        if resto['subscription_plan'] == 'PRO':
            plan_display = " (PRO)"
        elif resto['subscription_plan'] == 'SINGLE':
            plan_display = " (Single)"
            
        restaurant_list.append({
            'id': resto['main_owner__id'],
            'name': resto['name'] + plan_display,
            'role': resto['main_owner__role__name'],
            'plan': resto['subscription_plan']
        })
    
    # Add from User model (legacy entries without Restaurant model)
    for resto in restaurants_from_users:
        restaurant_list.append({
            'id': resto['id'],
            'name': resto['restaurant_name'],
            'role': resto['role__name'],
            'plan': 'LEGACY'
        })
    
    # Sort by name
    return sorted(restaurant_list, key=lambda x: x['name'])

def get_restaurant_owner_by_id(restaurant_id):
    """
    Helper function to get restaurant owner by ID, supporting all owner types.
    """
    return get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner', 'branch_owner'])

@login_required
def system_dashboard(request):
    """System-wide dashboard for administrators"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # System statistics - Use Restaurant model for accurate counts
    total_restaurants = Restaurant.objects.filter(is_main_restaurant=True).count()
    total_branches = Restaurant.objects.filter(is_main_restaurant=False).count()
    total_owners = User.objects.filter(role__name__in=['owner', 'main_owner', 'branch_owner']).count()
    total_users = User.objects.count()
    total_categories = MainCategory.objects.count()
    total_products = Product.objects.count()
    total_tables = TableInfo.objects.count()
    total_orders = Order.objects.count()
    
    # Recent activity
    recent_orders = Order.objects.select_related('table_info', 'ordered_by').order_by('-created_at')[:10]
    recent_users = User.objects.select_related('role').order_by('-created_at')[:10]
    
    # Restaurant breakdown - Use Restaurant model with optimized queries
    restaurants = []
    restaurant_list = Restaurant.objects.filter(
        is_main_restaurant=True
    ).select_related('main_owner', 'main_owner__role').prefetch_related(
        'main_owner__owned_users'
    ).order_by('name')[:10]  # Limit to first 10 for dashboard performance
    
    for restaurant in restaurant_list:
        owner = restaurant.main_owner
        restaurant_data = {
            'owner': owner,
            'restaurant': restaurant,
            'categories': MainCategory.objects.filter(owner=owner).count(),
            'products': Product.objects.filter(main_category__owner=owner).count(),
            'tables': TableInfo.objects.filter(owner=owner).count(),
            'orders': Order.objects.filter(table_info__owner=owner).count(),
            'staff': User.objects.filter(owner=owner).count(),
        }
        restaurants.append(restaurant_data)
    
    context = {
        'total_restaurants': total_restaurants,
        'total_branches': total_branches,
        'total_owners': total_owners,
        'total_users': total_users,
        'total_categories': total_categories,
        'total_products': total_products,
        'total_tables': total_tables,
        'total_orders': total_orders,
        'recent_orders': recent_orders,
        'recent_users': recent_users,
        'restaurants': restaurants,
    }
    
    return render(request, 'system_admin/dashboard.html', context)


@login_required
def statistics(request):
    """System-wide statistics for administrators"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    from datetime import datetime, timedelta
    from django.utils import timezone
    
    # Get comprehensive system statistics
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Basic counts - Updated for new role system
    stats = {
        'total_restaurants': User.objects.filter(
            role__name__in=['owner', 'main_owner', 'branch_owner'],
            restaurant_name__isnull=False
        ).exclude(restaurant_name='').count(),
        'total_users': User.objects.count(),
        'total_orders': Order.objects.count(),
        'total_products': Product.objects.count(),
        'total_categories': MainCategory.objects.count(),
        'total_tables': TableInfo.objects.count(),
    }
    
    # Time-based statistics
    stats.update({
        'orders_today': Order.objects.filter(created_at__date=today).count(),
        'orders_this_week': Order.objects.filter(created_at__date__gte=week_ago).count(),
        'orders_this_month': Order.objects.filter(created_at__date__gte=month_ago).count(),
        'new_users_today': User.objects.filter(date_joined__date=today).count(),
        'new_users_this_week': User.objects.filter(date_joined__date__gte=week_ago).count(),
        'new_users_this_month': User.objects.filter(date_joined__date__gte=month_ago).count(),
    })
    
    # Order status breakdown
    order_status_counts = {}
    for status in ['pending', 'confirmed', 'preparing', 'ready', 'delivered', 'cancelled']:
        order_status_counts[status] = Order.objects.filter(status=status).count()
    
    # User role breakdown
    user_role_counts = {}
    for role_obj in Role.objects.all():
        user_role_counts[role_obj.name] = User.objects.filter(role=role_obj).count()
    
    # Top restaurants by order count - Updated for new role system
    top_restaurants = User.objects.filter(
        role__name__in=['owner', 'main_owner', 'branch_owner'],
        restaurant_name__isnull=False
    ).exclude(restaurant_name='').annotate(
        order_count=Count('tableinfo__order')
    ).order_by('-order_count')[:10]
    
    context = {
        'stats': stats,
        'order_status_counts': order_status_counts,
        'user_role_counts': user_role_counts,
        'top_restaurants': top_restaurants,
    }
    
    return render(request, 'system_admin/statistics.html', context)

@login_required
def manage_all_restaurants(request):
    """Manage all restaurants system-wide with subscription plan information"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    plan_filter = request.GET.get('plan', '')
    subscription_status_filter = request.GET.get('subscription_status', '')
    per_page = int(request.GET.get('per_page', 10))  # Default to 10, allow customization
    page = request.GET.get('page', 1)
    
    # Start with all restaurants
    restaurants = Restaurant.objects.select_related('main_owner', 'branch_owner').order_by('-is_main_restaurant', 'name')
    
    # Apply search filter
    if search_query:
        restaurants = restaurants.filter(
            Q(name__icontains=search_query) |
            Q(main_owner__username__icontains=search_query) |
            Q(main_owner__first_name__icontains=search_query) |
            Q(main_owner__last_name__icontains=search_query) |
            Q(main_owner__email__icontains=search_query) |
            Q(address__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter:
        if status_filter == 'active':
            restaurants = restaurants.filter(is_active=True)
        elif status_filter == 'inactive':
            restaurants = restaurants.filter(is_active=False)
    
    # Apply subscription plan filter
    if plan_filter:
        restaurants = restaurants.filter(subscription_plan=plan_filter)
    
    # Apply subscription status filter
    if subscription_status_filter:
        # Filter by subscription status through main_owner relationship
        if subscription_status_filter == 'active':
            restaurants = restaurants.filter(main_owner__subscription__subscription_status='active')
        elif subscription_status_filter == 'blocked':
            restaurants = restaurants.filter(main_owner__subscription__subscription_status='blocked')
        elif subscription_status_filter == 'expired':
            restaurants = restaurants.filter(main_owner__subscription__subscription_status='expired')
        elif subscription_status_filter == 'no_subscription':
            restaurants = restaurants.filter(main_owner__subscription__isnull=True)
    
    # Get total count before pagination
    total_restaurants = restaurants.count()
    
    # Calculate subscription plan statistics (before filtering)
    all_restaurants = Restaurant.objects.select_related('main_owner', 'branch_owner')
    subscription_stats = {
        'total': all_restaurants.count(),
        'single_plan': all_restaurants.filter(subscription_plan='SINGLE').count(),
        'pro_plan': all_restaurants.filter(subscription_plan='PRO').count(),
        'main_restaurants': all_restaurants.filter(is_main_restaurant=True).count(),
        'branches': all_restaurants.filter(is_main_restaurant=False).count(),
        'active': all_restaurants.filter(is_active=True).count(),
        'inactive': all_restaurants.filter(is_active=False).count(),
    }
    
    
    # Pagination with customizable per_page
    from django.core.paginator import Paginator
    # Ensure per_page is within reasonable limits
    per_page = max(5, min(per_page, 50))  # Between 5 and 50
    paginator = Paginator(restaurants, per_page)
    try:
        restaurants_page = paginator.page(page)
    except:
        restaurants_page = paginator.page(1)
    
    # Add computed fields for template
    restaurant_data = []
    for restaurant in restaurants_page:
        # Add subscription plan info
        restaurant.subscription_display = restaurant.get_subscription_display()
        restaurant.can_create_branches_display = restaurant.can_create_branches()
        restaurant.branch_count = restaurant.branches.count() if restaurant.is_main_restaurant else 0
        
        # Add owner information from the User model for template compatibility
        main_owner = restaurant.main_owner
        restaurant.username = main_owner.username
        restaurant.email = main_owner.email
        restaurant.first_name = main_owner.first_name
        restaurant.last_name = main_owner.last_name
        
        # Add subscription status and days remaining
        try:
            subscription = main_owner.subscription
            restaurant.subscription_status = subscription.subscription_status
            restaurant.days_remaining = subscription.days_until_expiration
            restaurant.is_blocked = subscription.subscription_status == 'blocked' or subscription.is_blocked_by_admin
            restaurant.is_in_grace = subscription.is_in_grace_period
        except:
            # No subscription record found
            restaurant.subscription_status = 'unknown'
            restaurant.days_remaining = 0
            restaurant.is_blocked = False
            restaurant.is_in_grace = False
        
        # Use Restaurant model data when available, fallback to User model
        restaurant.phone_number = main_owner.phone_number
        restaurant.address = restaurant.address  # Always use Restaurant model address
        restaurant.date_joined = main_owner.date_joined
        restaurant.restaurant_name = restaurant.name  # Always use Restaurant model
        restaurant.restaurant_description = restaurant.description  # Always use Restaurant model
        
        # Debug: Add updated timestamp to check if data is fresh
        restaurant.debug_updated = restaurant.updated_at
        
        # Add get_full_name method result directly as property for template access
        restaurant.full_name_display = main_owner.get_full_name()
        
        # Add owner information for detailed views
        restaurant.owner_info = {
            'main_owner_name': main_owner.get_full_name() or main_owner.username,
            'main_owner_email': main_owner.email,
            'branch_owner_name': restaurant.branch_owner.get_full_name() or restaurant.branch_owner.username if restaurant.branch_owner else 'N/A',
            'branch_owner_email': restaurant.branch_owner.email if restaurant.branch_owner else 'N/A',
        }
        
        restaurant_data.append(restaurant)
    
    # Get filter options for dropdowns
    subscription_plans = [('SINGLE', 'Single Plan'), ('PRO', 'PRO Plan')]
    subscription_statuses = [('active', 'Active'), ('blocked', 'Blocked'), ('expired', 'Expired'), ('no_subscription', 'No Subscription')]
    status_options = [('active', 'Active'), ('inactive', 'Inactive')]
    per_page_options = [5, 10, 15, 20, 25, 50]
    
    context = {
        'restaurants': restaurants_page,  # Pass the paginated queryset
        'total_restaurants': total_restaurants,
        'filtered_count': total_restaurants,
        'subscription_stats': subscription_stats,
        'search_query': search_query,
        'status_filter': status_filter,
        'plan_filter': plan_filter,
        'subscription_status_filter': subscription_status_filter,
        'per_page': per_page,
        'subscription_plans': subscription_plans,
        'subscription_statuses': subscription_statuses,
        'status_options': status_options,
        'per_page_options': per_page_options,
        'paginator': paginator,
        'page_obj': restaurants_page,
    }
    
    return render(request, 'system_admin/manage_restaurants.html', context)

@login_required
def manage_all_users(request):
    """Manage all users system-wide"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Get all restaurants for filtering - Updated to include all owner types and PRO plans
    restaurants = get_all_restaurants_for_admin()
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '').strip()
    restaurant_filter = request.GET.get('restaurant')
    role_filter = request.GET.get('role')
    status_filter = request.GET.get('status')
    
    # Get pagination parameter
    per_page = int(request.GET.get('per_page', 20))
    if per_page not in [5, 10, 15, 20, 25, 30, 50]:
        per_page = 20
    
    # Start with all users
    users = User.objects.select_related('role', 'owner')
    
    # Apply search filter
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(restaurant_name__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(role__name__icontains=search_query)
        )
    
    # Apply restaurant filter
    if restaurant_filter:
        users = users.filter(Q(id=restaurant_filter) | Q(owner__id=restaurant_filter))
        selected_restaurant = get_restaurant_owner_by_id(restaurant_filter)
    else:
        selected_restaurant = None
    
    # Apply role filter
    if role_filter:
        users = users.filter(role__name=role_filter)
        
    # Apply status filter
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    
    # Get total count before pagination
    total_users = users.count()
    
    users = users.order_by('role__name', 'username')
    
    # Apply pagination
    paginator = Paginator(users, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Count filtered results
    filtered_count = users.count()
    
    # Get all roles for dropdown
    roles = Role.objects.all().order_by('name')
    
    context = {
        'page_obj': page_obj,
        'users': page_obj.object_list,
        'restaurants': restaurants,
        'roles': roles,
        'selected_restaurant': selected_restaurant,
        'search_query': search_query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'per_page': per_page,
        'total_users': total_users,
        'filtered_count': filtered_count,
    }
    
    return render(request, 'system_admin/manage_users.html', context)

@login_required
def view_all_orders(request):
    """View all orders system-wide"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Filter options
    status_filter = request.GET.get('status', 'all')
    restaurant_filter = request.GET.get('restaurant', 'all')
    
    orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by').order_by('-created_at')
    
    if status_filter != 'all':
        orders = orders.filter(status=status_filter)
    
    if restaurant_filter != 'all':
        orders = orders.filter(table_info__owner__id=restaurant_filter)
    
    # Get filter options - Updated for new role system
    restaurant_owners = User.objects.filter(
        role__name__in=['owner', 'main_owner', 'branch_owner'], 
        restaurant_name__isnull=False
    ).exclude(restaurant_name='')
    
    context = {
        'orders': orders,
        'restaurant_owners': restaurant_owners,
        'status_filter': status_filter,
        'restaurant_filter': restaurant_filter,
        'status_choices': Order.STATUS_CHOICES,
    }
    
    return render(request, 'system_admin/view_orders.html', context)

@login_required
def system_statistics(request):
    """Comprehensive system statistics"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # User statistics by role
    user_stats = {}
    for role in Role.objects.all():
        user_stats[role.name] = User.objects.filter(role=role).count()
    
    # Restaurant statistics - Updated for new role system
    restaurant_stats = []
    for owner in User.objects.filter(
        role__name__in=['owner', 'main_owner', 'branch_owner'], 
        restaurant_name__isnull=False
    ).exclude(restaurant_name=''):
        stats = {
            'restaurant_name': owner.restaurant_name,
            'owner': owner,
            'categories': MainCategory.objects.filter(owner=owner).count(),
            'products': Product.objects.filter(main_category__owner=owner).count(),
            'tables': TableInfo.objects.filter(owner=owner).count(),
            'total_orders': Order.objects.filter(table_info__owner=owner).count(),
            'pending_orders': Order.objects.filter(table_info__owner=owner, status='pending').count(),
            'completed_orders': Order.objects.filter(table_info__owner=owner, status='delivered').count(),
            'staff_count': User.objects.filter(owner=owner).count(),
        }
        restaurant_stats.append(stats)
    
    # Order statistics
    order_stats = {
        'total': Order.objects.count(),
        'pending': Order.objects.filter(status='pending').count(),
        'confirmed': Order.objects.filter(status='confirmed').count(),
        'preparing': Order.objects.filter(status='preparing').count(),
        'ready': Order.objects.filter(status='ready').count(),
        'delivered': Order.objects.filter(status='delivered').count(),
        'cancelled': Order.objects.filter(status='cancelled').count(),
    }
    
    context = {
        'user_stats': user_stats,
        'restaurant_stats': restaurant_stats,
        'order_stats': order_stats,
    }
    
    return render(request, 'system_admin/statistics.html', context)

@login_required
def create_restaurant_owner(request):
    """Create a new restaurant owner"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    if request.method == 'POST':
        try:
            # Get form data
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            restaurant_name = request.POST.get('restaurant_name', '').strip()
            restaurant_description = request.POST.get('restaurant_description', '').strip()
            phone_number = request.POST.get('phone_number', '').strip()
            address = request.POST.get('address', '').strip()
            password = request.POST.get('password', '')
            confirm_password = request.POST.get('confirm_password', '')
            
            # Additional fields
            cuisine_type = request.POST.get('cuisine_type', '').strip()
            opening_hours = request.POST.get('opening_hours', '').strip()
            
            # Subscription management fields
            quick_period = request.POST.get('quick_period', '')
            subscription_start_date = request.POST.get('subscription_start_date', '')
            subscription_end_date = request.POST.get('subscription_end_date', '')
            subscription_status = request.POST.get('subscription_status', 'active')
            
            # Subscription plan field
            subscription_plan = 'PRO' if request.POST.get('subscription_plan') == 'PRO' else 'SINGLE'
            
            # Handle subscription dates based on quick_period or custom dates
            if quick_period and quick_period != 'custom':
                # Use preset period - calculate dates automatically
                days = int(quick_period)
                start_date_obj = date.today()
                end_date_obj = start_date_obj + timedelta(days=days)
            elif quick_period == 'custom':
                # Use custom dates from form
                if not subscription_start_date or not subscription_end_date:
                    errors.append('Start and end dates are required when using custom period.')
                else:
                    try:
                        start_date_obj = datetime.strptime(subscription_start_date, '%Y-%m-%d').date()
                        end_date_obj = datetime.strptime(subscription_end_date, '%Y-%m-%d').date()
                        
                        if end_date_obj <= start_date_obj:
                            errors.append('Subscription end date must be after start date.')
                    except ValueError:
                        errors.append('Invalid date format for subscription dates.')
            else:
                # Default fallback (30 days)
                start_date_obj = date.today()
                end_date_obj = start_date_obj + timedelta(days=30)
            
            # Enhanced validation
            errors = []
            
            # Required field validation
            if not username:
                errors.append('Username is required.')
            if not email:
                errors.append('Email is required.')
            if not first_name:
                errors.append('First name is required.')
            if not last_name:
                errors.append('Last name is required.')
            if not restaurant_name:
                errors.append('Restaurant name is required.')
            if not phone_number:
                errors.append('Restaurant phone number is required.')
            if not address:
                errors.append('Restaurant address is required.')
            if not password:
                errors.append('Password is required.')
            if not confirm_password:
                errors.append('Password confirmation is required.')
            
            # Format validation
            if username and not username.replace('_', '').isalnum():
                errors.append('Username can only contain letters, numbers, and underscores.')
            
            if email and '@' not in email:
                errors.append('Please provide a valid email address.')
            
            if password != confirm_password:
                errors.append('Passwords do not match.')
            
            if password and len(password) < 6:
                errors.append('Password must be at least 6 characters long.')
            
            # Check for existing username and email
            if username and User.objects.filter(username=username).exists():
                errors.append(f'Username "{username}" already exists.')
            
            if email and User.objects.filter(email=email).exists():
                errors.append(f'Email "{email}" already exists.')
            
            if errors:
                for error in errors:
                    messages.error(request, error)
                return redirect('system_admin:manage_restaurants')
            
            # Get main_owner role (updated for new system)
            try:
                main_owner_role = Role.objects.get(name='main_owner')
            except Role.DoesNotExist:
                # Fallback to 'owner' role if main_owner doesn't exist
                main_owner_role = Role.objects.get(name='owner')
            
            # Create the restaurant description with additional info
            enhanced_description = restaurant_description
            if cuisine_type:
                enhanced_description += f"\n\nCuisine Type: {cuisine_type.title()}"
            if opening_hours:
                enhanced_description += f"\nOpening Hours: {opening_hours}"
            
            # Create the main owner user
            new_owner = User.objects.create(
                username=username,
                email=email,
                password=make_password(password),
                first_name=first_name,
                last_name=last_name,
                role=main_owner_role,
                restaurant_name=restaurant_name,
                restaurant_description=enhanced_description.strip(),
                phone_number=phone_number,
                address=address,
                is_active_staff=True,
                owner=None
            )
            
            # Create the Restaurant model object
            new_restaurant = Restaurant.objects.create(
                name=restaurant_name,
                description=enhanced_description.strip(),
                address=address,
                subscription_plan=subscription_plan,  # Use the PRO/SINGLE choice from form
                main_owner=new_owner,
                branch_owner=new_owner,  # For main restaurant, main_owner is also branch_owner
                is_main_restaurant=True,
                parent_restaurant=None,
                is_active=True
            )
            
            # Calculate subscription duration
            subscription_days = (end_date_obj - start_date_obj).days
            period_type = f"{quick_period} days" if quick_period != 'custom' else 'custom dates'
            
            # Create subscription with calculated dates and status
            subscription = RestaurantSubscription.objects.create(
                restaurant_owner=new_owner,
                subscription_start_date=start_date_obj,
                subscription_end_date=end_date_obj,
                subscription_status=subscription_status,
                created_by=request.user
            )
            
            # Log subscription creation
            SubscriptionLog.objects.create(
                subscription=subscription,
                action='created',
                description=f"Restaurant subscription created ({period_type}): {start_date_obj} to {end_date_obj} ({subscription_days} days) - Status: {subscription_status}",
                old_status='none',
                new_status=subscription_status,
                performed_by=request.user
            )
            
            success_msg = f'Restaurant "{restaurant_name}" and owner account "{username}" created successfully!'
            success_msg += f' Subscription Plan: {subscription_plan}'
            success_msg += f' | Status: {subscription_status} from {start_date_obj} to {end_date_obj} ({subscription_days} days).'
            if cuisine_type:
                success_msg += f' Cuisine type: {cuisine_type.title()}.'
            
            messages.success(request, success_msg)
            
            # Log the creation for system tracking
            print(f"[SYSTEM ADMIN] New restaurant created: {restaurant_name} ({subscription_plan} plan) by {request.user.username}")
            print(f"[SYSTEM ADMIN] Subscription created: {subscription_status} from {start_date_obj} to {end_date_obj}")
            
            return redirect('system_admin:manage_restaurants')
            
        except Role.DoesNotExist:
            messages.error(request, 'Owner role not found. Please ensure roles are properly configured.')
        except Exception as e:
            messages.error(request, f'Error creating restaurant owner: {str(e)}')
            print(f"[ERROR] Restaurant creation failed: {str(e)}")
    
    return redirect('system_admin:manage_restaurants')

@login_required
def get_restaurant_details(request, restaurant_id):
    """Get detailed restaurant information via AJAX - NEW Restaurant model version"""
    if not request.user.is_administrator():
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    try:
        # Fetch Restaurant model (not User model!)
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        
        # Get main owner information
        main_owner = restaurant.main_owner
        
        # Parse restaurant description for additional info
        cuisine_type = ""
        opening_hours = ""
        if restaurant.description:
            for line in restaurant.description.splitlines():
                if "Cuisine Type:" in line:
                    cuisine_type = line.replace("Cuisine Type:", "").strip()
                elif "Opening Hours:" in line:
                    opening_hours = line.replace("Opening Hours:", "").strip()
        
        # Get restaurant statistics
        from restaurant.models import MainCategory, Product, TableInfo
        from orders.models import Order
        
        stats = {
            'categories': MainCategory.objects.filter(owner=main_owner).count(),
            'products': Product.objects.filter(main_category__owner=main_owner).count(),
            'tables': TableInfo.objects.filter(owner=main_owner).count(),
            'orders': Order.objects.filter(table_info__owner=main_owner).count(),
            'staff': User.objects.filter(owner=main_owner).count(),
        }
        
        # Get subscription information from main_owner
        subscription_data = None
        if hasattr(main_owner, 'subscription'):
            subscription = main_owner.subscription
            subscription_data = {
                'start_date': subscription.subscription_start_date.strftime('%Y-%m-%d'),
                'end_date': subscription.subscription_end_date.strftime('%Y-%m-%d'),
                'subscription_status': subscription.subscription_status,
                'days_remaining': subscription.days_until_expiration,
                'is_active': subscription.is_active,
            }
        
        data = {
            'id': restaurant.id,
            'restaurant_name': restaurant.name,
            'restaurant_description': restaurant.description or '',
            'cuisine_type': cuisine_type,
            'opening_hours': opening_hours,
            'username': main_owner.username,
            'email': main_owner.email,
            'first_name': main_owner.first_name,
            'last_name': main_owner.last_name,
            'phone_number': main_owner.phone_number or '',
            'address': restaurant.address or '',
            'date_joined': main_owner.date_joined.strftime('%B %d, %Y'),
            'is_active': restaurant.is_active,
            'subscription_plan': restaurant.get_subscription_display(),
            'is_main_restaurant': restaurant.is_main_restaurant,
            'branch_count': restaurant.branches.count() if restaurant.is_main_restaurant else 0,
            'stats': stats,
            'subscription': subscription_data,
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def edit_restaurant(request, restaurant_id):
    """Edit restaurant information - NEW Restaurant model version"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Fetch Restaurant model (not User model!)
    restaurant_model = get_object_or_404(Restaurant, id=restaurant_id)
    main_owner = restaurant_model.main_owner
    
    if request.method == 'POST':
        try:
            # Get form data - all fields to match create form
            restaurant_name = request.POST.get('restaurant_name', '').strip()
            restaurant_description = request.POST.get('restaurant_description', '').strip()
            phone_number = request.POST.get('phone_number', '').strip()
            address = request.POST.get('address', '').strip()
            cuisine_type = request.POST.get('cuisine_type', '').strip()
            opening_hours = request.POST.get('opening_hours', '').strip()
            
            # Owner information
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            password = request.POST.get('password', '').strip()
            confirm_password = request.POST.get('confirm_password', '').strip()
            
            # Subscription management fields
            subscription_start_date = request.POST.get('subscription_start_date', '')
            subscription_end_date = request.POST.get('subscription_end_date', '')
            subscription_status = request.POST.get('subscription_status', 'active')
            
            # Account status field
            is_active = request.POST.get('is_active', 'true') == 'true'
            
            # Validation
            errors = []
            
            # Required field validation
            if not restaurant_name:
                errors.append('Restaurant name is required.')
            if not phone_number:
                errors.append('Phone number is required.')
            if not address:
                errors.append('Address is required.')
            if not username:
                errors.append('Username is required.')
            if not email:
                errors.append('Email is required.')
            if not first_name:
                errors.append('First name is required.')
            if not last_name:
                errors.append('Last name is required.')
            if not subscription_start_date:
                errors.append('Subscription start date is required.')
            if not subscription_end_date:
                errors.append('Subscription end date is required.')
            
            # Format validation
            if username and not username.replace('_', '').isalnum():
                errors.append('Username can only contain letters, numbers, and underscores.')
            
            if email and '@' not in email:
                errors.append('Please provide a valid email address.')
            
            # Password validation (only if provided)
            if password or confirm_password:
                if password != confirm_password:
                    errors.append('Passwords do not match.')
                if password and len(password) < 6:
                    errors.append('Password must be at least 6 characters long.')
            
            # Validate subscription dates
            if subscription_start_date and subscription_end_date:
                try:
                    start_date_obj = datetime.strptime(subscription_start_date, '%Y-%m-%d').date()
                    end_date_obj = datetime.strptime(subscription_end_date, '%Y-%m-%d').date()
                    
                    if end_date_obj <= start_date_obj:
                        errors.append('Subscription end date must be after start date.')
                except ValueError:
                    errors.append('Invalid date format for subscription dates.')
            
            # Check for existing username and email (exclude current main_owner)
            if username and User.objects.filter(username=username).exclude(id=main_owner.id).exists():
                errors.append(f'Username "{username}" already exists.')
            
            if email and User.objects.filter(email=email).exclude(id=main_owner.id).exists():
                errors.append(f'Email "{email}" already exists.')
            
            if errors:
                return JsonResponse({'success': False, 'errors': errors})
            
            # Create enhanced description
            enhanced_description = restaurant_description
            if cuisine_type:
                enhanced_description += f"\n\nCuisine Type: {cuisine_type.title()}"
            if opening_hours:
                enhanced_description += f"\nOpening Hours: {opening_hours}"
            
            # Update Restaurant model
            restaurant_model.name = restaurant_name
            restaurant_model.description = enhanced_description.strip()
            restaurant_model.address = address
            restaurant_model.is_active = is_active
            restaurant_model.save(update_fields=['name', 'description', 'address', 'is_active', 'updated_at'])
            
            # Update main_owner User model
            main_owner.username = username
            main_owner.email = email
            main_owner.first_name = first_name
            main_owner.last_name = last_name
            main_owner.phone_number = phone_number
            main_owner.is_active = is_active
            
            # Update password only if provided
            if password:
                main_owner.set_password(password)
            
            main_owner.save()
            
            # Handle subscription update or creation only if dates are provided
            subscription_msg = ''
            if subscription_start_date and subscription_end_date:
                start_date_obj = datetime.strptime(subscription_start_date, '%Y-%m-%d').date()
                end_date_obj = datetime.strptime(subscription_end_date, '%Y-%m-%d').date()
                
                if hasattr(main_owner, 'subscription'):
                    # Update existing subscription
                    subscription = main_owner.subscription
                    old_start_date = subscription.subscription_start_date
                    old_end_date = subscription.subscription_end_date
                    old_status = subscription.subscription_status
                    
                    subscription.subscription_start_date = start_date_obj
                    subscription.subscription_end_date = end_date_obj
                    subscription.subscription_status = subscription_status
                    subscription.save()
                    
                    # Log subscription update
                    from accounts.models import SubscriptionLog
                    SubscriptionLog.objects.create(
                        subscription=subscription,
                        action='updated',
                        description=f"Subscription updated by admin: dates {old_start_date}-{old_end_date} → {start_date_obj}-{end_date_obj}, status {old_status} → {subscription_status}",
                        old_status=old_status,
                        new_status=subscription_status,
                        performed_by=request.user
                    )
                    
                    subscription_msg = f' Subscription updated: {subscription_status} from {start_date_obj} to {end_date_obj}.'
                else:
                    # Create new subscription
                    from accounts.models import RestaurantSubscription, SubscriptionLog
                    subscription = RestaurantSubscription.objects.create(
                        restaurant_owner=main_owner,
                        subscription_start_date=start_date_obj,
                        subscription_end_date=end_date_obj,
                        subscription_status=subscription_status,
                        created_by=request.user
                    )
                    
                    # Log subscription creation
                    SubscriptionLog.objects.create(
                        subscription=subscription,
                        action='created',
                        description=f"New subscription created by admin: {subscription_status} from {start_date_obj} to {end_date_obj}",
                        old_status='none',
                        new_status=subscription_status,
                        performed_by=request.user
                    )
                    
                    subscription_msg = f' New subscription created: {subscription_status} from {start_date_obj} to {end_date_obj}.'
            
            success_msg = f'Restaurant "{restaurant_name}" updated successfully!'
            success_msg += subscription_msg
            if password:
                success_msg += ' Password has been changed.'
            
            return JsonResponse({'success': True, 'message': success_msg})
            
        except Exception as e:
            error_msg = f'Error updating restaurant: {str(e)}'
            messages.error(request, error_msg)
            return JsonResponse({'success': False, 'error': error_msg})
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)

@login_required
def delete_restaurant(request, restaurant_id):
    """Delete a restaurant (branch or main) - NEW Restaurant model version"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Fetch Restaurant model (not User model!)
    restaurant = get_object_or_404(Restaurant, id=restaurant_id)
    
    if request.method == 'POST':
        restaurant_name = restaurant.name
        is_main = restaurant.is_main_restaurant
        
        try:
            # If main restaurant, delete all branches first
            if is_main:
                branches = list(restaurant.branches.all())
                branch_count = len(branches)
                
                for branch in branches:
                    # Only clear branch_owner (don't clear parent_restaurant - violates CHECK constraint)
                    if branch.branch_owner:
                        branch.branch_owner = None
                        branch.save(update_fields=['branch_owner'])
                    # Delete branch directly
                    branch.delete()
                
                success_msg = f'Main restaurant "{restaurant_name}" and {branch_count} branch(es) deleted successfully.'
            else:
                # Branch deletion - simpler
                success_msg = f'Branch "{restaurant_name}" deleted successfully.'
            
            # Clear branch_owner if exists (don't clear parent_restaurant for branches)
            if restaurant.branch_owner:
                restaurant.branch_owner = None
                restaurant.save(update_fields=['branch_owner'])
            
            # Delete the restaurant
            restaurant.delete()
            
            messages.success(request, success_msg)
            print(f"[SYSTEM ADMIN] Restaurant deleted: {restaurant_name} (is_main={is_main}) by {request.user.username}")
            
        except Exception as e:
            messages.error(request, f'Error deleting restaurant: {str(e)}')
            print(f"[ERROR] Restaurant deletion failed: {str(e)}")
        
        return redirect('system_admin:manage_restaurants')
    
    # For GET requests, just redirect back to manage restaurants
    return redirect('system_admin:manage_restaurants')


def block_restaurant(request, restaurant_id):
    """Block a restaurant's subscription access"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner'])
    restaurant_name = restaurant_owner.restaurant_name or f"Restaurant {restaurant_owner.username}"
    
    if request.method == 'POST':
        try:
            # Get or create subscription
            subscription, created = RestaurantSubscription.objects.get_or_create(
                restaurant_owner=restaurant_owner,
                defaults={
                    'subscription_status': 'blocked',
                    'subscription_start_date': timezone.now().date(),
                    'subscription_end_date': timezone.now().date() + timedelta(days=30)
                }
            )
            
            if not created:
                old_status = subscription.subscription_status
                subscription.subscription_status = 'blocked'
                subscription.save()
                
                # Log the blocking action
                SubscriptionLog.objects.create(
                    subscription=subscription,
                    action='blocked',
                    description=f"Restaurant blocked by administrator",
                    old_status=old_status,
                    new_status='blocked',
                    performed_by=request.user
                )
            
            messages.success(request, f'Restaurant "{restaurant_name}" has been blocked successfully.')
            
        except Exception as e:
            messages.error(request, f'Error blocking restaurant: {str(e)}')
    
    return redirect('system_admin:manage_restaurants')


def unblock_restaurant(request, restaurant_id):
    """Unblock a restaurant's subscription access"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner'])
    restaurant_name = restaurant_owner.restaurant_name or f"Restaurant {restaurant_owner.username}"
    
    if request.method == 'POST':
        try:
            if hasattr(restaurant_owner, 'subscription'):
                subscription = restaurant_owner.subscription
                old_status = subscription.subscription_status
                
                # Determine new status based on dates
                current_date = timezone.now().date()
                if current_date <= subscription.subscription_end_date:
                    new_status = 'active'
                else:
                    new_status = 'expired'
                
                subscription.subscription_status = new_status
                subscription.save()
                
                # Log the unblocking action
                SubscriptionLog.objects.create(
                    subscription=subscription,
                    action='unblocked',
                    description=f"Restaurant unblocked by administrator",
                    old_status=old_status,
                    new_status=new_status,
                    performed_by=request.user
                )
                
                messages.success(request, f'Restaurant "{restaurant_name}" has been unblocked successfully.')
            else:
                messages.warning(request, f'Restaurant "{restaurant_name}" has no subscription to unblock.')
                
        except Exception as e:
            messages.error(request, f'Error unblocking restaurant: {str(e)}')
    
    return redirect('system_admin:manage_restaurants')


def extend_subscription(request, restaurant_id):
    """Extend a restaurant's subscription"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner'])
    restaurant_name = restaurant_owner.restaurant_name or f"Restaurant {restaurant_owner.username}"
    
    if request.method == 'POST':
        try:
            days_to_extend = int(request.POST.get('days', 30))
            
            if hasattr(restaurant_owner, 'subscription'):
                subscription = restaurant_owner.subscription
                old_end_date = subscription.subscription_end_date
                
                # Extend from current end date or today, whichever is later
                current_date = timezone.now().date()
                extend_from = max(subscription.subscription_end_date, current_date)
                subscription.subscription_end_date = extend_from + timedelta(days=days_to_extend)
                
                # Update status if necessary
                if subscription.subscription_status in ['expired', 'blocked']:
                    old_status = subscription.subscription_status
                    subscription.subscription_status = 'active'
                else:
                    old_status = subscription.subscription_status
                
                subscription.save()
                
                # Log the extension
                SubscriptionLog.objects.create(
                    subscription=subscription,
                    action='extended',
                    description=f"Subscription extended by {days_to_extend} days (from {old_end_date} to {subscription.subscription_end_date})",
                    old_status=old_status,
                    new_status=subscription.subscription_status,
                    performed_by=request.user
                )
                
                messages.success(request, f'Subscription for "{restaurant_name}" extended by {days_to_extend} days until {subscription.subscription_end_date}.')
            else:
                # Create new subscription
                end_date = timezone.now().date() + timedelta(days=days_to_extend)
                subscription = RestaurantSubscription.objects.create(
                    restaurant_owner=restaurant_owner,
                    subscription_status='active',
                    subscription_start_date=timezone.now().date(),
                    subscription_end_date=end_date
                )
                
                SubscriptionLog.objects.create(
                    subscription=subscription,
                    action='created',
                    description=f"New subscription created with {days_to_extend} days",
                    old_status='none',
                    new_status='active',
                    performed_by=request.user
                )
                
                messages.success(request, f'New subscription created for "{restaurant_name}" for {days_to_extend} days until {end_date}.')
                
        except ValueError:
            messages.error(request, 'Invalid number of days specified.')
        except Exception as e:
            messages.error(request, f'Error extending subscription: {str(e)}')
    
    return redirect('system_admin:manage_restaurants')


# ===== Categories Management =====

@login_required
def manage_categories(request):
    """Manage all categories across all restaurants"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Get all restaurants for filtering - Updated to include all owner types and PRO plans
    restaurants = get_all_restaurants_for_admin()
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '').strip()
    restaurant_filter = request.GET.get('restaurant')
    if restaurant_filter:
        try:
            restaurant_filter = int(restaurant_filter)
        except (ValueError, TypeError):
            restaurant_filter = None
    
    # Get pagination parameter
    per_page = int(request.GET.get('per_page', 20))
    if per_page not in [5, 10, 15, 20, 25, 30, 50]:
        per_page = 20
    
    # Start with all main categories
    main_categories = MainCategory.objects.select_related('owner').prefetch_related('subcategories')
    
    # Get total count before any filtering
    total_categories = MainCategory.objects.count()
    
    # Apply search filter
    if search_query:
        main_categories = main_categories.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(owner__restaurant_name__icontains=search_query)
        )
    
    # Apply restaurant filter
    if restaurant_filter:
        main_categories = main_categories.filter(owner__id=restaurant_filter)
        selected_restaurant = get_restaurant_owner_by_id(restaurant_filter)
    else:
        selected_restaurant = None
    
    # Count filtered results before pagination
    filtered_count = main_categories.count()
    
    main_categories = main_categories.order_by('owner__restaurant_name', 'name')
    
    # Apply pagination
    paginator = Paginator(main_categories, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'main_categories': page_obj.object_list,
        'restaurants': restaurants,
        'selected_restaurant': selected_restaurant,
        'search_query': search_query,
        'per_page': per_page,
        'total_categories': total_categories,
        'filtered_count': filtered_count,
    }
    return render(request, 'system_admin/manage_categories.html', context)

@login_required
def create_category(request):
    """Create a new main category"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            restaurant_id = data.get('restaurant')
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            
            if not restaurant_id or not name:
                return JsonResponse({'success': False, 'message': 'Restaurant and name are required'})
            
            # Get the restaurant owner - Updated for new role system
            restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner', 'branch_owner'])
            
            # Check if category with this name already exists for this restaurant
            if MainCategory.objects.filter(owner=restaurant_owner, name=name).exists():
                return JsonResponse({'success': False, 'message': 'A category with this name already exists for this restaurant'})
            
            # Create the category
            category = MainCategory.objects.create(
                owner=restaurant_owner,
                name=name,
                description=description
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Category "{name}" created successfully for {restaurant_owner.restaurant_name}'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error creating category: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def create_subcategory(request):
    """Create a new sub category"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            main_category_id = data.get('main_category')
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            
            if not main_category_id or not name:
                return JsonResponse({'success': False, 'message': 'Main category and name are required'})
            
            # Get the main category
            main_category = get_object_or_404(MainCategory, id=main_category_id)
            
            # Check if subcategory with this name already exists for this main category
            if SubCategory.objects.filter(main_category=main_category, name=name).exists():
                return JsonResponse({'success': False, 'message': 'A subcategory with this name already exists for this main category'})
            
            # Create the subcategory
            subcategory = SubCategory.objects.create(
                main_category=main_category,
                name=name,
                description=description
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Sub category "{name}" created successfully under {main_category.name}'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error creating sub category: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def edit_category(request, category_id):
    """Edit an existing main category"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    category = get_object_or_404(MainCategory, id=category_id)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            
            if not name:
                return JsonResponse({'success': False, 'message': 'Name is required'})
            
            # Check if category with this name already exists for this restaurant (excluding current)
            if MainCategory.objects.filter(owner=category.owner, name=name).exclude(id=category_id).exists():
                return JsonResponse({'success': False, 'message': 'A category with this name already exists for this restaurant'})
            
            # Update the category
            category.name = name
            category.description = description
            category.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Category "{name}" updated successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error updating category: {str(e)}'})
    
    # Return category data for editing
    return JsonResponse({
        'success': True,
        'id': category.id,
        'name': category.name,
        'description': category.description,
        'restaurant_name': category.owner.restaurant_name,
        'restaurant_id': category.owner.id
    })

@login_required
def delete_category(request, category_id):
    """Delete a main category"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            category = get_object_or_404(MainCategory, id=category_id)
            category_name = category.name
            restaurant_name = category.owner.restaurant_name
            
            # Check if category has products
            products_count = Product.objects.filter(main_category=category).count()
            if products_count > 0:
                return JsonResponse({
                    'success': False, 
                    'message': f'Cannot delete category "{category_name}". It has {products_count} products associated with it.'
                })
            
            # Delete the category (this will also delete subcategories due to cascade)
            category.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Category "{category_name}" from {restaurant_name} deleted successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error deleting category: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def category_details(request, category_id):
    """Get category details including subcategories and products"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    category = get_object_or_404(MainCategory, id=category_id)
    subcategories = category.subcategories.all()
    products = Product.objects.filter(main_category=category)
    
    context = {
        'category': category,
        'subcategories': subcategories,
        'products': products,
    }
    return render(request, 'system_admin/category_details.html', context)

@login_required
def edit_subcategory(request, subcategory_id):
    """Edit an existing sub category"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    subcategory = get_object_or_404(SubCategory, id=subcategory_id)
    
    if request.method == 'GET':
        # Return subcategory data for editing
        return JsonResponse({
            'success': True,
            'id': subcategory.id,
            'name': subcategory.name,
            'description': subcategory.description,
            'main_category': subcategory.main_category.name,
            'restaurant_name': subcategory.main_category.owner.restaurant_name,
        })
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            
            if not name:
                return JsonResponse({'success': False, 'message': 'Name is required'})
            
            # Check if subcategory with this name already exists for this main category (excluding current)
            if SubCategory.objects.filter(main_category=subcategory.main_category, name=name).exclude(id=subcategory_id).exists():
                return JsonResponse({'success': False, 'message': 'A subcategory with this name already exists for this main category'})
            
            # Update the subcategory
            subcategory.name = name
            subcategory.description = description
            subcategory.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Sub category "{name}" updated successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error updating sub category: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def delete_subcategory(request, subcategory_id):
    """Delete a sub category"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            subcategory = get_object_or_404(SubCategory, id=subcategory_id)
            subcategory_name = subcategory.name
            main_category_name = subcategory.main_category.name
            
            # Check if subcategory has products
            products_count = Product.objects.filter(sub_category=subcategory).count()
            if products_count > 0:
                return JsonResponse({
                    'success': False, 
                    'message': f'Cannot delete sub category "{subcategory_name}". It has {products_count} products associated with it.'
                })
            
            # Delete the subcategory
            subcategory.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Sub category "{subcategory_name}" from {main_category_name} deleted successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error deleting sub category: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})


# ===== Products Management =====

@login_required
def manage_products(request):
    """Manage all products across all restaurants"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Get all restaurants for filtering - Updated to include all owner types and PRO plans
    restaurants = get_all_restaurants_for_admin()
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '').strip()
    restaurant_filter = request.GET.get('restaurant')
    category_filter = request.GET.get('category')
    availability_filter = request.GET.get('availability')
    
    # Get pagination parameter
    per_page = int(request.GET.get('per_page', 20))
    if per_page not in [5, 10, 15, 20, 25, 30, 50]:
        per_page = 20
    
    products = Product.objects.select_related('main_category', 'sub_category', 'main_category__owner')
    
    # Apply search filter
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(main_category__name__icontains=search_query) |
            Q(sub_category__name__icontains=search_query) |
            Q(main_category__owner__restaurant_name__icontains=search_query)
        )
    
    # Apply restaurant filter
    if restaurant_filter:
        products = products.filter(main_category__owner__id=restaurant_filter)
        selected_restaurant = get_restaurant_owner_by_id(restaurant_filter)
        # Get categories for this restaurant
        categories = MainCategory.objects.filter(owner=selected_restaurant).order_by('name')
    else:
        selected_restaurant = None
        categories = MainCategory.objects.select_related('owner').order_by('owner__restaurant_name', 'name')
    
    # Apply category filter
    if category_filter:
        products = products.filter(main_category__id=category_filter)
        selected_category = get_object_or_404(MainCategory, id=category_filter)
    else:
        selected_category = None
    
    # Apply availability filter
    if availability_filter == 'available':
        products = products.filter(is_available=True)
    elif availability_filter == 'unavailable':
        products = products.filter(is_available=False)
    
    # Get total count before pagination
    total_products = products.count()
    
    products = products.order_by('main_category__owner__restaurant_name', 'main_category__name', 'name')
    
    # Apply pagination
    paginator = Paginator(products, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Count filtered results
    filtered_count = products.count()
    
    context = {
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'restaurants': restaurants,
        'categories': categories,
        'selected_restaurant': selected_restaurant,
        'selected_category': selected_category,
        'search_query': search_query,
        'availability_filter': availability_filter,
        'per_page': per_page,
        'total_products': total_products,
        'filtered_count': filtered_count,
    }
    return render(request, 'system_admin/manage_products.html', context)

@login_required
def create_product(request):
    """Create a new product"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            main_category_id = data.get('main_category')
            sub_category_id = data.get('sub_category')
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            price = data.get('price')
            station = data.get('station', 'kitchen')
            availability = data.get('availability', True)
            
            if not main_category_id or not name or not price:
                return JsonResponse({'success': False, 'message': 'Main category, name, and price are required'})
            
            # Validate price
            try:
                price = float(price)
                if price < 0:
                    return JsonResponse({'success': False, 'message': 'Price must be positive'})
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'message': 'Invalid price format'})
            
            # Get the main category
            main_category = get_object_or_404(MainCategory, id=main_category_id)
            
            # Get subcategory if provided
            sub_category = None
            if sub_category_id:
                sub_category = get_object_or_404(SubCategory, id=sub_category_id, main_category=main_category)
            
            # Check if product with this name already exists for this main category
            if Product.objects.filter(main_category=main_category, name=name).exists():
                return JsonResponse({'success': False, 'message': 'A product with this name already exists in this category'})
            
            # Create the product
            product = Product.objects.create(
                main_category=main_category,
                sub_category=sub_category,
                name=name,
                description=description,
                price=price,
                station=station,
                is_available=availability  # Fixed: use is_available field
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Product "{name}" created successfully for {main_category.owner.restaurant_name}'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error creating product: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def edit_product(request, product_id):
    """Edit an existing product"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    product = get_object_or_404(Product, id=product_id)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            price = data.get('price')
            station = data.get('station', 'kitchen')
            availability = data.get('availability', True)
            
            if not name or not price:
                return JsonResponse({'success': False, 'message': 'Name and price are required'})
            
            # Validate price
            try:
                price = float(price)
                if price < 0:
                    return JsonResponse({'success': False, 'message': 'Price must be positive'})
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'message': 'Invalid price format'})
            
            # Check if product with this name already exists for this main category (excluding current)
            if Product.objects.filter(main_category=product.main_category, name=name).exclude(id=product_id).exists():
                return JsonResponse({'success': False, 'message': 'A product with this name already exists in this category'})
            
            # Update the product
            product.name = name
            product.description = description
            product.price = price
            product.station = station
            product.is_available = availability  # Fixed: use is_available field
            product.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Product "{name}" updated successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error updating product: {str(e)}'})
    
    # Return product data for editing
    try:
        return JsonResponse({
            'id': product.id,
            'name': product.name,
            'description': product.description,
            'price': str(product.price),
            'station': product.station,
            'availability': product.is_available,  # Fixed: use is_available field
            'main_category_id': product.main_category.id,
            'main_category_name': product.main_category.name,
            'sub_category_id': product.sub_category.id if product.sub_category else None,
            'sub_category_name': product.sub_category.name if product.sub_category else None,
            'restaurant_name': product.main_category.owner.restaurant_name,
            'restaurant_id': product.main_category.owner.id,
            'image_url': product.get_image().url if product.get_image() else None
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error retrieving product data: {str(e)}'})

@login_required
def delete_product(request, product_id):
    """Delete a product"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            product = get_object_or_404(Product, id=product_id)
            product_name = product.name
            restaurant_name = product.main_category.owner.restaurant_name
            
            # Check if product has orders
            from orders.models import OrderItem
            orders_count = OrderItem.objects.filter(product=product).count()
            if orders_count > 0:
                return JsonResponse({
                    'success': False, 
                    'message': f'Cannot delete product "{product_name}". It has {orders_count} order items associated with it.'
                })
            
            # Delete the product
            product.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Product "{product_name}" from {restaurant_name} deleted successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error deleting product: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def product_details(request, product_id):
    """Get product details"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    product = get_object_or_404(Product, id=product_id)
    
    # Get order statistics
    from orders.models import OrderItem
    order_items = OrderItem.objects.filter(product=product)
    total_orders = order_items.count()
    total_quantity_sold = sum(item.quantity for item in order_items)
    total_revenue = sum(item.get_subtotal() for item in order_items)
    
    context = {
        'product': product,
        'total_orders': total_orders,
        'total_quantity_sold': total_quantity_sold,
        'total_revenue': total_revenue,
        'recent_orders': order_items.select_related('order', 'order__table_info').order_by('-created_at')[:10]
    }
    return render(request, 'system_admin/product_details.html', context)

@login_required
def get_subcategories(request, category_id):
    """Get subcategories for a main category (AJAX endpoint)"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    try:
        category = get_object_or_404(MainCategory, id=category_id)
        subcategories = category.subcategories.all().values('id', 'name')
        return JsonResponse({'success': True, 'subcategories': list(subcategories)})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required
def get_categories(request, restaurant_id):
    """Get main categories for a restaurant (AJAX endpoint)"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    try:
        restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner', 'branch_owner'])
        categories = MainCategory.objects.filter(owner=restaurant_owner).values('id', 'name')
        return JsonResponse({'success': True, 'categories': list(categories)})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


# ===== Tables Management =====

@login_required
def manage_tables(request):
    """Manage all tables across all restaurants"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Get all restaurants for filtering - Updated to include all owner types and PRO plans
    restaurants = get_all_restaurants_for_admin()
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '').strip()
    restaurant_filter = request.GET.get('restaurant')
    if restaurant_filter:
        try:
            restaurant_filter = int(restaurant_filter)
        except (ValueError, TypeError):
            restaurant_filter = None
    availability_filter = request.GET.get('availability')
    per_page = int(request.GET.get('per_page', 10))  # Default to 10, allow customization
    page = request.GET.get('page', 1)
    
    # Get total count before any filtering
    total_tables = TableInfo.objects.count()
    
    # Start with all tables
    tables = TableInfo.objects.select_related('owner').order_by('owner__restaurant_name', 'tbl_no')
    
    # Apply search filter
    if search_query:
        tables = tables.filter(
            Q(tbl_no__icontains=search_query) |
            Q(owner__username__icontains=search_query) |
            Q(owner__restaurant_name__icontains=search_query) |
            Q(capacity__icontains=search_query)
        )
    
    # Filter by restaurant if requested
    if restaurant_filter:
        tables = tables.filter(owner__id=restaurant_filter)
        selected_restaurant = get_restaurant_owner_by_id(restaurant_filter)
    else:
        selected_restaurant = None
        
    # Filter by availability
    if availability_filter:
        if availability_filter == 'available':
            tables = tables.filter(is_available=True)
        elif availability_filter == 'occupied':
            tables = tables.filter(is_available=False)
    
    # Count filtered results before pagination
    filtered_count = tables.count()
    
    # Pagination with customizable per_page
    from django.core.paginator import Paginator
    # Ensure per_page is within reasonable limits
    per_page = max(5, min(per_page, 50))  # Between 5 and 50
    paginator = Paginator(tables, per_page)
    try:
        tables_page = paginator.page(page)
    except:
        tables_page = paginator.page(1)
    
    # Filter options
    availability_options = [('available', 'Available'), ('occupied', 'Occupied')]
    per_page_options = [5, 10, 15, 20, 25, 50]

    context = {
        'tables': tables_page,
        'total_tables': total_tables,
        'filtered_count': filtered_count,
        'restaurants': restaurants,
        'selected_restaurant': selected_restaurant,
        'search_query': search_query,
        'availability_filter': availability_filter,
        'availability_options': availability_options,
        'per_page': per_page,
        'per_page_options': per_page_options,
        'paginator': paginator,
        'page_obj': tables_page,
    }
    return render(request, 'system_admin/manage_tables.html', context)

@login_required
def create_table(request):
    """Create a new table"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            restaurant_id = data.get('restaurant')
            tbl_no = data.get('tbl_no', '').strip()
            capacity = data.get('capacity')
            is_available = data.get('is_available', True)
            
            if not restaurant_id or not tbl_no or not capacity:
                return JsonResponse({'success': False, 'message': 'Restaurant, table number, and capacity are required'})
            
            # Validate capacity
            try:
                capacity = int(capacity)
                if capacity <= 0:
                    return JsonResponse({'success': False, 'message': 'Capacity must be a positive integer'})
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'message': 'Invalid capacity format'})
            
            # Get the restaurant owner - Updated for new role system
            restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner', 'branch_owner'])
            
            # Check if table with this number already exists for this restaurant
            if TableInfo.objects.filter(owner=restaurant_owner, tbl_no=tbl_no).exists():
                return JsonResponse({'success': False, 'message': 'A table with this number already exists for this restaurant'})
            
            # Create the table
            table = TableInfo.objects.create(
                owner=restaurant_owner,
                tbl_no=tbl_no,
                capacity=capacity,
                is_available=is_available
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Table {tbl_no} created successfully for {restaurant_owner.restaurant_name}'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error creating table: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def edit_table(request, table_id):
    """Edit an existing table"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    table = get_object_or_404(TableInfo, id=table_id)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            tbl_no = data.get('tbl_no', '').strip()
            capacity = data.get('capacity')
            is_available = data.get('is_available', True)
            
            if not tbl_no or not capacity:
                return JsonResponse({'success': False, 'message': 'Table number and capacity are required'})
            
            # Validate capacity
            try:
                capacity = int(capacity)
                if capacity <= 0:
                    return JsonResponse({'success': False, 'message': 'Capacity must be a positive integer'})
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'message': 'Invalid capacity format'})
            
            # Check if table with this number already exists for this restaurant (excluding current)
            if TableInfo.objects.filter(owner=table.owner, tbl_no=tbl_no).exclude(id=table_id).exists():
                return JsonResponse({'success': False, 'message': 'A table with this number already exists for this restaurant'})
            
            # Update the table
            table.tbl_no = tbl_no
            table.capacity = capacity
            table.is_available = is_available
            table.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Table {tbl_no} updated successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error updating table: {str(e)}'})
    
    # Return table data for editing
    return JsonResponse({
        'id': table.id,
        'tbl_no': table.tbl_no,
        'capacity': table.capacity,
        'is_available': table.is_available,
        'restaurant_name': table.owner.restaurant_name,
        'restaurant_id': table.owner.id
    })

@login_required
def delete_table(request, table_id):
    """Delete a table"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            table = get_object_or_404(TableInfo, id=table_id)
            table_no = table.tbl_no
            restaurant_name = table.owner.restaurant_name
            
            # Check if table has orders
            orders_count = Order.objects.filter(table_info=table).count()
            if orders_count > 0:
                return JsonResponse({
                    'success': False, 
                    'message': f'Cannot delete table {table_no}. It has {orders_count} orders associated with it.'
                })
            
            # Delete the table
            table.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Table {table_no} from {restaurant_name} deleted successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error deleting table: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def table_details(request, table_id):
    """Get table details including recent orders"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    table = get_object_or_404(TableInfo, id=table_id)
    
    # Get order statistics
    orders = Order.objects.filter(table_info=table)
    total_orders = orders.count()
    
    # Recent orders
    recent_orders = orders.select_related('ordered_by').order_by('-created_at')[:10]
    
    # Revenue statistics
    total_revenue = sum(order.total_amount for order in orders)
    
    context = {
        'table': table,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'recent_orders': recent_orders,
    }
    return render(request, 'system_admin/table_details.html', context)


# ===== Orders Management =====

@login_required
def manage_orders(request):
    """Manage all orders across all restaurants"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Get all restaurants for filtering - Updated to include all owner types and PRO plans
    restaurants = get_all_restaurants_for_admin()
    
    # Get search and filter parameters
    search_query = request.GET.get('search', '').strip()
    restaurant_filter = request.GET.get('restaurant')
    if restaurant_filter:
        try:
            restaurant_filter = int(restaurant_filter)
        except (ValueError, TypeError):
            restaurant_filter = None
    status_filter = request.GET.get('status')
    payment_status_filter = request.GET.get('payment_status')
    per_page = int(request.GET.get('per_page', 10))  # Default to 10, allow customization
    page = request.GET.get('page', 1)
    
    # Get total count before any filtering
    total_orders = Order.objects.count()
    
    orders = Order.objects.select_related('table_info', 'table_info__owner', 'ordered_by', 'confirmed_by')
    
    # Apply search filter
    if search_query:
        orders = orders.filter(
            Q(id__icontains=search_query) |
            Q(table_info__tbl_no__icontains=search_query) |
            Q(table_info__owner__username__icontains=search_query) |
            Q(table_info__owner__restaurant_name__icontains=search_query) |
            Q(ordered_by__username__icontains=search_query) |
            Q(status__icontains=search_query) |
            Q(payment_status__icontains=search_query)
        )
    
    # Apply filters
    if restaurant_filter:
        orders = orders.filter(table_info__owner__id=restaurant_filter)
        selected_restaurant = get_restaurant_owner_by_id(restaurant_filter)
    else:
        selected_restaurant = None

    if status_filter:
        orders = orders.filter(status=status_filter)

    if payment_status_filter:
        orders = orders.filter(payment_status=payment_status_filter)

    orders = orders.order_by('-created_at')
    
    # Count filtered results before pagination
    filtered_count = orders.count()
    
    # Pagination with customizable per_page
    from django.core.paginator import Paginator
    # Ensure per_page is within reasonable limits
    per_page = max(5, min(per_page, 50))  # Between 5 and 50
    paginator = Paginator(orders, per_page)
    try:
        orders_page = paginator.page(page)
    except:
        orders_page = paginator.page(1)

    # Get status choices for filter
    status_choices = Order.STATUS_CHOICES
    payment_status_choices = Order.PAYMENT_STATUS_CHOICES
    per_page_options = [5, 10, 15, 20, 25, 50]

    context = {
        'orders': orders_page,
        'total_orders': total_orders,
        'filtered_count': filtered_count,
        'restaurants': restaurants,
        'selected_restaurant': selected_restaurant,
        'status_choices': status_choices,
        'payment_status_choices': payment_status_choices,
        'selected_status': status_filter,
        'selected_payment_status': payment_status_filter,
        'search_query': search_query,
        'per_page': per_page,
        'per_page_options': per_page_options,
        'paginator': paginator,
        'page_obj': orders_page,
    }
    return render(request, 'system_admin/manage_orders.html', context)

@login_required
def order_details(request, order_id):
    """Get detailed order information"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    order = get_object_or_404(Order, id=order_id)
    order_items = order.order_items.select_related('product', 'product__main_category').all()
    
    context = {
        'order': order,
        'order_items': order_items,
    }
    return render(request, 'system_admin/order_details.html', context)

@login_required
def update_order_status(request, order_id):
    """Update order status"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            new_status = data.get('status')
            reason = data.get('reason', '').strip()
            
            if not new_status:
                return JsonResponse({'success': False, 'message': 'Status is required'})
            
            # Validate status
            valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]
            if new_status not in valid_statuses:
                return JsonResponse({'success': False, 'message': 'Invalid status'})
            
            order = get_object_or_404(Order, id=order_id)
            old_status = order.status
            
            # Update status
            order.status = new_status
            
            # If cancelling, store reason
            if new_status == 'cancelled' and reason:
                order.reason_if_cancelled = reason
            
            # If confirming, set confirmed_by to current admin user
            if new_status == 'confirmed':
                order.confirmed_by = request.user
            
            order.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Order status updated from "{old_status}" to "{new_status}"'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error updating order status: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def update_payment_status(request, order_id):
    """Update payment status"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            payment_status = data.get('payment_status')
            payment_amount = data.get('payment_amount')
            
            if not payment_status:
                return JsonResponse({'success': False, 'message': 'Payment status is required'})
            
            # Validate payment status
            valid_statuses = [choice[0] for choice in Order.PAYMENT_STATUS_CHOICES]
            if payment_status not in valid_statuses:
                return JsonResponse({'success': False, 'message': 'Invalid payment status'})
            
            order = get_object_or_404(Order, id=order_id)
            
            # Validate payment amount if provided
            if payment_amount is not None:
                try:
                    payment_amount = float(payment_amount)
                    if payment_amount < 0:
                        return JsonResponse({'success': False, 'message': 'Payment amount must be positive'})
                except (ValueError, TypeError):
                    return JsonResponse({'success': False, 'message': 'Invalid payment amount format'})
                
                order.payment_amount = payment_amount
            
            order.payment_status = payment_status
            order.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Payment status updated to "{payment_status}"'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error updating payment status: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def cancel_order(request, order_id):
    """Cancel an order with reason"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            reason = data.get('reason', '').strip()
            
            if not reason:
                return JsonResponse({'success': False, 'message': 'Cancellation reason is required'})
            
            order = get_object_or_404(Order, id=order_id)
            
            # Check if order can be cancelled
            if order.status in ['served', 'cancelled']:
                return JsonResponse({'success': False, 'message': 'Order cannot be cancelled in current status'})
            
            order.status = 'cancelled'
            order.reason_if_cancelled = reason
            order.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Order {order.order_number} cancelled successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error cancelling order: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})


# ===== Staff Management =====

@login_required
def manage_staff(request):
    """Manage all staff across all restaurants"""
    if not request.user.is_administrator():
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('accounts:login')
    
    # Get all restaurants for filtering - Updated for new role system
    restaurants = User.objects.filter(
        role__name__in=['owner', 'main_owner', 'branch_owner'], 
        restaurant_name__isnull=False
    ).exclude(restaurant_name='').order_by('restaurant_name')
    
    # Get all roles except administrator
    roles = Role.objects.exclude(name='administrator').order_by('name')
    
    # Filter parameters
    restaurant_filter = request.GET.get('restaurant')
    role_filter = request.GET.get('role')
    
    # Base query - exclude administrators
    staff = User.objects.exclude(role__name='administrator').select_related('role', 'owner')
    
    # Apply filters
    if restaurant_filter:
        selected_restaurant = get_object_or_404(User, id=restaurant_filter, role__name__in=['owner', 'main_owner', 'branch_owner'])
        # Get all staff for this restaurant (including the owner)
        staff = staff.filter(Q(id=restaurant_filter) | Q(owner_id=restaurant_filter))
    else:
        selected_restaurant = None
    
    if role_filter:
        staff = staff.filter(role__name=role_filter)
        selected_role = get_object_or_404(Role, name=role_filter)
    else:
        selected_role = None
    
    staff = staff.order_by('role__name', 'username')
    
    context = {
        'staff': staff,
        'restaurants': restaurants,
        'roles': roles,
        'selected_restaurant': selected_restaurant,
        'selected_role': selected_role,
    }
    return render(request, 'system_admin/manage_staff.html', context)

@login_required
def create_staff(request):
    """Create a new staff member"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = data.get('username', '').strip()
            email = data.get('email', '').strip()
            first_name = data.get('first_name', '').strip()
            last_name = data.get('last_name', '').strip()
            phone_number = data.get('phone_number', '').strip()
            password = data.get('password', '').strip()
            role_name = data.get('role')
            restaurant_id = data.get('restaurant')
            
            if not username or not email or not password or not role_name:
                return JsonResponse({'success': False, 'message': 'Username, email, password, and role are required'})
            
            # Check if username already exists
            if User.objects.filter(username=username).exists():
                return JsonResponse({'success': False, 'message': 'Username already exists'})
            
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                return JsonResponse({'success': False, 'message': 'Email already exists'})
            
            # Get role
            role = get_object_or_404(Role, name=role_name)
            
            # Get restaurant owner if not creating an owner
            restaurant_owner = None
            if role_name == 'owner':
                if not data.get('restaurant_name', '').strip():
                    return JsonResponse({'success': False, 'message': 'Restaurant name is required for owners'})
                restaurant_name = data.get('restaurant_name', '').strip()
            else:
                if not restaurant_id:
                    return JsonResponse({'success': False, 'message': 'Restaurant is required for staff members'})
                restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner', 'branch_owner'])
            
            # Create the user
            user = User.objects.create(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                password=make_password(password),
                role=role,
                owner=restaurant_owner,
                restaurant_name=restaurant_name if role_name == 'owner' else None
            )
            
            message = f'Staff member "{username}" created successfully'
            if role_name == 'owner':
                message += f' as restaurant owner for "{restaurant_name}"'
            else:
                message += f' for {restaurant_owner.restaurant_name}'
            
            return JsonResponse({
                'success': True,
                'message': message
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error creating staff member: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def edit_staff(request, staff_id):
    """Edit an existing staff member"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    staff_member = get_object_or_404(User, id=staff_id)
    
    # Don't allow editing administrators
    if staff_member.role.name == 'administrator':
        return JsonResponse({'success': False, 'message': 'Cannot edit administrator accounts'})
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = data.get('username', '').strip()
            email = data.get('email', '').strip()
            first_name = data.get('first_name', '').strip()
            last_name = data.get('last_name', '').strip()
            phone_number = data.get('phone_number', '').strip()
            password = data.get('password', '').strip()
            is_active = data.get('is_active', True)
            
            if not username or not email:
                return JsonResponse({'success': False, 'message': 'Username and email are required'})
            
            # Check if username already exists (excluding current user)
            if User.objects.filter(username=username).exclude(id=staff_id).exists():
                return JsonResponse({'success': False, 'message': 'Username already exists'})
            
            # Check if email already exists (excluding current user)
            if User.objects.filter(email=email).exclude(id=staff_id).exists():
                return JsonResponse({'success': False, 'message': 'Email already exists'})
            
            # Update the user
            staff_member.username = username
            staff_member.email = email
            staff_member.first_name = first_name
            staff_member.last_name = last_name
            staff_member.phone_number = phone_number
            staff_member.is_active = is_active
            
            # Update password if provided
            if password:
                staff_member.password = make_password(password)
            
            # Update restaurant name if owner
            if staff_member.role.name == 'owner':
                restaurant_name = data.get('restaurant_name', '').strip()
                if restaurant_name:
                    staff_member.restaurant_name = restaurant_name
            
            staff_member.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Staff member "{username}" updated successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error updating staff member: {str(e)}'})
    
    # Return staff data for editing
    return JsonResponse({
        'id': staff_member.id,
        'username': staff_member.username,
        'email': staff_member.email,
        'first_name': staff_member.first_name,
        'last_name': staff_member.last_name,
        'phone_number': staff_member.phone_number,
        'is_active': staff_member.is_active,
        'role_name': staff_member.role.name,
        'restaurant_name': staff_member.restaurant_name if staff_member.role.name == 'owner' else (staff_member.owner.restaurant_name if staff_member.owner else None),
        'restaurant_id': staff_member.owner.id if staff_member.owner else None
    })

@login_required
def delete_staff(request, staff_id):
    """Delete a staff member"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method == 'POST':
        try:
            staff_member = get_object_or_404(User, id=staff_id)
            
            # Don't allow deleting administrators
            if staff_member.role.name == 'administrator':
                return JsonResponse({'success': False, 'message': 'Cannot delete administrator accounts'})
            
            username = staff_member.username
            role_name = staff_member.role.name
            
            # Special handling for owners - check if they have staff
            if role_name == 'owner':
                staff_count = User.objects.filter(owner=staff_member).count()
                if staff_count > 0:
                    return JsonResponse({
                        'success': False, 
                        'message': f'Cannot delete owner "{username}". They have {staff_count} staff members. Please reassign or delete staff first.'
                    })
                
                # Check if they have restaurant data
                categories_count = MainCategory.objects.filter(owner=staff_member).count()
                tables_count = TableInfo.objects.filter(owner=staff_member).count()
                if categories_count > 0 or tables_count > 0:
                    return JsonResponse({
                        'success': False, 
                        'message': f'Cannot delete owner "{username}". Restaurant has associated data (categories, tables, etc.). Delete restaurant data first.'
                    })
            
            # Delete the staff member
            staff_member.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Staff member "{username}" ({role_name}) deleted successfully'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error deleting staff member: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
def staff_details(request, staff_id):
    """Get staff member details"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    staff_member = get_object_or_404(User, id=staff_id)
    
    # Get statistics based on role
    stats = {}
    if staff_member.role.name == 'owner':
        stats = {
            'total_staff': User.objects.filter(owner=staff_member).count(),
            'total_categories': MainCategory.objects.filter(owner=staff_member).count(),
            'total_products': Product.objects.filter(main_category__owner=staff_member).count(),
            'total_tables': TableInfo.objects.filter(owner=staff_member).count(),
            'total_orders': Order.objects.filter(table_info__owner=staff_member).count(),
        }
    elif staff_member.role.name == 'customer':
        stats = {
            'total_orders': Order.objects.filter(ordered_by=staff_member).count(),
            'total_spent': sum(order.total_amount for order in Order.objects.filter(ordered_by=staff_member)),
        }
    elif staff_member.role.name in ['customer_care', 'kitchen']:
        stats = {
            'orders_handled': Order.objects.filter(confirmed_by=staff_member).count() if staff_member.role.name == 'customer_care' else 0,
        }
    
    context = {
        'staff_member': staff_member,
        'stats': stats,
    }
    return render(request, 'system_admin/staff_details.html', context)

# User Management Functions
@login_required
def create_user(request):
    """Create a new user"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            email = request.POST.get('email')
            password = request.POST.get('password')
            first_name = request.POST.get('first_name', '')
            last_name = request.POST.get('last_name', '')
            role_id = request.POST.get('role')
            restaurant_id = request.POST.get('restaurant', None)
            is_active = request.POST.get('is_active', 'true') == 'true'
            
            # Validation
            if User.objects.filter(username=username).exists():
                return JsonResponse({'success': False, 'error': 'Username already exists'})
            
            if User.objects.filter(email=email).exists():
                return JsonResponse({'success': False, 'error': 'Email already exists'})
            
            # Create user
            role = get_object_or_404(Role, id=role_id)
            user = User.objects.create(
                username=username,
                email=email,
                password=make_password(password),
                first_name=first_name,
                last_name=last_name,
                role=role,
                is_active=is_active
            )
            
            # Set restaurant if provided
            if restaurant_id:
                restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner', 'branch_owner'])
                user.owner = restaurant_owner
                user.save()
            
            return JsonResponse({'success': True, 'message': 'User created successfully'})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def user_details(request, user_id):
    """Get user details"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        user = get_object_or_404(User, id=user_id)
        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role_id': user.role.id,
            'role_name': user.role.name,
            'restaurant_id': user.owner.id if user.owner else None,
            'restaurant_name': user.owner.restaurant_name if user.owner else None,
            'is_active': user.is_active,
            'date_joined': user.date_joined.isoformat(),
            'last_login': user.last_login.isoformat() if user.last_login else None,
        }
        return JsonResponse({'success': True, 'user': user_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def edit_user(request, user_id):
    """Edit existing user"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    if request.method == 'POST':
        try:
            user = get_object_or_404(User, id=user_id)
            
            username = request.POST.get('username')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name', '')
            last_name = request.POST.get('last_name', '')
            role_id = request.POST.get('role')
            restaurant_id = request.POST.get('restaurant', None)
            is_active = request.POST.get('is_active', 'true') == 'true'
            new_password = request.POST.get('new_password', '')
            
            # Validation
            if User.objects.filter(username=username).exclude(id=user_id).exists():
                return JsonResponse({'success': False, 'error': 'Username already exists'})
            
            if User.objects.filter(email=email).exclude(id=user_id).exists():
                return JsonResponse({'success': False, 'error': 'Email already exists'})
            
            # Update user
            user.username = username
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.role = get_object_or_404(Role, id=role_id)
            user.is_active = is_active
            
            # Update password if provided
            if new_password:
                user.password = make_password(new_password)
            
            # Set restaurant if provided
            if restaurant_id:
                restaurant_owner = get_object_or_404(User, id=restaurant_id, role__name__in=['owner', 'main_owner', 'branch_owner'])
                user.owner = restaurant_owner
            else:
                user.owner = None
            
            user.save()
            
            return JsonResponse({'success': True, 'message': 'User updated successfully'})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def delete_user(request, user_id):
    """Delete user"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    if request.method == 'POST':
        try:
            user = get_object_or_404(User, id=user_id)
            
            # Prevent deleting self
            if user.id == request.user.id:
                return JsonResponse({'success': False, 'error': 'Cannot delete yourself'})
            
            # Prevent deleting other administrators
            if user.is_administrator():
                return JsonResponse({'success': False, 'error': 'Cannot delete administrator users'})
            
            user.delete()
            return JsonResponse({'success': True, 'message': 'User deleted successfully'})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def get_order_status(request, order_id):
    """Get current order status for editing"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    try:
        order = get_object_or_404(Order, id=order_id)
        return JsonResponse({
            'success': True,
            'status': order.status,
            'order_number': order.order_number
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required  
def get_payment_status(request, order_id):
    """Get current payment status for editing"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    try:
        order = get_object_or_404(Order, id=order_id)
        return JsonResponse({
            'success': True,
            'payment_status': order.payment_status,
            'order_number': order.order_number,
            'payment_amount': float(order.payment_amount or 0)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
def toggle_restaurant_subscription_plan(request):
    """Admin function to change restaurant subscription plan"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'error': 'Access denied. Administrator privileges required.'})
    
    if request.method == 'POST':
        try:
            restaurant_id = request.POST.get('restaurant_id')
            new_plan = request.POST.get('new_plan')
            
            if not restaurant_id or new_plan not in ['SINGLE', 'PRO']:
                return JsonResponse({'success': False, 'error': 'Invalid parameters.'})
            
            restaurant = get_object_or_404(Restaurant, id=restaurant_id)
            
            # Check if downgrade is allowed
            if new_plan == 'SINGLE' and restaurant.subscription_plan == 'PRO':
                if restaurant.branches.exists():
                    # Check if force delete is confirmed
                    force_delete = request.POST.get('force_delete_branches', 'false').lower() == 'true'
                    
                    if not force_delete:
                        # Return branch information for confirmation dialog
                        branches_info = []
                        for branch in restaurant.branches.all():
                            branches_info.append({
                                'id': branch.id,
                                'name': branch.name,
                                'is_active': branch.is_active,
                                'created_date': branch.created_at.strftime('%Y-%m-%d') if hasattr(branch, 'created_at') else 'Unknown'
                            })
                        
                        return JsonResponse({
                            'success': False,
                            'requires_confirmation': True,
                            'branches_count': restaurant.branches.count(),
                            'branches': branches_info,
                            'message': f'Downgrading {restaurant.name} to SINGLE plan will permanently delete {restaurant.branches.count()} branch(es). This action cannot be undone.',
                            'restaurant_name': restaurant.name
                        })
                    else:
                        # Force delete confirmed - delete branches and downgrade
                        branches_count = restaurant.branches.count()
                        deleted_branches = []
                        for branch in restaurant.branches.all():
                            deleted_branches.append(branch.name)
                        
                        restaurant.branches.all().delete()
                        
                        # Continue with downgrade after branches are deleted
                        old_plan = restaurant.get_subscription_display()
                        restaurant.subscription_plan = new_plan
                        restaurant.save(update_fields=['subscription_plan', 'updated_at'])
                        
                        return JsonResponse({
                            'success': True,
                            'message': f'Successfully downgraded {restaurant.name} to SINGLE plan. Deleted branches: {", ".join(deleted_branches)}.',
                            'new_plan': restaurant.get_subscription_display(),
                            'deleted_branches': deleted_branches
                        })
            
            old_plan = restaurant.get_subscription_display()
            restaurant.subscription_plan = new_plan
            restaurant.save(update_fields=['subscription_plan', 'updated_at'])
            
            new_plan_display = restaurant.get_subscription_display()
            
            return JsonResponse({
                'success': True,
                'message': f'Successfully changed {restaurant.name} from {old_plan} to {new_plan_display}.',
                'new_plan': new_plan_display
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Error changing subscription plan: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required  
def toggle_restaurant_status(request):
    """Admin function to activate/deactivate restaurants"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'error': 'Access denied. Administrator privileges required.'})
    
    if request.method == 'POST':
        try:
            restaurant_id = request.POST.get('restaurant_id')
            restaurant = get_object_or_404(Restaurant, id=restaurant_id)
            
            # Toggle status
            restaurant.is_active = not restaurant.is_active
            restaurant.save(update_fields=['is_active', 'updated_at'])
            
            status_text = 'activated' if restaurant.is_active else 'deactivated'
            
            return JsonResponse({
                'success': True,
                'message': f'Successfully {status_text} {restaurant.name}.',
                'new_status': restaurant.is_active
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Error changing restaurant status: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required
def delete_restaurant_admin(request):
    """Admin function to delete restaurants"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'error': 'Access denied. Administrator privileges required.'})
    
    if request.method == 'POST':
        try:
            restaurant_id = request.POST.get('restaurant_id')
            restaurant = get_object_or_404(Restaurant, id=restaurant_id)
            
            restaurant_name = restaurant.name
            main_owner = restaurant.main_owner
            
            # Delete all branches first if this is a main restaurant
            if restaurant.is_main_restaurant:
                branches = list(restaurant.branches.all())
                for branch in branches:
                    # Only clear branch_owner (don't clear parent_restaurant - violates CHECK constraint)
                    if branch.branch_owner:
                        branch.branch_owner = None
                        branch.save(update_fields=['branch_owner'])
                    # Delete branch directly
                    branch.delete()
            
            # For branch deletion - don't clear parent_restaurant (violates CHECK constraint)
            # Just clear branch_owner if exists
            if restaurant.branch_owner:
                restaurant.branch_owner = None
                restaurant.save(update_fields=['branch_owner'])
            
            # Delete the restaurant directly (parent_restaurant stays until deletion)
            restaurant.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Successfully deleted restaurant: {restaurant_name}.'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Error deleting restaurant: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method.'})


@login_required
def restaurant_details_admin(request, restaurant_id):
    """Admin function to get detailed restaurant information"""
    if not request.user.is_administrator():
        return JsonResponse({'success': False, 'error': 'Access denied. Administrator privileges required.'})
    
    try:
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        
        # Get restaurant statistics
        branches_count = restaurant.branches.count()
        active_branches = restaurant.branches.filter(is_active=True).count()
        
        data = {
            'success': True,
            'restaurant': {
                'id': restaurant.id,
                'name': restaurant.name,
                'description': restaurant.description,
                'subscription_plan': restaurant.get_subscription_display(),
                'is_active': restaurant.is_active,
                'owner': {
                    'name': restaurant.main_owner.get_full_name() or restaurant.main_owner.username,
                    'email': restaurant.main_owner.email
                },
                'branches_count': branches_count,
                'active_branches': active_branches,
                'created_at': restaurant.created_at.strftime('%Y-%m-%d %H:%M'),
                'updated_at': restaurant.updated_at.strftime('%Y-%m-%d %H:%M')
            }
        }
        
        # Add branch information if it's a pro restaurant
        if restaurant.subscription_plan == 'PRO' and branches_count > 0:
            branches = restaurant.branches.all()
            data['restaurant']['branches'] = [
                {
                    'id': branch.id,
                    'name': branch.name,
                    'is_active': branch.is_active,
                    'created_at': branch.created_at.strftime('%Y-%m-%d')
                } for branch in branches
            ]
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Error getting restaurant details: {str(e)}'})