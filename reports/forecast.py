"""Sales forecasting from the restaurant's own history (last 8 weeks).

Simple, explainable methods — owners can see why a number is what it is:
  • expected sales per day: same weekday in the last 8 weeks (recent weeks count more) × recent trend
  • busy hours: average orders per hour for each weekday
  • ingredients to buy: expected dish sales (per weekday) × recipes, compared with current stock
  • rising / falling dishes: last 14 days vs the 14 days before
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Min, Q, Sum, Value
from django.db.models.functions import Coalesce, ExtractHour, ExtractIsoWeekDay, TruncDate
from django.utils import timezone

WEEKS = 8
HISTORY_DAYS = WEEKS * 7
NOT_SOLD = ('cancelled', 'customer_refused', 'kitchen_error', 'quality_issue', 'wasted')
DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def orders_for_owner(owner):
    """Orders of this restaurant (same rule as the payment screens); sold ones only."""
    from orders.models import Order
    from cashier.views_loyalty import _staff_order_q
    return Order.objects.filter(_staff_order_q(owner)).exclude(status__in=NOT_SOLD).distinct()


def _start_of(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()))


def build(owner, today=None):
    today = today or timezone.localdate()
    since = today - timedelta(days=HISTORY_DAYS)
    from orders.models import Order
    # Resolve this restaurant's orders once, then aggregate over a clean queryset: the ownership
    # filter joins through tables that can repeat an order (owner managing several branches),
    # which would double SUM()s. order_by() keeps Order's default ordering out of GROUP BY.
    order_ids = list(orders_for_owner(owner).filter(created_at__gte=_start_of(since), created_at__lt=_start_of(today))
                     .order_by().values_list('id', flat=True))
    orders = Order.objects.filter(id__in=order_ids).order_by()

    # ---- daily totals -------------------------------------------------------------------
    daily = {r['day']: (r['revenue'] or Decimal('0'), r['n']) for r in
             orders.order_by().annotate(day=TruncDate('created_at')).values('day')
             .annotate(revenue=Sum('total_amount'), n=Count('id', distinct=True))}
    # The restaurant's first sale ever (not just within the window): a quiet day 8 weeks ago must not
    # make an old restaurant look new
    first_sale = orders_for_owner(owner).filter(created_at__lt=_start_of(today)).order_by() \
        .aggregate(m=Min('created_at'))['m'] if daily else None
    first_day = timezone.localtime(first_sale).date() if first_sale else None
    days_of_history = (today - first_day).days if first_day else 0

    def total(a, b):   # revenue between days a (incl.) and b (excl.)
        return sum((v[0] for d, v in daily.items() if a <= d < b), Decimal('0'))

    recent, before = total(today - timedelta(days=28), today), total(today - timedelta(days=56), today - timedelta(days=28))
    trend = Decimal('1')
    if before > 0 and days_of_history >= 56:      # both 4-week windows fully covered
        trend = min(max(recent / before, Decimal('0.8')), Decimal('1.25'))

    forecast = []
    for i in range(7):
        day = today + timedelta(days=i)
        samples = []
        for w in range(1, WEEKS + 1):
            past = day - timedelta(days=7 * w)
            if first_day and past >= first_day:
                samples.append((WEEKS + 1 - w, daily.get(past, (Decimal('0'), 0))))
        if samples:
            weight = sum(s[0] for s in samples)
            revenue = sum(Decimal(s[0]) * s[1][0] for s in samples) / weight * trend
            count = sum(s[0] * s[1][1] for s in samples) / weight * float(trend)
            low = min(s[1][0] for s in samples)
            high = max(s[1][0] for s in samples)
        else:
            revenue, count, low, high = Decimal('0'), 0, Decimal('0'), Decimal('0')
        forecast.append({
            'date': day, 'weekday': DAY_NAMES[day.weekday()], 'is_today': i == 0,
            'revenue': revenue.quantize(Decimal('1')), 'orders': round(count),
            'low': low.quantize(Decimal('1')), 'high': high.quantize(Decimal('1')),
            'samples': len(samples),
        })
    peak = max((f['revenue'] for f in forecast), default=Decimal('0')) or Decimal('1')
    for f in forecast:
        f['bar'] = int(f['revenue'] / peak * 100)

    # ---- busy hours (average orders per hour, per weekday) -----------------------------
    # How often each weekday actually occurred in the history (young restaurants: fewer than 8)
    seen = [0] * 7
    if first_day:
        d = max(first_day, since)
        while d < today:
            seen[d.weekday()] += 1
            d += timedelta(days=1)
    seen = [max(1, n) for n in seen]
    hours = defaultdict(float)
    for r in orders.order_by().annotate(wd=ExtractIsoWeekDay('created_at'), hr=ExtractHour('created_at')) \
            .values('wd', 'hr').annotate(n=Count('id', distinct=True)):
        hours[(r['wd'] - 1, r['hr'])] = r['n'] / seen[r['wd'] - 1]
    active_hours = sorted({h for (_, h), v in hours.items() if v > 0})
    busiest = max(hours.values(), default=0) or 1
    heatmap = [{'weekday': DAY_NAMES[d],
                'cells': [{'hour': h, 'avg': round(hours.get((d, h), 0), 1),
                           'level': min(4, math.ceil(hours.get((d, h), 0) / busiest * 4))} for h in active_hours]}
               for d in range(7)]
    top_slots = sorted(((v, d, h) for (d, h), v in hours.items()), reverse=True)[:3]

    # ---- dishes: expected sales and trend ------------------------------------------------
    from orders.models import OrderItem
    items = OrderItem.objects.filter(order__in=order_ids, product__isnull=False)
    per_weekday = defaultdict(float)   # (product, weekday) → avg qty per day
    for r in items.order_by().annotate(wd=ExtractIsoWeekDay('order__created_at')).values('product', 'wd') \
            .annotate(q=Sum('quantity')):
        per_weekday[(r['product'], r['wd'] - 1)] = r['q'] / seen[r['wd'] - 1]
    expected_qty = defaultdict(float)
    for f in forecast:
        wd = f['date'].weekday()
        for (pid, d), q in per_weekday.items():
            if d == wd:
                expected_qty[pid] += q * float(trend)

    def qty_between(a, b):
        return {r['product']: r['q'] for r in items.filter(order__created_at__gte=_start_of(a),
                                                            order__created_at__lt=_start_of(b))
                .order_by().values('product').annotate(q=Sum('quantity'))}
    last14 = qty_between(today - timedelta(days=14), today)
    prev14 = qty_between(today - timedelta(days=28), today - timedelta(days=14))
    from restaurant.models import Product
    names = dict(Product.objects.filter(id__in=set(last14) | set(prev14) | set(expected_qty)).values_list('id', 'name'))
    movers = []
    for pid in set(last14) | set(prev14):
        now_q, then_q = last14.get(pid, 0), prev14.get(pid, 0)
        if max(now_q, then_q) < 5:
            continue           # too few to say anything
        change = ((now_q - then_q) / then_q * 100) if then_q else 100
        movers.append({'name': names.get(pid, '?'), 'now': now_q, 'before': then_q, 'change': round(change),
                       'new': not then_q})
    rising = sorted([m for m in movers if m['change'] > 0], key=lambda m: -m['change'])[:5]
    falling = sorted([m for m in movers if m['change'] < 0], key=lambda m: m['change'])[:5]

    return {
        'forecast': forecast,
        'week_total': sum((f['revenue'] for f in forecast), Decimal('0')),
        'trend_percent': round((trend - 1) * 100),
        'days_of_history': days_of_history,
        'enough_history': days_of_history >= 14,
        'heatmap': heatmap,
        'active_hours': active_hours,
        'top_slots': [{'weekday': DAY_NAMES[d], 'hour': h, 'avg': round(v, 1)} for v, d, h in top_slots if v > 0],
        'rising': rising,
        'falling': falling,
        'expected_qty': dict(expected_qty),   # for shopping_list(), which uses live stock
    }


def cached_build(owner, minutes=60):
    """History doesn't change during the day: keep the heavy part for an hour per restaurant."""
    from django.core.cache import cache
    key = f'forecast:{owner.pk}:{timezone.localdate().isoformat()}'
    data = cache.get(key)
    if data is None:
        data = build(owner)
        cache.set(key, data, minutes * 60)
    return data


def shopping_list(owner, expected_qty):
    """Ingredients the next 7 days will need beyond what is in stock (+ the item's low-stock level)."""
    from inventory.models import InventoryItem, RecipeIngredient
    usage = defaultdict(float)
    for ing in RecipeIngredient.objects.filter(product_id__in=list(expected_qty), item__owner=owner) \
            .select_related('item'):
        usage[ing.item_id] += float(ing.quantity) * expected_qty[ing.product_id]
    if not usage:
        return []
    items = InventoryItem.objects.filter(id__in=list(usage), is_active=True).annotate(
        stock=Coalesce(Sum('records__quantity_change'), Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))))
    out = []
    for item in items:
        need = usage[item.id]
        stock = float(item.stock)
        buy = need - stock + float(item.low_stock_threshold)
        if buy > 0:
            out.append({'item': item, 'need': round(need, 2), 'stock': round(stock, 2),
                        'buy': math.ceil(buy * 100) / 100,
                        'cost': (Decimal(str(math.ceil(buy * 100) / 100)) * item.unit_price).quantize(Decimal('0.01'))
                        if item.unit_price is not None else None})
    return sorted(out, key=lambda r: r['item'].name)
