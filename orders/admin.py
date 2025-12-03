from django.contrib import admin
from .models import Order, OrderItem
from .models_printjob import PrintJob

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['get_subtotal']
    
    def get_subtotal(self, obj):
        return obj.get_subtotal() if obj.id else 0
    get_subtotal.short_description = 'Subtotal'

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'table_info', 'ordered_by', 'status', 'total_amount', 'payment_status', 'created_at']
    list_filter = ['status', 'payment_status', 'created_at', 'table_info']
    search_fields = ['order_number', 'table_info__tbl_no', 'ordered_by__username']
    readonly_fields = ['order_number', 'total_amount', 'created_at', 'updated_at']
    inlines = [OrderItemInline]
    
    def save_model(self, request, obj, form, change):
        if not obj.order_number:
            # Generate order number
            import uuid
            obj.order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        super().save_model(request, obj, form, change)

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order', 'product', 'quantity', 'unit_price', 'get_subtotal']
    list_filter = ['order__status', 'product__main_category', 'created_at']
    search_fields = ['order__order_number', 'product__name']


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'restaurant', 'job_type', 'status', 'created_at', 'printed_at', 'retry_count']
    list_filter = ['status', 'job_type', 'created_at', 'restaurant']
    search_fields = ['restaurant__restaurant_name', 'order__order_number']
    readonly_fields = ['created_at', 'printed_at', 'content']
    
    fieldsets = (
        ('Job Information', {
            'fields': ('restaurant', 'job_type', 'status')
        }),
        ('Related Objects', {
            'fields': ('order', 'payment')
        }),
        ('Print Content', {
            'fields': ('content',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'printed_at')
        }),
        ('Error Tracking', {
            'fields': ('error_message', 'retry_count', 'printed_by_client')
        }),
    )
    
    actions = ['retry_failed_jobs', 'mark_as_completed']
    
    def retry_failed_jobs(self, request, queryset):
        """Retry selected failed print jobs"""
        count = 0
        for job in queryset.filter(status='failed'):
            if job.retry():
                count += 1
        self.message_user(request, f'{count} job(s) queued for retry')
    retry_failed_jobs.short_description = 'Retry failed jobs'
    
    def mark_as_completed(self, request, queryset):
        """Mark selected jobs as completed"""
        count = queryset.update(status='completed')
        self.message_user(request, f'{count} job(s) marked as completed')
    mark_as_completed.short_description = 'Mark as completed'
