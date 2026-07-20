import logging
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db.models import Case, When, IntegerField, F
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from ..permissions import IsSubscriptionActive
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.db import transaction

from orders.models import Order, DeliveryRider, DeliveryAssignment
from accounts.models import User
from .helpers import get_restaurant_owner

logger = logging.getLogger(__name__)


def _notify_delivery_status(order_id, assignment_status, status_display):
    """Broadcast a delivery status change to the delivery WS group."""
    def _send():
        try:
            cl = get_channel_layer()
            if cl is None:
                return
            async_to_sync(cl.group_send)(
                f'delivery_{order_id}',
                {
                    'type': 'delivery_status_update',
                    'status': assignment_status,
                    'status_display': status_display,
                    'timestamp': timezone.now().isoformat(),
                },
            )
        except Exception as e:
            logger.error(f'_notify_delivery_status error: {e}')
    transaction.on_commit(_send)


# ── Rider profile helpers ──────────────────────────────────────────────────────

def _rider_data(rider, owner_id=None):
    if rider.owner_id:
        restaurant = rider.owner.restaurant_name or rider.owner.username
        is_local = (rider.owner_id == owner_id) if owner_id is not None else True
    else:
        restaurant = 'Global'
        is_local = False
    return {
        'id': rider.id,
        'user_id': rider.user_id,
        'name': rider.user.get_full_name() or rider.user.username,
        'phone': rider.user.phone_number,
        'vehicle': rider.vehicle_type,
        'vehicle_display': rider.get_vehicle_type_display(),
        'is_available': rider.is_available,
        'is_active': rider.is_active,
        'restaurant': restaurant,
        'owner_id': rider.owner_id,
        'is_local': is_local,
        'is_global': rider.owner_id is None,
    }


def _assignment_data(a):
    return {
        'id': a.id,
        'order_id': a.order_id,
        'order_number': a.order.order_number,
        'order_status': a.order.status,
        'delivery_address': a.order.delivery_address,
        'delivery_phone': a.order.delivery_phone,
        'delivery_lat': float(a.order.delivery_lat) if a.order.delivery_lat is not None else None,
        'delivery_lng': float(a.order.delivery_lng) if a.order.delivery_lng is not None else None,
        'status': a.status,
        'status_display': a.get_status_display(),
        'assigned_at': a.assigned_at.isoformat(),
        'picked_up_at': a.picked_up_at.isoformat() if a.picked_up_at else None,
        'delivered_at': a.delivered_at.isoformat() if a.delivered_at else None,
        'rider': _rider_data(a.rider),
        'customer_name': (
            a.order.ordered_by.get_full_name() or a.order.ordered_by.username
            if a.order.ordered_by else 'Guest'
        ),
        'total_amount': str(a.order.total_amount),
        'items': [
            {
                'name': i.product.name if i.product else '[deleted]',
                'qty': i.quantity,
            }
            for i in a.order.order_items.select_related('product').all()
        ],
    }


# ── Endpoint: list available riders for assignment ─────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def riders_list(request):
    """
    GET /api/v1/delivery/riders/
    Returns riders belonging to the caller's restaurant.
    Allowed for: owner, cashier, customer_care, manager, administrator.
    """
    user = request.user
    if not (user.is_owner() or user.is_main_owner() or user.is_branch_owner() or
            user.is_cashier() or user.is_customer_care() or user.is_manager() or
            user.is_administrator()):
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

    owner = get_restaurant_owner(request)
    if not owner and not user.is_administrator():
        return Response({'error': 'No restaurant context.'}, status=status.HTTP_400_BAD_REQUEST)

    scope = request.GET.get('scope', 'local')
    only_available = request.GET.get('available') == '1'

    qs = DeliveryRider.objects.select_related('user', 'owner').filter(is_active=True)
    if only_available:
        qs = qs.filter(is_available=True)

    owner_id = owner.id if owner else None

    if user.is_administrator() or scope == 'global':
        # Global pool: all restaurants + global riders, local riders sorted first
        if owner_id:
            qs = qs.annotate(
                _priority=Case(
                    When(owner_id=owner_id, then=0),   # own restaurant first
                    When(owner_id=None, then=1),        # global riders second
                    default=2,                          # other restaurants last
                    output_field=IntegerField(),
                )
            ).order_by('_priority', F('last_location_at').desc(nulls_last=True))
        else:
            qs = qs.order_by(F('last_location_at').desc(nulls_last=True))
    else:
        # Local only: this restaurant's riders + global riders (no owner)
        if owner:
            from django.db.models import Q as _Q
            qs = qs.filter(_Q(owner=owner) | _Q(owner__isnull=True))

    return Response({'riders': [_rider_data(r, owner_id) for r in qs]})


