"""
Print Job Queue System for Remote Printing
Allows print jobs to be queued and picked up by print clients
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class PrintJob(models.Model):
    """
    Print jobs that need to be printed by restaurant's local print client
    """
    JOB_TYPE_CHOICES = [
        ('kot', 'Kitchen Order Ticket'),
        ('bot', 'Bar Order Ticket'),
        ('receipt', 'Payment Receipt'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('printing', 'Printing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    # Restaurant identification
    restaurant = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        related_name='print_jobs',
        help_text="Restaurant owner whose printer should print this"
    )
    
    # Job details
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Content
    content = models.TextField(help_text="Print content (plain text)")
    
    # Printer configuration
    printer_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Specific printer name to use (blank for auto-detect)"
    )
    
    # Related objects
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='print_jobs'
    )
    payment = models.ForeignKey(
        'cashier.Payment',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='print_jobs'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    printed_at = models.DateTimeField(null=True, blank=True)
    
    # Error tracking
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    
    # Client info
    printed_by_client = models.CharField(max_length=255, blank=True, help_text="Client identifier")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'status', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.job_type.upper()} - {self.restaurant.restaurant_name} - {self.status}"
    
    def mark_printing(self, client_id):
        """Mark job as being printed"""
        self.status = 'printing'
        self.printed_by_client = client_id
        self.save(update_fields=['status', 'printed_by_client'])
    
    def mark_completed(self):
        """Mark job as successfully printed"""
        self.status = 'completed'
        self.printed_at = timezone.now()
        self.save(update_fields=['status', 'printed_at'])
    
    def mark_failed(self, error_msg):
        """Mark job as failed"""
        self.status = 'failed'
        self.error_message = error_msg
        self.retry_count += 1
        self.save(update_fields=['status', 'error_message', 'retry_count'])
    
    def retry(self):
        """Retry a failed print job"""
        if self.status == 'failed':
            self.status = 'pending'
            self.error_message = ''
            self.save(update_fields=['status', 'error_message'])
            return True
        return False
    
    @property
    def age_seconds(self):
        """How long ago was this job created (in seconds)"""
        return (timezone.now() - self.created_at).total_seconds()
    
    @property
    def is_stale(self):
        """Is this job older than 1 hour and still pending?"""
        return self.status == 'pending' and self.age_seconds > 3600
