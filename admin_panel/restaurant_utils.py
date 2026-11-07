"""
Utility functions for restaurant data filtering based on user roles
"""
from django.db.models import Q
from restaurant.models_restaurant import Restaurant


def get_user_restaurants(user):
    """
    Get restaurants accessible to the current user based on their role
    
    Returns:
    - Main owners: All restaurants they own (main + branches)
    - Branch owners: Only their assigned branch
    - Regular owners: Their restaurants (backward compatibility)
    - Staff (managers, kitchen, bar, etc.): Their owner's restaurants
    """
    # select_related prevents N+1 FK queries when looping over results and
    # accessing restaurant.main_owner or restaurant.branch_owner attributes.
    _base = Restaurant.objects.select_related('main_owner', 'branch_owner')
    if user.is_main_owner():
        return _base.filter(main_owner=user).order_by('-is_main_restaurant', 'name')
    elif user.is_branch_owner():
        return _base.filter(branch_owner=user).order_by('name')
    elif user.is_owner() and not user.is_main_owner():
        return _base.filter(
            Q(main_owner=user) | Q(branch_owner=user)
        ).order_by('name')
    elif user.owner:
        # Staff members (managers, kitchen, bar, cashier, etc.) - access their owner's restaurants
        if user.owner.is_main_owner():
            return _base.filter(main_owner=user.owner).order_by('-is_main_restaurant', 'name')
        elif user.owner.is_branch_owner():
            return _base.filter(branch_owner=user.owner).order_by('name')
        else:
            return _base.filter(
                Q(main_owner=user.owner) | Q(branch_owner=user.owner)
            ).order_by('name')
    else:
        return Restaurant.objects.none()


def get_current_restaurant(user, session_restaurant_id=None):
    """
    Get the current active restaurant for the user
    
    For branch owners: Always their assigned restaurant
    For main owners: Session restaurant or main restaurant
    """
    accessible_restaurants = get_user_restaurants(user)
    
    if user.is_branch_owner():
        # Branch owners can only work with their assigned restaurant
        return accessible_restaurants.first()
    
    elif user.is_main_owner():
        # Main owners can switch between their restaurants
        if session_restaurant_id:
            try:
                return accessible_restaurants.get(id=session_restaurant_id)
            except Restaurant.DoesNotExist:
                pass
        # Default to main restaurant
        return accessible_restaurants.filter(is_main_restaurant=True).first()
    
    elif user.is_owner():
        # Regular owners (backward compatibility)
        if session_restaurant_id:
            try:
                return accessible_restaurants.get(id=session_restaurant_id)
            except Restaurant.DoesNotExist:
                pass
        return accessible_restaurants.first()
    
    return None


def filter_data_by_restaurant(queryset, user, current_restaurant=None):
    """
    Filter any queryset to only include data for the user's accessible restaurants
    
    Args:
    - queryset: Django queryset to filter
    - user: Current user
    - current_restaurant: Specific restaurant to filter by (optional)
    
    Returns filtered queryset
    """
    if current_restaurant:
        # Filter by specific restaurant
        if hasattr(queryset.model, 'restaurant'):
            return queryset.filter(restaurant=current_restaurant)
        elif hasattr(queryset.model, 'restaurant_id'):
            return queryset.filter(restaurant_id=current_restaurant.id)
    
    # Filter by all user's accessible restaurants
    accessible_restaurants = get_user_restaurants(user)
    
    if hasattr(queryset.model, 'restaurant'):
        return queryset.filter(restaurant__in=accessible_restaurants)
    elif hasattr(queryset.model, 'restaurant_id'):
        return queryset.filter(restaurant_id__in=accessible_restaurants.values_list('id', flat=True))
    
    # If no restaurant field, return all (for models not restaurant-specific)
    return queryset


def can_access_restaurant(user, restaurant):
    """
    Check if user can access a specific restaurant
    """
    accessible_restaurants = get_user_restaurants(user)
    return accessible_restaurants.filter(id=restaurant.id).exists()