# ── Endpoint: assign a rider to a delivery order ───────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def assign_rider(request):
    """
    POST /api/v1/delivery/assign/
    Body: { order_id, rider_id }
    Moves order to out_for_delivery and creates DeliveryAssignment.
    Allowed for: owner, cashier, customer_care, manager.
    """
    user = request.user
    if not (user.is_owner() or user.is_main_owner() or user.is_branch_owner() or
            user.is_cashier() or user.is_customer_care() or user.is_manager() or
            user.is_administrator()):
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

    order_id = request.data.get('order_id')
    rider_id = request.data.get('rider_id')
    if not order_id or not rider_id:
        return Response({'error': 'order_id and rider_id are required.'}, status=status.HTTP_400_BAD_REQUEST)

    rider = get_object_or_404(DeliveryRider, id=rider_id, is_active=True)

    if not user.is_administrator():
        from django.db.models import Q as _Q
        owner = get_restaurant_owner(request)
        order_scope = (
            _Q(table_info__owner=owner) |
            _Q(table_info__restaurant__main_owner=owner) |
            _Q(table_info__restaurant__branch_owner=owner) |
            _Q(ordered_by__owner=owner) |
            _Q(ordered_by__owner__managed_restaurant__main_owner=owner)
        )
        order = get_object_or_404(Order, order_scope, id=order_id, order_type='delivery')
    else:
        order = get_object_or_404(Order, id=order_id, order_type='delivery')

    try:
        with transaction.atomic():
            # Re-fetch with row lock — prevents two cashiers assigning the same
            # global rider simultaneously (critical for cross-restaurant pool).
            rider = DeliveryRider.objects.select_for_update().get(id=rider.id)
            if not rider.is_available:
                raise ValueError('This rider just became unavailable. Please select another.')

            DeliveryAssignment.objects.filter(order=order).delete()
            assignment = DeliveryAssignment.objects.create(order=order, rider=rider)
            rider.is_available = False
            rider.save(update_fields=['is_available'])
            order.status = 'out_for_delivery'
            order.save(update_fields=['status', 'updated_at'])
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)

    _notify_delivery_status(order.id, 'assigned', 'Assigned')
    return Response({'success': True, 'assignment': _assignment_data(assignment)})


