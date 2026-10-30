"""Loyalty points pages: cashier lookup/link (web + app), owner settings, customer balance."""
import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import get_owner_filter
from mobile_api.permissions import IsSubscriptionActive
from orders.models import Order
from .models_loyalty import LoyaltyProgram, LoyaltyTransaction
from . import loyalty as svc


def _staff_order_q(owner):
    """Orders of this restaurant (same rule as the payment screens)."""
    return (Q(table_info__owner=owner) | Q(table_info__restaurant__main_owner=owner)
            | Q(table_info__restaurant__branch_owner=owner)
            | Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner)
            | Q(order_type__in=['delivery', 'pickup'], restaurant_owner=owner)
            | Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
            | Q(order_type__in=['delivery', 'pickup'], restaurant_owner__managed_restaurant__main_owner=owner))


def _is_payment_staff(user):
    return (user.is_cashier() or user.is_customer_care() or user.is_any_owner() or user.is_manager()) \
        and user.has_feature('process_payments')


def _order_for_staff(user, order_id, owner=None):
    if not _is_payment_staff(user):
        raise PermissionDenied
    if owner is None:
        try:
            owner = get_owner_filter(user)
        except PermissionDenied:
            owner = None
    if owner is None:
        raise PermissionDenied
    order = get_object_or_404(Order.objects.filter(_staff_order_q(owner)).distinct(), id=order_id)
    if user.is_customer_care() and order.ordered_by_id != user.id:
        raise PermissionDenied  # same rule as the payment screens: customer care pays only their own orders
    return order


# ---------------------------------------------------------------------------
# Cashier: points for an order, link a walk-in customer (web JSON + app API)
# ---------------------------------------------------------------------------

def _order_loyalty(user, order, body, method):
    if method == 'POST':
        phone = body.get('phone', '') if isinstance(body, dict) else ''
        with transaction.atomic():
            locked = Order.objects.select_for_update(of=('self',)).get(pk=order.pk)
            svc.link_customer(locked, phone if isinstance(phone, str) else '', user)
    return svc.order_summary(order)


