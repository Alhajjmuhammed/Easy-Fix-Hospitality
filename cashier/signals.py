from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Payment


@receiver(post_save, sender=Payment)
def _loyalty_payment_voided(sender, instance, **kwargs):
    """Points used to pay come back when that payment is voided."""
    if instance.payment_method == 'loyalty' and instance.is_voided:
        from .loyalty import refund_voided_payment
        try:
            refund_voided_payment(instance)  # own savepoint: a failure can't spoil the void
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Loyalty refund failed for payment %s', instance.pk, exc_info=True)
