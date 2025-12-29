"""
Security Utilities for Restaurant Ordering System
Provides session validation, input sanitization, and audit logging
"""

import logging
import bleach
from functools import wraps
from django.http import JsonResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.utils import timezone
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)


# ============================================================================
# SESSION VALIDATION
# ============================================================================

def validate_session_restaurant_id(session):
    """
    Validate and sanitize the selected_restaurant_id from session.
    Returns the restaurant owner User object or None if invalid.
    """
    from accounts.models import User
    
    restaurant_id = session.get('selected_restaurant_id')
    if not restaurant_id:
        return None
    
    # Validate it's an integer
    try:
        restaurant_id = int(restaurant_id)
    except (ValueError, TypeError):
        logger.warning(f"Invalid restaurant_id in session: {restaurant_id}")
        # Clear invalid session data
        if 'selected_restaurant_id' in session:
            del session['selected_restaurant_id']
        return None
    
    # Validate the restaurant exists and is an owner
    try:
        restaurant = User.objects.get(
            id=restaurant_id,
            role__name__in=['owner', 'main_owner', 'branch_owner'],
            is_active=True
        )
        return restaurant
    except User.DoesNotExist:
        logger.warning(f"Restaurant owner not found for id: {restaurant_id}")
        if 'selected_restaurant_id' in session:
            del session['selected_restaurant_id']
        return None


def validate_session_table(session, restaurant=None):
    """
    Validate the selected_table from session.
    Returns (table_number, table_id) tuple or (None, None) if invalid.
    """
    from restaurant.models import TableInfo
    
    table_number = session.get('selected_table')
    table_id = session.get('selected_table_id')
    
    if not table_number:
        return None, None
    
    # Sanitize table number (alphanumeric, hyphens, underscores only)
    import re
    if not re.match(r'^[A-Za-z0-9\-_]+$', str(table_number)):
        logger.warning(f"Invalid table number format: {table_number}")
        _clear_table_session(session)
        return None, None
    
    # Validate table exists if we have table_id
    if table_id:
        try:
            table_id = int(table_id)
            query = {'id': table_id, 'tbl_no': table_number}
            if restaurant:
                query['owner'] = restaurant
            
            TableInfo.objects.get(**query)
        except (ValueError, TypeError, TableInfo.DoesNotExist):
            logger.warning(f"Table validation failed: {table_number} (id: {table_id})")
            _clear_table_session(session)
            return None, None
    
    return table_number, table_id


def _clear_table_session(session):
    """Clear table-related session data"""
    for key in ['selected_table', 'selected_table_id', 'selected_restaurant_owner']:
        if key in session:
            del session[key]


def validate_cart_data(cart):
    """
    Validate and sanitize cart data from session.
    Returns sanitized cart dict or empty dict if invalid.
    """
    from restaurant.models import Product
    
    if not isinstance(cart, dict):
        return {}
    
    sanitized_cart = {}
    
    for product_id, item in cart.items():
        # Validate product_id is numeric
        try:
            pid = int(product_id)
        except (ValueError, TypeError):
            continue
        
        # Validate item structure
        if not isinstance(item, dict):
            continue
        
        # Validate required fields
        try:
            quantity = int(item.get('quantity', 0))
            price = Decimal(str(item.get('price', 0)))
            
            if quantity <= 0 or quantity > 1000:  # Reasonable max quantity
                continue
            if price < 0 or price > Decimal('1000000'):  # Reasonable max price
                continue
            
            # Verify product exists
            product = Product.objects.filter(id=pid, is_available=True).first()
            if not product:
                continue
            
            # Sanitize name
            name = sanitize_text(str(item.get('name', '')))[:200]
            
            sanitized_cart[str(pid)] = {
                'name': name,
                'price': str(price),
                'original_price': str(item.get('original_price', price)),
                'has_promotion': bool(item.get('has_promotion', False)),
                'quantity': quantity,
                'image': item.get('image'),
            }
        except (ValueError, TypeError, InvalidOperation):
            continue
    
    return sanitized_cart


# ============================================================================
# INPUT SANITIZATION
# ============================================================================

# Allowed HTML tags for rich text (very restrictive)
ALLOWED_TAGS = ['b', 'i', 'u', 'strong', 'em', 'br']
ALLOWED_ATTRIBUTES = {}


