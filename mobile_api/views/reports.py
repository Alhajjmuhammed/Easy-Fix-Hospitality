import logging
from datetime import timedelta

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.response import Response
from django.db.models import Sum, Count, Q, F
from django.utils import timezone

from orders.models import Order, OrderItem
from .helpers import get_restaurant_owner

logger = logging.getLogger(__name__)


def _is_report_staff(user):
    return (
        user.is_customer_care() or user.is_cashier() or
        user.is_owner() or user.is_main_owner() or
        user.is_branch_owner() or user.is_manager()
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def cc_reports(request):
    """My Reports for Customer Care – mirrors the web customer_care_reports view."""
    if not _is_report_staff(request.user):
        return Response({'error': 'Access denied.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    # --- Period filter ---
    period = request.GET.get('period', 'today')
    today = timezone.now().date()

    if period == 'today':
        date_from = today
        date_to = today
    elif period == 'weekly':
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif period == 'monthly':
        date_from = today.replace(day=1)
        date_to = today
    elif period == 'yearly':
        date_from = today.replace(month=1, day=1)
        date_to = today
    else:
        date_from = today
        date_to = today

    # Support custom from_date / to_date overrides
    from datetime import datetime
    raw_from = request.GET.get('from_date')
    raw_to   = request.GET.get('to_date')
    if raw_from:
        try:
            date_from = datetime.strptime(raw_from, '%Y-%m-%d').date()
        except ValueError:
            pass
    if raw_to:
        try:
            date_to = datetime.strptime(raw_to, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Base queryset – CC sees only their own orders (all order types including delivery/pickup)
    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
    )
    orders = Order.objects.filter(
        _tq,
        ordered_by=request.user,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).distinct()

    # --- Payment-status filter ---
    payment_status = request.GET.get('payment_status', 'all')
    if payment_status in ('paid', 'unpaid', 'partial'):
        orders = orders.filter(payment_status=payment_status)

    orders = orders.select_related('table_info').prefetch_related(
        'order_items__product__main_category',
        'payments',
    ).order_by('-created_at')

    # --- Aggregate stats ---
    agg = orders.aggregate(
        total_revenue=Sum('total_amount'),
        total_orders=Count('id'),
        paid_orders=Count('id',    filter=Q(payment_status='paid')),
        unpaid_orders=Count('id',  filter=Q(payment_status='unpaid')),
        partial_orders=Count('id', filter=Q(payment_status='partial')),
    )
    total_orders  = agg['total_orders']  or 0
    total_revenue = float(agg['total_revenue'] or 0)
    total_items   = orders.aggregate(t=Sum('order_items__quantity'))['t'] or 0
    avg_order     = round(total_revenue / total_orders, 2) if total_orders else 0

    stats = {
        'total_orders':   total_orders,
        'total_revenue':  total_revenue,
        'total_items':    total_items,
        'avg_order_value': avg_order,
        'paid_orders':    agg['paid_orders']    or 0,
        'unpaid_orders':  agg['unpaid_orders']  or 0,
        'partial_orders': agg['partial_orders'] or 0,
    }

    # --- Order list (max 100) ---
    orders_list = []
    for order in orders[:100]:
        orders_list.append({
            'id':             order.id,
            'order_number':   order.order_number,
            'table_number':   order.table_info.tbl_no if order.table_info else 'N/A',
            'status':         order.status,
            'payment_status': order.payment_status,
            'total_amount':   float(order.total_amount),
            'items_count':    order.order_items.count(),
            'created_at':     order.created_at.isoformat(),
        })

    return Response({
        'stats':   stats,
        'orders':  orders_list,
        'period':  period,
        'date_from': str(date_from),
        'date_to':   str(date_to),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def owner_reports(request):
    """
    Restaurant-wide revenue report for owners and managers.
    Returns summary across ALL orders in the restaurant (not just the caller's).
    Access: owner, main_owner, branch_owner, manager.
    """
    user = request.user
    if not (user.is_owner() or user.is_main_owner() or user.is_branch_owner() or user.is_manager()):
        return Response({'error': 'Access denied. Owner or manager role required.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    # --- Period filter ---
    period = request.GET.get('period', 'today')
    today = timezone.now().date()

    if period == 'today':
        date_from = today
        date_to = today
    elif period == 'weekly':
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif period == 'monthly':
        date_from = today.replace(day=1)
        date_to = today
    elif period == 'yearly':
        date_from = today.replace(month=1, day=1)
        date_to = today
    else:
        date_from = today
        date_to = today

    from datetime import datetime as _dt
    raw_from = request.GET.get('from_date')
    raw_to   = request.GET.get('to_date')
    if raw_from:
        try:
            date_from = _dt.strptime(raw_from, '%Y-%m-%d').date()
        except ValueError:
            pass
    if raw_to:
        try:
            date_to = _dt.strptime(raw_to, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Build dual-FK order filter (mirrors reports/views.py pattern).
    # TableInfo links to an owner either via the legacy `owner` FK (owner is NULL on restaurant)
    # or via the newer `restaurant` FK (where restaurant.main_owner / .branch_owner = owner).
    from restaurant.models import Restaurant as _Restaurant
    restaurant_obj = _Restaurant.objects.filter(
        Q(main_owner=owner) | Q(branch_owner=owner)
    ).first()

    if restaurant_obj:
        table_q = (
            Q(table_info__restaurant=restaurant_obj) |
            Q(table_info__owner=owner, table_info__restaurant__isnull=True) |
            Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) |
            Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
        )
    else:
        table_q = (
            Q(table_info__owner=owner) |
            Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) |
            Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
        )

    orders = Order.objects.filter(
        table_q,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).select_related('table_info', 'ordered_by').prefetch_related('payments')

    payment_status = request.GET.get('payment_status', 'all')
    if payment_status in ('paid', 'unpaid', 'partial'):
        orders = orders.filter(payment_status=payment_status)

    orders = orders.order_by('-created_at')

    agg = orders.aggregate(
        total_revenue=Sum('total_amount'),
        total_orders=Count('id'),
        paid_orders=Count('id',    filter=Q(payment_status='paid')),
        unpaid_orders=Count('id',  filter=Q(payment_status='unpaid')),
        partial_orders=Count('id', filter=Q(payment_status='partial')),
    )
    total_orders  = agg['total_orders']  or 0
    total_revenue = float(agg['total_revenue'] or 0)
    total_items   = orders.aggregate(t=Sum('order_items__quantity'))['t'] or 0
    avg_order     = round(total_revenue / total_orders, 2) if total_orders else 0

    # Per-staff cashier breakdown
    from django.db.models import Sum as _Sum
    from cashier.models import Payment
    if restaurant_obj:
        cashier_table_q = (
            Q(order__table_info__restaurant=restaurant_obj) |
            Q(order__table_info__owner=owner, order__table_info__restaurant__isnull=True) |
            Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner=owner) |
            Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner__managed_restaurant__main_owner=owner)
        )
    else:
        cashier_table_q = (
            Q(order__table_info__owner=owner) |
            Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner=owner) |
            Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner__managed_restaurant__main_owner=owner)
        )
    cashier_totals = (
        Payment.objects.filter(
            cashier_table_q,
            order__created_at__date__gte=date_from,
            order__created_at__date__lte=date_to,
            is_voided=False,
        )
        .values('processed_by__username', 'processed_by__first_name', 'processed_by__last_name')
        .annotate(collected=_Sum('amount'))
        .order_by('-collected')
    )

    orders_list = []
    for order in orders[:200]:
        orders_list.append({
            'id':             order.id,
            'order_number':   order.order_number,
            'table_number':   order.table_info.tbl_no if order.table_info else 'N/A',
            'ordered_by':     order.ordered_by.get_full_name() or order.ordered_by.username if order.ordered_by else 'Unknown',
            'status':         order.status,
            'payment_status': order.payment_status,
            'total_amount':   float(order.total_amount),
            'items_count':    order.order_items.count(),
            'created_at':     order.created_at.isoformat(),
        })

    return Response({
        'stats': {
            'total_orders':    total_orders,
            'total_revenue':   total_revenue,
            'total_items':     total_items,
            'avg_order_value': avg_order,
            'paid_orders':     agg['paid_orders']    or 0,
            'unpaid_orders':   agg['unpaid_orders']  or 0,
            'partial_orders':  agg['partial_orders'] or 0,
        },
        'cashier_totals': list(cashier_totals),
        'orders':   orders_list,
        'period':   period,
        'date_from': str(date_from),
        'date_to':   str(date_to),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def cashier_reports(request):
    """
    Report for cashiers:
    - Restaurant-wide orders (all staff, all tables) for the period
    - Their personal payment collections (payments they processed)
    - Top products sold in the period
    Access: cashier only (owners/managers use owner_reports).
    """
    user = request.user
    if not user.is_cashier():
        return Response({'error': 'Access denied. Cashier role required.'}, status=403)

    owner = get_restaurant_owner(request)
    if owner is None:
        return Response({'error': 'Restaurant not found.'}, status=404)

    # --- Period filter ---
    period = request.GET.get('period', 'today')
    today = timezone.now().date()

    if period == 'today':
        date_from = today
        date_to = today
    elif period == 'weekly':
        date_from = today - timedelta(days=today.weekday())
        date_to = today
    elif period == 'monthly':
        date_from = today.replace(day=1)
        date_to = today
    elif period == 'yearly':
        date_from = today.replace(month=1, day=1)
        date_to = today
    else:
        date_from = today
        date_to = today

    from datetime import datetime as _dt
    raw_from = request.GET.get('from_date')
    raw_to   = request.GET.get('to_date')
    if raw_from:
        try:
            date_from = _dt.strptime(raw_from, '%Y-%m-%d').date()
        except ValueError:
            pass
    if raw_to:
        try:
            date_to = _dt.strptime(raw_to, '%Y-%m-%d').date()
        except ValueError:
            pass

    # --- Restaurant-wide orders for the period (all order types) ---
    _tq = (
        Q(table_info__owner=owner) |
        Q(table_info__restaurant__main_owner=owner) |
        Q(table_info__restaurant__branch_owner=owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner=owner) |
        Q(order_type__in=['delivery', 'pickup'], ordered_by__owner__managed_restaurant__main_owner=owner)
    )
    orders = Order.objects.filter(
        _tq,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).distinct()

    payment_status_filter = request.GET.get('payment_status', 'all')
    if payment_status_filter in ('paid', 'unpaid', 'partial'):
        orders = orders.filter(payment_status=payment_status_filter)

    orders = orders.select_related('table_info', 'ordered_by').prefetch_related(
        'order_items__product', 'payments'
    ).order_by('-created_at')

    agg = orders.aggregate(
        total_revenue=Sum('total_amount'),
        total_orders=Count('id'),
        paid_orders=Count('id',   filter=Q(payment_status='paid')),
        unpaid_orders=Count('id', filter=Q(payment_status='unpaid')),
        partial_orders=Count('id', filter=Q(payment_status='partial')),
    )
    total_orders  = agg['total_orders']  or 0
    total_revenue = float(agg['total_revenue'] or 0)
    total_items   = orders.aggregate(t=Sum('order_items__quantity'))['t'] or 0
    avg_order     = round(total_revenue / total_orders, 2) if total_orders else 0

    # --- Cashier's personal payment collections ---
    from cashier.models import Payment
    from django.db.models import Sum as _Sum
    _ptq = (
        Q(order__table_info__owner=owner) |
        Q(order__table_info__restaurant__main_owner=owner) |
        Q(order__table_info__restaurant__branch_owner=owner) |
        Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner=owner) |
        Q(order__order_type__in=['delivery', 'pickup'], order__ordered_by__owner__managed_restaurant__main_owner=owner)
    )
    my_payments = Payment.objects.filter(
        _ptq,
        processed_by=user,
        is_voided=False,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    my_collections = my_payments.aggregate(
        total=_Sum('amount'),
        count=Count('id'),
    )
    my_total_collected = float(my_collections['total'] or 0)
    my_payment_count   = my_collections['count'] or 0

    # Payment method breakdown for cashier
    from django.db.models import Sum as _S
    method_breakdown = list(
        my_payments
        .values('payment_method')
        .annotate(total=_S('amount'), count=Count('id'))
        .order_by('-total')
    )

    # --- Top 5 products ---
    top_products = list(
        OrderItem.objects.filter(order__in=orders)
        .values('product__name')
        .annotate(qty=Sum('quantity'), revenue=Sum(F('unit_price') * F('quantity')))
        .order_by('-qty')[:5]
    )

    # --- Order list (max 100, most recent first) ---
    orders_list = []
    for order in orders[:100]:
        orders_list.append({
            'id':             order.id,
            'order_number':   order.order_number,
            'table_number':   order.table_info.tbl_no if order.table_info else 'N/A',
            'ordered_by':     order.ordered_by.get_full_name() or order.ordered_by.username if order.ordered_by else 'Unknown',
            'status':         order.status,
            'payment_status': order.payment_status,
            'total_amount':   float(order.total_amount),
            'items_count':    order.order_items.count(),
            'created_at':     order.created_at.isoformat(),
        })

    return Response({
        'stats': {
            'total_orders':       total_orders,
            'total_revenue':      total_revenue,
            'total_items':        total_items,
            'avg_order_value':    avg_order,
            'paid_orders':        agg['paid_orders']    or 0,
            'unpaid_orders':      agg['unpaid_orders']  or 0,
            'partial_orders':     agg['partial_orders'] or 0,
            'my_total_collected': my_total_collected,
            'my_payment_count':   my_payment_count,
        },
        'my_payment_methods': [
            {
                'method': m['payment_method'],
                'total':  float(m['total'] or 0),
                'count':  m['count'],
            }
            for m in method_breakdown
        ],
        'top_products': [
            {'name': p['product__name'], 'qty': p['qty']}
            for p in top_products
        ],
        'orders':    orders_list,
        'period':    period,
        'date_from': str(date_from),
        'date_to':   str(date_to),
    })
