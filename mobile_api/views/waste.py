import logging

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from rest_framework import status

from restaurant.models import Product
from waste_management.models import FoodWasteLog
from .helpers import get_restaurant_owner

logger = logging.getLogger(__name__)


def _allowed(user):
    return (
        user.is_cashier() or user.is_customer_care() or
        user.is_owner() or user.is_main_owner() or
        user.is_branch_owner() or user.is_manager()
    )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def waste(request):
    if not _allowed(request.user):
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return _list_waste(request, owner)
    return _record_waste(request, owner)


def _list_waste(request, owner):
    """Return recent waste logs for this restaurant."""
    _pq = (
        Q(product__main_category__owner=owner) |
        Q(product__main_category__restaurant__main_owner=owner) |
        Q(product__main_category__restaurant__branch_owner=owner)
    )
    logs = FoodWasteLog.objects.filter(_pq).distinct().select_related(
        'product', 'recorded_by'
    ).order_by('-created_at')[:50]

    data = []
    for log in logs:
        data.append({
            'id': log.id,
            'product_name': log.product.name if log.product else '[deleted product]',
            'quantity_wasted': log.quantity_wasted,
            'waste_reason': log.waste_reason,
            'disposal_method': log.disposal_method,
            'total_cost': float(log.total_cost),
            'notes': log.notes,
            'recorded_by': log.recorded_by.get_full_name() or log.recorded_by.username,
            'created_at': log.created_at.isoformat(),
        })
    return Response({'waste_logs': data})


def _record_waste(request, owner):
    """Record a new food waste log."""
    product_id = request.data.get('product_id')
    quantity = request.data.get('quantity_wasted')
    waste_reason = request.data.get('waste_reason', 'other')
    disposal_method = request.data.get('disposal_method', 'waste_bin')
    notes = request.data.get('notes', '')

    if not product_id or not quantity:
        return Response({'error': 'product_id and quantity_wasted are required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return Response({'error': 'quantity_wasted must be a positive integer.'}, status=status.HTTP_400_BAD_REQUEST)

    _pq2 = (
        Q(main_category__owner=owner) |
        Q(main_category__restaurant__main_owner=owner) |
        Q(main_category__restaurant__branch_owner=owner)
    )
    product = Product.objects.filter(_pq2, id=product_id).first()
    if product is None:
        return Response({'error': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

    valid_reasons = [r[0] for r in FoodWasteLog.WASTE_REASON_CHOICES]
    valid_methods = [m[0] for m in FoodWasteLog.DISPOSAL_METHOD_CHOICES]
    if waste_reason not in valid_reasons:
        waste_reason = 'other'
    if disposal_method not in valid_methods:
        disposal_method = 'waste_bin'

    # Costs are auto-calculated by FoodWasteLog.save() via calculate_costs()
    log = FoodWasteLog.objects.create(
        product=product,
        quantity_wasted=quantity,
        waste_reason=waste_reason,
        disposal_method=disposal_method,
        notes=notes,
        recorded_by=request.user,
    )

    logger.info('Waste recorded by %s: %s × %d (%s)', request.user, product.name, quantity, waste_reason)

    return Response({
        'success': True,
        'id': log.id,
        'product_name': product.name,
        'quantity_wasted': quantity,
        'total_cost': float(log.total_cost),
    }, status=status.HTTP_201_CREATED)
