from django.contrib import admin
from .models import AttendanceQRToken, Shift, AttendanceRecord


@admin.register(AttendanceQRToken)
class AttendanceQRTokenAdmin(admin.ModelAdmin):
    list_display = ('owner', 'restaurant', 'token', 'regenerated_at')
    search_fields = ('owner__username', 'token')


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'restaurant', 'shift_type', 'start_time', 'end_time', 'grace_minutes', 'is_active')
    list_filter = ('shift_type', 'is_active')
    search_fields = ('name', 'owner__username')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('staff', 'date', 'check_in', 'check_out', 'work_minutes', 'is_late', 'is_overtime', 'check_in_via')
    list_filter = ('is_late', 'is_overtime', 'check_in_via')
    search_fields = ('staff__username', 'staff__first_name', 'staff__last_name')
    date_hierarchy = 'date'
