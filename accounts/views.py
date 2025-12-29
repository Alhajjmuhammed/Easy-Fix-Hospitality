from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from decimal import Decimal
import json
import logging
from .forms import UserRegistrationForm, UserLoginForm, OwnerRegistrationForm, CustomerRegistrationForm
from .models import Role, User

logger = logging.getLogger(__name__)

# Import security decorators
try:
    from restaurant_system.security_decorators import rate_limit_login, rate_limit_registration
    RATE_LIMITING_ENABLED = True
except ImportError:
    # Fallback if django-ratelimit not installed
    RATE_LIMITING_ENABLED = False
    def rate_limit_login(func):
        return func
    def rate_limit_registration(func):
        return func

@ensure_csrf_cookie
@rate_limit_login
def login_view(request):
    if request.user.is_authenticated:
        return redirect('restaurant:home')
    
    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                login(request, user)
                
                # Log successful login
                try:
                    from .security_utils import log_security_event
                    log_security_event(
                        request, 'login', user,
                        description=f"User '{user.username}' logged in successfully",
                        extra_data={'role': user.role.name if user.role else 'no_role'}
                    )
                except Exception as e:
                    logger.warning(f"Failed to log login event: {e}")
                
                messages.success(request, f'Welcome back, {user.first_name or user.username}!')
                
                # Role-based redirect
                if user.is_administrator():
                    return redirect('system_admin:dashboard')  # Redirect admins to system dashboard
                elif user.is_owner():
                    return redirect('admin_panel:admin_dashboard')  # Owners now use admin panel
                elif user.is_kitchen_staff():
                    return redirect('orders:kitchen_dashboard')
                elif user.is_customer_care():
                    return redirect('orders:customer_care_dashboard')
                elif user.is_cashier():
                    return redirect('cashier:dashboard')
                else:
                    return redirect('restaurant:menu')
            else:
                # Log failed login attempt
                try:
                    from .security_utils import log_security_event
                    log_security_event(
                        request, 'login_failed', None,
                        description=f"Failed login attempt for username: {username}",
                        extra_data={'attempted_username': username}
                    )
                except Exception as e:
                    logger.warning(f"Failed to log login failure: {e}")
                
                # Add error to form instead of messages
                form.add_error(None, 'Invalid username or password.')
    else:
        form = UserLoginForm()
    
    return render(request, 'accounts/login.html', {'form': form})

@require_POST
def logout_view(request):
    """Logout view - requires POST to prevent CSRF logout attacks"""
    # Log logout event before clearing session
    try:
        if request.user.is_authenticated:
            from .security_utils import log_security_event
            log_security_event(
                request, 'logout', request.user,
                description=f"User '{request.user.username}' logged out"
            )
    except Exception as e:
        logger.warning(f"Failed to log logout event: {e}")
    
    # Clear cart and session data before logout
    if 'cart' in request.session:
        del request.session['cart']
    if 'selected_table' in request.session:
        del request.session['selected_table']
    if 'selected_restaurant_id' in request.session:
        del request.session['selected_restaurant_id']
    if 'selected_restaurant_name' in request.session:
        del request.session['selected_restaurant_name']
    
    logout(request)
    messages.success(request, 'You have been logged out successfully. Your cart has been cleared.')
    return redirect('accounts:login')

@rate_limit_registration
def register_view(request):
    # Redirect already authenticated users
    if request.user.is_authenticated:
        messages.info(request, 'You are already logged in.')
        return redirect('restaurant:home')
        
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            
            # Set default role as customer
            from .models import Role
            customer_role, created = Role.objects.get_or_create(
                name='customer',
                defaults={'description': 'Customer'}
            )
            user.role = customer_role
            user.owner = None  # Customers don't have an owner initially
            user.save()
            
            messages.success(request, 'Registration successful! You can now log in.')
            return redirect('accounts:login')
    else:
        form = UserRegistrationForm()
    
    return render(request, 'accounts/register.html', {'form': form})


