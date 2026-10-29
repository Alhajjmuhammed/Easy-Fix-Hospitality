from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from restaurant.models import TableInfo, Product
from decimal import Decimal

User = get_user_model()

class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('served', 'Served'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('customer_refused', 'Customer Refused'),
        ('kitchen_error', 'Kitchen Error'),
        ('quality_issue', 'Quality Issue'),
        ('wasted', 'Food Wasted'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
        ('partial', 'Partial'),
    ]
    
    ORDER_TYPE_CHOICES = [
        ('dine-in',  'Dine In'),
        ('delivery', 'Delivery'),
        ('pickup',   'Pickup'),
    ]

    order_number = models.CharField(max_length=20, unique=True)
    table_info = models.ForeignKey(TableInfo, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    ordered_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='orders_placed')
    confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders_confirmed')
    entered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders_entered')
    # Set only for delivery/pickup orders (no table): the restaurant owner the order
    # was placed with. Self-registered customers have no owner, so without this
    # remote orders could not be linked to a restaurant.
    restaurant_owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='remote_orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    order_type = models.CharField(max_length=20, choices=ORDER_TYPE_CHOICES, default='dine-in')
    delivery_address = models.TextField(blank=True, default='')
    delivery_phone = models.CharField(max_length=30, blank=True, default='')
    delivery_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    delivery_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    # Fee charged on this delivery order (fixed when the order is placed; 0 otherwise)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    delivery_fee_taxed = models.BooleanField(default=False)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    reason_if_cancelled = models.TextField(blank=True)
    special_instructions = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    preparing_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    served_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        table_num = self.table_info.tbl_no if self.table_info else 'Unknown'
        owner = self.get_owner()
        restaurant = owner.restaurant_name if owner else 'Unknown'
        return f"Order {self.order_number} - Table {table_num} ({restaurant})"
    
    @property
    def owner(self):
        """Get the owner this order belongs to through the customer"""
        if self.restaurant_owner_id:
            return self.restaurant_owner
        return self.ordered_by.get_owner()
    
    def get_owner(self):
        """Alternative method to get owner for consistency"""
        return self.owner

    @property
    def display_instructions(self):
        """special_instructions without the internal [offline:...] de-duplication tags."""
        import re
        return re.sub(r'\[offline(?:-append)?:[^\]]*\]', '', self.special_instructions or '').strip()
    
    def get_total_products(self):
        return sum(item.quantity for item in self.order_items.all())
    
    def get_subtotal(self):
        """Get subtotal before tax and discounts"""
        return sum(item.get_subtotal() for item in self.order_items.all())
    
    def get_total_discount(self):
        """Calculate total discount amount from promotional items"""
        total_discount = Decimal('0.00')
        for item in self.order_items.all():
            if not hasattr(item.product, 'get_active_promotion'):
                continue
            promo = item.product.get_active_promotion()
            if promo:
                # Derive discount directly from promotion — no 2nd DB query
                discount_per_item = item.product.price * (promo.discount_percentage / Decimal('100'))
                total_discount += discount_per_item * item.quantity
        return total_discount
    
    @staticmethod
    def compute_total(food_subtotal, tax_rate, delivery_fee=Decimal('0'), fee_taxed=False):
        """The one formula for an order total: food + fee + tax (tax on the fee only if the restaurant chose so)."""
        food = Decimal(str(food_subtotal))
        fee = Decimal(str(delivery_fee or 0))
        taxable = food + (fee if fee_taxed else Decimal('0'))
        return food + fee + taxable * Decimal(str(tax_rate))

    def get_tax_amount(self):
        """Calculate tax from stored order total — historically accurate regardless of current tax rate."""
        tax = self.total_amount - self.get_subtotal() - (self.delivery_fee or Decimal('0'))
        return max(Decimal('0.00'), tax)

    def charged_tax_rate(self, subtotal=None):
        """
        Tax rate this order was actually charged at, recovered from the stored total.
        Call it BEFORE items change; pass the pre-change food subtotal if already known.
        """
        if subtotal is None:
            subtotal = self.get_subtotal()
        subtotal = Decimal(str(subtotal))
        fee = self.delivery_fee or Decimal('0')
        base = subtotal + (fee if self.delivery_fee_taxed else Decimal('0'))
        if base > 0 and self.total_amount:
            return max(Decimal('0'), (self.total_amount - subtotal - fee) / base)
        return self._get_tax_rate_decimal()

    def total_for_subtotal(self, food_subtotal, tax_rate):
        """New total after items change: same tax rate, delivery fee kept as charged."""
        return self.compute_total(food_subtotal, tax_rate, self.delivery_fee, self.delivery_fee_taxed)
    
    def _get_tax_rate_decimal(self):
        """Resolve applicable tax rate for dine-in, delivery, and pickup orders."""
        if self.table_info:
            return self.table_info.get_tax_rate()
        # Delivery/pickup: look up the restaurant linked to the ordering customer.
        _owner = self.restaurant_owner if self.restaurant_owner_id else (self.ordered_by.owner if self.ordered_by else None)
        if _owner:
            from restaurant.models_restaurant import Restaurant as _Restaurant
            from django.db.models import Q as _Q
            _r = _Restaurant.objects.filter(
                _Q(main_owner=_owner) | _Q(branch_owner=_owner)
            ).first()
            if _r and _r.tax_rate:
                return _r.tax_rate
        return Decimal('0')

    @property
    def tax_rate(self):
        """Tax rate as percentage for display"""
        return float(self._get_tax_rate_decimal() * 100)

    def get_total(self):
        """Get final total including tax and delivery fee"""
        subtotal = self.get_subtotal()
        tax = self.get_tax_amount()
        return subtotal + tax + (self.delivery_fee or Decimal('0'))

    def calculate_total(self):
        subtotal = sum(item.get_subtotal() for item in self.order_items.all())
        self.total_amount = self.total_for_subtotal(subtotal, self._get_tax_rate_decimal())
        return self.total_amount
    
    def is_table_occupying(self):
        """Check if this order should occupy the table"""
        # Table is occupied if order is active (not cancelled or paid)
        return self.status not in ['cancelled', 'customer_refused', 'kitchen_error', 'quality_issue', 'wasted'] and self.payment_status != 'paid'
    
    def occupy_table(self):
        """Mark the table as occupied by this order"""
        if self.table_info and self.is_table_occupying():
            self.table_info.is_available = False
            self.table_info.save(update_fields=['is_available'])

    def release_table(self):
        """Release the table when order is completed or cancelled"""
        if not self.table_info:
            return
        from django.db import transaction
        with transaction.atomic():
            table = TableInfo.objects.select_for_update(of=('self',)).get(pk=self.table_info_id)
            other_active = Order.objects.filter(
                table_info=table,
                status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
                payment_status__in=['unpaid', 'partial']
            ).exclude(id=self.id).exists()
            if not other_active:
                table.is_available = True
                table.save(update_fields=['is_available'])
    
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Occupy table when order is created
        if is_new:
            self.occupy_table()
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['table_info', 'status']),          # Compound index for common queries
            models.Index(fields=['table_info', 'payment_status']),  # Payment status lookups
            models.Index(fields=['ordered_by']),                    # User order history
            models.Index(fields=['created_at', 'status']),          # Date-filtered status reports
        ]

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='order_items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    special_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        product_name = self.product.name if self.product else '[deleted product]'
        return f"{self.quantity}x {product_name} for Order {self.order.order_number}"
    
    def get_subtotal(self):
        return self.quantity * self.unit_price
    
    def get_total_price(self):
        """Get total price considering current promotional pricing"""
        # Use current promotional price if available
        if hasattr(self.product, 'get_current_price'):
            current_price = self.product.get_current_price()
            return self.quantity * current_price
        return self.get_subtotal()
    
    def save(self, *args, **kwargs):
        if self.unit_price is None and self.product:
            self.unit_price = self.product.price
        super().save(*args, **kwargs)


