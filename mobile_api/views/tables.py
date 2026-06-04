from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Q

from restaurant.models import TableInfo
from orders.models import Order
from ..serializers import TableSerializer
from .helpers import get_restaurant_owner


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def tables(request):
    """List all tables for the restaurant."""
    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    qs = TableInfo.objects.filter(
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    ).distinct().order_by('tbl_no')
    return Response({'tables': TableSerializer(qs, many=True).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def table_detail(request, table_id):
    """Single table with active-order count."""
    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    table = get_object_or_404(
        TableInfo,
        Q(owner=owner) | Q(restaurant__main_owner=owner) | Q(restaurant__branch_owner=owner),
        id=table_id,
    )

    active_count = Order.objects.filter(
        table_info=table,
        status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
        payment_status__in=['unpaid', 'partial'],
    ).count()

    data = TableSerializer(table).data
    data['active_orders_count'] = active_count
    return Response(data)
