from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required


def _safe_csv(value):
    """Prevent CSV formula injection: prefix dangerous leading characters."""
    s = str(value) if value is not None else ''
    if s and s[0] in ('=', '+', '-', '@', '|', '%'):
        return '\t' + s
    return s
from django.contrib import messages
from django.db import models, transaction
from django.db.models import Count, Q, Prefetch, Sum, Avg, F
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from .models import MainCategory, SubCategory, Product, TableInfo, HappyHourPromotion, Restaurant, Event
from .forms import ProductForm, MainCategoryForm, SubCategoryForm, TableForm, StaffForm, HappyHourPromotionForm, EventForm
from orders.models import Order
from accounts.models import User, Role

def home(request):
    # Owners, managers and admins belong in the admin panel, not the customer-facing home page
    if request.user.is_authenticated and (
        request.user.is_owner() or
        request.user.is_manager() or
        request.user.is_admin()
    ):
        return redirect('admin_panel:admin_dashboard')
    return render(request, 'restaurant/home.html')


def browse_restaurants(request):
    """List restaurants that allow remote ordering (delivery & pickup)."""
    from restaurant.models_restaurant import Restaurant as RestaurantModel

    # If user explicitly wants to switch, clear current remote session
    if request.GET.get('switch') == '1':
        for key in ('selected_restaurant_id', 'selected_restaurant_name',
                    'order_type', 'delivery_address', 'delivery_phone',
                    'selected_table', 'selected_table_id', 'cart'):
            request.session.pop(key, None)
        request.session.modified = True
        return redirect('restaurant:browse_restaurants')

    # Detect active remote-order session so we can show a "continue or switch" prompt
    active_restaurant_name = None
    active_order_type = request.session.get('order_type', 'dine-in')
    if active_order_type in ('delivery', 'pickup') and request.session.get('selected_restaurant_id'):
        active_restaurant_name = request.session.get('selected_restaurant_name', 'your restaurant')

    search = request.GET.get('q', '').strip()
    qs = RestaurantModel.objects.filter(allow_remote_orders=True, is_active=True).select_related('main_owner')
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(address__icontains=search)
        )
    return render(request, 'restaurant/browse_restaurants.html', {
        'restaurants': qs,
        'search': search,
        'active_restaurant_name': active_restaurant_name,
        'active_order_type': active_order_type,
    })


@login_required
def select_order_type(request, restaurant_id):
    """Choose Delivery or Pickup for a remote-order restaurant."""
    from restaurant.models_restaurant import Restaurant as RestaurantModel
    restaurant_obj = get_object_or_404(
        RestaurantModel,
        id=restaurant_id,
        allow_remote_orders=True,
        is_active=True,
    )
    owner = restaurant_obj.main_owner

    if request.method == 'POST':
        chosen_type = request.POST.get('order_type', 'pickup')
        request.session['selected_restaurant_id'] = owner.id
        request.session['selected_restaurant_name'] = restaurant_obj.name
        request.session['order_type'] = chosen_type
        # Clear old table data so it doesn't interfere
        request.session.pop('selected_table', None)
        request.session.pop('selected_table_id', None)

        if chosen_type == 'delivery':
            return redirect('restaurant:delivery_info', restaurant_id=restaurant_obj.id)
        else:
            request.session['delivery_address'] = ''
            request.session['delivery_phone'] = ''
            return redirect('restaurant:menu')

    return render(request, 'restaurant/select_order_type.html', {
        'restaurant': restaurant_obj,
    })


@login_required
def delivery_info(request, restaurant_id):
    """Enter delivery address and phone for a delivery order."""
    from restaurant.models_restaurant import Restaurant as RestaurantModel
    restaurant_obj = get_object_or_404(
        RestaurantModel,
        id=restaurant_id,
        allow_remote_orders=True,
        is_active=True,
    )
    owner = restaurant_obj.main_owner

    if request.method == 'POST':
        address = request.POST.get('delivery_address', '').strip()
        phone = request.POST.get('delivery_phone', '').strip()
        if not address:
            messages.error(request, 'Please enter your delivery address.')
        elif not phone:
            messages.error(request, 'Please enter your phone number so the rider can contact you.')
        else:
            request.session['selected_restaurant_id'] = owner.id
            request.session['selected_restaurant_name'] = restaurant_obj.name
            request.session['order_type'] = 'delivery'
            request.session['delivery_address'] = address
            request.session['delivery_phone'] = phone
            request.session.pop('selected_table', None)
            request.session.pop('selected_table_id', None)
            return redirect('restaurant:menu')

    return render(request, 'restaurant/delivery_info.html', {
        'restaurant': restaurant_obj,
        'delivery_address': request.session.get('delivery_address', ''),
        'delivery_phone': request.session.get('delivery_phone', ''),
    })


