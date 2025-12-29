"""
Views for hierarchical restaurant/branch management
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from decimal import Decimal
import logging
from accounts.models import User, Role
from restaurant.models_restaurant import Restaurant

# Import bleach for input sanitization
try:
    import bleach
    def sanitize_input(text, max_length=500):
        """Sanitize text input to prevent XSS"""
        if not text:
            return ''
        # Strip all HTML tags and limit length
        return bleach.clean(str(text), tags=[], strip=True)[:max_length]
except ImportError:
    def sanitize_input(text, max_length=500):
        """Fallback sanitization without bleach"""
        if not text:
            return ''
        import html
        return html.escape(str(text))[:max_length]

logger = logging.getLogger(__name__)


@login_required
def manage_branches(request):
    """View for main owners to manage their branches"""
    if not request.user.is_main_owner():
        messages.error(request, 'Only main owners can manage branches.')
        return redirect('admin_panel:admin_dashboard')
    
    # Get all restaurants owned by this main owner
    restaurants = Restaurant.objects.filter(main_owner=request.user).order_by('-is_main_restaurant', 'name')
    
    # Get main restaurant
    main_restaurant = restaurants.filter(is_main_restaurant=True).first()
    
    # If no main restaurant exists, this is a legacy user who needs to upgrade
    if not main_restaurant:
        context = {
            'restaurants': [],
            'total_restaurants': 0,
            'main_restaurant': None,
            'branches': [],
            'can_add_branch': False,
            'subscription_plan': 'Not Set',
            'subscription_plan_code': 'NONE',
            'branches_allowed': 0,
            'needs_upgrade': True,
            'user': request.user
        }
        messages.warning(request, 'Please upgrade to PRO plan to start managing your restaurant network.')
        return render(request, 'admin_panel/manage_branches.html', context)
    
    # Check PRO plan access for branch features
    if not request.user.can_access_branch_features():
        messages.info(request, 'Upgrade to PRO plan to create branches and manage multiple locations.')
        # Don't block access, just show limited view
    
    # Pagination
    paginator = Paginator(restaurants, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Check subscription capabilities
    can_add_branch = main_restaurant.can_create_branches() if main_restaurant else False
    
    context = {
        'restaurants': page_obj,
        'total_restaurants': restaurants.count(),
        'main_restaurant': main_restaurant,
        'branches': restaurants.filter(is_main_restaurant=False),
        'can_add_branch': can_add_branch,
        'subscription_plan': main_restaurant.get_subscription_display() if main_restaurant else 'Unknown',
        'subscription_plan_code': main_restaurant.subscription_plan if main_restaurant else 'SINGLE',
        'branches_allowed': main_restaurant.get_remaining_branches_count() if main_restaurant else 0,
    }
    
    return render(request, 'admin_panel/manage_branches.html', context)


@login_required
def add_branch(request):
    """Add a new branch under main owner"""
    if not request.user.is_main_owner():
        messages.error(request, 'Only main owners can add branches.')
        return redirect('admin_panel:admin_dashboard')
    
    # Check PRO plan access for branch features
    if not request.user.can_access_branch_features():
        messages.error(request, 'Adding branches requires a PRO subscription. Please upgrade your plan.')
        return redirect('admin_panel:admin_dashboard')
    
    # Get main restaurant
    main_restaurant = Restaurant.objects.filter(main_owner=request.user, is_main_restaurant=True).first()
    
    # Check if restaurant can create branches based on subscription plan
    if not main_restaurant:
        messages.error(request, 'You must have a main restaurant to create branches.')
        return redirect('admin_panel:manage_branches')
    
    if not main_restaurant.can_create_branches():
        messages.error(request, f'Your subscription plan ({main_restaurant.get_subscription_display()}) does not allow branch creation. Please upgrade to Pro Plan to create branches.')
        return redirect('admin_panel:manage_branches')
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get and sanitize form data to prevent XSS
                name = sanitize_input(request.POST.get('name', ''), max_length=200)
                description = sanitize_input(request.POST.get('description', ''), max_length=1000)
                address = sanitize_input(request.POST.get('address', ''), max_length=500)
                branch_owner_username = request.POST.get('branch_owner_username', '').strip()
                branch_owner_email = request.POST.get('branch_owner_email', '').strip()
                branch_owner_name = sanitize_input(request.POST.get('branch_owner_name', ''), max_length=200)
                branch_owner_password = request.POST.get('branch_owner_password', '').strip()
                auto_create_credentials = request.POST.get('auto_create_credentials') == 'on'
                
                # Validation
                if not name:
                    messages.error(request, 'Branch name is required.')
                    return render(request, 'admin_panel/add_branch.html', {'main_restaurant': main_restaurant})
                
                if not address:
                    messages.error(request, 'Branch address is required.')
                    return render(request, 'admin_panel/add_branch.html', {'main_restaurant': main_restaurant})
                
                # Handle branch owner creation
                branch_owner = None
                
                if auto_create_credentials and branch_owner_username:
                    # Create new branch owner user
                    if User.objects.filter(username=branch_owner_username).exists():
                        messages.error(request, f'Username "{branch_owner_username}" already exists.')
                        return render(request, 'admin_panel/add_branch.html', {'main_restaurant': main_restaurant})
                    
                    if not branch_owner_email:
                        messages.error(request, 'Email is required when creating new credentials.')
                        return render(request, 'admin_panel/add_branch.html', {'main_restaurant': main_restaurant})
                    
                    if not branch_owner_password:
                        messages.error(request, 'Password is required when creating new credentials.')
                        return render(request, 'admin_panel/add_branch.html', {'main_restaurant': main_restaurant})
                    
                    if len(branch_owner_password) < 8:
                        messages.error(request, 'Password must be at least 8 characters long.')
                        return render(request, 'admin_panel/add_branch.html', {'main_restaurant': main_restaurant})
                    
                    # Get branch_owner role
                    branch_owner_role = Role.objects.get(name='branch_owner')
                    
                    # Use the custom password provided by the user
                    password = branch_owner_password
                    
                    # Create branch owner user
                    branch_owner = User.objects.create_user(
                        username=branch_owner_username,
                        email=branch_owner_email,
                        password=password,
                        first_name=branch_owner_name.split()[0] if branch_owner_name else '',
                        last_name=' '.join(branch_owner_name.split()[1:]) if len(branch_owner_name.split()) > 1 else '',
                        role=branch_owner_role,
                        is_active=True
                    )
                    
                    # Store password to show to main owner
                    new_password = password
                    
                elif branch_owner_username:
                    # Use existing user
                    try:
                        branch_owner = User.objects.get(username=branch_owner_username)
                        # Upgrade to branch_owner role if needed
                        if not branch_owner.is_branch_owner():
                            branch_owner_role = Role.objects.get(name='branch_owner')
                            branch_owner.role = branch_owner_role
                            branch_owner.save()
                        new_password = None
                    except User.DoesNotExist:
                        messages.error(request, f'User "{branch_owner_username}" not found.')
                        return render(request, 'admin_panel/add_branch.html', {'main_restaurant': main_restaurant})
                else:
                    # Use main owner as branch owner
                    branch_owner = request.user
                    new_password = None
                
                # Generate unique QR code
                import uuid
                qr_code = f"REST-{uuid.uuid4().hex[:12].upper()}"
                
                # Create restaurant
                restaurant = Restaurant.objects.create(
                    name=name,
                    description=description,
                    address=address,
                    main_owner=request.user,
                    branch_owner=branch_owner,
                    is_main_restaurant=False,
                    parent_restaurant=main_restaurant,
                    qr_code=qr_code,
                    # Copy settings from main restaurant if available
                    tax_rate=main_restaurant.tax_rate if main_restaurant else 0.0800,
                    auto_print_kot=main_restaurant.auto_print_kot if main_restaurant else True,
                    auto_print_bot=main_restaurant.auto_print_bot if main_restaurant else True,
                )
                
                success_message = f'Branch "{name}" created successfully!'
                
                # If new credentials were created, show them in context instead of messages
                if new_password:
                    context = {
                        'main_restaurant': main_restaurant,
                        'branch_created': True,
                        'branch_name': name,
                        'branch_credentials': {
                            'username': branch_owner_username,
                            'email': branch_owner_email,
                            'password': new_password,
                            'full_name': branch_owner_name if branch_owner_name else 'Not specified',
                            'role': 'Branch Owner',
                            'branch_id': restaurant.id
                        }
                    }
                    messages.success(request, success_message)
                    return render(request, 'admin_panel/add_branch.html', context)
                else:
                    messages.success(request, success_message)
                
                return redirect('admin_panel:main_owner_dashboard')
                
        except Exception as e:
            logger.error(f'Error creating branch: {str(e)}')
            messages.error(request, 'Error creating branch. Please try again.')
    
    context = {
        'main_restaurant': main_restaurant,
    }
    
    return render(request, 'admin_panel/add_branch.html', context)


@login_required
def edit_branch(request, restaurant_id):
    """Edit a branch"""
    restaurant = get_object_or_404(Restaurant, id=restaurant_id)
    
    # Check permissions
    if not (request.user.is_main_owner() and restaurant.main_owner == request.user):
        messages.error(request, 'Permission denied.')
        return redirect('admin_panel:admin_dashboard')
    
    # Check PRO plan access for branch features
    if not request.user.can_access_branch_features():
        messages.error(request, 'Editing branches requires a PRO subscription. Please upgrade your plan.')
        return redirect('admin_panel:admin_dashboard')
    
    if request.method == 'POST':
        try:
            # Update restaurant details
            restaurant.name = request.POST.get('name', '').strip()
            restaurant.description = request.POST.get('description', '').strip()
            restaurant.address = request.POST.get('address', '').strip()
            try:
                restaurant.tax_rate = float(request.POST.get('tax_rate', 8.0)) / 100
            except (ValueError, TypeError):
                restaurant.tax_rate = 0.08  # Default to 8%
            restaurant.auto_print_kot = request.POST.get('auto_print_kot') == 'on'
            restaurant.auto_print_bot = request.POST.get('auto_print_bot') == 'on'
            restaurant.kitchen_printer_name = request.POST.get('kitchen_printer_name', '').strip()
            restaurant.bar_printer_name = request.POST.get('bar_printer_name', '').strip()
            restaurant.receipt_printer_name = request.POST.get('receipt_printer_name', '').strip()
            
            # Update branch owner details if they exist
            if restaurant.branch_owner:
                # Get new values from form
                new_username = request.POST.get('branch_owner', '').strip()
                branch_owner_email = request.POST.get('branch_owner_email', '').strip()
                branch_owner_first_name = request.POST.get('branch_owner_first_name', '').strip()
                branch_owner_last_name = request.POST.get('branch_owner_last_name', '').strip()
                new_password = request.POST.get('new_password', '').strip()
                
                # Check if username changed
                if new_username and new_username != restaurant.branch_owner.username:
                    # Check if new username is already taken
                    if User.objects.filter(username=new_username).exclude(id=restaurant.branch_owner.id).exists():
                        messages.error(request, f'Username "{new_username}" is already taken by another user.')
                        return render(request, 'admin_panel/edit_branch.html', {'restaurant': restaurant})
                    restaurant.branch_owner.username = new_username
                
                # Check if email changed
                if branch_owner_email and branch_owner_email != restaurant.branch_owner.email:
                    # Check if email is already used by another user
                    if User.objects.filter(email=branch_owner_email).exclude(id=restaurant.branch_owner.id).exists():
                        messages.error(request, f'Email "{branch_owner_email}" is already used by another user.')
                        return render(request, 'admin_panel/edit_branch.html', {'restaurant': restaurant})
                    restaurant.branch_owner.email = branch_owner_email
                
                # Update name fields
                if branch_owner_first_name:
                    restaurant.branch_owner.first_name = branch_owner_first_name
                
                if branch_owner_last_name:
                    restaurant.branch_owner.last_name = branch_owner_last_name
                
                # Update password if provided
                if new_password:
                    restaurant.branch_owner.set_password(new_password)
                
                # Save branch owner changes
                restaurant.branch_owner.save()
            
            restaurant.save()
            messages.success(request, f'Branch "{restaurant.name}" updated successfully!')
            return redirect('admin_panel:manage_branches')
            
        except Exception as e:
            logger.error(f'Error updating branch: {str(e)}')
            messages.error(request, 'Error updating branch. Please try again.')
    
    context = {
        'restaurant': restaurant,
    }
    
    return render(request, 'admin_panel/edit_branch.html', context)


@login_required
@require_POST
def delete_branch(request, restaurant_id):
    """Delete a branch"""
    
    
    try:
        restaurant = get_object_or_404(Restaurant, id=restaurant_id)
        
        
        # Check permissions
        if not (request.user.is_main_owner() and restaurant.main_owner == request.user):
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Permission denied'})
            else:
                messages.error(request, 'Permission denied')
                return redirect('admin_panel:main_owner_dashboard')
        
        # Check if this is main restaurant with branches
        if restaurant.is_main_restaurant and restaurant.branches.exists():
            branch_count = restaurant.branches.count()
            
            error_msg = f'Cannot delete main restaurant while it has {branch_count} branch(es). Delete all branches first.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            else:
                messages.error(request, error_msg)
                return redirect('admin_panel:main_owner_dashboard')
        
        # Allow deleting main restaurant if it has NO branches
        if restaurant.is_main_restaurant and not restaurant.branches.exists():
            pass  # Main restaurant with no branches can be deleted
        
        # Store data before any operations (to avoid reference issues)
        restaurant_name = restaurant.name
        branch_owner = restaurant.branch_owner
        restaurant_id = restaurant.id
        main_owner = restaurant.main_owner
        
        # Check if branch owner is ONLY managing this branch (not the main owner)
        is_dedicated_branch_owner = (
            branch_owner and 
            branch_owner != main_owner and
            branch_owner.role and 
            branch_owner.role.name == 'branch_owner'
        )
        
        # Check for dependent data that might prevent deletion
        from restaurant.models import TableInfo, Product, MainCategory
        from orders.models import Order
        
        dependent_tables = TableInfo.objects.filter(
            Q(restaurant_id=restaurant_id) | Q(owner=branch_owner)
        ).count()
        dependent_categories = MainCategory.objects.filter(
            Q(restaurant_id=restaurant_id) | Q(owner=branch_owner)
        ).count()
        dependent_orders = Order.objects.filter(
            Q(table_info__restaurant_id=restaurant_id) | Q(table_info__owner=branch_owner)
        ).count()
        
        # Warning if there is dependent data
        if dependent_tables > 0 or dependent_categories > 0 or dependent_orders > 0:
            warning_parts = []
            if dependent_tables > 0:
                warning_parts.append(f"{dependent_tables} tables")
            if dependent_categories > 0:
                warning_parts.append(f"{dependent_categories} categories")
            if dependent_orders > 0:
                warning_parts.append(f"{dependent_orders} orders")
            
            warning_msg = f"This branch has {', '.join(warning_parts)}. Deleting it will also delete all related data. Are you sure?"
        
        # Delete all related data explicitly
        from waste_management.models import FoodWasteLog
        from reports.models import SalesReport
        from orders.models import Order, BillRequest
        from orders.models_printjob import PrintJob
        from accounts.models import User
        
        
        
        # 1. Delete waste logs related to products from this restaurant
        waste_logs = FoodWasteLog.objects.filter(
            Q(product__main_category__restaurant_id=restaurant_id) |
            Q(product__main_category__owner=branch_owner)
        )
        waste_count = waste_logs.count()
        waste_logs.delete()
        
        
        # 2. Delete reports related to this branch owner (will cascade to ProductSalesDetail, etc.)
        sales_reports = SalesReport.objects.filter(owner=branch_owner)
        report_count = sales_reports.count()
        sales_reports.delete()
        
        
        # 3. Delete print jobs
        print_jobs = PrintJob.objects.filter(restaurant_id=restaurant_id)
        print_count = print_jobs.count()
        print_jobs.delete()
        
        
        # 4. Delete bill requests
        bill_requests = BillRequest.objects.filter(
            Q(table_info__restaurant_id=restaurant_id) |
            Q(table_info__owner=branch_owner)
        )
        bill_count = bill_requests.count()
        bill_requests.delete()
        
        
        # 5. Delete orders (this will cascade to order items)
        orders = Order.objects.filter(
            Q(table_info__restaurant_id=restaurant_id) |
            Q(table_info__owner=branch_owner)
        )
        order_count = orders.count()
        orders.delete()
        
        
        # 6. Delete products (through categories - will cascade to products, subcategories, etc.)
        categories = MainCategory.objects.filter(
            Q(restaurant_id=restaurant_id) | Q(owner=branch_owner)
        )
        category_count = categories.count()
        categories.delete()
        
        
        # 7. Delete tables
        tables = TableInfo.objects.filter(
            Q(restaurant_id=restaurant_id) | Q(owner=branch_owner)
        )
        table_count = tables.count()
        tables.delete()
        
        
        # 8. Delete all users (staff) that belong to this branch owner (if dedicated branch owner)
        if is_dedicated_branch_owner and branch_owner:
            branch_staff = User.objects.filter(owner=branch_owner)
            staff_count = branch_staff.count()
            if staff_count > 0:
                staff_names = [f"{u.username} ({u.get_full_name()})" for u in branch_staff[:5]]  # Log first 5
                
                branch_staff.delete()
        
        # 9. Clear NULLABLE foreign key references before deleting (to bypass PROTECT)
        
        # Only clear branch_owner (don't clear parent_restaurant - violates CHECK constraint)
        # Branches MUST have parent_restaurant until deletion per CHECK constraint
        if restaurant.branch_owner:
            restaurant.branch_owner = None
            restaurant.save(update_fields=['branch_owner'])
        
        # 10. Now we can safely delete the restaurant (parent_restaurant stays until deletion)
        restaurant.delete()
        
        # 11. Finally delete the branch owner user account ONLY if it's a dedicated branch owner
        if is_dedicated_branch_owner and branch_owner:
            branch_owner_name = branch_owner.get_full_name() or branch_owner.username
            branch_owner_username = branch_owner.username
            branch_owner.delete()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': f'Branch "{restaurant_name}" deleted successfully'})
        else:
            messages.success(request, f'Branch "{restaurant_name}" deleted successfully')
            return redirect('admin_panel:main_owner_dashboard')
            
    except Exception as e:
        logger.error(f'Error deleting branch: {str(e)}', exc_info=True)
        
        error_msg = str(e)
        if 'foreign key' in error_msg.lower() or 'constraint' in error_msg.lower():
            error_msg = "Cannot delete branch because it has related data (orders, tables, etc.). Please remove related data first."
        else:
            error_msg = "Error deleting branch. Please try again."
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg})
        else:
            messages.error(request, error_msg)
            return redirect('admin_panel:main_owner_dashboard')


@login_required
def switch_restaurant(request):
    """Switch current restaurant context"""
    restaurant_id = request.POST.get('restaurant_id') if request.method == 'POST' else request.GET.get('restaurant_id')
    
    
    
    
    if restaurant_id:
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id)
            
            
            # Check if user can access this restaurant
            can_access = restaurant.can_user_access(request.user)
            
            
            if can_access:
                # Store the OWNER User ID, not Restaurant ID
                # For branches, use branch_owner; for main restaurants, use main_owner
                owner_user = restaurant.branch_owner if not restaurant.is_main_restaurant and restaurant.branch_owner else restaurant.main_owner
                
                request.session['selected_restaurant_id'] = owner_user.id  # Store User.id
                request.session['selected_restaurant_name'] = restaurant.name
                
                # Ensure view_all_restaurants flag is cleared when selecting specific restaurant
                request.session['view_all_restaurants'] = False
                
                # Save session to ensure changes are persisted
                request.session.save()
                
                
                
                
                # Always redirect to main admin dashboard
                redirect_url_name = 'admin_panel:admin_dashboard'
                redirect_url_path = '/admin-panel/'
                
                
                
                if request.method == 'POST':
                    return JsonResponse({
                        'success': True, 
                        'message': f'Switched to {restaurant.name}',
                        'restaurant_name': restaurant.name,
                        'redirect_url': redirect_url_path  # Send actual path for JavaScript
                    })
                else:
                    messages.success(request, f'Switched to {restaurant.name}')
                    return redirect(redirect_url_name)
            else:
                
                if request.method == 'POST':
                    return JsonResponse({'success': False, 'error': 'Access denied'})
                else:
                    messages.error(request, 'Access denied')
        except Restaurant.DoesNotExist:
            
            if request.method == 'POST':
                return JsonResponse({'success': False, 'error': 'Restaurant not found'})
            else:
                messages.error(request, 'Restaurant not found')
    
    
    # Always redirect to admin dashboard
    return redirect('admin_panel:admin_dashboard')


@login_required
@require_POST
def toggle_restaurant_status(request, restaurant_id):
    """Toggle restaurant active/inactive status"""
    if not request.user.is_main_owner():
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    try:
        restaurant = get_object_or_404(Restaurant, id=restaurant_id, main_owner=request.user)
        
        # Toggle status
        restaurant.is_active = not restaurant.is_active
        restaurant.save()
        
        status = 'activated' if restaurant.is_active else 'deactivated'
        
        
        
        return JsonResponse({
            'success': True,
            'message': f'Restaurant "{restaurant.name}" has been {status}',
            'is_active': restaurant.is_active
        })
    
    except Exception as e:
        logger.error(f'Error toggling branch status: {str(e)}')
        return JsonResponse({'success': False, 'error': 'Failed to toggle branch status. Please try again.'})


@login_required
def restaurant_selection(request):
    """Show restaurant selection interface for main owners"""
    if not request.user.is_main_owner():
        messages.error(request, 'Only main owners can access restaurant selection.')
        return redirect('admin_panel:admin_dashboard')
    
    restaurants = Restaurant.objects.filter(main_owner=request.user).order_by('-is_main_restaurant', 'name')
    current_restaurant_id = request.session.get('selected_restaurant_id')
    current_restaurant = None
    
    
    
    
    
    if current_restaurant_id:
        try:
            current_restaurant = Restaurant.objects.get(id=current_restaurant_id)
        except Restaurant.DoesNotExist:
            pass  # Restaurant not found, keep current_restaurant as None
    
    context = {
        'restaurants': restaurants,
        'current_restaurant': current_restaurant,
        'show_all_option': True,  # Allow "All Restaurants" view
    }
    
    return render(request, 'admin_panel/restaurant_selection.html', context)


@login_required
def set_view_all_restaurants(request):
    """Set context to view all restaurants (for main owners)"""
    if not request.user.is_main_owner():
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    # Clear restaurant selection to show all restaurants
    if 'selected_restaurant_id' in request.session:
        del request.session['selected_restaurant_id']
    if 'selected_restaurant_name' in request.session:
        del request.session['selected_restaurant_name']
    
    request.session['view_all_restaurants'] = True
    
    return JsonResponse({
        'success': True, 
        'message': 'Now viewing all restaurants',
        'restaurant_name': 'All Restaurants'
    })


@login_required
@require_POST
def upgrade_to_pro(request):
    """Upgrade restaurant to PRO subscription plan"""
    if not request.user.is_main_owner():
        return JsonResponse({'success': False, 'error': 'Only main owners can upgrade subscription plans.'})
    
    try:
        # Get main restaurant
        main_restaurant = Restaurant.objects.filter(main_owner=request.user, is_main_restaurant=True).first()
        
        if not main_restaurant:
            # Legacy user upgrading from SINGLE to PRO - need to create Restaurant record
            import uuid
            
            # Get user's restaurant info from User model (legacy)
            restaurant_name = request.user.restaurant_name or f"{request.user.get_full_name()}'s Restaurant"
            restaurant_desc = request.user.restaurant_description or ""
            
            # Create main restaurant record
            main_restaurant = Restaurant.objects.create(
                name=restaurant_name,
                description=restaurant_desc,
                address=request.user.address or "No address provided",
                main_owner=request.user,
                branch_owner=request.user,
                is_main_restaurant=True,
                subscription_plan='PRO',  # Create as PRO directly
                qr_code=request.user.restaurant_qr_code or f"REST-{uuid.uuid4().hex[:12].upper()}",
                tax_rate=request.user.tax_rate,
                auto_print_kot=request.user.auto_print_kot,
                auto_print_bot=request.user.auto_print_bot,
                kitchen_printer_name=request.user.kitchen_printer_name,
                bar_printer_name=request.user.bar_printer_name,
                receipt_printer_name=request.user.receipt_printer_name,
            )
            
            return JsonResponse({
                'success': True, 
                'message': f'Successfully upgraded {main_restaurant.name} to PRO plan! You can now create unlimited branches and manage your restaurant network.',
                'new_plan': 'Pro Plan (Multi-Branch)',
                'first_time_upgrade': True
            })
        
        if main_restaurant.subscription_plan == 'PRO':
            return JsonResponse({'success': False, 'error': 'Already on PRO plan.'})
        
        # Upgrade to PRO
        if main_restaurant.upgrade_to_pro():
            return JsonResponse({
                'success': True, 
                'message': f'Successfully upgraded {main_restaurant.name} to PRO plan! You can now create unlimited branches.',
                'new_plan': 'Pro Plan (Multi-Branch)'
            })
        else:
            return JsonResponse({'success': False, 'error': 'Failed to upgrade subscription plan.'})
            
    except Exception as e:
        logger.error(f'Error upgrading subscription: {str(e)}')
        return JsonResponse({'success': False, 'error': 'Error upgrading subscription. Please try again.'})


@login_required
@require_POST
def downgrade_to_single(request):
    """Downgrade restaurant to SINGLE subscription plan"""
    if not request.user.is_main_owner():
        return JsonResponse({'success': False, 'error': 'Only main owners can change subscription plans.'})
    
    try:
        # Get main restaurant
        main_restaurant = Restaurant.objects.filter(main_owner=request.user, is_main_restaurant=True).first()
        
        if not main_restaurant:
            return JsonResponse({'success': False, 'error': 'No main restaurant found.'})
        
        if main_restaurant.subscription_plan == 'SINGLE':
            return JsonResponse({'success': False, 'error': 'Already on SINGLE plan.'})
        
        # Check if any branches exist
        if main_restaurant.branches.exists():
            branch_count = main_restaurant.branches.count()
            return JsonResponse({
                'success': False, 
                'error': f'Cannot downgrade to SINGLE plan while {branch_count} branch(es) exist. Please delete all branches first.'
            })
        
        # Downgrade to SINGLE
        if main_restaurant.downgrade_to_single():
            return JsonResponse({
                'success': True, 
                'message': f'Successfully downgraded {main_restaurant.name} to SINGLE plan.',
                'new_plan': 'Single Restaurant'
            })
        else:
            return JsonResponse({'success': False, 'error': 'Failed to downgrade subscription plan.'})
            
    except Exception as e:
        logger.error(f'Error downgrading subscription: {str(e)}')
        return JsonResponse({'success': False, 'error': 'Error downgrading subscription. Please try again.'})


@login_required 
def setup_main_restaurant(request):
    """Setup main restaurant for users who don't have one yet"""
    if not request.user.is_main_owner():
        messages.error(request, 'Only main owners can setup restaurants.')
        return redirect('admin_panel:admin_dashboard')
    
    # Check if user already has a main restaurant
    if Restaurant.objects.filter(main_owner=request.user, is_main_restaurant=True).exists():
        messages.info(request, 'You already have a main restaurant setup.')
        return redirect('admin_panel:manage_branches')
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                name = request.POST.get('name', '').strip()
                description = request.POST.get('description', '').strip()
                address = request.POST.get('address', '').strip()
                subscription_plan = request.POST.get('subscription_plan', 'SINGLE')
                tax_rate = request.POST.get('tax_rate', '8.0')
                
                if not name or not address:
                    messages.error(request, 'Restaurant name and address are required.')
                    return render(request, 'admin_panel/setup_main_restaurant.html')
                
                # Convert tax rate percentage to decimal
                try:
                    tax_rate_decimal = Decimal(tax_rate) / 100
                except (ValueError, TypeError):
                    tax_rate_decimal = Decimal('0.08')  # Default 8%
                
                # Generate unique QR code
                import uuid
                qr_code = f"REST-{uuid.uuid4().hex[:12].upper()}"
                
                # Create main restaurant
                restaurant = Restaurant.objects.create(
                    name=name,
                    description=description,
                    address=address,
                    main_owner=request.user,
                    branch_owner=request.user,  # Main owner manages main restaurant
                    is_main_restaurant=True,
                    subscription_plan=subscription_plan,
                    qr_code=qr_code,
                    tax_rate=tax_rate_decimal,
                )
                
                messages.success(request, f'Main restaurant "{name}" created successfully with {restaurant.get_subscription_display()} plan!')
                return redirect('admin_panel:manage_branches')
                
        except Exception as e:
            logger.error(f'Error creating restaurant: {str(e)}')
            messages.error(request, 'Error creating restaurant. Please try again.')
            
    context = {
        'subscription_plans': Restaurant.SUBSCRIPTION_PLANS,
    }
    return render(request, 'admin_panel/setup_main_restaurant.html', context)
