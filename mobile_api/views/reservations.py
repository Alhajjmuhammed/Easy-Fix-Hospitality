"""Table reservations API (customers book/cancel; staff list, add, change status, assign tables)."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from restaurant.models import TableInfo
from restaurant.models_reservation import Reservation, reservations_for_owner
from restaurant.models_restaurant import Restaurant
from restaurant import reservations as svc
from ..permissions import IsSubscriptionActive
from .helpers import get_restaurant_owner


def _is_staff(user):
    return (user.is_owner() or user.is_main_owner() or user.is_branch_owner() or user.is_manager()
            or user.is_cashier() or user.is_customer_care())


def _serialize(res, staff=False):
    local = timezone.localtime(res.start)
    data = {
        'id': res.id,
        'restaurant_id': res.restaurant_id,
        'restaurant_name': res.restaurant.name,
        'name': res.name,
        'party_size': res.party_size,
        'start': res.start.isoformat(),
        'date': local.strftime('%Y-%m-%d'),
        'time': local.strftime('%H:%M'),
        'duration_minutes': res.duration_minutes,
        'table_id': res.table_id,
        'table_number': res.table.tbl_no if res.table_id else None,
        'status': res.status,
        'status_display': res.get_status_display(),
        'notes': res.notes,
    }
    if staff:
        data.update({
            'phone': res.phone,
            'email': res.email,
            'staff_notes': res.staff_notes,
            'source': res.source,
            'warnings': res.warnings() if res.is_active else [],
            'next_statuses': list(Reservation.STAFF_TRANSITIONS.get(res.status, ())),
        })
    else:
        data.update({'phone': res.phone, 'can_cancel': res.can_customer_cancel()})
    return data


def _error(e):
    return Response({'error': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)


def _staff_scope(request):
    """(owner, error_response) for staff with reservation permission."""
    user = request.user
    if not _is_staff(user) or not (user.has_feature('view_reservations') or user.has_feature('manage_reservations')):
        return None, Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
    owner = get_restaurant_owner(request)
    if owner is None:
        return None, Response({'error': 'Restaurant not found.'}, status=status.HTTP_404_NOT_FOUND)
    return owner, None


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def reservations(request):
    user = request.user
    if user.is_customer():
        return _customer_reservations(request)

    owner, denied = _staff_scope(request)
    if denied:
        return denied

    if request.method == 'POST':
        if not user.has_feature('manage_reservations'):
            return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
        restaurants = Restaurant.objects.filter(Q(branch_owner=owner) | Q(main_owner=owner))
        rid = request.data.get('restaurant_id')
        restaurant = restaurants.filter(id=rid).first() if rid else Restaurant.for_owner(owner)
        if restaurant is None:
            return Response({'error': 'Restaurant not found.'}, status=status.HTTP_404_NOT_FOUND)
        table = None
        if request.data.get('table_id'):
            table = TableInfo.objects.filter(id=request.data['table_id'], restaurant=restaurant).first()
            if table is None:
                return Response({'error': 'Table not found.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            start = svc.parse_start(request.data.get('date'), request.data.get('time'))
            res, warnings = svc.create_reservation(
                restaurant, name=request.data.get('name'), phone=request.data.get('phone'),
                email=request.data.get('email', ''), party_size=request.data.get('party_size'),
                start=start, notes=request.data.get('notes', ''), table=table,
                created_by=user, source='staff', staff=True,
            )
        except ValidationError as e:
            return _error(e)
        return Response({'reservation': _serialize(res, staff=True), 'warnings': warnings},
                        status=status.HTTP_201_CREATED)

    try:
        day = timezone.datetime.strptime(request.GET.get('date', ''), '%Y-%m-%d').date()
    except ValueError:
        day = timezone.localdate()
    qs = reservations_for_owner(owner).select_related('restaurant', 'table').filter(start__date=day)
    status_filter = request.GET.get('status', 'active')
    if status_filter == 'active':
        qs = qs.filter(status__in=Reservation.ACTIVE_STATUSES)
    elif status_filter in dict(Reservation.STATUS_CHOICES):
        qs = qs.filter(status=status_filter)
    pending = reservations_for_owner(owner).select_related('restaurant', 'table') \
        .filter(status='pending', start__gte=timezone.now()).order_by('start')[:20]
    return Response({
        'date': day.isoformat(),
        'reservations': [_serialize(r, staff=True) for r in qs],
        'pending_upcoming': [_serialize(r, staff=True) for r in pending],
        'can_manage': user.has_feature('manage_reservations'),
    })


def _customer_reservations(request):
    user = request.user
    if request.method == 'GET':
        qs = Reservation.objects.filter(customer=user).select_related('restaurant', 'table')
        cutoff = timezone.now() - timedelta(days=30)
        return Response({'reservations': [_serialize(r) for r in qs.filter(start__gte=cutoff).order_by('-start')[:50]]})

    # Booking: the restaurant comes from X-Restaurant-ID and must be bookable and not blocked.
    if get_restaurant_owner(request) is None:
        return Response({'error': 'Restaurant not found.'}, status=status.HTTP_404_NOT_FOUND)
    rid = request.headers.get('X-Restaurant-ID') or request.data.get('restaurant_id')
    try:
        restaurant = Restaurant.objects.filter(id=int(rid)).first()
    except (TypeError, ValueError):
        restaurant = None
    if restaurant is None:
        return Response({'error': 'Restaurant not found.'}, status=status.HTTP_404_NOT_FOUND)
    try:
        start = svc.parse_start(request.data.get('date'), request.data.get('time'))
        res, _ = svc.create_reservation(
            restaurant, name=request.data.get('name') or user.get_full_name() or user.username,
            phone=request.data.get('phone') or getattr(user, 'phone_number', ''),
            email=user.email or '', party_size=request.data.get('party_size'), start=start,
            notes=request.data.get('notes', ''), customer=user, created_by=user, source='app',
        )
    except ValidationError as e:
        return _error(e)
    return Response({'reservation': _serialize(res)}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def reservation_status(request, pk):
    owner, denied = _staff_scope(request)
    if denied:
        return denied
    if not request.user.has_feature('manage_reservations'):
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
    res = get_object_or_404(reservations_for_owner(owner), pk=pk)
    try:
        res = svc.change_status(res, request.data.get('status', ''), request.user)
    except ValidationError as e:
        return _error(e)
    return Response({'reservation': _serialize(res, staff=True)})


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def reservation_table(request, pk):
    owner, denied = _staff_scope(request)
    if denied:
        return denied
    if not request.user.has_feature('manage_reservations'):
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
    res = get_object_or_404(reservations_for_owner(owner).select_related('restaurant'), pk=pk)
    table = None
    if request.data.get('table_id'):
        table = TableInfo.objects.filter(id=request.data['table_id'], restaurant=res.restaurant).first()
        if table is None:
            return Response({'error': 'Table not found.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        warnings = svc.assign_table(res, table, request.user)
    except ValidationError as e:
        return _error(e)
    return Response({'reservation': _serialize(res, staff=True), 'warnings': warnings})


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def reservation_cancel(request, pk):
    """Customer cancels their own booking."""
    if not request.user.is_customer():
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
    res = get_object_or_404(Reservation, pk=pk, customer=request.user)
    try:
        res = svc.customer_cancel(res, request.user)
    except ValidationError as e:
        return _error(e)
    return Response({'reservation': _serialize(res)})