@login_required
@require_http_methods(['GET', 'POST'])
def order_loyalty_web(request, order_id):
    try:
        order = _order_for_staff(request.user, order_id)
    except PermissionDenied:
        return JsonResponse({'error': 'Access denied'}, status=403)
    try:
        body = json.loads(request.body or b'{}') if request.method == 'POST' else None
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid request'}, status=400)
    try:
        return JsonResponse(_order_loyalty(request.user, order, body, request.method))
    except ValidationError as e:
        return JsonResponse({'error': ' '.join(e.messages)}, status=400)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def order_loyalty_api(request, order_id):
    from mobile_api.views.helpers import get_restaurant_owner
    try:
        order = _order_for_staff(request.user, order_id, owner=get_restaurant_owner(request))
    except PermissionDenied:
        return Response({'error': 'Access denied.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        return Response(_order_loyalty(request.user, order, request.data, request.method))
    except ValidationError as e:
        return Response({'error': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Customer: my points
# ---------------------------------------------------------------------------

def _my_points(user):
    from restaurant.models_restaurant import Restaurant
    rows = (LoyaltyTransaction.objects.filter(customer=user).values('program_owner')
            .annotate(points=Sum('points')).order_by())
    out = []
    for row in rows:
        program = LoyaltyProgram.objects.filter(owner_id=row['program_owner']).first()
        if program is None or not program.enabled:
            continue
        r = Restaurant.for_owner(program.owner)
        recent = LoyaltyTransaction.objects.filter(customer=user, program_owner_id=row['program_owner'])[:10]
        out.append({
            'restaurant_name': r.name if r else (program.owner.restaurant_name or ''),
            'points': row['points'],
            'worth': str(svc.money_value(program, max(row['points'], 0))),
            'min_redeem_points': program.min_redeem_points,
            'spend_per_point': str(program.spend_per_point),
            'history': [{'points': t.points, 'kind': t.get_kind_display(), 'note': t.note,
                         'date': t.created_at.isoformat()} for t in recent],
        })
    return out


def _code_for(user, programs):
    """The customer shows this code to the cashier to spend points (customers with points only)."""
    return svc.redeem_code(user) if programs and user.is_customer() else None


@login_required
def my_points_web(request):
    programs = _my_points(request.user)
    return render(request, 'cashier/my_points.html', {'programs': programs, 'code': _code_for(request.user, programs)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_points_api(request):
    programs = _my_points(request.user)
    return Response({'programs': programs, 'code': _code_for(request.user, programs)})


# ---------------------------------------------------------------------------
# Owner: settings + customers
# ---------------------------------------------------------------------------

def _parse_money(value, label):
    try:
        d = Decimal(str(value).strip().replace(',', '')).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f'Enter a valid {label}.')
    if not d.is_finite() or d <= 0 or d >= Decimal('1000000000'):
        raise ValidationError(f'Enter a valid {label}.')
    return d


@login_required
def loyalty_settings(request):
    user = request.user
    if not user.is_any_owner():
        messages.error(request, 'Only restaurant owners can manage loyalty points.')
        return redirect('restaurant:home')
    business = svc.business_owner(user)
    can_edit = business == user           # branch owners see their business's programme, read-only
    program, _ = LoyaltyProgram.objects.get_or_create(owner=business)
    if request.method == 'POST':
        if not can_edit:
            messages.error(request, 'Loyalty points are set by the main restaurant owner.')
            return redirect('cashier:loyalty_settings')
        action = request.POST.get('action', 'settings')
        try:
            if action == 'settings':
                program.enabled = request.POST.get('enabled') == 'on'
                program.spend_per_point = _parse_money(request.POST.get('spend_per_point'), 'amount per point')
                program.point_value = _parse_money(request.POST.get('point_value'), 'value of a point')
                try:
                    program.min_redeem_points = max(1, min(1000000, int(request.POST.get('min_redeem_points'))))
                except (TypeError, ValueError):
                    raise ValidationError('Enter the minimum points to use.')
                program.save()
                messages.success(request, 'Loyalty settings saved.')
            elif action == 'adjust':
                _adjust(program, request.POST, user)
                messages.success(request, 'Points adjusted.')
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        return redirect('cashier:loyalty_settings')

    customers = (LoyaltyTransaction.objects.filter(program_owner=business).values(
        'customer', 'customer__username', 'customer__first_name', 'customer__last_name', 'customer__phone_number')
        .annotate(points=Sum('points')).order_by('-points')[:100])
    totals = LoyaltyTransaction.objects.filter(program_owner=business).aggregate(
        outstanding=Sum('points'), redeemed=Sum('points', filter=Q(kind='redeem')))
    return render(request, 'cashier/loyalty_settings.html', {
        'program': program, 'can_edit': can_edit, 'customers': customers,
        'outstanding': totals['outstanding'] or 0, 'redeemed': -(totals['redeemed'] or 0),
        'outstanding_worth': svc.money_value(program, max(totals['outstanding'] or 0, 0)),
    })


def _adjust(program, data, user):
    from accounts.models import User
    try:
        customer_id = int(data.get('customer_id'))
        points = int(data.get('points'))
    except (TypeError, ValueError):
        raise ValidationError('Enter a whole number of points.')
    if points == 0 or abs(points) > 1000000:
        raise ValidationError('Enter a whole number of points.')
    customer = User.objects.filter(pk=customer_id, role__name='customer').first()
    if customer is None or not LoyaltyTransaction.objects.filter(program_owner=program.owner, customer=customer).exists():
        raise ValidationError('Customer not found.')
    with transaction.atomic():
        LoyaltyProgram.objects.select_for_update().get(pk=program.pk)
        if svc.balance(program.owner, customer) + points < 0:
            raise ValidationError('A customer cannot go below 0 points.')
        LoyaltyTransaction.objects.create(program_owner=program.owner, customer=customer, kind='adjust',
                                          points=points, created_by=user,
                                          note=(data.get('note') or 'Manual adjustment')[:200].replace('\x00', ''))