def menu(request):
    """Display menu with cart functionality"""
    # Initialize logger at the start
    import logging
    logger = logging.getLogger(__name__)
    
    # Allow delivery/pickup remote orders to skip table selection
    order_type = request.session.get('order_type', 'dine-in')
    is_remote_order = order_type in ('delivery', 'pickup')

    if 'selected_table' not in request.session and not is_remote_order:
        messages.warning(request, 'Please select your table number first.')
        return redirect('orders:select_table')

    table_number = request.session.get('selected_table', '')
    
    # Get current restaurant for filtering menu
    current_restaurant = None
    
    # For staff users (customer_care, kitchen, bar, buffet, service, cashier), use their assigned restaurant
    if request.user.is_authenticated and (
        request.user.is_customer_care() or 
        request.user.is_kitchen_staff() or 
        request.user.is_bar_staff() or 
        request.user.is_buffet_staff() or 
        request.user.is_service_staff() or 
        request.user.is_cashier()
    ):
        # Staff users get their restaurant from User.owner
        current_restaurant = request.user.get_owner()
        if current_restaurant:
            # Get display name - for branches, show parent restaurant name
            from restaurant.models_restaurant import Restaurant
            try:
                if current_restaurant.is_branch_owner():
                    rest_obj = Restaurant.objects.get(branch_owner=current_restaurant, is_main_restaurant=False)
                    display_name = rest_obj.parent_restaurant.name if rest_obj.parent_restaurant else current_restaurant.restaurant_name
                else:
                    rest_obj = Restaurant.objects.filter(main_owner=current_restaurant, is_main_restaurant=True).first()
                    display_name = rest_obj.name if rest_obj else current_restaurant.restaurant_name
            except Restaurant.DoesNotExist:
                display_name = current_restaurant.restaurant_name
            
            # Ensure session data is set for consistency
            request.session['selected_restaurant_id'] = current_restaurant.id
            request.session['selected_restaurant_name'] = display_name
        else:
            messages.error(request, 'You are not assigned to any restaurant. Please contact your administrator.')
            return redirect('accounts:login')
    else:
        # For regular customers, use QR code session
        selected_restaurant_id = request.session.get('selected_restaurant_id')
        
        if selected_restaurant_id:
            try:
                # Support all owner types: owner, main_owner, branch_owner
                current_restaurant = User.objects.get(
                    id=selected_restaurant_id,
                    role__name__in=['owner', 'main_owner', 'branch_owner']
                )
            except User.DoesNotExist:
                messages.error(request, 'Selected restaurant not found.')
                return redirect('orders:select_table')
    
    # Filter categories by current restaurant
    if current_restaurant:
        # Try to find the Restaurant object for this owner
        from restaurant.models_restaurant import Restaurant
        restaurant_obj = None
        
        try:
            # Check if this user has a Restaurant object (PRO plan)
            # Priority: branch_owner first (for branch staff), then main restaurant (for main owner)
            restaurant_obj = Restaurant.objects.filter(
                Q(branch_owner=current_restaurant)
            ).first()
            
            if not restaurant_obj:
                # Not a branch owner, check if they own a main restaurant
                restaurant_obj = Restaurant.objects.filter(
                    Q(main_owner=current_restaurant),
                    Q(is_main_restaurant=True)
                ).first()
            
        except Exception as e:
            pass
        
        # Filter categories by BOTH owner field AND restaurant field
        if restaurant_obj:
            # PRO plan: filter by Restaurant object OR by User owner
            # Create filtered prefetches for subcategories and products
            # Note: SubCategory and Product inherit owner/restaurant through main_category
            subcategory_filter = (
                Q(main_category__restaurant=restaurant_obj) | 
                Q(main_category__owner=current_restaurant)
            )
            product_filter = (
                Q(sub_category__main_category__restaurant=restaurant_obj) | 
                Q(sub_category__main_category__owner=current_restaurant)
            )
            
            subcategories_prefetch = Prefetch(
                'subcategories',
                queryset=SubCategory.objects.filter(subcategory_filter, is_active=True)
            )
            products_prefetch = Prefetch(
                'subcategories__products',
                queryset=Product.objects.filter(product_filter, is_available=True)
            )
            
            categories = MainCategory.objects.filter(
                Q(restaurant=restaurant_obj) | Q(owner=current_restaurant),
                is_active=True
            ).prefetch_related(subcategories_prefetch, products_prefetch).order_by('name')
            
            # For branches, show parent restaurant name instead of branch name
            if restaurant_obj.is_main_restaurant:
                restaurant_name = restaurant_obj.name
            else:
                # Branch: show parent restaurant name
                restaurant_name = restaurant_obj.parent_restaurant.name if restaurant_obj.parent_restaurant else restaurant_obj.name
            
            # Update session if it's wrong (for existing sessions before the fix)
            if request.session.get('selected_restaurant_name') != restaurant_name:
                request.session['selected_restaurant_name'] = restaurant_name
                request.session.modified = True
        else:
            # SINGLE plan: filter by owner only
            subcategories_prefetch = Prefetch(
                'subcategories',
                queryset=SubCategory.objects.filter(main_category__owner=current_restaurant, is_active=True)
            )
            products_prefetch = Prefetch(
                'subcategories__products',
                queryset=Product.objects.filter(sub_category__main_category__owner=current_restaurant, is_available=True)
            )
            
            categories = MainCategory.objects.filter(
                is_active=True, 
                owner=current_restaurant
            ).prefetch_related(subcategories_prefetch, products_prefetch).order_by('name')
            
            restaurant_name = current_restaurant.restaurant_name
    else:
        # Fallback: try traditional owner filtering for staff/tied customers
        try:
            from accounts.models import get_owner_filter
            owner_filter = get_owner_filter(request.user)
            if owner_filter:
                categories = MainCategory.objects.filter(
                    Q(owner=owner_filter) |
                    Q(restaurant__main_owner=owner_filter) |
                    Q(restaurant__branch_owner=owner_filter),
                    is_active=True,
                ).distinct().prefetch_related('subcategories__products').order_by('name')
                restaurant_name = owner_filter.restaurant_name
            else:
                messages.error(request, 'Please select your restaurant and table first.')
                return redirect('orders:select_table')
        except Exception as e:
            messages.error(request, 'Unable to load menu. Please try again.')
            return redirect('orders:select_table')
    
    # Safety check - if we somehow got here without categories
    if 'categories' not in locals():
        messages.error(request, 'Unable to load menu. Please select your table first.')
        return redirect('orders:select_table')

    # Get cart from session - handle empty cart safely
    cart = request.session.get('cart', {})
    cart_count = 0
    cart_total = 0
    
    if cart:
        try:
            cart_count = sum(item.get('quantity', 0) for item in cart.values() if isinstance(item, dict))
            cart_total = sum(
                float(item.get('price', 0)) * item.get('quantity', 0) 
                for item in cart.values() 
                if isinstance(item, dict)
            )
        except (ValueError, TypeError):
            # Reset cart if there's corrupted data
            cart = {}
            request.session['cart'] = cart
            cart_count = 0
            cart_total = 0

    # Pre-compute Happy Hour promotion data for all products (prevents N+1 in template)
    if current_restaurant and 'categories' in locals():
        _now = timezone.localtime(timezone.now())
        _current_day = str(_now.weekday() + 1)
        _current_time = _now.time()

        # 1 query + 3 prefetch queries instead of N*3 queries per product
        _all_promos = list(HappyHourPromotion.objects.filter(
            owner=current_restaurant,
            is_active=True,
            days_of_week__contains=_current_day,
        ).prefetch_related('products', 'main_categories', 'sub_categories')
         .order_by('-discount_percentage'))

        # Filter to time-active promotions in Python (no extra DB)
        _active_promos = []
        for _promo in _all_promos:
            if _promo.start_time <= _promo.end_time:
                if _promo.start_time <= _current_time <= _promo.end_time:
                    _active_promos.append(_promo)
            else:  # cross-midnight
                if _current_time >= _promo.start_time or _current_time <= _promo.end_time:
                    _active_promos.append(_promo)

        # Build product-id → best-promotion lookup (highest discount wins)
        _promo_by_product = {}
        _promo_by_maincategory = {}
        _promo_by_subcategory = {}
        for _promo in _active_promos:
            for _p in _promo.products.all():
                _promo_by_product.setdefault(_p.id, _promo)
            for _mc in _promo.main_categories.all():
                _promo_by_maincategory.setdefault(_mc.id, _promo)
            for _sc in _promo.sub_categories.all():
                _promo_by_subcategory.setdefault(_sc.id, _promo)

        # Force queryset evaluation and attach cached promotion data to each product
        categories = list(categories)
        for _cat in categories:
            for _subcat in _cat.subcategories.all():
                for _product in _subcat.products.all():
                    _promo = (
                        _promo_by_product.get(_product.id) or
                        _promo_by_maincategory.get(_product.main_category_id) or
                        (_promo_by_subcategory.get(_product.sub_category_id) if _product.sub_category_id else None)
                    )
                    _product._active_promotion_cache = _promo
                    if _promo:
                        _disc = _product.price * (_promo.discount_percentage / Decimal('100'))
                        _product._calculated_price_cache = max(_product.price - _disc, Decimal('0.01'))
                    else:
                        _product._calculated_price_cache = _product.price

    # Determine base template based on user role
    if request.user.is_authenticated:
        if request.user.is_cashier() or request.user.is_customer_care():
            base_template = 'cashier_base.html'
        else:
            base_template = 'base.html'
    else:
        base_template = 'base.html'
    
    context = {
        'categories': categories,
        'table_number': table_number,
        'cart': cart,
        'cart_count': cart_count,
        'cart_total': cart_total,
        'restaurant_name': restaurant_name,
        'current_restaurant': current_restaurant,
        'base_template': base_template,
        'order_type': order_type,
        'is_remote_order': is_remote_order,
        'delivery_address': request.session.get('delivery_address', ''),
    }

    return render(request, 'restaurant/menu.html', context)

