from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from datetime import datetime, timedelta
from django.db.models import Sum, Count, Avg, Q

User = get_user_model()

class SalesReport(models.Model):
    """Main sales report model for storing comprehensive sales data"""
    
    REPORT_TYPES = [
        ('overall', 'Overall'),
        ('category', 'By Category'),
        ('subcategory', 'By Sub Category'),
    ]
    
    PERIOD_TYPES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('custom', 'Custom Range'),
    ]
    
    # Report identification
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    period_type = models.CharField(max_length=20, choices=PERIOD_TYPES)
    date_from = models.DateField()
    date_to = models.DateField()
    
    # Owner/Restaurant context
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sales_reports')
    
    # Category context (null for overall reports)
    category = models.ForeignKey('restaurant.MainCategory', on_delete=models.SET_NULL, null=True, blank=True)
    subcategory = models.ForeignKey('restaurant.SubCategory', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Sales metrics
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_orders = models.IntegerField(default=0)
    total_items_sold = models.IntegerField(default=0)
    average_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Payment method breakdown
    cash_payments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    card_payments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    digital_payments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    voucher_payments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Discount/Promotion impact
    total_discounts = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Tax information
    total_tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Timestamps
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='generated_reports')
    
    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['owner', 'date_from', 'date_to']),
            models.Index(fields=['report_type', 'period_type']),
        ]
    
    def __str__(self):
        period_str = f"{self.date_from} to {self.date_to}"
        context_str = ""
        if self.subcategory:
            context_str = f" - {self.subcategory.name}"
        elif self.category:
            context_str = f" - {self.category.name}"
        
        return f"{self.get_report_type_display()} Report ({period_str}){context_str}"


class ProductSalesDetail(models.Model):
    """Detailed product sales for each report"""
    
    report = models.ForeignKey(SalesReport, on_delete=models.CASCADE, related_name='product_details')
    product = models.ForeignKey('restaurant.Product', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Sales metrics for this product
    quantity_sold = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    average_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['-quantity_sold', '-total_revenue']
        indexes = [
            models.Index(fields=['report', 'quantity_sold']),
        ]
    
    def __str__(self):
        return f"{self.product.name} - {self.quantity_sold} sold"


class CashierPerformance(models.Model):
    """Cashier performance tracking for reports"""
    
    report = models.ForeignKey(SalesReport, on_delete=models.CASCADE, related_name='cashier_performance')
    cashier = models.ForeignKey(User, on_delete=models.PROTECT, related_name='performance_records')
    
    # Performance metrics
    orders_processed = models.IntegerField(default=0)
    total_sales = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    average_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Payment processing
    cash_handled = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    void_transactions = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-total_sales', '-orders_processed']
    
    def __str__(self):
        return f"{self.cashier.get_full_name()} - {self.orders_processed} orders"


class HourlyBreakdown(models.Model):
    """Hourly sales breakdown for time analysis"""
    
    report = models.ForeignKey(SalesReport, on_delete=models.CASCADE, related_name='hourly_breakdown')
    hour = models.IntegerField()  # 0-23
    
    # Hourly metrics
    orders_count = models.IntegerField(default=0)
    revenue = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        ordering = ['hour']
        unique_together = ['report', 'hour']
    
    def __str__(self):
        return f"Hour {self.hour:02d}:00 - {self.orders_count} orders"