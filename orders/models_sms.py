"""SMS: each business's own provider account (Africa's Talking) and a log of what was sent."""
from django.conf import settings
from django.db import models


class SmsAccount(models.Model):
    PROVIDER_CHOICES = [('africastalking', "Africa's Talking")]
    ENV_CHOICES = [('sandbox', 'Test (sandbox)'), ('live', 'Live')]
    EVENTS = [
        ('order_confirmed', 'Order confirmed (delivery & pickup)'),
        ('order_ready', 'Order ready for pickup'),
        ('out_for_delivery', 'Order out for delivery'),
        ('order_delivered', 'Order delivered'),
        ('payment_receipt', 'Payment received (receipt)'),
        ('reservation', 'Table reservation confirmed / declined / cancelled'),
    ]

    # Business (main/single) owner; branches use it too
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sms_account')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='africastalking')
    environment = models.CharField(max_length=10, choices=ENV_CHOICES, default='sandbox')
    enabled = models.BooleanField(default=False)
    credentials_encrypted = models.TextField(blank=True, default='')
    sender_id = models.CharField(max_length=11, blank=True, default='',
                                 help_text='Registered sender name or short code (optional)')
    events = models.JSONField(default=list, blank=True)   # list of EVENTS keys that are switched on
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"SMS [{self.owner.username}] {'on' if self.enabled else 'off'}"

    @property
    def credentials(self):
        from cashier.secure_fields import decrypt_dict
        return decrypt_dict(self.credentials_encrypted)

    @credentials.setter
    def credentials(self, value):
        from cashier.secure_fields import encrypt_dict
        self.credentials_encrypted = encrypt_dict(value)


class SmsLog(models.Model):
    STATUS_CHOICES = [('queued', 'Queued'), ('sent', 'Sent'), ('failed', 'Failed')]

    account = models.ForeignKey(SmsAccount, on_delete=models.CASCADE, related_name='logs')
    event = models.CharField(max_length=30)
    to = models.CharField(max_length=20)
    message = models.CharField(max_length=480)
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reservation_id = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='queued')
    provider_message_id = models.CharField(max_length=100, blank=True, default='')
    cost = models.CharField(max_length=30, blank=True, default='')
    error = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['account', 'created_at']),
                   models.Index(fields=['to', 'created_at']),
                   models.Index(fields=['reservation_id'])]
        constraints = [
            # An order gets each kind of text once, even when two requests race
            models.UniqueConstraint(fields=['order', 'event'], condition=models.Q(order__isnull=False),
                                    name='sms_once_per_order_event'),
        ]