@login_required
def owner_dashboard(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get owner filter for data isolation
    from accounts.models import get_owner_filter
    owner_filter = None
    try:
        owner_filter = get_owner_filter(request.user)
        
        # Dashboard statistics - filtered by owner
        if owner_filter:
            total_products = Product.objects.filter(
                Q(main_category__owner=owner_filter) |
                Q(main_category__restaurant__main_owner=owner_filter) |
                Q(main_category__restaurant__branch_owner=owner_filter)
            ).distinct().count()
            # Combine order counts — single query with conditional aggregation instead of 2 separate counts
            _order_counts = Order.objects.filter(
                Q(table_info__owner=owner_filter) |
                Q(table_info__restaurant__main_owner=owner_filter) |
                Q(table_info__restaurant__branch_owner=owner_filter) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner_filter) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner_filter)
            ).distinct().aggregate(
                total=Count('id'),
                pending=Count('id', filter=Q(status='pending')),
            )
            total_orders   = _order_counts['total'] or 0
            pending_orders = _order_counts['pending'] or 0
            total_staff = User.objects.filter(owner=owner_filter).exclude(role__name='customer').count()
            
            # Recent orders - filtered by owner
            recent_orders = Order.objects.filter(
                Q(table_info__owner=owner_filter) |
                Q(table_info__restaurant__main_owner=owner_filter) |
                Q(table_info__restaurant__branch_owner=owner_filter) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner_filter) |
                Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner_filter)
            ).distinct().select_related('table_info', 'ordered_by').order_by('-created_at')[:5]
        else:
            # Administrator sees all data
            total_products = Product.objects.count()
            total_orders = Order.objects.count()
            pending_orders = Order.objects.filter(status='pending').count()
            total_staff = User.objects.exclude(role__name='customer').count()
            recent_orders = Order.objects.select_related('table_info', 'ordered_by').order_by('-created_at')[:5]
    except Exception:
        # Fallback - no data if user not properly associated
        total_products = total_orders = pending_orders = total_staff = 0
        recent_orders = Order.objects.none()
    
    # Popular products — scoped to the owner's products (admin sees all)
    if owner_filter:
        popular_products = Product.objects.filter(
            Q(main_category__owner=owner_filter) |
            Q(main_category__restaurant__main_owner=owner_filter) |
            Q(main_category__restaurant__branch_owner=owner_filter)
        ).distinct().annotate(
            order_count=Count('orderitem')
        ).order_by('-order_count')[:5]
    else:
        popular_products = Product.objects.annotate(
            order_count=Count('orderitem')
        ).order_by('-order_count')[:5]
    
    context = {
        'total_products': total_products,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'total_staff': total_staff,
        'recent_orders': recent_orders,
        'popular_products': popular_products,
    }
    
    return render(request, 'restaurant/owner_dashboard.html', context)

@login_required
def manage_staff(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get staff members belonging to this owner only
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    if owner_filter:
        staff_members = User.objects.filter(owner=owner_filter).exclude(role__name='customer').select_related('role').order_by('role__name', 'username')
    else:
        staff_members = User.objects.exclude(role__name='customer').select_related('role').order_by('role__name', 'username')
    
    return render(request, 'restaurant/manage_staff.html', {'staff_members': staff_members})

@login_required
@transaction.atomic
def add_staff(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'success': False, 'message': 'Access denied. Owner privileges required.'})
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    if request.method == 'POST':
        # Handle AJAX request from owner dashboard
        if request.headers.get('Content-Type') == 'application/json':
            try:
                import json
                data = json.loads(request.body)
                
                # Validate required fields
                required_fields = ['username', 'email', 'first_name', 'last_name', 'role', 'password']
                for field in required_fields:
                    if not data.get(field):
                        return JsonResponse({'success': False, 'message': f'{field.replace("_", " ").title()} is required'})
                
                # Check if username already exists
                if User.objects.filter(username=data['username']).exists():
                    return JsonResponse({'success': False, 'message': 'Username already exists'})
                
                # Check if email already exists
                if User.objects.filter(email=data['email']).exists():
                    return JsonResponse({'success': False, 'message': 'Email already exists'})
                
                # Validate role - owners can add staff roles only (not other owners)
                staff_roles = ['manager', 'kitchen', 'bar', 'cashier', 'buffet', 'service', 'customer_care', 'customer']
                owner_roles = ['main_owner', 'branch_owner', 'owner', 'administrator']
                
                if data['role'] in owner_roles:
                    return JsonResponse({'success': False, 'message': 'Cannot create owner or administrator roles through this interface. Use Admin Panel.'})
                
                if data['role'] not in staff_roles:
                    return JsonResponse({'success': False, 'message': 'Invalid role. Only staff roles can be added (kitchen, bar, cashier, buffet, service, customer care).'})
                
                # Get the role object
                try:
                    role = Role.objects.get(name=data['role'])
                except Role.DoesNotExist:
                    return JsonResponse({'success': False, 'message': 'Role not found'})
                
                # Create the user
                from accounts.models import get_owner_filter
                owner_filter = get_owner_filter(request.user)
                user = User.objects.create_user(
                    username=data['username'],
                    email=data['email'],
                    password=data['password'],
                    first_name=data['first_name'],
                    last_name=data['last_name'],
                    role=role,
                    phone_number=data.get('phone_number', ''),
                    is_active_staff=True,
                    owner=owner_filter if owner_filter else None
                )
                
                return JsonResponse({
                    'success': True, 
                    'message': f'{user.get_full_name()} added as {role.get_name_display()} successfully!'
                })
                
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
            except Exception as e:
                logger.error(f"Error creating user: {str(e)}", exc_info=True)
                return JsonResponse({'success': False, 'message': 'Error creating user. Please try again.'})
        
        # Handle regular form submission
        form = StaffForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            # Set owner for the new staff member
            from accounts.models import get_owner_filter
            owner_filter = get_owner_filter(request.user)
            if owner_filter:
                user.owner = owner_filter
            user.save()
            messages.success(request, f'{user.get_full_name()} added as {user.role.get_name_display()}!')
            return redirect('restaurant:manage_staff')
        else:
            messages.error(request, 'Invalid form submission. Please use the dashboard form.')
            return redirect('restaurant:owner_dashboard')
    else:
        return redirect('restaurant:owner_dashboard')