@rate_limit_registration
def register_owner_view(request):
    """Separate registration for restaurant owners"""
    # Redirect already authenticated users
    if request.user.is_authenticated:
        messages.info(request, 'You are already logged in.')
        return redirect('restaurant:home')
        
    if request.method == 'POST':
        form = OwnerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            
            # Set role as owner
            owner_role, created = Role.objects.get_or_create(
                name='owner',
                defaults={'description': 'Restaurant Owner'}
            )
            user.role = owner_role
            user.owner = None  # Owners don't have an owner
            user.save()
            
            messages.success(request, f'Owner registration successful for {user.restaurant_name}! You can now log in.')
            return redirect('accounts:login')
    else:
        form = OwnerRegistrationForm()
    
    return render(request, 'accounts/register_owner.html', {'form': form})

@login_required
def profile_view(request):
    """Role-based profile view"""
    user = request.user
    
    # Get user's recent orders for customer care profiles only
    recent_orders = []
    if user.is_customer_care():
        from orders.models import Order
        recent_orders = Order.objects.filter(ordered_by=user).order_by('-created_at')[:5]
    
    # Get staff management data for owner/admin
    staff_users = []
    if user.is_owner() or user.is_administrator():
        staff_users = User.objects.filter(role__name__in=['customer_care', 'kitchen']).select_related('role')
    
    context = {
        'user': user,
        'recent_orders': recent_orders,
        'staff_users': staff_users,
        'restaurant_name': user.get_restaurant_name(request) if user.is_customer() else None,
    }
    
    # Role-based template selection
    if user.is_administrator():
        template = 'accounts/profile_admin.html'
    elif user.is_owner():
        template = 'accounts/profile_owner.html'
    elif user.is_customer_care():
        template = 'accounts/profile_customer_care.html'
    elif user.is_kitchen_staff():
        template = 'accounts/profile_kitchen.html'
    elif user.is_cashier():
        template = 'accounts/profile_cashier.html'
    else:  # customer
        template = 'accounts/profile_customer.html'
    
    return render(request, template, context)

