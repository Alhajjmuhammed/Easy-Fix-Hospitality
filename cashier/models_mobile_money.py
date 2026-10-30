"""Mobile money: each restaurant's own provider account, and the charges sent to customers' phones."""
import secrets

from django.conf import settings
from django.db import models

from .secure_fields import decrypt_dict, encrypt_dict


def _token():
    return secrets.token_urlsafe(24)


class MobileMoneyAccount(models.Model):
    PROVIDER_CHOICES = [
        ('mpesa_daraja', 'M-Pesa Kenya (Safaricom Daraja)'),
        ('flutterwave', 'Flutterwave (Tanzania, Uganda, Rwanda, Ghana, Kenya)'),
    ]
    ENV_CHOICES = [('sandbox', 'Test (sandbox)'), ('live', 'Live')]

    # The team owner whose orders are paid into this account (a branch can have its own)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='mobile_money_account')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    environment = models.CharField(max_length=10, choices=ENV_CHOICES, default='sandbox')
    enabled = models.BooleanField(default=False)
    allow_customer_payments = models.BooleanField(
        default=True, help_text='Customers can pay their own orders from the app / website')
    credentials_encrypted = models.TextField(blank=True, default='')
    # Secret part of the callback URL that identifies this account to the provider
    webhook_token = models.CharField(max_length=64, unique=True, default=_token)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_provider_display()} [{self.owner.username}] {'on' if self.enabled else 'off'}"

    @property
    def credentials(self):
        return decrypt_dict(self.credentials_encrypted)

    @credentials.setter
    def credentials(self, value):
        self.credentials_encrypted = encrypt_dict(value)


class MobileMoneyCharge(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Waiting for customer'),
        ('successful', 'Paid'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled by customer'),
        ('expired', 'Timed out'),
        ('unknown', 'Not confirmed — check before taking another payment'),
    ]
    # A late "paid" from the provider still counts for these (the money did arrive)
    LATE_SUCCESS_OK = ('pending', 'expired', 'unknown')

    account = models.ForeignKey(MobileMoneyAccount, on_delete=models.PROTECT, related_name='charges')
    provider = models.CharField(max_length=20, blank=True, default='')  # provider used for this charge
    order = models.ForeignKey('orders.Order', on_delete=models.PROTECT, related_name='mobile_money_charges')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    phone = models.CharField(max_length=20)
    reference = models.CharField(max_length=64, unique=True)            # our id sent to the provider
    provider_ref = models.CharField(max_length=100, blank=True, default='', db_index=True)
    receipt = models.CharField(max_length=100, blank=True, default='')   # e.g. M-Pesa receipt number
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    failure_reason = models.CharField(max_length=255, blank=True, default='')
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     related_name='+')
    payment = models.OneToOneField('cashier.Payment', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='mobile_money_charge')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency} {self.status}"