@login_required
def manage_promotions(request):
    """View all Happy Hour promotions for the current owner"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Import restaurant context utilities
    from admin_panel.restaurant_utils import get_restaurant_context
    
    # Get restaurant context
    session_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant_context = get_restaurant_context(request.user, session_restaurant_id, request)
    current_restaurant = restaurant_context['current_restaurant']
    view_all_restaurants = restaurant_context['view_all_restaurants']
    
    # Get filter parameters
    search_query = request.GET.get('search', '').strip()
    restaurant_filter = request.GET.get('restaurant', '').strip()
    status_filter = request.GET.get('status', '').strip()
    
    # Determine which restaurant to filter by
    target_restaurant = None
    if restaurant_filter:
        try:
            from restaurant.models_restaurant import Restaurant
            target_restaurant = Restaurant.objects.get(id=restaurant_filter)
            # Security: verify user has access to this restaurant
            if not request.user.is_administrator():
                if not restaurant_context['accessible_restaurants'].filter(id=target_restaurant.id).exists():
                    target_restaurant = None
        except Restaurant.DoesNotExist:
            target_restaurant = None
    elif current_restaurant and not view_all_restaurants:
        target_restaurant = current_restaurant
    
    if target_restaurant:
        # Filter promotions by specific selected restaurant
        if target_restaurant.is_main_restaurant:
            # Main restaurant: show promotions owned by main owner
            promotions = HappyHourPromotion.objects.filter(
                owner=target_restaurant.main_owner
            ).order_by('-created_at')
        else:
            # Branch restaurant: only show promotions owned by branch owner
            if target_restaurant.branch_owner:
                promotions = HappyHourPromotion.objects.filter(
                    owner=target_restaurant.branch_owner
                ).order_by('-created_at')
            else:
                promotions = HappyHourPromotion.objects.none()
    else:
        # Get promotions from all accessible restaurants
        accessible_restaurants = restaurant_context['accessible_restaurants']
        
        if accessible_restaurants.exists():
            owner_query = Q()
            for restaurant in accessible_restaurants:
                if restaurant.main_owner:
                    owner_query |= Q(owner=restaurant.main_owner)
                if restaurant.branch_owner:
                    owner_query |= Q(owner=restaurant.branch_owner)
            promotions = HappyHourPromotion.objects.filter(owner_query).order_by('-created_at')
        else:
            promotions = HappyHourPromotion.objects.none()
    
    # Apply search filter
    if search_query:
        promotions = promotions.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter:
        if status_filter == 'active':
            promotions = promotions.filter(is_active=True)
        elif status_filter == 'inactive':
            promotions = promotions.filter(is_active=False)
    
    # Calculate real-time statistics — evaluate queryset once (3→1 query)
    _promotions_list = list(promotions)
    total_promotions = len(_promotions_list)
    active_promotions = sum(1 for p in _promotions_list if p.is_active)
    currently_running = sum(1 for p in _promotions_list if p.is_currently_active())
    
    # Pagination
    try:
        per_page = int(request.GET.get('per_page', 5))
    except (ValueError, TypeError):
        per_page = 5
    paginator = Paginator(_promotions_list, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'promotions': page_obj.object_list,
        'page_obj': page_obj,
        'total_promotions': total_promotions,
        'active_promotions': active_promotions,
        'currently_running': currently_running,
        **restaurant_context,  # Include restaurant context for templates
    }
    
    return render(request, 'restaurant/manage_promotions.html', context)


@login_required
@transaction.atomic
def add_promotion(request):
    """Add a new Happy Hour promotion"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Import restaurant context utilities
    from admin_panel.restaurant_utils import get_restaurant_context
    
    # Get restaurant context
    session_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant_context = get_restaurant_context(request.user, session_restaurant_id, request)
    current_restaurant = restaurant_context['current_restaurant']
    
    if request.method == 'POST':
        # Get restaurant_id from form (when in "All Restaurants" mode)
        restaurant_id = request.POST.get('restaurant')
        
        # Determine target restaurant for the promotion
        if restaurant_id:
            # User selected a specific restaurant from dropdown
            try:
                target_restaurant = Restaurant.objects.get(id=restaurant_id)
                
                # Validate user has permission for this restaurant
                accessible_restaurants = restaurant_context.get('accessible_restaurants', [])
                if target_restaurant not in accessible_restaurants:
                    messages.error(request, 'You do not have permission to add promotions to this restaurant.')
                    return redirect('restaurant:manage_promotions')
                
                # Determine owner based on restaurant type
                if target_restaurant.is_main_restaurant:
                    promotion_owner = target_restaurant.main_owner
                else:
                    promotion_owner = target_restaurant.branch_owner or target_restaurant.main_owner
                    
            except Restaurant.DoesNotExist:
                messages.error(request, 'Selected restaurant does not exist.')
                return redirect('restaurant:manage_promotions')
        else:
            # No specific restaurant selected, use current context
            target_restaurant = current_restaurant
            if target_restaurant:
                if target_restaurant.is_main_restaurant:
                    promotion_owner = target_restaurant.main_owner
                else:
                    promotion_owner = target_restaurant.branch_owner or target_restaurant.main_owner
            else:
                promotion_owner = request.user
        
        form = HappyHourPromotionForm(request.POST, owner=promotion_owner)
        if form.is_valid():
            promotion = form.save(commit=False)
            promotion.owner = promotion_owner
            promotion.save()
            form.save_m2m()  # Save many-to-many relationships
            restaurant_name = target_restaurant.name if target_restaurant else promotion_owner.restaurant_name
            messages.success(request, f'Happy Hour promotion "{promotion.name}" created successfully for {restaurant_name}!')
            return redirect('restaurant:manage_promotions')
    else:
        # Determine default owner for form initialization
        if current_restaurant:
            if current_restaurant.is_main_restaurant:
                promotion_owner = current_restaurant.main_owner
            else:
                promotion_owner = current_restaurant.branch_owner or current_restaurant.main_owner
        else:
            promotion_owner = request.user
            
        form = HappyHourPromotionForm(owner=promotion_owner)
    
    context = {
        'form': form,
        **restaurant_context,  # Include restaurant context for templates
    }
    
    return render(request, 'restaurant/add_promotion.html', context)


@login_required
@transaction.atomic
def edit_promotion(request, promotion_id):
    """Edit an existing Happy Hour promotion"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Import restaurant context utilities
    from admin_panel.restaurant_utils import get_restaurant_context
    
    # Get restaurant context
    session_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant_context = get_restaurant_context(request.user, session_restaurant_id, request)
    current_restaurant = restaurant_context['current_restaurant']
    
    # Get promotion - check if user has access to this promotion's restaurant
    try:
        promotion = get_object_or_404(HappyHourPromotion, id=promotion_id)
        
        # Validate user has access to this promotion's restaurant
        accessible_restaurants = restaurant_context.get('accessible_restaurants', [])
        
        # Find promotion's restaurant by checking owner
        promotion_restaurant = None
        for rest in accessible_restaurants:
            if rest.is_main_restaurant and rest.main_owner == promotion.owner:
                promotion_restaurant = rest
                break
            elif not rest.is_main_restaurant and (rest.branch_owner == promotion.owner or rest.main_owner == promotion.owner):
                promotion_restaurant = rest
                break
        
        if not promotion_restaurant:
            messages.error(request, 'You do not have permission to edit this promotion.')
            return redirect('restaurant:manage_promotions')
            
    except HappyHourPromotion.DoesNotExist:
        messages.error(request, 'Promotion not found.')
        return redirect('restaurant:manage_promotions')
    
    if request.method == 'POST':
        # Get restaurant_id from form
        restaurant_id = request.POST.get('restaurant')
        
        # Determine the owner to use for the form
        # If restaurant_id provided, check if it's different from current
        if restaurant_id:
            try:
                target_restaurant = Restaurant.objects.get(id=restaurant_id)
                
                # Find current promotion's restaurant
                current_promo_restaurant = None
                for rest in accessible_restaurants:
                    if rest.is_main_restaurant and rest.main_owner == promotion.owner:
                        current_promo_restaurant = rest
                        break
                    elif not rest.is_main_restaurant and (rest.branch_owner == promotion.owner or rest.main_owner == promotion.owner):
                        current_promo_restaurant = rest
                        break
                
                # Only validate and change if restaurant is actually different
                if current_promo_restaurant and target_restaurant.id != current_promo_restaurant.id:
                    # Validate user has permission for new restaurant
                    accessible_restaurants = restaurant_context.get('accessible_restaurants', [])
                    if target_restaurant not in accessible_restaurants:
                        messages.error(request, 'You do not have permission to assign promotions to this restaurant.')
                        return redirect('restaurant:manage_promotions')
                    
                    # Determine owner based on restaurant type
                    if target_restaurant.is_main_restaurant:
                        new_owner = target_restaurant.main_owner
                    else:
                        new_owner = target_restaurant.branch_owner or target_restaurant.main_owner
                else:
                    # Same restaurant or keeping current, use existing owner
                    new_owner = promotion.owner
                    
            except Restaurant.DoesNotExist:
                messages.error(request, 'Selected restaurant does not exist.')
                return redirect('restaurant:manage_promotions')
        else:
            # No restaurant_id provided, keep current owner
            new_owner = promotion.owner
        
        form = HappyHourPromotionForm(request.POST, instance=promotion, owner=new_owner)
        if form.is_valid():
            updated_promotion = form.save(commit=False)
            updated_promotion.owner = new_owner
            updated_promotion.save()
            form.save_m2m()  # Save many-to-many relationships
            messages.success(request, f'Promotion "{promotion.name}" updated successfully!')
            return redirect('restaurant:manage_promotions')
    else:
        form = HappyHourPromotionForm(instance=promotion, owner=promotion.owner)
    
    # Get current selected products, categories, and subcategories
    selected_products = list(promotion.products.values_list('id', flat=True))
    selected_main_categories = list(promotion.main_categories.values_list('id', flat=True))
    selected_sub_categories = list(promotion.sub_categories.values_list('id', flat=True))
    
    # Find promotion's current restaurant
    promotion_restaurant = None
    for rest in accessible_restaurants:
        if rest.is_main_restaurant and rest.main_owner == promotion.owner:
            promotion_restaurant = rest
            break
        elif not rest.is_main_restaurant and (rest.branch_owner == promotion.owner or rest.main_owner == promotion.owner):
            promotion_restaurant = rest
            break
    
    context = {
        'form': form,
        'promotion': promotion,
        'promotion_restaurant': promotion_restaurant,
        'selected_products': selected_products,
        'selected_main_categories': selected_main_categories,
        'selected_sub_categories': selected_sub_categories,
        **restaurant_context,  # Include restaurant context for templates
    }
    
    return render(request, 'restaurant/edit_promotion.html', context)


@login_required
def delete_promotion(request, promotion_id):
    """Delete a Happy Hour promotion"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Import restaurant context utilities
    from admin_panel.restaurant_utils import get_restaurant_context
    
    # Get restaurant context
    session_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant_context = get_restaurant_context(request.user, session_restaurant_id, request)
    current_restaurant = restaurant_context['current_restaurant']
    
    # Get promotion with proper owner filtering
    try:
        if current_restaurant:
            if current_restaurant.is_main_restaurant:
                promotion = get_object_or_404(HappyHourPromotion, id=promotion_id, owner=current_restaurant.main_owner)
            else:
                promotion = get_object_or_404(HappyHourPromotion, id=promotion_id, owner=current_restaurant.branch_owner or current_restaurant.main_owner)
        else:
            from accounts.models import get_owner_filter
            owner_filter = get_owner_filter(request.user)
            promotion = get_object_or_404(HappyHourPromotion, id=promotion_id, owner=owner_filter)
    except HappyHourPromotion.DoesNotExist:
        messages.error(request, 'Promotion not found or access denied.')
        return redirect('restaurant:manage_promotions')
    
    if request.method == 'POST':
        promotion_name = promotion.name
        promotion.delete()
        messages.success(request, f'Promotion "{promotion_name}" deleted successfully!')
        return redirect('restaurant:manage_promotions')
    
    context = {
        'promotion': promotion,
        **restaurant_context,  # Include restaurant context for templates
    }
    
    return render(request, 'restaurant/delete_promotion.html', context)


