"""Loyalty points: earned on paid orders, redeemed as a payment method at the cashier."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class LoyaltyProgram(models.Model):
    """One per business (main/single owner); branches share it."""
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='loyalty_program')
    enabled = models.BooleanField(default=False)
    spend_per_point = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1000'),
                                          validators=[MinValueValidator(Decimal('0.01'))],
                                          help_text='Customers earn 1 point for every this much spent')
    point_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('50'),
                                      validators=[MinValueValidator(Decimal('0.01'))],
                                      help_text='How much 1 point is worth when paying')
    min_redeem_points = models.PositiveIntegerField(default=100,
                                                    help_text='Smallest number of points a customer can use at once')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Loyalty [{self.owner.username}] {'on' if self.enabled else 'off'}"


class LoyaltyOrderCustomer(models.Model):
    """A walk-in order the cashier linked to a registered customer (by phone) so they earn points."""
    order = models.OneToOneField('orders.Order', on_delete=models.CASCADE, related_name='loyalty_link')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    linked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)


class LoyaltyTransaction(models.Model):
    KIND_CHOICES = [
        ('earn', 'Earned'),
        ('reverse', 'Earning reversed'),
        ('redeem', 'Used to pay'),
        ('refund', 'Returned (payment voided)'),
        ('adjust', 'Manual adjustment'),
    ]
    program_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='loyalty_transactions')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    points = models.IntegerField()  # + added, - taken
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    payment = models.ForeignKey('cashier.Payment', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='loyalty_transactions')
    note = models.CharField(max_length=200, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['program_owner', 'customer'])]

    def __str__(self):
        return f"{self.customer_id} {self.kind} {self.points:+d}"


class LoyaltyRedeemCode(models.Model):
    """The customer's personal code (shown in their app / web) that the cashier must enter to spend
    their points. A new code is made after every use, so a code can't be reused."""
    customer = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='loyalty_code')
    code = models.CharField(max_length=6)
    updated_at = models.DateTimeField(auto_now=True)