def qr_code_access(request, qr_code):
    """Handle QR code access to restaurant"""
    try:
        # Clean the QR code - remove any trailing slashes or whitespace
        qr_code = qr_code.strip().rstrip('/')
        
        # First try to find restaurant by QR code in Restaurant model (new system)
        from restaurant.models_restaurant import Restaurant
        restaurant_obj = None
        user_restaurant = None
        
        try:
            restaurant_obj = Restaurant.objects.get(qr_code=qr_code)
            # Get the associated user (main_owner or branch_owner)
            # For branches, use branch_owner; for main restaurants, use main_owner
            user_restaurant = restaurant_obj.main_owner if restaurant_obj.is_main_restaurant else restaurant_obj.branch_owner
        except Restaurant.DoesNotExist:
            # Fallback: try to find in User model (legacy system)
            try:
                user_restaurant = User.objects.get(
                    restaurant_qr_code=qr_code, 
                    role__name__in=['owner', 'main_owner', 'branch_owner'], 
                    is_active=True
                )
                # Try to get the corresponding Restaurant object
                # Check if branch owner first, then main owner
                try:
                    if user_restaurant.is_branch_owner():
                        restaurant_obj = Restaurant.objects.get(branch_owner=user_restaurant, is_main_restaurant=False)
                    else:
                        restaurant_obj = Restaurant.objects.get(main_owner=user_restaurant, is_main_restaurant=True)
                except Restaurant.DoesNotExist:
                    # Legacy user without Restaurant object - create minimal context
                    restaurant_obj = None
            except User.DoesNotExist:
                raise User.DoesNotExist("QR code not found in either system")
        
        # Ensure we have a valid user
        if not user_restaurant or not user_restaurant.is_active:
            raise User.DoesNotExist("Restaurant owner not found or inactive")
        
        # For compatibility, set restaurant variable to user_restaurant for legacy code
        restaurant = user_restaurant
        
        # Check if restaurant subscription is active
        # For branches (PRO plan), check the MAIN owner's subscription
        from accounts.models import RestaurantSubscription
        
        # Determine which owner's subscription to check
        subscription_owner = restaurant
        if restaurant_obj and not restaurant_obj.is_main_restaurant:
            # This is a branch - check the main owner's subscription (PRO plan cascade)
            subscription_owner = restaurant_obj.main_owner
        
        try:
            subscription = RestaurantSubscription.objects.get(restaurant_owner=subscription_owner)
            if not subscription.is_active:
                # Restaurant is blocked - show unavailable message
                reason = "This restaurant is temporarily unavailable."
                if subscription.is_blocked_by_admin:
                    reason = "This restaurant is temporarily suspended. Please contact the restaurant for more information."
                elif subscription.subscription_status == 'expired':
                    reason = "This restaurant is temporarily unavailable due to expired subscription."
                
                from django.utils import timezone
                # Get display name for branches
                display_name = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
                if restaurant_obj and not restaurant_obj.is_main_restaurant and restaurant_obj.parent_restaurant:
                    display_name = restaurant_obj.parent_restaurant.name
                
                return render(request, 'accounts/restaurant_unavailable.html', {
                    'restaurant': restaurant,
                    'restaurant_obj': restaurant_obj,  # Pass Restaurant object if available
                    'qr_code': qr_code,
                    'reason': reason,
                    'subscription_status': subscription.subscription_status,
                    'current_time': timezone.now(),
                    'display_name': display_name
                })
        except RestaurantSubscription.DoesNotExist:
            # No subscription - restaurant unavailable
            from django.utils import timezone
            # Get display name for branches
            display_name = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
            if restaurant_obj and not restaurant_obj.is_main_restaurant and restaurant_obj.parent_restaurant:
                display_name = restaurant_obj.parent_restaurant.name
            
            return render(request, 'accounts/restaurant_unavailable.html', {
                'restaurant': restaurant,
                'restaurant_obj': restaurant_obj,  # Pass Restaurant object if available
                'qr_code': qr_code,
                'reason': "This restaurant is temporarily unavailable.",
                'subscription_status': 'no_subscription',
                'current_time': timezone.now(),
                'display_name': display_name
            })
        
        # Store restaurant in session - ALWAYS use User ID (owner)
        # select_table expects User.objects.get(id=selected_restaurant_id)
        # restaurant = user_restaurant (always a User object)
        request.session['selected_restaurant_id'] = restaurant.id  # User ID
        request.session['selected_restaurant_name'] = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
        request.session['access_method'] = 'qr_code'
        
        # If user is not logged in, show restaurant info and prompt for login/register
        if not request.user.is_authenticated:
            # Get the display name - for branches, show main restaurant name
            display_name = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
            if restaurant_obj and not restaurant_obj.is_main_restaurant and restaurant_obj.parent_restaurant:
                display_name = restaurant_obj.parent_restaurant.name
            
            return render(request, 'accounts/qr_restaurant_access.html', {
                'restaurant': restaurant,
                'restaurant_obj': restaurant_obj,  # Pass Restaurant object if available
                'qr_code': qr_code,
                'display_name': display_name
            })
        
        # If user is already logged in as customer, switch restaurant context and continue
        if request.user.is_customer():
            restaurant_name = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
            messages.success(request, f'Welcome to {restaurant_name}!')
            return redirect('orders:select_table')
        
        # If user is staff of this restaurant, redirect to appropriate dashboard
        if request.user.get_owner() == restaurant:
            if request.user.is_kitchen_staff():
                return redirect('orders:kitchen_dashboard')
            elif request.user.is_cashier():
                return redirect('cashier:dashboard')
            elif request.user.is_owner():
                return redirect('admin_panel:admin_dashboard')
        
        # Default: redirect to menu
        restaurant_name = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
        messages.success(request, f'Welcome to {restaurant_name}!')
        return redirect('restaurant:menu')
        
    except User.DoesNotExist:
        # Log the QR code that failed for debugging
        logger.warning(f"QR Code Access Failed: '{qr_code}'")
        messages.error(request, f'Invalid QR code. Restaurant not found. (Code: {qr_code})')
        return redirect('accounts:login')


