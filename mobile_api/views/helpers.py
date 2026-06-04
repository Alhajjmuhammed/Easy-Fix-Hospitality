"""
Shared helper used by all mobile API views.
"""
from django.contrib.auth import get_user_model

User = get_user_model()


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
            return restaurant.branch_owner or restaurant.main_owner
        except Exception:
            pass

    # Last resort: owner FK on the customer user
    return user.get_owner()