# ── Endpoint: auto-assign best available rider (local first, then global) ─────

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def auto_assign_rider(request):
    """
    POST /api/v1/delivery/auto-assign/
    Body: { order_id }
    System picks the best available rider automatically:
      1. Tries the restaurant's own riders first (sorted by most recently active).
      2. Falls back to any globally available rider if none are local.
    Returns who was assigned and whether they came from a local or global pool.
    """
    user = request.user
    if not (user.is_owner() or user.is_main_owner() or user.is_branch_owner() or
            user.is_cashier() or user.is_customer_care() or user.is_manager() or
            user.is_administrator()):
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

    order_id = request.data.get('order_id')
    if not order_id:
        return Response({'error': 'order_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

    order = get_object_or_404(Order, id=order_id, order_type='delivery')

    owner = get_restaurant_owner(request)

    from django.db.models import Q as _Q
    available_qs = DeliveryRider.objects.select_related('user', 'owner').filter(
        is_active=True, is_available=True
    ).order_by(F('last_location_at').desc(nulls_last=True))

    # Step 1: try local riders (this restaurant only, not global pool yet)
    if owner and not user.is_administrator():
        local_qs = available_qs.filter(owner=owner)
    else:
        local_qs = available_qs
    rider = local_qs.first()
    source = 'local'

    # Step 2: fall back to global riders (null owner), then any restaurant
    if not rider and owner and not user.is_administrator():
        rider = available_qs.filter(owner__isnull=True).first()
        if rider:
            source = 'global'
        else:
            rider = available_qs.exclude(owner=owner).first()
            if rider:
                source = 'global'

    if not rider:
        return Response(
            {'error': 'No available riders at this time. All riders are currently on deliveries.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Lock the chosen rider inside the transaction to prevent double-assignment
    # when multiple cashiers auto-assign from the global pool simultaneously.
    assignment = None
    try:
        with transaction.atomic():
            locked = DeliveryRider.objects.select_related('user', 'owner').select_for_update().filter(
                id=rider.id, is_available=True
            ).first()
            if not locked:
                raise ValueError('Rider was just taken. Try again.')

            DeliveryAssignment.objects.filter(order=order).delete()
            assignment = DeliveryAssignment.objects.create(order=order, rider=locked)
            locked.is_available = False
            locked.save(update_fields=['is_available'])
            order.status = 'out_for_delivery'
            order.save(update_fields=['status', 'updated_at'])
            rider = locked  # use the locked instance for the response
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)

    _notify_delivery_status(order.id, 'assigned', 'Assigned')
    return Response({
        'success': True,
        'source': source,
        'rider_name': rider.user.get_full_name() or rider.user.username,
        'rider_restaurant': (rider.owner.restaurant_name or rider.owner.username) if rider.owner_id else 'Global',
        'is_cross_restaurant': source == 'global',
        'assignment': _assignment_data(assignment),
    })


# ── Endpoint: rider pushes GPS location (REST fallback when WS is down) ───────

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def update_location(request):
    """
    POST /api/v1/delivery/location/
    Body: { lat, lng }
    Only the assigned delivery rider for any active order can call this.
    Persists to DB and broadcasts via WebSocket group.
    """
    user = request.user
    if not user.is_delivery_rider():
        return Response({'error': 'Only delivery riders can update location.'}, status=status.HTTP_403_FORBIDDEN)

    lat = request.data.get('lat')
    lng = request.data.get('lng')
    if lat is None or lng is None:
        return Response({'error': 'lat and lng are required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        rider = user.rider_profile
    except DeliveryRider.DoesNotExist:
        return Response({'error': 'Rider profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    rider.current_lat = lat
    rider.current_lng = lng
    rider.last_location_at = timezone.now()
    rider.save(update_fields=['current_lat', 'current_lng', 'last_location_at'])

    # Broadcast to all active delivery groups this rider is involved in
    active = DeliveryAssignment.objects.filter(
        rider=rider,
        status__in=['assigned', 'picked_up']
    ).values_list('order_id', flat=True)

    def _broadcast():
        cl = get_channel_layer()
        if not cl:
            return
        ts = timezone.now().isoformat()
        for oid in active:
            try:
                async_to_sync(cl.group_send)(
                    f'delivery_{oid}',
                    {
                        'type': 'location_broadcast',
                        'lat': float(lat),
                        'lng': float(lng),
                        'timestamp': ts,
                    },
                )
            except Exception as e:
                logger.error(f'location broadcast error for order {oid}: {e}')

    transaction.on_commit(_broadcast)
    return Response({'success': True})


# ── Endpoint: customer / staff get current tracking info ──────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def track_order(request, order_id):
    """
    GET /api/v1/delivery/<order_id>/track/
    Returns rider's current GPS + assignment details.
    """
    order = get_object_or_404(Order, id=order_id)
    user = request.user

    # Permission: the customer who placed it, the assigned rider, or restaurant staff
    can_view = user.is_administrator() or order.ordered_by == user

    if not can_view:
        try:
            assignment = order.delivery_assignment
            can_view = assignment.rider.user == user
        except DeliveryAssignment.DoesNotExist:
            pass

    if not can_view:
        # Staff: verify the order belongs to their restaurant using the same ownership
        # filter pattern as _list_orders (covers dine-in, delivery, and pickup).
        owner = get_restaurant_owner(request)
        if owner:
            from django.db.models import Q as _Q
            _stq = (
                _Q(table_info__owner=owner) |
                _Q(table_info__restaurant__main_owner=owner) |
                _Q(table_info__restaurant__branch_owner=owner) |
                _Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) |
                _Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
            )
            can_view = Order.objects.filter(_stq, id=order.id).exists()

    if not can_view:
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)

    try:
        assignment = DeliveryAssignment.objects.select_related(
            'rider__user', 'order'
        ).get(order=order)
    except DeliveryAssignment.DoesNotExist:
        return Response({'error': 'No delivery assignment for this order.'}, status=status.HTTP_404_NOT_FOUND)

    rider = assignment.rider
    return Response({
        'assignment': _assignment_data(assignment),
        'rider_lat': float(rider.current_lat) if rider.current_lat else None,
        'rider_lng': float(rider.current_lng) if rider.current_lng else None,
        'last_location_at': rider.last_location_at.isoformat() if rider.last_location_at else None,
    })


# ── Endpoint: rider marks order as picked up ──────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def mark_picked_up(request, order_id):
    """
    POST /api/v1/delivery/<order_id>/pickup/
    Only the assigned rider can call this.
    """
    user = request.user
    if not user.is_delivery_rider():
        return Response({'error': 'Only delivery riders can call this.'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id)
    try:
        assignment = DeliveryAssignment.objects.select_related('rider__user').get(order=order)
    except DeliveryAssignment.DoesNotExist:
        return Response({'error': 'No assignment found.'}, status=status.HTTP_404_NOT_FOUND)

    if assignment.rider.user != user:
        return Response({'error': 'You are not the assigned rider.'}, status=status.HTTP_403_FORBIDDEN)

    if assignment.status != 'assigned':
        return Response({'error': f'Cannot pick up — current status is {assignment.status}.'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        assignment.status = 'picked_up'
        assignment.picked_up_at = timezone.now()
        assignment.save(update_fields=['status', 'picked_up_at'])

    _notify_delivery_status(order.id, 'picked_up', 'Picked Up')
    return Response({'success': True, 'status': 'picked_up'})


# ── Endpoint: rider marks order as delivered ──────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def mark_delivered(request, order_id):
    """
    POST /api/v1/delivery/<order_id>/complete/
    Only the assigned rider can call this.
    """
    user = request.user
    if not user.is_delivery_rider():
        return Response({'error': 'Only delivery riders can call this.'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id)
    try:
        assignment = DeliveryAssignment.objects.select_related('rider__user').get(order=order)
    except DeliveryAssignment.DoesNotExist:
        return Response({'error': 'No assignment found.'}, status=status.HTTP_404_NOT_FOUND)

    if assignment.rider.user != user:
        return Response({'error': 'You are not the assigned rider.'}, status=status.HTTP_403_FORBIDDEN)

    if assignment.status not in ('assigned', 'picked_up'):
        return Response({'error': f'Cannot complete — status is {assignment.status}.'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        assignment.status = 'delivered'
        assignment.delivered_at = timezone.now()
        assignment.save(update_fields=['status', 'delivered_at'])

        # Mark rider available again
        rider = assignment.rider
        rider.is_available = True
        rider.save(update_fields=['is_available'])

        # Update the order to delivered
        order.status = 'delivered'
        order.save(update_fields=['status', 'updated_at'])

    _notify_delivery_status(order.id, 'delivered', 'Delivered')
    return Response({'success': True, 'status': 'delivered'})


# ── Endpoint: rider sees their own assignments ─────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def my_assignments(request):
    """
    GET /api/v1/delivery/assignments/
    Returns the rider's active and recent assignments.
    """
    user = request.user
    if not user.is_delivery_rider():
        return Response({'error': 'Only delivery riders can call this.'}, status=status.HTTP_403_FORBIDDEN)

    try:
        rider = user.rider_profile
    except DeliveryRider.DoesNotExist:
        return Response({'error': 'Rider profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    assignments = DeliveryAssignment.objects.select_related(
        'order__ordered_by', 'rider__user'
    ).prefetch_related('order__order_items__product').filter(
        rider=rider
    ).order_by('-assigned_at')[:20]

    return Response({
        'is_available': rider.is_available,
        'assignments': [_assignment_data(a) for a in assignments],
    })


# ── Endpoint: toggle rider availability ───────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def toggle_availability(request):
    """
    POST /api/v1/delivery/availability/
    Rider toggles their own availability flag.
    """
    user = request.user
    if not user.is_delivery_rider():
        return Response({'error': 'Only delivery riders can call this.'}, status=status.HTTP_403_FORBIDDEN)

    try:
        rider = user.rider_profile
    except DeliveryRider.DoesNotExist:
        return Response({'error': 'Rider profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    rider.is_available = not rider.is_available
    rider.save(update_fields=['is_available'])
    return Response({'success': True, 'is_available': rider.is_available})
