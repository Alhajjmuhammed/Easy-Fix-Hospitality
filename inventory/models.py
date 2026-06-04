from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.utils import timezone

User = get_user_model()


class InventoryCategory(models.Model):
    """A custom category label defined by the owner (e.g. 'Fresh Produce', 'Japanese Spirits')."""
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='inventory_categories'
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ['owner', 'name']

    def __str__(self):
        return self.name


class InventoryUnit(models.Model):
    """A custom unit of measure defined by the owner (e.g. 'kg', 'bottles (720ml)', 'trays')."""
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='inventory_units'
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ['owner', 'name']

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    """A trackable inventory item (ingredient, supply, etc.)"""

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='inventory_items',
        help_text="Restaurant owner who owns this inventory item"
    )
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True, default='', help_text="e.g. Produce, Meat, Beverages — enter your own")
    unit = models.CharField(max_length=100, default='', help_text="e.g. kg, pieces, bottles — enter your own")
    low_stock_threshold = models.DecimalField(
        max_digits=10, decimal_places=2, default=5,
        validators=[MinValueValidator(0)],
        help_text="Alert when current stock falls at or below this value"
    )
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Cost per unit of this item (optional, used for cost tracking in reports)"
    )
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'name']
        unique_together = ['owner', 'name']

    def __str__(self):
        return f"{self.name} ({self.unit})" if self.unit else self.name

    @property
    def current_stock(self):
        """Calculate current stock from all records."""
        from django.db.models import Sum
        total = self.records.aggregate(total=Sum('quantity_change'))['total']
        return total or 0

    @property
    def is_low_stock(self):
        return 0 < self.current_stock <= self.low_stock_threshold

    @property
    def is_out_of_stock(self):
        return self.current_stock <= 0


class InventoryRecord(models.Model):
    """A single manual stocktake or adjustment entry."""

    RECORD_TYPE_CHOICES = [
        ('opening', 'Opening Stock'),
        ('received', 'Stock Received'),
        ('closing', 'Closing Count'),
        ('adjustment', 'Manual Adjustment'),
        ('used', 'Used / Consumed'),
        ('waste', 'Waste / Spoilage'),
        ('returned', 'Returned to Supplier'),
    ]

    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='records'
    )
    record_type = models.CharField(max_length=20, choices=RECORD_TYPE_CHOICES)
    # Positive = stock in (received, opening, returned), Negative = stock out (used, waste, adjustment down)
    quantity_change = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Positive to add stock, negative to remove stock"
    )
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Cost per unit at time of this record — used for budget/spend tracking"
    )
    notes = models.TextField(blank=True, default='')
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='inventory_records'
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        direction = "+" if self.quantity_change >= 0 else ""
        return f"{self.item.name} {direction}{self.quantity_change} ({self.get_record_type_display()}) @ {self.recorded_at:%Y-%m-%d %H:%M}"

    @property
    def transaction_cost(self):
        """Total cost of this record: |qty| × unit_price (record's price, or item's price as fallback)."""
        price = self.unit_price if self.unit_price is not None else self.item.unit_price
        if price is None:
            return None
        return abs(self.quantity_change) * price
