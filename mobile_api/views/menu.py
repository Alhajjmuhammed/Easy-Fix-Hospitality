from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.db.models import Prefetch, Q

from restaurant.models import MainCategory, SubCategory, Product
from ..serializers import CategorySerializer, ProductSerializer
from .helpers import get_restaurant_owner


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def menu(request):
    """
    Full menu for a restaurant.

    Query params:
      - restaurant_id  : (customers) which restaurant
      - since          : ISO-8601 datetime – return only items updated after this time
    """
    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    since_param = request.GET.get('since')
    _cat_q = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )
    categories = MainCategory.objects.filter(_cat_q, is_active=True).distinct().order_by('name')

    if since_param:
        try:
            since_dt = parse_datetime(since_param)
            if since_dt:
                changed_cat_ids = Product.objects.filter(
                    Q(main_category__owner=owner) |
                    Q(main_category__restaurant__main_owner=owner) |
                    Q(main_category__restaurant__branch_owner=owner),
                    updated_at__gt=since_dt,
                ).values_list('main_category_id', flat=True).distinct()

                categories = categories.filter(
                    updated_at__gt=since_dt
                ) | categories.filter(id__in=changed_cat_ids)
        except Exception:
            pass  # Bad format → return full menu

    categories = categories.prefetch_related(
        Prefetch(
            'subcategories',
            queryset=SubCategory.objects.filter(is_active=True).prefetch_related(
                Prefetch(
                    'products',
                    queryset=Product.objects.filter(is_available=True).select_related('sub_category'),
                )
            ),
        )
    )

    return Response({
        'categories': CategorySerializer(categories, many=True, context={'request': request}).data,
        'synced_at': timezone.now().isoformat(),
        'restaurant_name': getattr(owner, 'restaurant_name', ''),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def menu_changes(request):
    """
    Return only products changed since a timestamp.
    Used for efficient background sync.

    Query params:
      - since  (required): ISO-8601 datetime
    """
    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    since_param = request.GET.get('since')
    if not since_param:
        return Response({'error': "'since' parameter is required."}, status=400)

    since_dt = parse_datetime(since_param)
    if not since_dt:
        return Response({'error': 'Invalid datetime format for since.'}, status=400)

    changed = Product.objects.filter(
        Q(main_category__owner=owner) |
        Q(main_category__restaurant__main_owner=owner) |
        Q(main_category__restaurant__branch_owner=owner),
        updated_at__gt=since_dt,
    ).distinct().select_related('main_category', 'sub_category')

    return Response({
        'has_changes': changed.exists(),
        'changed_products': ProductSerializer(changed, many=True, context={'request': request}).data,
        'checked_at': timezone.now().isoformat(),
    })
