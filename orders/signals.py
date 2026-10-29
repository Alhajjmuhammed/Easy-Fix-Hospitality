from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from .models import Order


@receiver(post_init, sender=Order)
def _remember_status(sender, instance, **kwargs):
    # __dict__ lookup: never triggers a query when 'status' was deferred (.only()/.defer()).
    instance._loaded_status = instance.__dict__.get('status')


@receiver(post_save, sender=Order)
def _status_changed(sender, instance, created, update_fields=None, **kwargs):
    old = getattr(instance, '_loaded_status', None)
    instance._loaded_status = instance.status
    if created or old is None or old == instance.status:
        return
    if update_fields is not None and 'status' not in update_fields:
        return
    from .push import notify_customer_status
    try:
        notify_customer_status(instance, instance.status)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Customer status push failed for order %s', instance.pk, exc_info=True)
