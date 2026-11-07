"""Recipes: what one serving of a dish uses from inventory, and taking it out of stock for orders.

Stock follows the order status (reconciled, never double-counted):
  preparing / ready / served / out for delivery / delivered → ingredients used
  kitchen error / quality issue / food wasted              → ingredients used, shown as waste
  pending / confirmed / cancelled / customer refused       → nothing used (put back if already taken)
  cancelled after served / out for delivery / delivered   → kept: the food was handed over
What was already taken is kept when only the status label changes or other lines change, so a
recipe edit only applies to servings added or changed after it.
Selling never stops because of stock: counts may go below zero and show as out of stock.
"""
import logging
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum

logger = logging.getLogger(__name__)

USED_STATUSES = frozenset({'preparing', 'ready', 'served', 'out_for_delivery', 'delivered'})
WASTE_STATUSES = frozenset({'kitchen_error', 'quality_issue', 'wasted'})
# Food has left the kitchen: cancelling now does not bring the ingredients back
# (same rule the order views use for product stock).
HANDED_OVER_STATUSES = frozenset({'served', 'out_for_delivery', 'delivered'})
_UNKNOWN = object()


def stock_group(status):
    """'used', 'waste' or None. Stock only changes when an order moves between these groups."""
    if status in USED_STATUSES:
        return 'used'
    if status in WASTE_STATUSES:
        return 'waste'
    return None
MAX_INGREDIENTS = 50
CENT = Decimal('0.01')


def products_for_owner(owner):
    """The menu products that belong to this owner's restaurant (same rule as Product.owner)."""
    from restaurant.models import Product
    return (Product.objects.filter(
        Q(main_category__restaurant__branch_owner=owner)
        | Q(main_category__restaurant__branch_owner__isnull=True, main_category__restaurant__main_owner=owner)
        | Q(main_category__restaurant__isnull=True, main_category__owner=owner))
        .select_related('main_category', 'main_category__restaurant').order_by('main_category__name', 'name'))


def recipe_cost(ingredients):
    """(cost, complete). complete is False when an ingredient has no price in inventory."""
    cost, complete = Decimal('0'), True
    for ing in ingredients:
        if ing.item.unit_price is None:
            complete = False
        else:
            cost += ing.quantity * ing.item.unit_price
    return cost.quantize(CENT, ROUND_HALF_UP), complete


def margin_percent(price, cost):
    if not price:
        return None
    return ((price - cost) / price * 100).quantize(Decimal('1'), ROUND_HALF_UP)


@transaction.atomic
def save_recipe(owner, product, item_ids, quantities):
    from .models import InventoryItem, RecipeIngredient
    from .purchasing import to_decimal
    if len(item_ids) != len(quantities):
        raise ValidationError('The recipe form was not valid. Please reload the page.')
    items = {i.id: i for i in InventoryItem.objects.filter(owner=owner)}
    wanted = {}
    for item_id, qty in zip(item_ids, quantities):
        if not (item_id or qty):
            continue
        try:
            item = items.get(int(item_id))
        except (TypeError, ValueError):
            item = None
        if item is None:
            raise ValidationError('Please choose an ingredient for every line.')
        if item.id in wanted:
            raise ValidationError(f'{item.name} is listed twice. Put the total in one line.')
        wanted[item.id] = _qty(qty, item.name)
    if len(wanted) > MAX_INGREDIENTS:
        raise ValidationError(f'A recipe can have at most {MAX_INGREDIENTS} ingredients.')
    RecipeIngredient.objects.filter(product=product).delete()
    RecipeIngredient.objects.bulk_create(
        [RecipeIngredient(product=product, item_id=i, quantity=q) for i, q in wanted.items()])
    return len(wanted)


def _qty(value, name):
    try:
        d = Decimal(str(value).strip().replace(',', ''))
    except Exception:
        raise ValidationError(f'Enter a valid quantity for {name}.')
    if not d.is_finite() or d <= 0 or d >= Decimal('1000000'):
        raise ValidationError(f'Enter a valid quantity for {name}.')
    # Same precision as stock records (2 decimals), so what is costed is exactly what is taken
    d = d.quantize(CENT, ROUND_HALF_UP)
    if d <= 0:
        raise ValidationError(f'The quantity for {name} is too small (use a smaller unit, e.g. grams).')
    return d


# ---------------------------------------------------------------------------
# Stock deduction for orders
# ---------------------------------------------------------------------------

def _wanted_usage(order):
    """{inventory item id: quantity} this order should have taken out of stock right now."""
    from .models import RecipeIngredient
    if order.status not in USED_STATUSES and order.status not in WASTE_STATUSES:
        return {}
    servings = defaultdict(int)
    for product_id, qty in order.order_items.filter(product__isnull=False).values_list('product_id', 'quantity'):
        servings[product_id] += qty
    usage = defaultdict(Decimal)
    for ing in (RecipeIngredient.objects.filter(product_id__in=servings)
                .select_related('item', 'product__main_category__restaurant')):
        owner = ing.product.owner
        if owner is None or ing.item.owner_id != owner.id:
            continue  # e.g. the dish moved to another restaurant: never touch someone else's stock
        usage[ing.item_id] += ing.quantity * servings[ing.product_id]
    return {k: v.quantize(CENT, ROUND_HALF_UP) for k, v in usage.items()}