def customer_register_view(request, qr_code):
    """Customer registration specifically for QR code access"""
    try:
        # Clean the QR code
        qr_code = qr_code.strip().rstrip('/')
        
        # First try to find restaurant by QR code in Restaurant model (new system)
        from restaurant.models_restaurant import Restaurant
        restaurant_obj = None
        user_restaurant = None
        
        try:
            restaurant_obj = Restaurant.objects.get(qr_code=qr_code)
            # Get the associated user (main_owner or branch_owner)
            # For branches, use branch_owner; for main restaurants, use main_owner
            user_restaurant = restaurant_obj.main_owner if restaurant_obj.is_main_restaurant else restaurant_obj.branch_owner
        except Restaurant.DoesNotExist:
            # Fallback: try to find in User model (legacy system)
            user_restaurant = User.objects.get(
                restaurant_qr_code=qr_code,
                role__name__in=['owner', 'main_owner', 'branch_owner'],
                is_active=True
            )
            # Try to get the corresponding Restaurant object
            try:
                if user_restaurant.is_branch_owner():
                    restaurant_obj = Restaurant.objects.get(branch_owner=user_restaurant, is_main_restaurant=False)
                else:
                    restaurant_obj = Restaurant.objects.get(main_owner=user_restaurant, is_main_restaurant=True)
            except Restaurant.DoesNotExist:
                restaurant_obj = None
        
        # For compatibility, set restaurant variable to user_restaurant for legacy code
        restaurant = user_restaurant
        
        # Check if restaurant subscription is active before allowing registration
        # For branches (PRO plan), check the MAIN owner's subscription
        from accounts.models import RestaurantSubscription
        
        # Determine which owner's subscription to check
        subscription_owner = restaurant
        if restaurant_obj and not restaurant_obj.is_main_restaurant:
            # This is a branch - check the main owner's subscription (PRO plan cascade)
            subscription_owner = restaurant_obj.main_owner
        
        try:
            subscription = RestaurantSubscription.objects.get(restaurant_owner=subscription_owner)
            if not subscription.is_active:
                # Restaurant is blocked - show unavailable message instead of registration
                reason = "This restaurant is temporarily unavailable for new registrations."
                if subscription.is_blocked_by_admin:
                    reason = "This restaurant is temporarily suspended. New registrations are not available."
                elif subscription.subscription_status == 'expired':
                    reason = "This restaurant is temporarily unavailable due to expired subscription."
                
                from django.utils import timezone
                # Get display name for branches
                display_name = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
                if restaurant_obj and not restaurant_obj.is_main_restaurant and restaurant_obj.parent_restaurant:
                    display_name = restaurant_obj.parent_restaurant.name
                
                return render(request, 'accounts/restaurant_unavailable.html', {
                    'restaurant': restaurant,
                    'qr_code': qr_code,
                    'reason': reason,
                    'subscription_status': subscription.subscription_status,
                    'current_time': timezone.now(),
                    'display_name': display_name
                })
        except RestaurantSubscription.DoesNotExist:
            # No subscription - registration not available
            from django.utils import timezone
            # Get display name for branches
            display_name = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
            if restaurant_obj and not restaurant_obj.is_main_restaurant and restaurant_obj.parent_restaurant:
                display_name = restaurant_obj.parent_restaurant.name
            
            return render(request, 'accounts/restaurant_unavailable.html', {
                'restaurant': restaurant,
                'qr_code': qr_code,
                'reason': "This restaurant is temporarily unavailable for new registrations.",
                'subscription_status': 'no_subscription',
                'current_time': timezone.now(),
                'display_name': display_name
            })
        
        if request.method == 'POST':
            form = CustomerRegistrationForm(request.POST)
            if form.is_valid():
                user = form.save(commit=False)
                user.set_password(form.cleaned_data['password'])
                
                # Set as customer role
                customer_role, created = Role.objects.get_or_create(
                    name='customer',
                    defaults={'description': 'Customer'}
                )
                user.role = customer_role
                user.owner = None  # Universal customer - not tied to specific restaurant
                user.save()
                
                # Auto-login the user
                user = authenticate(
                    request=request,
                    username=form.cleaned_data['username'],
                    password=form.cleaned_data['password']
                )
                if user:
                    login(request, user)
                    
                    # Store restaurant info in session AFTER login (login() cycles session)
                    # ALWAYS store the USER (owner) ID, NOT the Restaurant object ID
                    # This is what select_table expects: User.objects.get(id=selected_restaurant_id)
                    request.session['selected_restaurant_id'] = restaurant.id  # restaurant = user_restaurant (User model)
                    request.session['selected_restaurant_name'] = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
                    request.session['access_method'] = 'qr_code'
                    request.session.modified = True  # Force session save
                    
                    # Use display name for message (main restaurant name for branches)
                    display_name_msg = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
                    if restaurant_obj and not restaurant_obj.is_main_restaurant and restaurant_obj.parent_restaurant:
                        display_name_msg = restaurant_obj.parent_restaurant.name
                    messages.success(request, f'Welcome to {display_name_msg}! Account created successfully.')
                    return redirect('orders:select_table')
                
        else:
            form = CustomerRegistrationForm()
            
            # Store restaurant info in session for GET requests too
            # This ensures session data is available even if user refreshes
            # ALWAYS store the USER (owner) ID, NOT the Restaurant object ID
            request.session['selected_restaurant_id'] = restaurant.id  # restaurant = user_restaurant (User model)
            request.session['selected_restaurant_name'] = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
            request.session['access_method'] = 'qr_code'
        
        # Get the display name - for branches, show main restaurant name
        display_name = restaurant_obj.name if restaurant_obj else restaurant.restaurant_name
        if restaurant_obj and not restaurant_obj.is_main_restaurant and restaurant_obj.parent_restaurant:
            display_name = restaurant_obj.parent_restaurant.name
        
        context = {
            'form': form,
            'restaurant': restaurant,
            'qr_code': qr_code,
            'display_name': display_name
        }
        return render(request, 'accounts/customer_register.html', context)
        
    except User.DoesNotExist:
        messages.error(request, 'Invalid QR code. Restaurant not found.')
        return redirect('accounts:login')


