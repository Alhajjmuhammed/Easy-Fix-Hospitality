from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, Prefetch
from django.http import JsonResponse
from django.core.paginator import Paginator
from .models import MainCategory, SubCategory, Product, TableInfo, HappyHourPromotion, Restaurant
from .forms import ProductForm, MainCategoryForm, SubCategoryForm, TableForm, StaffForm, HappyHourPromotionForm
from orders.models import Order
from accounts.models import User, Role

def home(request):
    return render(request, 'restaurant/home.html')

def menu(request):
    """Display menu with cart functionality"""
    # Initialize logger at the start
    import logging
    logger = logging.getLogger(__name__)
    
    # Check if table is selected
    if 'selected_table' not in request.session:
        messages.warning(request, 'Please select your table number first.')
        return redirect('orders:select_table')

    table_number = request.session['selected_table']
    
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
        
        # DEBUG LOGGING
        logger.debug(f"[MENU DEBUG] current_restaurant: {current_restaurant.username} (ID: {current_restaurant.id})")
        
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
            
            # DEBUG LOGGING
            if restaurant_obj:
                logger.debug(f"[MENU DEBUG] Found restaurant_obj: {restaurant_obj.name} (is_main: {restaurant_obj.is_main_restaurant})")
        except Exception as e:
            # DEBUG LOGGING
            logger.debug(f"[MENU DEBUG] Exception finding restaurant_obj: {e}")
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
            
            # DEBUG LOGGING
            logger.debug(f"[MENU DEBUG] Categories count: {categories.count()}")
            for cat in categories[:10]:  # Log first 10
                cat_owner = cat.owner.username if cat.owner else 'None'
                cat_restaurant = cat.restaurant.name if cat.restaurant else 'None'
                logger.debug(f"[MENU DEBUG]   - {cat.name} (owner={cat_owner}, restaurant={cat_restaurant})")
            
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
        # DEBUG LOGGING
        logger.debug(f"[MENU DEBUG] current_restaurant is None! User: {request.user}, Session: {request.session.get('selected_restaurant_id')}")
        
        # Fallback: try traditional owner filtering for staff/tied customers
        try:
            from accounts.models import get_owner_filter
            owner_filter = get_owner_filter(request.user)
            if owner_filter:
                categories = MainCategory.objects.filter(
                    is_active=True, 
                    owner=owner_filter
                ).prefetch_related('subcategories__products').order_by('name')
                restaurant_name = owner_filter.restaurant_name
            else:
                # NO FILTERING - This is the bug! Redirect to table selection
                logger.debug(f"[MENU DEBUG] No owner_filter! Redirecting to table selection")
                messages.error(request, 'Please select your restaurant and table first.')
                return redirect('orders:select_table')
        except Exception as e:
            # DEBUG LOGGING
            logger.debug(f"[MENU DEBUG] Exception in fallback: {e}")
            messages.error(request, 'Unable to load menu. Please try again.')
            return redirect('orders:select_table')
    
    # Safety check - if we somehow got here without categories
    if 'categories' not in locals():
        logger.debug(f"[MENU DEBUG] No categories variable defined!")
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

    # FINAL DEBUG: Log what's being passed to template
    logger.debug(f"[MENU DEBUG] Passing {categories.count()} categories to template:")
    for cat in categories:
        cat_owner = cat.owner.username if cat.owner else 'None'
        cat_restaurant = cat.restaurant.name if cat.restaurant else 'None'
        logger.debug(f"[MENU DEBUG]   Template will show: {cat.name} (owner={cat_owner}, restaurant={cat_restaurant})")
    
    context = {
        'categories': categories,
        'table_number': table_number,
        'cart': cart,
        'cart_count': cart_count,
        'cart_total': cart_total,
        'restaurant_name': restaurant_name,
        'current_restaurant': current_restaurant,
    }

    return render(request, 'restaurant/menu.html', context)