@login_required
def get_restaurant_products(request):
    """Get products, categories, and subcategories for a specific restaurant (AJAX endpoint)"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    try:
        restaurant_id = request.GET.get('restaurant_id')
        
        if not restaurant_id:
            return JsonResponse({'success': False, 'message': 'Restaurant ID required'})
        
        # Import Restaurant model
        from restaurant.models import Restaurant
        from admin_panel.restaurant_utils import get_restaurant_context as _get_ctx
        
        # Get restaurant and determine owner
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        
        # Security: verify user has access to this restaurant
        if not request.user.is_administrator():
            _session_rid = request.session.get('selected_restaurant_id')
            _ctx = _get_ctx(request.user, _session_rid, request)
            if not _ctx['accessible_restaurants'].filter(id=restaurant.id).exists():
                return JsonResponse({'success': False, 'message': 'Access denied'})
        
        if restaurant.is_main_restaurant:
            owner = restaurant.main_owner
        else:
            owner = restaurant.branch_owner or restaurant.main_owner
        
        # Get products, main categories, and subcategories for this owner
        products = Product.objects.filter(
            Q(main_category__owner=owner) |
            Q(main_category__restaurant__main_owner=owner) |
            Q(main_category__restaurant__branch_owner=owner)
        ).distinct().values('id', 'name')
        main_categories = MainCategory.objects.filter(
            Q(owner=owner) |
            Q(restaurant__main_owner=owner) |
            Q(restaurant__branch_owner=owner)
        ).distinct().values('id', 'name')
        sub_categories = SubCategory.objects.filter(
            Q(main_category__owner=owner) |
            Q(main_category__restaurant__main_owner=owner) |
            Q(main_category__restaurant__branch_owner=owner)
        ).distinct().values('id', 'name')
        
        return JsonResponse({
            'success': True,
            'products': list(products),
            'main_categories': list(main_categories),
            'sub_categories': list(sub_categories)
        })
        
    except Exception as e:
        logger.error(f"Error fetching restaurant items: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': 'Error fetching restaurant items. Please try again.'})


@login_required 
def toggle_promotion(request, promotion_id):
    """Toggle promotion active/inactive status via AJAX"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        return JsonResponse({'success': False, 'message': 'Access denied.'})
    
    # Import restaurant context utilities
    from admin_panel.restaurant_utils import get_restaurant_context
    
    # Get restaurant context
    session_restaurant_id = request.session.get('selected_restaurant_id')
    restaurant_context = get_restaurant_context(request.user, session_restaurant_id, request)
    current_restaurant = restaurant_context['current_restaurant']
    
    try:
        # Get promotion with proper owner filtering
        if current_restaurant:
            if current_restaurant.is_main_restaurant:
                promotion = HappyHourPromotion.objects.get(id=promotion_id, owner=current_restaurant.main_owner)
            else:
                promotion = HappyHourPromotion.objects.get(id=promotion_id, owner=current_restaurant.branch_owner or current_restaurant.main_owner)
        else:
            from accounts.models import get_owner_filter
            owner_filter = get_owner_filter(request.user)
            promotion = HappyHourPromotion.objects.get(id=promotion_id, owner=owner_filter)
        
        promotion.is_active = not promotion.is_active
        promotion.save()
        
        return JsonResponse({
            'success': True,
            'is_active': promotion.is_active,
            'message': f'Promotion {"activated" if promotion.is_active else "deactivated"} successfully!'
        })
    except HappyHourPromotion.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Promotion not found.'})