def sanitize_text(text, max_length=None, strip_html=True):
    """
    Sanitize text input - remove/escape dangerous content.
    
    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length (None for no limit)
        strip_html: If True, strip all HTML. If False, allow safe subset.
    """
    if text is None:
        return ''
    
    text = str(text)
    
    if strip_html:
        # Remove all HTML tags
        text = bleach.clean(text, tags=[], strip=True)
    else:
        # Allow only safe HTML tags
        text = bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
    
    # Remove null bytes and other dangerous characters
    text = text.replace('\x00', '').replace('\r\n', '\n')
    
    # Truncate if needed
    if max_length and len(text) > max_length:
        text = text[:max_length]
    
    return text.strip()


def sanitize_special_instructions(text):
    """Sanitize order special instructions"""
    return sanitize_text(text, max_length=500, strip_html=True)


def sanitize_notes(text):
    """Sanitize general notes fields"""
    return sanitize_text(text, max_length=1000, strip_html=True)


# ============================================================================
# VIEW DECORATORS
# ============================================================================

def require_restaurant_context(view_func):
    """
    Decorator that ensures valid restaurant context exists in session.
    Redirects to login if no valid restaurant is selected.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Staff users get their restaurant automatically
        if request.user.is_authenticated:
            if hasattr(request.user, 'is_customer_care') and (
                request.user.is_customer_care() or 
                request.user.is_kitchen_staff() or 
                request.user.is_bar_staff() or 
                request.user.is_buffet_staff() or 
                request.user.is_service_staff() or 
                request.user.is_cashier()
            ):
                restaurant = request.user.get_owner()
                if restaurant:
                    request.session['selected_restaurant_id'] = restaurant.id
                    request.session['selected_restaurant_name'] = restaurant.restaurant_name
                    return view_func(request, *args, **kwargs)
                else:
                    messages.error(request, 'You are not assigned to any restaurant.')
                    return redirect('accounts:login')
        
        # Validate restaurant from session
        restaurant = validate_session_restaurant_id(request.session)
        if not restaurant:
            messages.warning(request, 'Please scan a restaurant QR code to start ordering.')
            return redirect('accounts:login')
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def require_table_selection(view_func):
    """
    Decorator that ensures a valid table is selected in session.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        restaurant = validate_session_restaurant_id(request.session)
        table_number, table_id = validate_session_table(request.session, restaurant)
        
        if not table_number:
            messages.warning(request, 'Please select your table number first.')
            return redirect('orders:select_table')
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def ajax_login_required(view_func):
    """
    Decorator for AJAX views that require authentication.
    Returns JSON error instead of redirect.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'Authentication required',
                'redirect': '/accounts/login/'
            }, status=401)
        return view_func(request, *args, **kwargs)
    
    return wrapper


def ajax_restaurant_required(view_func):
    """
    Decorator for AJAX views that require restaurant context.
    Returns JSON error instead of redirect.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        restaurant = validate_session_restaurant_id(request.session)
        if not restaurant:
            return JsonResponse({
                'success': False,
                'error': 'Restaurant context required. Please scan QR code.',
                'redirect': '/accounts/login/'
            }, status=400)
        return view_func(request, *args, **kwargs)
    
    return wrapper


# ============================================================================
# AUDIT LOGGING
# ============================================================================

def log_security_event(event_type, user, description, ip_address=None, extra_data=None):
    """
    Log security-related events for audit trail.
    
    Args:
        event_type: Type of event (login, logout, failed_login, permission_denied, etc.)
        user: User object or None for anonymous
        description: Human-readable description
        ip_address: Client IP address
        extra_data: Dict of additional data to log
    """
    from accounts.models import AuditLog
    
    try:
        AuditLog.objects.create(
            event_type=event_type,
            user=user if user and user.is_authenticated else None,
            username=user.username if user and hasattr(user, 'username') else 'anonymous',
            description=description,
            ip_address=ip_address or '',
            extra_data=extra_data or {}
        )
    except Exception as e:
        logger.error(f"Failed to create audit log: {e}")


def get_client_ip(request):
    """Get client IP address from request, handling proxies"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('HTTP_X_REAL_IP')
        if not ip:
            ip = request.META.get('REMOTE_ADDR', '')
    return ip


def audit_action(action_type, model_name=None):
    """
    Decorator to automatically log view actions.
    
    Usage:
        @audit_action('create', 'Product')
        def create_product(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)
            
            # Log successful actions (2xx responses)
            if hasattr(response, 'status_code') and 200 <= response.status_code < 300:
                description = f"{action_type.upper()} {model_name or 'resource'}"
                if kwargs:
                    description += f" (params: {kwargs})"
                
                log_security_event(
                    event_type=f'action_{action_type}',
                    user=request.user,
                    description=description,
                    ip_address=get_client_ip(request),
                    extra_data={
                        'view': view_func.__name__,
                        'method': request.method,
                        'path': request.path
                    }
                )
            
            return response
        return wrapper
    return decorator
