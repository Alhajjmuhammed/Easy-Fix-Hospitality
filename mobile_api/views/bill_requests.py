import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone

from orders.models import BillRequest, Order
from restaurant.models import TableInfo
from django.db.models import Q
from ..serializers import BillRequestSerializer
from .helpers import get_restaurant_owner

logger = logging.getLogger(__name__)


def _is_bill_staff(user):
    return (
        user.is_cashier() or user.is_customer_care() or
        user.is_owner() or user.is_main_owner() or
        user.is_branch_owner() or user.is_manager()
    )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def bill_requests(request):
    if request.method == 'GET':
        return _list_bill_requests(request)
    return _create_bill_request(request)


def _list_bill_requests(request):
    if not _is_bill_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    qs = BillRequest.objects.filter(
        _tq,
        status='pending',
    ).distinct().select_related('table_info', 'requested_by').order_by('-created_at')

    return Response({'bill_requests': BillRequestSerializer(qs, many=True).data})


def _create_bill_request(request):
    user = request.user
    # Staff roles (cashier, owner, manager, customer_care) may also create bill requests
    is_staff_user = _is_bill_staff(user)
    if not user.is_customer() and not is_staff_user:
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    table_id = request.data.get('table_id')
    if not table_id:
        return Response({'error': 'table_id is required.'}, status=400)

    _tq_br = (
        Q(owner=owner) |
        Q(restaurant__main_owner=owner) |
        Q(restaurant__branch_owner=owner)
    )
    table = get_object_or_404(TableInfo.objects.filter(_tq_br).distinct(), id=table_id)

    # Mirror web's request_bill: customer must have an active unpaid order at this table.
    has_active_order = Order.objects.filter(
        table_info=table,
        ordered_by=user,
        status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
        payment_status__in=['unpaid', 'partial'],
    ).exists()
    if not has_active_order:
        return Response(
            {'error': 'You do not have an active order at this table.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Mirror web's request_bill: prevent duplicate pending bill requests.
    # Wrapped in a transaction with select_for_update to prevent TOCTOU duplicates
    # from two simultaneous POST requests from the same table.
    from django.db import transaction as _tx
    with _tx.atomic():
        existing = BillRequest.objects.select_for_update(of=('self',)).filter(table_info=table, status='pending').first()
        if existing:
            return Response(
                {
                    'bill_request': BillRequestSerializer(existing).data,
                    'message': f'Bill already requested for Table {table.tbl_no}. Staff will bring it shortly.',
                },
                status=status.HTTP_200_OK,
            )

        br = BillRequest.objects.create(
            table_info=table,
            requested_by=user,
            status='pending',
        )
    logger.info('Bill request created: table %s by %s', table.tbl_no, user.username)

    return Response(
        {'bill_request': BillRequestSerializer(br).data, 'message': 'Bill request submitted.'},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def complete_bill_request(request, request_id):
    if not _is_bill_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner)
    )
    from django.db import transaction as _tx2
    br = get_object_or_404(BillRequest.objects.filter(_tq).distinct(), id=request_id)
    with _tx2.atomic():
        br = BillRequest.objects.select_for_update(of=('self',)).get(pk=br.pk)
        if br.status == 'completed':
            return Response({'message': 'Already completed.'})
        br.status = 'completed'
        br.completed_by = request.user
        br.completed_at = timezone.now()
        br.save(update_fields=['status', 'completed_by', 'completed_at'])

    return Response({'message': 'Bill request marked as completed.'})
