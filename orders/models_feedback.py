"""Customer ratings & feedback on finished orders."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class OrderRating(models.Model):
    order = models.OneToOneField('orders.Order', on_delete=models.CASCADE, related_name='rating')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='order_ratings')
    # The owner account whose staff served the order (branch owner or main owner)
    restaurant_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                         related_name='received_ratings')
    food_stars = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    delivery_stars = models.PositiveSmallIntegerField(null=True, blank=True,
                                                      validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True, default='')
    reply = models.TextField(blank=True, default='')
    replied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['restaurant_owner', 'created_at'])]

    def __str__(self):
        return f"Order {self.order_id}: {self.food_stars}★"

    @property
    def is_low(self):
        return self.food_stars <= 2 or (self.delivery_stars is not None and self.delivery_stars <= 2)
