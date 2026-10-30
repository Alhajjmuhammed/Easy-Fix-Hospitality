from decimal import Decimal

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
    # Set when the stock came in through a purchase order delivery
    purchase_line = models.ForeignKey(
        'PurchaseOrderLine',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='stock_records'
    )

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


# ---------------------------------------------------------------------------
# Suppliers & purchase orders
# ---------------------------------------------------------------------------

def _money(value):
    return (value or Decimal('0')).quantize(Decimal('0.01'))


class Supplier(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='suppliers')
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=120, blank=True, default='')
    phone = models.CharField(max_length=40, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    address = models.CharField(max_length=255, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ['owner', 'name']

    def __str__(self):
        return self.name


class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('partial', 'Partly received'),
        ('received', 'Received'),
        ('closed', 'Closed (part delivered)'),
        ('cancelled', 'Cancelled'),
    ]
    EDITABLE = ('draft', 'sent')
    RECEIVABLE = ('draft', 'sent', 'partial')

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='purchase_orders')
    number = models.PositiveIntegerField()
    supplier = models.ForeignKey(Supplier, on_delete=models.RESTRICT, related_name='purchase_orders')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    order_date = models.DateField(default=timezone.localdate)
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-number']
        unique_together = ['owner', 'number']

    def __str__(self):
        return f"PO-{self.number:05d} {self.supplier.name}"

    @property
    def code(self):
        return f"PO-{self.number:05d}"

    @property
    def is_editable(self):
        return self.status in self.EDITABLE and not self.lines.filter(received_quantity__gt=0).exists()

    @property
    def ordered_total(self):
        return _money(sum((l.line_total for l in self.lines.all()), Decimal('0')))

    @property
    def received_total(self):
        return _money(sum((l.received_total for l in self.lines.all()), Decimal('0')))

    @property
    def paid_total(self):
        return _money(self.payments.aggregate(t=models.Sum('amount'))['t'])

    @property
    def is_finished(self):
        """No more deliveries will come: what was delivered is the final bill."""
        return self.status in ('received', 'closed')

    @property
    def payable_total(self):
        """Most that may be paid: the order total while deliveries can still come, else what was delivered."""
        return self.received_total if self.is_finished else self.ordered_total

    @property
    def amount_owed(self):
        """What we owe for goods actually delivered, minus what was paid (never negative)."""
        return max(self.received_total - self.paid_total, Decimal('0.00'))

    @property
    def supplier_credit(self):
        """Paid more than was finally delivered (e.g. prepaid, then part delivered and closed)."""
        if not self.is_finished:
            return Decimal('0.00')
        return max(self.paid_total - self.received_total, Decimal('0.00'))

    @property
    def payment_status(self):
        paid = self.paid_total
        if paid <= 0:
            return 'unpaid'
        # Nothing delivered yet: compare with the order total (prepaid orders count as paid)
        due = self.received_total if (self.received_total > 0 or self.is_finished) else self.ordered_total
        if paid >= due:
            return 'paid'
        return 'partly_paid'

    def get_payment_status_display(self):
        return {'unpaid': 'Unpaid', 'partly_paid': 'Partly paid', 'paid': 'Paid'}[self.payment_status]


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey(InventoryItem, on_delete=models.RESTRICT, related_name='purchase_lines')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    received_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.item.name} × {self.quantity}"

    @property
    def remaining(self):
        return max(self.quantity - self.received_quantity, Decimal('0'))

    @property
    def line_total(self):
        return _money(self.quantity * self.unit_price)

    @property
    def received_total(self):
        return _money(self.received_quantity * self.unit_price)


class SupplierPayment(models.Model):
    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank', 'Bank transfer'),
        ('mobile_money', 'Mobile money'),
        ('cheque', 'Cheque'),
        ('other', 'Other'),
    ]
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    paid_on = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='cash')
    reference = models.CharField(max_length=100, blank=True, default='')
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_on', '-id']

    def __str__(self):
        return f"{self.order.code} {self.amount}"