@login_required
def owner_dashboard(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get owner filter for data isolation
    from accounts.models import get_owner_filter
    try:
        owner_filter = get_owner_filter(request.user)
        
        # Dashboard statistics - filtered by owner
        if owner_filter:
            total_products = Product.objects.filter(main_category__owner=owner_filter).count()
            total_orders = Order.objects.filter(table_info__owner=owner_filter).count()
            pending_orders = Order.objects.filter(status='pending', table_info__owner=owner_filter).count()
            total_staff = User.objects.filter(owner=owner_filter).exclude(role__name='customer').count()
            
            # Recent orders - filtered by owner
            recent_orders = Order.objects.filter(
                table_info__owner=owner_filter
            ).select_related('table_info', 'ordered_by').order_by('-created_at')[:5]
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
    
    # Popular products
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
def manage_products(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get products with owner filtering
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    if owner_filter:
        products = Product.objects.filter(main_category__owner=owner_filter).select_related('main_category', 'sub_category').order_by('-created_at')
    else:
        products = Product.objects.select_related('main_category', 'sub_category').order_by('-created_at')
    
    return render(request, 'restaurant/manage_products.html', {'products': products})

@login_required
def add_product(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get owner filter for form
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, owner=owner_filter)
        if form.is_valid():
            product = form.save(commit=False)
            # Verify the main category belongs to this owner
            if owner_filter and product.main_category.owner != owner_filter:
                messages.error(request, 'Access denied. Category not found.')
                return redirect('restaurant:manage_products')
            product.save()
            messages.success(request, 'Product added successfully!')
            return redirect('restaurant:manage_products')
    else:
        form = ProductForm(owner=owner_filter)
    
    return render(request, 'restaurant/add_product.html', {'form': form})

@login_required
def edit_product(request, product_id):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get product with owner filtering
    from accounts.models import get_owner_filter
    try:
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            product = get_object_or_404(Product, id=product_id, main_category__owner=owner_filter)
        else:
            product = get_object_or_404(Product, id=product_id)
    except Exception:
        messages.error(request, 'Product not found or access denied.')
        return redirect('restaurant:manage_products')
    
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product, owner=owner_filter)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated successfully!')
            return redirect('restaurant:manage_products')
    else:
        form = ProductForm(instance=product, owner=owner_filter)
    
    return render(request, 'restaurant/edit_product.html', {'form': form, 'product': product})

@login_required
def delete_product(request, product_id):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get product with owner filtering
    from accounts.models import get_owner_filter
    try:
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            product = get_object_or_404(Product, id=product_id, main_category__owner=owner_filter)
        else:
            product = get_object_or_404(Product, id=product_id)
    except Exception:
        messages.error(request, 'Product not found or access denied.')
        return redirect('restaurant:manage_products')
    
    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Product deleted successfully!')
        return redirect('restaurant:manage_products')
    
    return render(request, 'restaurant/delete_product.html', {'product': product})

@login_required
def manage_categories(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get categories with owner filtering
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    if owner_filter:
        main_categories = MainCategory.objects.filter(owner=owner_filter).prefetch_related('subcategories').order_by('name')
    else:
        main_categories = MainCategory.objects.prefetch_related('subcategories').order_by('name')
    
    return render(request, 'restaurant/manage_categories.html', {'main_categories': main_categories})

@login_required
def add_category(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    if request.method == 'POST':
        form = MainCategoryForm(request.POST)
        if form.is_valid():
            # Set owner before saving
            from accounts.models import get_owner_filter
            owner_filter = get_owner_filter(request.user)
            category = form.save(commit=False)
            if owner_filter:
                category.owner = owner_filter
            category.save()
            messages.success(request, 'Category added successfully!')
            return redirect('restaurant:manage_categories')
    else:
        form = MainCategoryForm()
    
    return render(request, 'restaurant/add_category.html', {'form': form})

@login_required
def add_subcategory(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    if request.method == 'POST':
        form = SubCategoryForm(request.POST)
        if form.is_valid():
            # Verify the main category belongs to this owner
            from accounts.models import get_owner_filter
            owner_filter = get_owner_filter(request.user)
            subcategory = form.save(commit=False)
            
            if owner_filter and subcategory.main_category.owner != owner_filter:
                messages.error(request, 'Access denied. Category not found.')
                return redirect('restaurant:manage_categories')
            
            subcategory.save()
            messages.success(request, 'Subcategory added successfully!')
            return redirect('restaurant:manage_categories')
    else:
        form = SubCategoryForm()
        # Filter main categories by owner
        from accounts.models import get_owner_filter
        owner_filter = get_owner_filter(request.user)
        if owner_filter:
            form.fields['main_category'].queryset = MainCategory.objects.filter(owner=owner_filter)
    
    return render(request, 'restaurant/add_subcategory.html', {'form': form})

@login_required
def manage_staff(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
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
def add_staff(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
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
                
                # Validate role (owner can only add kitchen and customer_care)
                allowed_roles = ['kitchen', 'customer_care']
                if data['role'] not in allowed_roles:
                    return JsonResponse({'success': False, 'message': 'Invalid role. Owner can only add Kitchen Staff or Customer Care.'})
                
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
        form = StaffForm()
    
    return render(request, 'restaurant/add_staff.html', {'form': form})

@login_required
def view_orders(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    status_filter = request.GET.get('status', 'all')
    
    # Get orders with owner filtering
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    if owner_filter:
        orders = Order.objects.filter(table_info__owner=owner_filter).select_related('table_info', 'ordered_by', 'confirmed_by').order_by('-created_at')
    else:
        orders = Order.objects.select_related('table_info', 'ordered_by', 'confirmed_by').order_by('-created_at')
    
    if status_filter != 'all':
        orders = orders.filter(status=status_filter)
    
    context = {
        'orders': orders,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,
    }
    
    return render(request, 'restaurant/view_orders.html', context)

@login_required
def manage_tables(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    # Get tables with owner filtering
    from accounts.models import get_owner_filter
    owner_filter = get_owner_filter(request.user)
    if owner_filter:
        tables = TableInfo.objects.filter(owner=owner_filter).order_by('tbl_no')
    else:
        tables = TableInfo.objects.order_by('tbl_no')
    
    return render(request, 'restaurant/manage_tables.html', {'tables': tables})

@login_required
def add_table(request):
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        messages.error(request, 'Access denied. Owner privileges required.')
        return redirect('restaurant:home')
    
    if request.method == 'POST':
        form = TableForm(request.POST)
        if form.is_valid():
            # Set owner before saving
            from accounts.models import get_owner_filter
            owner_filter = get_owner_filter(request.user)
            table = form.save(commit=False)
            if owner_filter:
                table.owner = owner_filter
            table.save()
            messages.success(request, 'Table added successfully!')
            return redirect('restaurant:manage_tables')
    else:
        form = TableForm()
    
    return render(request, 'restaurant/add_table.html', {'form': form})


# Happy Hour Management Views
@login_required
def manage_promotions(request):
    """View all Happy Hour promotions for the current owner"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
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
    
    # Calculate real-time statistics for dashboard
    total_promotions = promotions.count()
    active_promotions = promotions.filter(is_active=True).count()
    currently_running = len([p for p in promotions if p.is_currently_active()])
    
    # Pagination
    try:
        per_page = int(request.GET.get('per_page', 5))
    except (ValueError, TypeError):
        per_page = 5
    paginator = Paginator(promotions, per_page)
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
def add_promotion(request):
    """Add a new Happy Hour promotion"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
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
def edit_promotion(request, promotion_id):
    """Edit an existing Happy Hour promotion"""
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
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
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
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
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    try:
        restaurant_id = request.GET.get('restaurant_id')
        
        if not restaurant_id:
            return JsonResponse({'success': False, 'message': 'Restaurant ID required'})
        
        # Import Restaurant model
        from restaurant.models import Restaurant
        
        # Get restaurant and determine owner
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        
        if restaurant.is_main_restaurant:
            owner = restaurant.main_owner
        else:
            owner = restaurant.branch_owner or restaurant.main_owner
        
        # Get products, main categories, and subcategories for this owner
        products = Product.objects.filter(main_category__owner=owner).values('id', 'name')
        main_categories = MainCategory.objects.filter(owner=owner).values('id', 'name')
        sub_categories = SubCategory.objects.filter(main_category__owner=owner).values('id', 'name')
        
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
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
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
    if not (request.user.is_owner() or request.user.is_main_owner() or request.user.is_branch_owner()):
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
        main_category__owner=owner_filter
    ).distinct().select_related('main_category', 'sub_category')
    
    context = {
        'promotion': promotion,
        'affected_products': affected_products,
        'affected_count': affected_products.count(),
    }
    
    return render(request, 'restaurant/promotion_preview.html', context)