class BillRequest(models.Model):
    """Model to track customer bill requests"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
    ]
    
    table_info = models.ForeignKey(TableInfo, on_delete=models.SET_NULL, null=True, blank=True, related_name='bill_requests')
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bill_requests')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bill_requests_completed')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['table_info', 'status']),
        ]
    
    def __str__(self):
        tbl = self.table_info.tbl_no if self.table_info else 'N/A'
        return f"Bill Request - Table {tbl} ({self.status})"

    @property
    def owner(self):
        """Get the restaurant owner this bill request belongs to"""
        if self.table_info:
            return self.table_info.get_owner()
        return None


# Import PrintJob model
from .models_printjob import PrintJob


class DeliveryRider(models.Model):
    VEHICLE_CHOICES = [
        ('motorcycle', 'Motorcycle'),
        ('bicycle', 'Bicycle'),
        ('car', 'Car'),
        ('foot', 'On Foot'),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='rider_profile'
    )
    owner = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name='delivery_riders',
        limit_choices_to={'role__name__in': ['owner', 'main_owner', 'branch_owner']},
        null=True, blank=True,
    )
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_CHOICES, default='motorcycle')
    is_available = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    # Last known GPS position — updated by rider's phone every ~5 s during active delivery
    current_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    current_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    last_location_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        name = self.user.get_full_name() or self.user.username
        return f"{name} ({self.get_vehicle_type_display()})"

    class Meta:
        ordering = ['user__first_name', 'user__username']


class DeliveryAssignment(models.Model):
    STATUS_CHOICES = [
        ('assigned', 'Assigned'),
        ('picked_up', 'Picked Up'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ]

    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name='delivery_assignment'
    )
    rider = models.ForeignKey(
        DeliveryRider, on_delete=models.PROTECT, related_name='assignments'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='assigned')
    assigned_at = models.DateTimeField(auto_now_add=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Delivery #{self.order.order_number} → {self.rider}"

    class Meta:
        ordering = ['-assigned_at']