@login_required
def promotion_preview(request, promotion_id):
    """Preview promotion details and affected products"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    promotion = get_object_or_404(HappyHourPromotion, id=promotion_id, owner=owner_filter)
    
    # Get all affected products
    from django.db.models import Q
    affected_products = Product.objects.filter(
        Q(pk__in=promotion.products.all()) |
        Q(main_category__in=promotion.main_categories.all()) |
        Q(sub_category__in=promotion.sub_categories.all()),
        Q(main_category__owner=owner_filter) |
        Q(main_category__restaurant__main_owner=owner_filter) |
        Q(main_category__restaurant__branch_owner=owner_filter)
    ).distinct().select_related('main_category', 'sub_category')
    
    from admin_panel.restaurant_utils import get_restaurant_context as _grc
    _rc = _grc(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'promotion': promotion,
        'affected_products': affected_products,
        'affected_count': affected_products.count(),
        **_rc,
    }
    
    return render(request, 'restaurant/promotion_preview.html', context)


# ============================================================================
# EVENT MANAGEMENT VIEWS
# ============================================================================

from .models import Event
from .forms import EventForm
from django.db.models import Sum, Count, Avg
from datetime import datetime, timedelta


@login_required
def manage_events(request):
    """List all events for the restaurant owner"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    # Get restaurant for currency
    from .models_restaurant import Restaurant
    from django.db.models import Q as DBQ
    restaurant = Restaurant.objects.filter(
        DBQ(main_owner=owner_filter) | DBQ(branch_owner=request.user)
    ).first()
    currency_symbol = restaurant.get_currency_symbol() if restaurant else '$'
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    event_type_filter = request.GET.get('event_type', '')
    date_filter = request.GET.get('date_filter', 'all')
    search_query = request.GET.get('search', '')
    
    # Base queryset
    events = Event.objects.filter(owner=owner_filter)
    
    # Apply filters
    if status_filter:
        events = events.filter(status=status_filter)
    
    if event_type_filter:
        events = events.filter(event_type=event_type_filter)
    
    if search_query:
        events = events.filter(
            Q(title__icontains=search_query) |
            Q(contact_name__icontains=search_query) |
            Q(contact_phone__icontains=search_query)
        )
    
    # Date filters
    from django.utils.timezone import localtime
    today = localtime(timezone.now()).date()
    if date_filter == 'today':
        events = events.filter(event_date=today)
    elif date_filter == 'week':
        week_end = today + timedelta(days=7)
        events = events.filter(event_date__gte=today, event_date__lte=week_end)
    elif date_filter == 'month':
        month_end = today + timedelta(days=30)
        events = events.filter(event_date__gte=today, event_date__lte=month_end)
    elif date_filter == 'upcoming':
        events = events.filter(event_date__gte=today).exclude(status__in=['completed', 'cancelled'])
    elif date_filter == 'past':
        events = events.filter(event_date__lt=today)
    
    # Calculate summary statistics
    all_events = Event.objects.filter(owner=owner_filter)
    
    # Fully paid events
    fully_paid_events = all_events.filter(payment_status='fully_paid')
    paid_amount = fully_paid_events.aggregate(total=Sum('amount_paid'))['total'] or 0

    # Unpaid events - total balance due
    unpaid_events_list = all_events.filter(payment_status='unpaid').exclude(status='cancelled')
    unpaid_amount = sum(event.price_per_pax * event.total_pax for event in unpaid_events_list)

    # Partially-paid / deposit-paid events also contribute to total potential revenue
    partial_events = all_events.filter(
        payment_status__in=['partially_paid', 'deposit_paid']
    ).exclude(status='cancelled')
    partial_revenue = sum(event.price_per_pax * event.total_pax for event in partial_events)

    total_revenue = paid_amount + unpaid_amount + partial_revenue
    
    # Pending payments: sum of balance due for events not fully paid or cancelled
    from django.db.models import F
    pending_events = all_events.exclude(payment_status='fully_paid').exclude(status='cancelled')
    pending_payments = sum((event.price_per_pax * event.total_pax) - event.amount_paid 
                          for event in pending_events)
    
    summary = {
        'total_events': all_events.count(),
        'upcoming_events': all_events.filter(event_date__gte=today).exclude(status__in=['completed', 'cancelled']).count(),
        'total_revenue': total_revenue,
        'pending_payments': pending_payments,
        'paid_events': fully_paid_events.count(),
        'paid_amount': paid_amount,
        'unpaid_events': unpaid_events_list.count(),
        'unpaid_amount': unpaid_amount,
        'today_events': all_events.filter(event_date=today).count(),
    }
    
    # Pagination
    paginator = Paginator(events.order_by('-event_date', '-start_time'), 10)
    page_number = request.GET.get('page')
    events_page = paginator.get_page(page_number)
    
    from admin_panel.restaurant_utils import get_restaurant_context as _grc
    _rc = _grc(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'events': events_page,
        'summary': summary,
        'status_filter': status_filter,
        'event_type_filter': event_type_filter,
        'date_filter': date_filter,
        'search_query': search_query,
        'event_types': Event.EVENT_TYPE_CHOICES,
        'status_choices': Event.EVENT_STATUS_CHOICES,
        'currency_symbol': currency_symbol,
        **_rc,
    }

    return render(request, 'restaurant/manage_events.html', context)


@login_required
@transaction.atomic
def add_event(request):
    """Add a new event"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    # Get restaurant for currency
    from .models_restaurant import Restaurant
    from django.db.models import Q as DBQ
    restaurant = Restaurant.objects.filter(
        DBQ(main_owner=owner_filter) | DBQ(branch_owner=request.user)
    ).first()
    currency_symbol = restaurant.get_currency_symbol() if restaurant else '$'
    
    if request.method == 'POST':
        form = EventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.owner = owner_filter
            event.created_by = request.user
            event.save()
            messages.success(request, f'Event "{event.title}" created successfully!')
            return redirect('restaurant:manage_events')
    else:
        form = EventForm()
    
    from admin_panel.restaurant_utils import get_restaurant_context as _grc
    _rc = _grc(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'form': form,
        'action': 'Add',
        'currency_symbol': currency_symbol,
        **_rc,
    }
    
    return render(request, 'restaurant/event_form.html', context)


@login_required
@transaction.atomic
def edit_event(request, event_id):
    """Edit an existing event"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    event = get_object_or_404(Event, id=event_id, owner=owner_filter)
    
    # Get restaurant for currency
    from .models_restaurant import Restaurant
    from django.db.models import Q as DBQ
    restaurant = Restaurant.objects.filter(
        DBQ(main_owner=owner_filter) | DBQ(branch_owner=request.user)
    ).first()
    currency_symbol = restaurant.get_currency_symbol() if restaurant else '$'
    
    if request.method == 'POST':
        form = EventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            messages.success(request, f'Event "{event.title}" updated successfully!')
            return redirect('restaurant:manage_events')
    else:
        form = EventForm(instance=event)
    
    from admin_panel.restaurant_utils import get_restaurant_context as _grc
    _rc = _grc(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'form': form,
        'event': event,
        'action': 'Edit',
        'currency_symbol': currency_symbol,
        **_rc,
    }
    
    return render(request, 'restaurant/event_form.html', context)


@login_required
def view_event(request, event_id):
    """View event details"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    event = get_object_or_404(Event, id=event_id, owner=owner_filter)
    
    # Get restaurant for currency
    from .models_restaurant import Restaurant
    from django.db.models import Q as DBQ
    restaurant = Restaurant.objects.filter(
        DBQ(main_owner=owner_filter) | DBQ(branch_owner=request.user)
    ).first()
    currency_symbol = restaurant.get_currency_symbol() if restaurant else '$'
    
    from admin_panel.restaurant_utils import get_restaurant_context as _grc
    _rc = _grc(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'event': event,
        'currency_symbol': currency_symbol,
        **_rc,
    }
    
    return render(request, 'restaurant/event_detail.html', context)


@login_required
def delete_event(request, event_id):
    """Delete an event"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        return JsonResponse({'success': False, 'message': 'Access denied.'})
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    try:
        event = Event.objects.get(id=event_id, owner=owner_filter)
        title = event.title
        event.delete()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'Event "{title}" deleted successfully!'
            })
        
        messages.success(request, f'Event "{title}" deleted successfully!')
        return redirect('restaurant:manage_events')
    except Event.DoesNotExist:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'Event not found.'})
        messages.error(request, 'Event not found.')
        return redirect('restaurant:manage_events')