def sync_order_stock(order):
    """Bring the stock taken for this order in line with its status and items. Safe to call
    any number of times. Never raises: a stock problem must not stop an order."""
    from orders.models import Order
    from .models import InventoryRecord, RecipeIngredient
    try:
        # Set by _order_pre_save when this instance's status was just saved (a status change);
        # unknown when the sync comes from an item change.
        prev_status = getattr(order, '_stock_prev_status', _UNKNOWN)
        changed_products = _pop_changed_products(order.pk)   # popped either way: a status change starts afresh
        with transaction.atomic():
            # Lock the order so two simultaneous changes can't both take the stock
            order = Order.objects.select_for_update().filter(pk=order.pk).first()
            if order is None:
                return
            records = InventoryRecord.objects.filter(source_order=order)
            wanted = _wanted_usage(order)
            if not wanted and not records.exists():
                return
            taken = {r['item_id']: -r['total'] for r in records.values('item_id').annotate(total=Sum('quantity_change'))}
            if not stock_group(order.status):
                if order.status == 'cancelled' and _was_handed_over(prev_status, order):
                    return  # the customer already had the food: what was taken stays used
            elif any(taken.values()):
                # Something was already taken: keep it for what did not change, so a recipe
                # edited since then is not applied to servings already cooked.
                if prev_status is not _UNKNOWN:
                    if stock_group(prev_status):
                        wanted = dict(taken)   # only the label changes (e.g. served -> wasted)
                elif changed_products is not None:
                    touched = set(RecipeIngredient.objects.filter(product_id__in=changed_products)
                                  .values_list('item_id', flat=True))
                    wanted = {i: (wanted.get(i, Decimal('0')) if i in touched else taken.get(i, Decimal('0')))
                              for i in set(wanted) | set(taken)}
            kind = 'waste' if order.status in WASTE_STATUSES else 'used'
            if stock_group(order.status):
                # Food that was cooked and then lost counts as waste (and back to "used" if corrected)
                records.filter(record_type__in=('used', 'waste')).exclude(record_type=kind).update(record_type=kind)
            label = f'Order #{order.order_number}'
            for item_id in set(wanted) | set(taken):
                diff = wanted.get(item_id, Decimal('0')) - taken.get(item_id, Decimal('0'))
                if diff == 0:
                    continue
                if diff > 0:
                    InventoryRecord.objects.create(item_id=item_id, record_type=kind, quantity_change=-diff,
                                                   notes=f'{label} (recipe)', source_order=order)
                else:
                    InventoryRecord.objects.create(
                        item_id=item_id, record_type='adjustment', quantity_change=-diff,
                        notes=f'{label} {order.get_status_display().lower()} — ingredients put back',
                        source_order=order)
    except Exception:
        logger.warning('Recipe stock update failed for order %s', getattr(order, 'pk', None), exc_info=True)


def _was_handed_over(prev_status, order):
    if prev_status is not _UNKNOWN:
        return prev_status in HANDED_OVER_STATUSES
    return order.served_at is not None


# ---------------------------------------------------------------------------
# Signal hooks (connected in InventoryConfig.ready): remember the status an order had
# before a save, and which dishes' lines changed in an order, so sync_order_stock only
# reconciles what changed. Marks live on the thread's DB connection; a mark left behind by a
# rolled-back change only makes the next sync reconcile a little more (the old behaviour).
# ---------------------------------------------------------------------------

def _changed_marks():
    from django.db import connection
    marks = getattr(connection, '_inventory_changed_products', None)
    if marks is None:
        marks = connection._inventory_changed_products = {}
    return marks


def _pop_changed_products(order_id):
    return _changed_marks().pop(order_id, None)


def _mark_changed(order_id, *product_ids):
    if order_id is None:
        return
    marks = _changed_marks()
    if len(marks) > 500 and order_id not in marks:
        marks.clear()   # e.g. many orders edited before cooking: losing marks only means a full reconcile
    marks.setdefault(order_id, set()).update(p for p in product_ids if p is not None)


def _order_pre_save(sender, instance, **kwargs):
    # _loaded_status is kept by orders.signals: the status last loaded or saved
    instance._stock_prev_status = getattr(instance, '_loaded_status', None)


def _item_post_init(sender, instance, **kwargs):
    instance._stock_loaded_product = instance.__dict__.get('product_id')


def _item_pre_save(sender, instance, **kwargs):
    _mark_changed(instance.order_id, instance.product_id, getattr(instance, '_stock_loaded_product', None))


def _item_post_save(sender, instance, **kwargs):
    instance._stock_loaded_product = instance.product_id


def _item_pre_delete(sender, instance, origin=None, **kwargs):
    from orders.models import Order
    if isinstance(origin, Order):
        return  # the whole order is being deleted
    _mark_changed(instance.order_id, instance.product_id)


def connect_signals():
    from django.db.models.signals import post_init, post_save, pre_delete, pre_save
    from orders.models import Order, OrderItem
    pre_save.connect(_order_pre_save, sender=Order, dispatch_uid='inventory_order_pre_save')
    post_init.connect(_item_post_init, sender=OrderItem, dispatch_uid='inventory_item_post_init')
    pre_save.connect(_item_pre_save, sender=OrderItem, dispatch_uid='inventory_item_pre_save')
    post_save.connect(_item_post_save, sender=OrderItem, dispatch_uid='inventory_item_post_save')
    pre_delete.connect(_item_pre_delete, sender=OrderItem, dispatch_uid='inventory_item_pre_delete')
