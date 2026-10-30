from django.db import transaction
from django.db.models.signals import post_delete, post_init, post_save
from django.dispatch import receiver

from .models import Order, OrderItem


@receiver(post_init, sender=Order)
def _remember_status(sender, instance, **kwargs):
    # __dict__ lookup: never triggers a query when 'status' was deferred (.only()/.defer()).
    instance._loaded_status = instance.__dict__.get('status')
    instance._loaded_payment_status = instance.__dict__.get('payment_status')


@receiver(post_save, sender=Order)
def _payment_status_changed(sender, instance, created, update_fields=None, **kwargs):
    """Loyalty points follow whether the order is fully paid (earned, or taken back after a void)."""
    if update_fields is not None and 'payment_status' not in update_fields:
        return
    old = None if created else getattr(instance, '_loaded_payment_status', None)
    instance._loaded_payment_status = instance.payment_status
    if old == instance.payment_status or (not created and old is None):
        return
    if instance.payment_status == 'paid' or old == 'paid':
        from cashier.loyalty import sync_order_points  # never raises
        sync_order_points(instance)


@receiver(post_save, sender=Order)
def _status_changed(sender, instance, created, update_fields=None, **kwargs):
    if created:
        instance._loaded_status = instance.status
        return
    if update_fields is not None and 'status' not in update_fields:
        return  # status not written — keep the last saved value for the next comparison
    old = getattr(instance, '_loaded_status', None)
    instance._loaded_status = instance.status
    if old is None or old == instance.status:
        return
    from inventory.recipes import stock_group
    if stock_group(old) != stock_group(instance.status):
        # Only moves like confirmed→preparing or served→wasted touch stock; normal kitchen
        # steps (preparing→ready→served) cost nothing extra.
        _sync_recipe_stock(instance)
    if getattr(instance, '_skip_status_push', False):
        return  # e.g. the customer cancelled it themselves
    from .push import notify_customer_status
    try:
        notify_customer_status(instance, instance.status)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Customer status push failed for order %s', instance.pk, exc_info=True)


# ── Recipe stock: ingredients follow the order's status and items ──────────────

def _sync_recipe_stock(order):
    from inventory.recipes import sync_order_stock  # never raises
    sync_order_stock(order)


class _PendingOrders(set):
    """Order ids whose items changed in the current transaction; synced once each after commit."""

    done = False

    def __call__(self):
        self.done = True
        for order_id in list(self):
            _sync_recipe_stock_by_id(order_id)
        self.clear()


@receiver(post_save, sender=OrderItem)
@receiver(post_delete, sender=OrderItem)
def _order_item_changed(sender, instance, origin=None, **kwargs):
    if isinstance(origin, Order):
        return  # the whole order is being deleted: what was used stays used
    from django.db import connection
    if not connection.in_atomic_block:
        _sync_recipe_stock_by_id(instance.order_id)
        return
    # One after-commit callback per transaction (adding 10 items syncs the order once).
    # The callback is gone after a rollback, so look for it instead of remembering it.
    pending = getattr(connection, '_recipe_pending', None)
    if pending is None or pending.done or not any(entry[1] is pending for entry in connection.run_on_commit):
        pending = connection._recipe_pending = _PendingOrders()
        # robust: a failure here must never turn a saved order into an error or skip
        # the kitchen / push callbacks queued after it
        transaction.on_commit(pending, robust=True)
    pending.add(instance.order_id)


def _sync_recipe_stock_by_id(order_id):
    try:
        order = Order.objects.filter(pk=order_id).only('id', 'status').first()
        # Nothing is taken from stock before the kitchen starts, so most item edits need no work
        if order is not None and order.status not in ('pending', 'confirmed', 'cancelled', 'customer_refused'):
            _sync_recipe_stock(order)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Recipe stock sync failed for order %s', order_id, exc_info=True)