@login_required
@require_POST
def update_tax_rate(request):
    """Update restaurant owner's tax rate"""
    if not request.user.is_owner():
        return JsonResponse({'success': False, 'message': 'Only restaurant owners can update tax rates.'})
    
    try:
        data = json.loads(request.body)
        tax_rate = Decimal(str(data.get('tax_rate', 0)))
        
        # Validate tax rate (0% to 99.99%)
        if tax_rate < 0 or tax_rate > Decimal('0.9999'):
            return JsonResponse({'success': False, 'message': 'Tax rate must be between 0% and 99.99%'})
        
        # Update user's tax rate
        request.user.tax_rate = tax_rate
        request.user.save()
        
        return JsonResponse({'success': True, 'message': 'Tax rate updated successfully',
                            'tax_rate_percentage': float(tax_rate * 100)})
        
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return JsonResponse({'success': False, 'message': 'Invalid tax rate value'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'An error occurred while updating tax rate'})


def access_blocked_view(request):
    """
    View for displaying access blocked page when subscription is inactive
    """
    from django.utils import timezone
    
    # Get the reason from URL parameters
    reason = request.GET.get('reason', 'Your restaurant subscription has expired or access has been restricted.')
    
    context = {
        'reason': reason,
        'current_time': timezone.now(),
    }
    
    return render(request, 'accounts/access_blocked.html', context)
