"""Dish stock (Product.available_in_stock): one rule for every place that takes or gives back stock.

- An order never pushes stock below 0: it takes what is left (orders always go through — no lost
  sales) and the order line remembers how much it really took (OrderItem.stock_taken).
- Cancelling / removing a line gives back exactly what it took. Lines from before this rule
  (stock_taken is None) give back their full quantity, as before.
- A line that got less than it ordered (stock_short > 0) is shown to the kitchen as a warning.
"""
from django.db import transaction
from django.db.models import F


def take_stock(product_id, quantity):
    """Take up to `quantity` units of a product's stock, never below 0. Returns the units taken."""
    from restaurant.models import Product
    quantity = int(quantity or 0)
    if not product_id or quantity <= 0:
        return 0
    with transaction.atomic():
        current = (Product.objects.select_for_update(of=('self',)).filter(pk=product_id)
                   .values_list('available_in_stock', flat=True).first())
        if current is None:
            return 0
        taken = max(0, min(quantity, current))
        if taken:
            Product.objects.filter(pk=product_id).update(available_in_stock=F('available_in_stock') - taken)
        return taken


def take_for_item(item):
    """Take stock for a newly created order line and record it on the line."""
    taken = take_stock(item.product_id, item.quantity)
    item.stock_taken = taken
    type(item).objects.filter(pk=item.pk).update(stock_taken=taken)
    return taken


def take_more_for_item(item, extra_quantity):
    """An existing line's quantity grew by `extra_quantity`: take that much more."""
    taken = take_stock(item.product_id, extra_quantity)
    if item.stock_taken is None:            # legacy line: it took its whole earlier quantity
        item.stock_taken = item.quantity - int(extra_quantity) + taken
    else:
        item.stock_taken += taken
    type(item).objects.filter(pk=item.pk).update(stock_taken=item.stock_taken)
    return taken


def give_back(item):
    """Put back what this order line took (cancel / remove) — at most once per line, even if two
    requests (e.g. remove item + cancel order) do it at the same moment: the line's row is locked and
    re-read, then marked as having nothing left to give back."""
    from restaurant.models import Product
    if not item.product_id or not item.pk:
        return 0
    Line = type(item)
    with transaction.atomic():
        row = (Line.objects.select_for_update(of=('self',)).filter(pk=item.pk)
               .values_list('stock_taken', 'quantity', 'product_id').first())
        if row is None:
            return 0
        stock_taken, quantity, product_id = row
        qty = quantity if stock_taken is None else stock_taken
        if qty > 0 and product_id:
            Product.objects.filter(pk=product_id).update(available_in_stock=F('available_in_stock') + qty)
        if stock_taken != 0:
            Line.objects.filter(pk=item.pk).update(stock_taken=0)   # nothing left to give back
    item.stock_taken = 0
    return qty if product_id else 0


ACTIVE_STATUSES = ('pending', 'confirmed', 'preparing', 'ready')


def give_back_order(order):
    """An order is cancelled or deleted while still in the kitchen: put back what its lines took.
    Orders already handed over (served / out for delivery / delivered) or already cancelled are
    left alone — that food is gone, or was given back when it was cancelled."""
    if order.status not in ACTIVE_STATUSES:
        return 0
    return sum(give_back(item) for item in order.order_items.all())