@login_required
def update_event_status(request, event_id):
    """Update event status via AJAX"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        return JsonResponse({'success': False, 'message': 'Access denied.'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method.'})
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    try:
        event = Event.objects.get(id=event_id, owner=owner_filter)
        
        import json
        data = json.loads(request.body)
        new_status = data.get('status')
        
        if new_status and new_status in dict(Event.EVENT_STATUS_CHOICES):
            event.status = new_status
            event.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Event status updated to {event.get_status_display()}!',
                'status': event.status,
                'status_display': event.get_status_display(),
                'status_color': event.get_status_color()
            })
        else:
            return JsonResponse({'success': False, 'message': 'Invalid status.'})
    except Event.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Event not found.'})


@login_required
def event_reports(request):
    """Event reports and analytics"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    # Get restaurant for currency
    from .models_restaurant import Restaurant
    from django.db.models import Q as DBQ
    restaurant = Restaurant.objects.filter(
        DBQ(main_owner=owner_filter) | DBQ(branch_owner=request.user)
    ).first()
    currency_symbol = restaurant.get_currency_symbol() if restaurant else '$'
    
    # Date range filter
    from django.utils.timezone import localtime
    period = request.GET.get('period', 'month')
    today = localtime(timezone.now()).date()
    
    if period == 'week':
        start_date = today - timedelta(days=7)
    elif period == 'month':
        start_date = today - timedelta(days=30)
    elif period == 'quarter':
        start_date = today - timedelta(days=90)
    elif period == 'year':
        start_date = today - timedelta(days=365)
    else:
        start_date = today - timedelta(days=30)
    
    # Get events in period
    events = Event.objects.filter(
        owner=owner_filter,
        event_date__gte=start_date,
        event_date__lte=today
    )
    
    # Calculate statistics
    completed_events = events.filter(status='completed')
    
    # Fully paid events - total amount from completed payments
    fully_paid_events = events.filter(payment_status='fully_paid')
    paid_amount = fully_paid_events.aggregate(total=Sum('amount_paid'))['total'] or 0
    
    # Unpaid events - total balance due
    unpaid_events_list = events.filter(payment_status='unpaid').exclude(status='cancelled')
    unpaid_amount = sum(event.price_per_pax * event.total_pax for event in unpaid_events_list)
    
    stats = {
        'total_events': events.count(),
        'completed_events': completed_events.count(),
        'cancelled_events': events.filter(status='cancelled').count(),
        'total_pax': events.aggregate(total=Sum('total_pax'))['total'] or 0,
        'average_pax': events.aggregate(avg=Avg('total_pax'))['avg'] or 0,
        'total_revenue': completed_events.aggregate(total=Sum('amount_paid'))['total'] or 0,
        'total_expected': events.exclude(status='cancelled').aggregate(
            total=Sum(F('total_pax') * F('price_per_pax'))
        )['total'] or 0,
        'pending_payments': events.exclude(payment_status='fully_paid').exclude(status='cancelled').count(),
        'paid_events_count': fully_paid_events.count(),
        'paid_amount': paid_amount,
        'unpaid_events_count': unpaid_events_list.count(),
        'unpaid_amount': unpaid_amount,
    }
    
    # Events by type
    events_by_type = events.values('event_type').annotate(
        count=Count('id'),
        total_pax=Sum('total_pax'),
        revenue=Sum('amount_paid')
    ).order_by('-count')
    
    # Events by status
    events_by_status = events.values('status').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Upcoming events
    upcoming_events = Event.objects.filter(
        owner=owner_filter,
        event_date__gte=today
    ).exclude(status__in=['completed', 'cancelled']).order_by('event_date')[:5]
    
    # Recent completed events
    recent_completed = Event.objects.filter(
        owner=owner_filter,
        status='completed'
    ).order_by('-event_date')[:5]
    
    # Check if this is an embedded request
    embed = request.GET.get('embed', '0') == '1'
    
    from admin_panel.restaurant_utils import get_restaurant_context as _grc
    _rc = _grc(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'stats': stats,
        'events_by_type': events_by_type,
        'events_by_status': events_by_status,
        'upcoming_events': upcoming_events,
        'recent_completed': recent_completed,
        'period': period,
        'start_date': start_date,
        'end_date': today,
        'event_types': dict(Event.EVENT_TYPE_CHOICES),
        'status_choices': dict(Event.EVENT_STATUS_CHOICES),
        'embed': embed,
        'currency_symbol': currency_symbol,
        **_rc,
    }
    
    # Use a simpler template for embedded mode
    template = 'restaurant/event_reports_embed.html' if embed else 'restaurant/event_reports.html'
    return render(request, template, context)