def get_restaurant_context(user, session_restaurant_id=None, request=None):
    """
    Get standardized restaurant context for views
    
    Returns dictionary with restaurant context variables
    """
    accessible_restaurants = get_user_restaurants(user)
    
    # Determine view mode - check session if available
    view_all_restaurants = False
    if request and hasattr(request, 'session'):
        view_all_restaurants = request.session.get('view_all_restaurants', False)
    
    # Get current restaurant based on session or default
    current_restaurant = None
    
    if session_restaurant_id and not view_all_restaurants:
        # session_restaurant_id stores User (owner) ID, not Restaurant ID
        # User has selected a specific restaurant and not in "view all" mode
        try:
            from accounts.models import User
            selected_user = User.objects.get(id=session_restaurant_id)

            # Exact restaurant chosen in switch_restaurant (needed for a branch the main
            # owner runs himself). Only trusted while it still belongs to the owner user
            # stored in selected_restaurant_id, so older sessions behave as before.
            selected_pk = request.session.get('selected_restaurant_pk') if request and hasattr(request, 'session') else None
            if selected_pk:
                exact = accessible_restaurants.filter(id=selected_pk).first()
                if exact:
                    exact_owner = exact.branch_owner if (not exact.is_main_restaurant and exact.branch_owner) else exact.main_owner
                    if exact_owner and exact_owner.id == selected_user.id:
                        current_restaurant = exact

            # Find the Restaurant object for this user
            if current_restaurant:
                pass
            elif selected_user.is_branch_owner():
                current_restaurant = accessible_restaurants.filter(branch_owner=selected_user, is_main_restaurant=False).first()
            else:
                current_restaurant = accessible_restaurants.filter(main_owner=selected_user, is_main_restaurant=True).first()
            
            if not current_restaurant:
                # Invalid restaurant in session, clear it
                if request and hasattr(request, 'session'):
                    if 'selected_restaurant_id' in request.session:
                        del request.session['selected_restaurant_id']
        except User.DoesNotExist:
            # Invalid user in session, clear it
            if request and hasattr(request, 'session'):
                if 'selected_restaurant_id' in request.session:
                    del request.session['selected_restaurant_id']
            current_restaurant = None
    
    # If no current restaurant and not viewing all, set a default
    if not current_restaurant and not view_all_restaurants:
        if user.is_branch_owner():
            # Branch owners always work with their assigned restaurant
            current_restaurant = accessible_restaurants.first()
        elif user.is_main_owner():
            # Main owners default to main restaurant unless viewing all
            current_restaurant = accessible_restaurants.filter(is_main_restaurant=True).first()
        elif user.is_owner():
            # Regular owners default to their restaurant
            current_restaurant = accessible_restaurants.first()
        elif user.owner:
            # Staff members (managers, kitchen, bar, etc.) - get their owner's default restaurant
            if user.owner.is_branch_owner():
                # Staff of branch owner - get that branch
                current_restaurant = accessible_restaurants.first()
            elif user.owner.is_main_owner():
                # Staff of main owner - get main restaurant
                current_restaurant = accessible_restaurants.filter(is_main_restaurant=True).first()
            else:
                # Staff of regular owner
                current_restaurant = accessible_restaurants.first()
    
    # If view_all_restaurants is True, current_restaurant should be None for aggregated views
    if view_all_restaurants:
        current_restaurant = None
    
    # Restaurant name for display
    if view_all_restaurants:
        context_name = "All Locations"
    elif current_restaurant:
        context_name = current_restaurant.name
    else:
        context_name = "Restaurant System"
    
    # Get restaurant logo
    restaurant_logo = None
    if current_restaurant and current_restaurant.logo:
        restaurant_logo = current_restaurant.logo
    elif not view_all_restaurants and accessible_restaurants.exists():
        # If no current restaurant but user has restaurants, get first one with logo
        first_restaurant_with_logo = accessible_restaurants.exclude(logo__isnull=True).exclude(logo__exact='').first()
        if first_restaurant_with_logo:
            restaurant_logo = first_restaurant_with_logo.logo
    
    return {
        'current_restaurant': current_restaurant,
        'accessible_restaurants': accessible_restaurants,
        'view_all_restaurants': view_all_restaurants,
        'restaurant_name': context_name,
        'restaurant_logo': restaurant_logo,
        'can_manage_branches': user.can_access_branch_features(),
        'can_switch_restaurants': len(accessible_restaurants) > 1 or user.is_main_owner(),
    }

# Order statuses that are not a sale: never count them as revenue.
NON_REVENUE_STATUSES = ('cancelled', 'customer_refused', 'kitchen_error', 'quality_issue', 'wasted')


def restaurant_orders_q(restaurant):
    """
    Q() matching the orders of exactly ONE restaurant (main or branch), never its
    sister branches.

    - dine-in orders on this restaurant's tables;
    - legacy tables that carry only an owner (restaurant is NULL) of this restaurant's
      operator (skipped for a branch the main owner runs himself, where that owner is
      the MAIN restaurant's owner);
    - delivery/pickup orders (no table) placed with this restaurant's operator.
    """
    if restaurant.is_main_restaurant:
        operator = restaurant.main_owner
        self_managed_branch = False
    else:
        operator = restaurant.branch_owner or restaurant.main_owner
        self_managed_branch = operator == restaurant.main_owner
    q = Q(table_info__restaurant=restaurant)
    if not self_managed_branch:
        q |= Q(table_info__owner=operator, table_info__restaurant__isnull=True)
    if not self_managed_branch:
        # A branch the main owner runs himself can't be told apart for delivery/pickup orders
        # (they carry the main owner): they belong to the main restaurant, so count them once
        remote = Q(order_type__in=['delivery', 'pickup'], table_info__isnull=True)
        q |= remote & (Q(restaurant_owner=operator) |
                       Q(restaurant_owner__isnull=True, ordered_by__owner=operator))
    return q


def restaurant_tables_products_q(restaurant):
    """(tables_q, products_q) for exactly one restaurant, same rules as restaurant_orders_q."""
    if restaurant.is_main_restaurant:
        operator = restaurant.main_owner
    else:
        operator = restaurant.branch_owner or restaurant.main_owner
        if operator == restaurant.main_owner:
            operator = None  # self-managed branch: owner rows belong to the main restaurant
    tables_q = Q(restaurant=restaurant)
    products_q = Q(main_category__restaurant=restaurant)
    if operator is not None:
        tables_q |= Q(owner=operator, restaurant__isnull=True)
        products_q |= Q(main_category__owner=operator, main_category__restaurant__isnull=True)
    return tables_q, products_q
