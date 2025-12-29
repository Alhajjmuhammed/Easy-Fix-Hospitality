from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe
from decimal import Decimal

register = template.Library()

# Currency symbols mapping (kept in sync with models)
CURRENCY_SYMBOLS = {
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'KES': 'KSh',
    'TZS': 'TSh',
    'UGX': 'USh',
    'RWF': 'RF',
    'ZAR': 'R',
    'NGN': '₦',
    'GHS': 'GH₵',
    'INR': '₹',
    'AED': 'AED',
    'SAR': 'SAR',
    'CNY': '¥',
    'JPY': '¥',
}

# Currencies that typically don't use decimal places
INTEGER_CURRENCIES = ['KES', 'TZS', 'UGX', 'RWF', 'JPY']


def get_user_currency_info(user, request=None):
    """
    Get currency info for a user, handling all ownership types.
    Returns (currency_code, currency_symbol)
    """
    if not user or not user.is_authenticated:
        return 'USD', '$'
    
    # Try to get currency from Restaurant model first (for branch support)
    try:
        from restaurant.models_restaurant import Restaurant
        
        # Check session for selected restaurant
        if request and hasattr(request, 'session'):
            selected_restaurant_id = request.session.get('selected_restaurant_id')
            if selected_restaurant_id:
                # Get the restaurant from selected owner
                try:
                    from accounts.models import User
                    selected_user = User.objects.get(id=selected_restaurant_id)
                    if selected_user.is_branch_owner():
                        restaurant = Restaurant.objects.filter(
                            branch_owner=selected_user, 
                            is_main_restaurant=False
                        ).first()
                    else:
                        restaurant = Restaurant.objects.filter(
                            main_owner=selected_user, 
                            is_main_restaurant=True
                        ).first()
                    
                    if restaurant:
                        return restaurant.currency_code, restaurant.get_currency_symbol()
                except Exception:
                    pass
        
        # For owners, check their own currency setting
        if user.is_owner() or user.is_main_owner() or user.is_branch_owner():
            return user.currency_code, CURRENCY_SYMBOLS.get(user.currency_code, '$')
        
        # For staff, check their owner's currency setting
        if user.owner:
            return user.owner.currency_code, CURRENCY_SYMBOLS.get(user.owner.currency_code, '$')
            
    except Exception:
        pass
    
    # Default to USD
    return 'USD', '$'


@register.simple_tag(takes_context=True)
def currency_symbol(context):
    """Get the current currency symbol based on user/restaurant context"""
    request = context.get('request')
    user = context.get('user')
    
    _, symbol = get_user_currency_info(user, request)
    return symbol


@register.filter
def currency(value, user=None):
    """
    Format a price with the appropriate currency symbol.
    Usage in templates: {{ price|currency:user }}
    """
    if user is None:
        # Default to USD if no user provided
        symbol = '$'
        use_decimals = True
    else:
        currency_code = getattr(user, 'currency_code', 'USD')
        symbol = CURRENCY_SYMBOLS.get(currency_code, '$')
        use_decimals = currency_code not in INTEGER_CURRENCIES
    
    try:
        amount = float(value) if value else 0.0
        if use_decimals:
            return f"{symbol}{amount:,.2f}"
        else:
            return f"{symbol}{amount:,.0f}"
    except (TypeError, ValueError):
        return f"{symbol}0.00"


@register.simple_tag(takes_context=True)
def format_price(context, value):
    """
    Format a price with currency symbol based on context.
    Usage in templates: {% format_price price %}
    Output is escaped to prevent XSS.
    """
    request = context.get('request')
    user = context.get('user')
    
    currency_code, symbol = get_user_currency_info(user, request)
    use_decimals = currency_code not in INTEGER_CURRENCIES
    
    # Escape symbol to prevent XSS if currency data is manipulated
    safe_symbol = escape(symbol)
    
    try:
        amount = float(value) if value else 0.0
        if use_decimals:
            return mark_safe(f"{safe_symbol}{amount:,.2f}")
        else:
            return mark_safe(f"{safe_symbol}{amount:,.0f}")
    except (TypeError, ValueError):
        return mark_safe(f"{safe_symbol}0.00")


@register.simple_tag(takes_context=True)
def get_restaurant_name(context):
    """Get restaurant name with request context"""
    request = context.get('request')
    user = context.get('user')
    
    if not user or not user.is_authenticated:
        return "Restaurant System"
    
    if user.is_customer():
        return user.get_restaurant_name(request)
    elif user.is_owner() or user.is_main_owner() or user.is_branch_owner():
        # Use get_restaurant_name for all owners to handle branch→main logic
        return user.get_restaurant_name(request)
    elif user.is_kitchen_staff() or user.is_bar_staff() or user.is_buffet_staff() or user.is_service_staff() or user.is_cashier() or user.is_customer_care():
        # For staff members, use the get_restaurant_name method
        return user.get_restaurant_name(request)
    
    return "Restaurant System"

@register.simple_tag(takes_context=True) 
def current_restaurant_name(context):
    """Get current restaurant name from session"""
    request = context.get('request')
    
    if request and hasattr(request, 'session'):
        restaurant_name = request.session.get('selected_restaurant_name')
        if restaurant_name:
            return restaurant_name
    
    return "Restaurant"