@login_required
@transaction.atomic
def record_event_payment(request, event_id):
    """Record a payment for an event"""
    import logging
    logger = logging.getLogger(__name__)
    
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        return JsonResponse({'success': False, 'message': 'Access denied.'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method.'})
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    try:
        event = Event.objects.get(id=event_id, owner=owner_filter)
        
        import json
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            return JsonResponse({'success': False, 'message': 'Invalid JSON data.'})
            
        payment_amount = Decimal(str(data.get('amount', 0)))
        is_deposit = data.get('is_deposit', False)
        
        logger.info(f"Recording payment: Event {event_id}, Amount {payment_amount}, Is Deposit {is_deposit}")
        
        if payment_amount <= 0:
            return JsonResponse({'success': False, 'message': 'Invalid payment amount.'})
        
        # Update payment amounts — guard against overpayment
        new_total = event.amount_paid + payment_amount
        if new_total > event.total_amount:
            return JsonResponse({
                'success': False,
                'message': f'Payment would exceed total event cost ({event.total_amount}).'
            })
        event.amount_paid = new_total
        
        if is_deposit and event.deposit_amount == 0:
            event.deposit_amount = payment_amount
        
        event.save()  # This will auto-update payment_status
        
        logger.info(f"Payment recorded successfully: Event {event_id}, New total {event.amount_paid}, Status {event.payment_status}")
        
        return JsonResponse({
            'success': True,
            'message': f'Payment of {payment_amount} recorded successfully!',
            'amount_paid': str(event.amount_paid),
            'balance_due': str(event.balance_due),
            'payment_status': event.payment_status,
            'payment_status_display': event.get_payment_status_display(),
            'payment_status_color': event.get_payment_status_color()
        })
    except Event.DoesNotExist:
        logger.error(f"Event {event_id} not found")
        return JsonResponse({'success': False, 'message': 'Event not found.'})
    except (ValueError, TypeError) as e:
        logger.error(f"Payment error: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid payment amount. Please enter a valid number.'})
    except Exception as e:
        logger.error(f"Unexpected error recording payment: {str(e)}")
        return JsonResponse({'success': False, 'message': 'An error occurred while recording the payment.'}, status=500)


@login_required
def approve_event_payment(request, event_id):
    """Approve/confirm an event payment"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    try:
        event = Event.objects.get(id=event_id, owner=owner_filter)
        
        # Check if there's amount to approve (payment_status should be deposit_paid or partially_paid)
        if event.amount_paid > 0:
            # If amount paid equals total amount, mark as fully paid
            if event.amount_paid >= event.total_amount:
                event.payment_status = 'fully_paid'
            else:
                event.payment_status = 'partially_paid'
            
            event.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Payment approved successfully!',
                'payment_status': event.payment_status,
                'payment_status_display': event.get_payment_status_display()
            })
        else:
            return JsonResponse({'success': False, 'message': 'No payment recorded for this event.'})
    
    except Event.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Event not found.'})
    except Exception as e:
        logger.error(f"Error approving event payment: {str(e)}")
        return JsonResponse({'success': False, 'message': 'An error occurred while approving the payment.'}, status=500)


@login_required
def export_events_csv(request):
    """Export events to CSV"""
    import csv
    from django.http import HttpResponse
    
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        return HttpResponse('Access denied', status=403)
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    # Get restaurant for currency
    from .models_restaurant import Restaurant
    from django.db.models import Q as DBQ
    restaurant = Restaurant.objects.filter(
        DBQ(main_owner=owner_filter) | DBQ(branch_owner=request.user)
    ).first()
    currency_symbol = restaurant.get_currency_symbol() if restaurant else '$'
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    event_type_filter = request.GET.get('event_type', '')
    date_filter = request.GET.get('date_filter', 'all')
    search_query = request.GET.get('search', '')
    
    # Base queryset
    events = Event.objects.filter(owner=owner_filter)
    
    # Apply filters
    if status_filter:
        events = events.filter(status=status_filter)
    
    if event_type_filter:
        events = events.filter(event_type=event_type_filter)
    
    if search_query:
        events = events.filter(
            Q(title__icontains=search_query) |
            Q(contact_name__icontains=search_query) |
            Q(contact_phone__icontains=search_query)
        )
    
    # Date filters
    from django.utils.timezone import localtime
    today = localtime(timezone.now()).date()
    if date_filter == 'today':
        events = events.filter(event_date=today)
    elif date_filter == 'week':
        week_end = today + timedelta(days=7)
        events = events.filter(event_date__gte=today, event_date__lte=week_end)
    elif date_filter == 'month':
        month_end = today + timedelta(days=30)
        events = events.filter(event_date__gte=today, event_date__lte=month_end)
    elif date_filter == 'upcoming':
        events = events.filter(event_date__gte=today).exclude(status__in=['completed', 'cancelled'])
    elif date_filter == 'past':
        events = events.filter(event_date__lt=today)
    
    events = events.order_by('-event_date', '-start_time')
    
    # Calculate summary statistics
    all_filtered_events = events
    fully_paid = all_filtered_events.filter(payment_status='fully_paid')
    unpaid_only = all_filtered_events.filter(payment_status='unpaid').exclude(status='cancelled')
    
    paid_amount = fully_paid.aggregate(total=Sum('amount_paid'))['total'] or 0
    unpaid_amount = sum(event.price_per_pax * event.total_pax for event in unpaid_only)
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="events_export_{today.strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Event Date', 'Start Time', 'End Time', 'Event Title', 'Event Type',
        'Total PAX', 'Price per PAX', 'Total Amount', 'Amount Paid', 'Balance Due',
        'Contact Name', 'Contact Phone', 'Contact Email', 'Status', 'Payment Status',
        'Description', 'Created At'
    ])
    
    for event in events:
        writer.writerow([
            event.event_date.strftime('%Y-%m-%d'),
            event.start_time.strftime('%H:%M') if event.start_time else '',
            event.end_time.strftime('%H:%M') if event.end_time else '',
            _safe_csv(event.title),
            event.get_event_type_display(),
            event.total_pax,
            f'{currency_symbol}{event.price_per_pax}',
            f'{currency_symbol}{event.total_amount}',
            f'{currency_symbol}{event.amount_paid}',
            f'{currency_symbol}{event.balance_due}',
            _safe_csv(event.contact_name),
            _safe_csv(event.contact_phone),
            _safe_csv(event.contact_email or ''),
            event.get_status_display(),
            event.get_payment_status_display(),
            _safe_csv(event.description or ''),
            event.created_at.strftime('%Y-%m-%d %H:%M')
        ])
    
    # Add summary rows
    writer.writerow([])  # Empty row
    writer.writerow(['SUMMARY'])
    writer.writerow(['Total Events:', events.count()])
    writer.writerow(['Fully Paid Events:', fully_paid.count(), f'{currency_symbol}{paid_amount:.2f}'])
    writer.writerow(['Unpaid Events:', unpaid_only.count(), f'{currency_symbol}{unpaid_amount:.2f}'])
    writer.writerow(['Total Revenue (Paid + Unpaid):', '', f'{currency_symbol}{(paid_amount + unpaid_amount):.2f}'])
    
    return response


@login_required
def export_events_pdf(request):
    """Export events to PDF"""
    from django.http import HttpResponse
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from io import BytesIO
    
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner() or request.user.is_manager()):
        return HttpResponse('Access denied', status=403)
    
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    # Get restaurant for currency and name
    from .models_restaurant import Restaurant
    from django.db.models import Q as DBQ
    restaurant = Restaurant.objects.filter(
        DBQ(main_owner=owner_filter) | DBQ(branch_owner=request.user)
    ).first()
    currency_symbol = restaurant.get_currency_symbol() if restaurant else '$'
    restaurant_name = restaurant.name if restaurant else 'Restaurant'
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    event_type_filter = request.GET.get('event_type', '')
    date_filter = request.GET.get('date_filter', 'all')
    search_query = request.GET.get('search', '')
    
    # Base queryset
    events = Event.objects.filter(owner=owner_filter)
    
    # Apply filters
    if status_filter:
        events = events.filter(status=status_filter)
    
    if event_type_filter:
        events = events.filter(event_type=event_type_filter)
    
    if search_query:
        events = events.filter(
            Q(title__icontains=search_query) |
            Q(contact_name__icontains=search_query) |
            Q(contact_phone__icontains=search_query)
        )
    
    # Date filters
    from django.utils.timezone import localtime
    today = localtime(timezone.now()).date()
    if date_filter == 'today':
        events = events.filter(event_date=today)
    elif date_filter == 'week':
        week_end = today + timedelta(days=7)
        events = events.filter(event_date__gte=today, event_date__lte=week_end)
    elif date_filter == 'month':
        month_end = today + timedelta(days=30)
        events = events.filter(event_date__gte=today, event_date__lte=month_end)
    elif date_filter == 'upcoming':
        events = events.filter(event_date__gte=today).exclude(status__in=['completed', 'cancelled'])
    elif date_filter == 'past':
        events = events.filter(event_date__lt=today)
    
    events = events.order_by('-event_date', '-start_time')
    
    # Calculate summary statistics
    all_filtered_events = events
    fully_paid = all_filtered_events.filter(payment_status='fully_paid')
    unpaid_only = all_filtered_events.filter(payment_status='unpaid').exclude(status='cancelled')
    
    paid_amount = fully_paid.aggregate(total=Sum('amount_paid'))['total'] or 0
    unpaid_amount = sum(event.price_per_pax * event.total_pax for event in unpaid_only)
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=12,
        alignment=1  # Center
    )
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=20,
        alignment=1,
        textColor=colors.gray
    )
    
    # Title
    elements.append(Paragraph(f"{restaurant_name} - Events Report", title_style))
    
    # Filter info
    filter_info = f"Generated on: {today.strftime('%B %d, %Y')}"
    if date_filter != 'all':
        filter_info += f" | Period: {date_filter.title()}"
    if status_filter:
        filter_info += f" | Status: {status_filter.title()}"
    if event_type_filter:
        filter_info += f" | Type: {event_type_filter.replace('_', ' ').title()}"
    elements.append(Paragraph(filter_info, subtitle_style))
    
    # Table data
    table_data = [['Date', 'Event', 'Type', 'PAX', 'Total', 'Paid', 'Balance', 'Contact', 'Status']]
    
    total_revenue = 0
    total_paid = 0
    total_pax = 0
    
    for event in events:
        table_data.append([
            event.event_date.strftime('%m/%d/%Y'),
            event.title[:25] + '...' if len(event.title) > 25 else event.title,
            event.get_event_type_display()[:12],
            str(event.total_pax),
            f'{currency_symbol}{event.total_amount:.2f}',
            f'{currency_symbol}{event.amount_paid:.2f}',
            f'{currency_symbol}{event.balance_due:.2f}',
            event.contact_name[:15] + '...' if len(event.contact_name) > 15 else event.contact_name,
            event.get_status_display()
        ])
        total_revenue += event.total_amount
        total_paid += event.amount_paid
        total_pax += event.total_pax
    
    # Add totals row
    if events:
        table_data.append([
            'TOTAL', '', '', str(total_pax),
            f'{currency_symbol}{total_revenue:.2f}',
            f'{currency_symbol}{total_paid:.2f}',
            f'{currency_symbol}{total_revenue - total_paid:.2f}',
            '', ''
        ])
    
    # Create table
    if len(table_data) > 1:
        table = Table(table_data, colWidths=[0.9*inch, 1.8*inch, 1*inch, 0.5*inch, 0.9*inch, 0.9*inch, 0.9*inch, 1.2*inch, 0.9*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -2), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f8f9fc')]),
            # Total row styling
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8eaf6')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No events found matching the criteria.", styles['Normal']))
    
    # Summary
    elements.append(Spacer(1, 0.3*inch))
    summary_text = f"Total Events: {events.count()} | Total PAX: {total_pax} | Total Revenue: {currency_symbol}{total_revenue:.2f} | Collected: {currency_symbol}{total_paid:.2f}"
    elements.append(Paragraph(summary_text, subtitle_style))
    
    # Add Paid/Unpaid breakdown
    elements.append(Spacer(1, 0.15*inch))
    breakdown_style = ParagraphStyle(
        'Breakdown',
        parent=styles['Normal'],
        fontSize=10,
        alignment=1,
        textColor=colors.HexColor('#1e3a5f')
    )
    breakdown_text = f"<b>Fully Paid:</b> {fully_paid.count()} events ({currency_symbol}{paid_amount:.2f}) | <b>Unpaid:</b> {unpaid_only.count()} events ({currency_symbol}{unpaid_amount:.2f})"
    elements.append(Paragraph(breakdown_text, breakdown_style))
    
    doc.build(elements)
    
    # Return response
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="events_report_{today.strftime("%Y%m%d")}.pdf"'
    
    return response


