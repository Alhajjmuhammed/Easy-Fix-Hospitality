"""
Shared helper used by all mobile API views.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()


def client_supports_delivery_fee(request):
    """App builds that show the delivery fee send 'X-App-Features: delivery-fee'."""
    features = request.headers.get('X-App-Features', '') if request is not None else ''
    return 'delivery-fee' in {f.strip() for f in features.split(',')}


def customer_restaurant_q(request, owner, prefix=''):
    """
    For customers, a Q limiting rows to the one restaurant they selected (plus legacy
    rows that only carry the owner FK). A main owner is also main_owner of every branch,
    so owner-based filters alone would mix branch menus/tables into the main restaurant.
    Returns None for staff or when no restaurant id was sent.
    """
    if not request.user.is_customer():
        return None
    rid = (
        request.headers.get('X-Restaurant-ID')
        or request.GET.get('restaurant_id')
        or (request.data.get('restaurant_id') if hasattr(request, 'data') else None)
    )
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    return Q(**{f'{prefix}restaurant_id': rid}) | Q(**{f'{prefix}restaurant__isnull': True, f'{prefix}owner': owner})


def open_restaurant_owner(restaurant):
    """
    The restaurant's owner account if customers may use it right now, else None
    (restaurant inactive, owner deactivated, or subscription blocked/expired).
    """
    owner = restaurant.branch_owner or restaurant.main_owner
    # Blocking/expiring a subscription deactivates the owner account.
    if not restaurant.is_active or not owner or not owner.is_active:
        return None
    from accounts.models import RestaurantSubscription
    sub = RestaurantSubscription.objects.filter(restaurant_owner=restaurant.main_owner or owner).first()
    if sub and not sub.is_active:
        return None
    return owner


def get_restaurant_owner(request):
    """
    Return the restaurant owner (User with owner role) relevant to this request.

    - Staff (cashier, customer_care, owner, manager) → resolved via user.get_owner()
    - Customer → resolved via:
        1. X-Restaurant-ID request header  (Restaurant.id — NOT a User ID)
        2. restaurant_id query / POST param
        3. user.get_owner() fallback
    Returns None if no restaurant can be resolved.
    """
    user = request.user

    if not user.is_customer():
        return user.get_owner()

    # Customer path: pick up restaurant context from the request.
    # X-Restaurant-ID / restaurant_id carries a Restaurant.id (not a User ID).
    restaurant_id = (
        request.headers.get('X-Restaurant-ID')
        or request.GET.get('restaurant_id')
        or (request.data.get('restaurant_id') if hasattr(request, 'data') else None)
    )

    if restaurant_id:
        try:
            from restaurant.models_restaurant import Restaurant
            restaurant = Restaurant.objects.select_related(
                'branch_owner', 'main_owner'
            ).get(id=int(restaurant_id))
            return open_restaurant_owner(restaurant)
        except Exception:
            pass

    # Last resort: owner FK on the customer user
    return user.get_owner()
