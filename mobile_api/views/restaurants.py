import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response

from restaurant.models_restaurant import Restaurant
from accounts.models import RestaurantSubscription

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def restaurant_by_qr(request):
    """
    Resolve a QR code string to a restaurant.
    GET /api/mobile/restaurants/scan/?code=<qr_code>
    Returns the same restaurant object used by restaurants_list so the
    client can set its X-Restaurant-ID header and proceed to table selection.
    """
    qr_code = request.query_params.get('code', '').strip().rstrip('/')
    if not qr_code:
        return Response({'error': 'QR code is required.'}, status=400)

    try:
        restaurant_obj = Restaurant.objects.select_related(
            'branch_owner', 'main_owner', 'parent_restaurant'
        ).get(qr_code=qr_code)
    except Restaurant.DoesNotExist:
        return Response({'error': 'Invalid QR code. Restaurant not found.'}, status=404)

    owner = restaurant_obj.branch_owner or restaurant_obj.main_owner
    if not owner or not owner.is_active:
        return Response({'error': 'This restaurant is currently unavailable.'}, status=404)

    # Check subscription — branches cascade to main owner's subscription
    subscription_owner = owner
    if not restaurant_obj.is_main_restaurant and restaurant_obj.main_owner:
        subscription_owner = restaurant_obj.main_owner

    try:
        subscription = RestaurantSubscription.objects.get(restaurant_owner=subscription_owner)
        if not subscription.is_active:
            return Response({'error': 'This restaurant is temporarily unavailable.'}, status=403)
    except RestaurantSubscription.DoesNotExist:
        return Response({'error': 'This restaurant is temporarily unavailable.'}, status=403)

    logo_url = None
    if restaurant_obj.logo:
        try:
            logo_url = request.build_absolute_uri(restaurant_obj.logo.url)
        except Exception as e:
            logger.warning('Failed to build logo URL for restaurant %s: %s', restaurant_obj.id, e)

    return Response({
        'restaurant': {
            'id': restaurant_obj.id,
            'name': restaurant_obj.name,
            'description': restaurant_obj.description or '',
            'address': restaurant_obj.address or '',
            'logo_url': logo_url,
            'allow_remote_orders': restaurant_obj.allow_remote_orders,
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def restaurants_list(request):
    """
    Return all active restaurants available for customer ordering.
    Each entry uses `id` (Restaurant.id) as the identifier — clients send this
    as the X-Restaurant-ID header.  No internal User IDs are exposed.
    Only restaurants with an active subscription are returned — mirrors the
    subscription check performed by the web's qr_code_access view and the
    mobile's restaurant_by_qr endpoint.
    """
    restaurants = Restaurant.objects.select_related(
        'branch_owner', 'main_owner', 'parent_restaurant'
    ).order_by('name')

    # Pre-fetch all active subscription owner IDs to avoid N+1 queries.
    active_owner_ids = set(
        RestaurantSubscription.objects.filter(
            subscription_status='active',
            is_blocked_by_admin=False,
        ).values_list('restaurant_owner_id', flat=True)
    )

    data = []
    for r in restaurants:
        owner = r.branch_owner or r.main_owner
        if not owner or not owner.is_active:
            continue

        # Branches cascade to their main owner's subscription.
        subscription_owner = owner
        if not r.is_main_restaurant and r.main_owner:
            subscription_owner = r.main_owner

        if subscription_owner.id not in active_owner_ids:
            continue

        logo_url = None
        if r.logo:
            try:
                logo_url = request.build_absolute_uri(r.logo.url)
            except Exception as e:
                logger.warning('Failed to build logo URL for restaurant %s: %s', r.id, e)

        data.append({
            'id': r.id,          # use this as X-Restaurant-ID
            'name': r.name,
            'description': r.description or '',
            'address': r.address or '',
            'logo_url': logo_url,
            'allow_remote_orders': r.allow_remote_orders,
        })

    return Response({'restaurants': data})
