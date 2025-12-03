from django import template
from django.utils.safestring import mark_safe

register = template.Library()

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
    elif user.is_kitchen_staff() or user.is_bar_staff() or user.is_cashier() or user.is_customer_care():
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