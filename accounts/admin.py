from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import User, Role, AuditLog, RestaurantSubscription, SubscriptionLog

# Import Token model only if rest_framework is installed
try:
    from rest_framework.authtoken.models import Token
    HAS_REST_FRAMEWORK = True
except ImportError:
    HAS_REST_FRAMEWORK = False
    Token = None

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    list_filter = ['name', 'created_at']
    search_fields = ['name', 'description']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Admin for viewing audit logs - read-only"""
    list_display = ['created_at', 'event_type', 'username', 'short_description', 'ip_address']
    list_filter = ['event_type', 'created_at']
    search_fields = ['username', 'description', 'ip_address', 'target_model', 'target_id']
    readonly_fields = ['event_type', 'user', 'username', 'description', 'ip_address', 
                       'user_agent', 'extra_data', 'target_model', 'target_id', 'created_at']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    def short_description(self, obj):
        """Truncate description for list display"""
        return obj.description[:100] + '...' if len(obj.description) > 100 else obj.description
    short_description.short_description = 'Description'
    
    def has_add_permission(self, request):
        return False  # Audit logs should only be created programmatically
    
    def has_change_permission(self, request, obj=None):
        return False  # Audit logs should never be modified
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser  # Only superusers can delete (for cleanup)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'role', 'is_active', 'has_print_token', 'created_at']
    list_filter = ['role', 'is_active', 'is_staff', 'created_at']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'phone_number', 'address', 'is_active_staff')
        }),
        ('Restaurant Info (Owners Only)', {
            'fields': ('restaurant_name', 'restaurant_description', 'restaurant_qr_code', 'tax_rate', 'owner'),
            'classes': ('collapse',)
        }),
        ('Auto-Print Settings (Owners Only)', {
            'fields': ('auto_print_kot', 'auto_print_bot'),
        }),
        ('Printer Configuration (Owners Only)', {
            'fields': ('kitchen_printer_name', 'bar_printer_name', 'receipt_printer_name', 'get_available_printers'),
            'description': 'Configure specific printers for different print jobs. Leave blank to use auto-detected printer.',
        }),
        ('Print Client Token', {
            'fields': ('get_print_token',),
            'classes': ('collapse',)
        }),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'phone_number', 'address', 'is_active_staff')
        }),
    )
    
    readonly_fields = ['get_print_token', 'get_available_printers']
    
    def has_print_token(self, obj):
        """Check if user has API token"""
        if not HAS_REST_FRAMEWORK or Token is None:
            return False
        return Token.objects.filter(user=obj).exists()
    has_print_token.boolean = True
    has_print_token.short_description = 'Print Token'
    
    def get_print_token(self, obj):
        """Display API token with copy button"""
        if not HAS_REST_FRAMEWORK or Token is None:
            return format_html(
                '<div style="padding: 10px; background: #fff3cd; border-radius: 5px;">'
                '<strong>REST Framework not installed</strong><br>'
                '<small>Install: <code>pip install djangorestframework</code></small>'
                '</div>'
            )
        
        try:
            token = Token.objects.get(user=obj)
            return format_html(
                '<div style="padding: 10px; background: #f0f0f0; border-radius: 5px;">'
                '<strong>API Token:</strong><br>'
                '<code style="font-size: 14px; background: white; padding: 5px; display: inline-block; margin: 5px 0;">{}</code><br>'
                '<small>Use this token in print_client/config.json</small><br>'
                '<a href="#" onclick="navigator.clipboard.writeText(\'{}\'); alert(\'Token copied!\'); return false;" '
                'style="display: inline-block; margin-top: 5px; padding: 5px 10px; background: #417690; color: white; '
                'text-decoration: none; border-radius: 3px;">📋 Copy Token</a>'
                '</div>',
                token.key,
                token.key
            )
        except Token.DoesNotExist:
            return format_html(
                '<div style="padding: 10px; background: #fff3cd; border-radius: 5px;">'
                '<strong>No token generated yet</strong><br>'
                '<small>Run: <code>python manage.py generate_print_token {}</code></small>'
                '</div>',
                obj.username
            )
    get_print_token.short_description = 'Print Client API Token'
    
    def get_available_printers(self, obj):
        """Display list of available printers on the system"""
        try:
            import win32print  # type: ignore
            printers = []
            for printer_info in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL):
                printers.append(printer_info[2])
            
            if printers:
                printer_list = '<br>'.join([f'• {p}' for p in printers])
                return format_html(
                    '<div style="padding: 10px; background: #f0f0f0; border-radius: 5px;">'
                    '<strong>Available Printers:</strong><br>'
                    '<div style="margin-top: 5px; font-family: monospace; font-size: 12px;">{}</div>'
                    '<small style="color: #666; margin-top: 5px; display: block;">'
                    'Copy the exact printer name above and paste it into the printer fields.'
                    '</small>'
                    '</div>',
                    printer_list
                )
            else:
                return format_html(
                    '<div style="padding: 10px; background: #fff3cd; border-radius: 5px;">'
                    'No printers found on this system.'
                    '</div>'
                )
        except ImportError:
            return format_html(
                '<div style="padding: 10px; background: #fff3cd; border-radius: 5px;">'
                '<strong>Win32print not available</strong><br>'
                '<small>Printer detection only works on Windows systems.</small>'
                '</div>'
            )
        except Exception as e:
            return format_html(
                '<div style="padding: 10px; background: #ffcccc; border-radius: 5px;">'
                '<strong>Error detecting printers:</strong><br>'
                '<small>{}</small>'
                '</div>',
                str(e)
            )
    get_available_printers.short_description = 'Available Printers on System'


# Customize Token admin for better display (only if REST Framework is installed)
if HAS_REST_FRAMEWORK and Token is not None:
    class TokenAdmin(admin.ModelAdmin):
        list_display = ['key', 'user', 'created']
        search_fields = ['user__username']
        readonly_fields = ['key', 'created']
    
    # Try to unregister if it exists, then register custom one
    try:
        admin.site.unregister(Token)
    except admin.sites.NotRegistered:
        pass  # Token wasn't registered yet, that's fine
    
    admin.site.register(Token, TokenAdmin)

