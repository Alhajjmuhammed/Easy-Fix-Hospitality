from django.contrib import admin
from .models import InventoryItem, InventoryRecord


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'unit', 'current_stock', 'low_stock_threshold', 'owner', 'is_active']
    list_filter = ['category', 'unit', 'is_active']
    search_fields = ['name', 'owner__username', 'owner__restaurant_name']


@admin.register(InventoryRecord)
class InventoryRecordAdmin(admin.ModelAdmin):
    list_display = ['item', 'record_type', 'quantity_change', 'recorded_by', 'recorded_at']
    list_filter = ['record_type', 'recorded_at']
    search_fields = ['item__name', 'notes']
