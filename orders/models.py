from django.db import models
from django.contrib.auth import get_user_model
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
    
    order_number = models.CharField(max_length=20, unique=True)
    table_info = models.ForeignKey(TableInfo, on_delete=models.CASCADE, related_name='orders')
    ordered_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders_placed')
    confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders_confirmed')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    reason_if_cancelled = models.TextField(blank=True)
    special_instructions = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Order {self.order_number} - Table {self.table_info.tbl_no} ({self.get_owner().restaurant_name})"
    
    @property
    def owner(self):
        """Get the owner this order belongs to through the customer"""
        return self.ordered_by.get_owner()
    
    def get_owner(self):
        """Alternative method to get owner for consistency"""
        return self.owner
    
    def get_total_products(self):
        return sum(item.quantity for item in self.order_items.all())
    
    def get_subtotal(self):
        """Get subtotal before tax and discounts"""
        return sum(item.get_total_price() for item in self.order_items.all())
    
    def get_total_discount(self):
        """Calculate total discount amount from promotional items"""
        total_discount = Decimal('0.00')
        for item in self.order_items.all():
            if hasattr(item.product, 'has_active_promotion') and item.product.has_active_promotion():
                original_price = item.product.price
                discounted_price = item.product.get_current_price()
                discount_per_item = original_price - discounted_price
                total_discount += discount_per_item * item.quantity
        return total_discount
    
    def get_tax_amount(self):
        """Calculate tax amount using restaurant/branch configured tax rate"""
        # Use centralized tax rate from table
        tax_rate = self.table_info.get_tax_rate()
        return self.get_subtotal() * tax_rate
    
    @property
    def tax_rate(self):
        """Tax rate as percentage for display"""
        # Use centralized tax rate from table
        tax_rate_decimal = self.table_info.get_tax_rate()
        return float(tax_rate_decimal * 100)
    
    def get_total(self):
        """Get final total including tax"""
        subtotal = self.get_subtotal()
        tax = self.get_tax_amount()
        return subtotal + tax
    
    def calculate_total(self):
        total = sum(item.get_subtotal() for item in self.order_items.all())
        self.total_amount = total
        return total
    
    def is_table_occupying(self):
        """Check if this order should occupy the table"""
        # Table is occupied if order is active (not cancelled or paid)
        return self.status not in ['cancelled', 'customer_refused', 'kitchen_error', 'quality_issue', 'wasted'] and self.payment_status != 'paid'
    
    def occupy_table(self):
        """Mark the table as occupied by this order"""
        if self.is_table_occupying():
            self.table_info.is_available = False
            self.table_info.save()
    
    def release_table(self):
        """Release the table when order is completed or cancelled"""
        # Check if any other active orders are using this table
        other_active_orders = Order.objects.filter(
            table_info=self.table_info,
            status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
            payment_status__in=['unpaid', 'partial']
        ).exclude(id=self.id)
        
        # Only release table if no other active orders
        if not other_active_orders.exists():
            self.table_info.is_available = True
            self.table_info.save()
    
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
            models.Index(fields=['table_info', 'status']),  # Compound index for common queries
        ]

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='order_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    special_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.quantity}x {self.product.name} for Order {self.order.order_number}"
    
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
        if not self.unit_price:
            self.unit_price = self.product.price
        super().save(*args, **kwargs)


class BillRequest(models.Model):
    """Model to track customer bill requests"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
    ]
    
    table_info = models.ForeignKey(TableInfo, on_delete=models.CASCADE, related_name='bill_requests')
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bill_requests')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bill_requests_completed')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Bill Request - Table {self.table_info.tbl_no} ({self.status})"
    
    @property
    def owner(self):
        """Get the restaurant owner this bill request belongs to"""
        return self.table_info.owner


# Import PrintJob model
from .models_printjob import PrintJob
