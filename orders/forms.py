from django import forms
from django.db.models import Q
from restaurant.models import TableInfo
from .models import Order
from accounts.models import get_owner_filter

class TableSelectionForm(forms.Form):
    table_number = forms.CharField(
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg text-center',
            'placeholder': 'Enter table number',
            'required': True,
            'style': 'font-size: 1.5rem; font-weight: bold;'
        }),
        label='Table Number'
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.restaurant = kwargs.pop('restaurant', None)  # Add restaurant parameter
        super().__init__(*args, **kwargs)
    
    def clean_table_number(self):
        table_number = self.cleaned_data['table_number'].strip()
        
        try:
            # Filter tables by restaurant (from QR code) or user's owner
            queryset = TableInfo.objects.all()
            
            if self.restaurant:
                # Use restaurant from QR code
                queryset = queryset.filter(
                    Q(owner=self.restaurant) |
                    Q(restaurant__main_owner=self.restaurant) |
                    Q(restaurant__branch_owner=self.restaurant)
                )
            elif self.user:
                # Fall back to user's owner filter
                owner_filter = get_owner_filter(self.user)
                if owner_filter:
                    queryset = queryset.filter(
                        Q(owner=owner_filter) |
                        Q(restaurant__main_owner=owner_filter) |
                        Q(restaurant__branch_owner=owner_filter)
                    )
            
            table = queryset.get(tbl_no=table_number)
            if not table.is_available:
                raise forms.ValidationError('This table is currently not available.')
        except TableInfo.DoesNotExist:
            if self.restaurant:
                raise forms.ValidationError(f'Table {table_number} not found at {self.restaurant.restaurant_name}.')
            else:
                raise forms.ValidationError('Invalid table number. Please check and try again.')
        
        return table_number

class OrderForm(forms.Form):
    special_instructions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Any special instructions for your order? (Optional)'
        }),
        label='Special Instructions'
    )

class OrderStatusForm(forms.Form):
    STATUS_CHOICES = [
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('served', 'Served'),
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

class CancelOrderForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Please provide a reason for cancelling this order...',
            'required': True
        }),
        label='Cancellation Reason'
    )
