from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Product, MainCategory, SubCategory, TableInfo, HappyHourPromotion
from accounts.models import User, Role

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'description', 'main_category', 'sub_category', 'price', 
                 'available_in_stock', 'is_available', 'preparation_time', 'station']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Product description'}),
            'main_category': forms.Select(attrs={'class': 'form-select'}),
            'sub_category': forms.Select(attrs={'class': 'form-select'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'available_in_stock': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'is_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'preparation_time': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'station': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        owner = kwargs.pop('owner', None)
        super().__init__(*args, **kwargs)
        
        # Filter main categories by owner
        if owner:
            self.fields['main_category'].queryset = MainCategory.objects.filter(owner=owner)
        
        self.fields['sub_category'].queryset = SubCategory.objects.none()
        
        if 'main_category' in self.data:
            try:
                main_category_id = int(self.data.get('main_category'))
                self.fields['sub_category'].queryset = SubCategory.objects.filter(main_category_id=main_category_id)
            except (ValueError, TypeError):
                pass
        elif self.instance.pk:
            self.fields['sub_category'].queryset = self.instance.main_category.subcategories.all()

class MainCategoryForm(forms.ModelForm):
    class Meta:
        model = MainCategory
        fields = ['name', 'description', 'image', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Category description'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class SubCategoryForm(forms.ModelForm):
    class Meta:
        model = SubCategory
        fields = ['main_category', 'name', 'description', 'is_active']
        widgets = {
            'main_category': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Subcategory name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Subcategory description'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class TableForm(forms.ModelForm):
    class Meta:
        model = TableInfo
        fields = ['tbl_no', 'capacity', 'is_available']
        widgets = {
            'tbl_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Table number'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '20'}),
            'is_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class StaffForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'})
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'})
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone_number', 'role']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # SECURITY: Only allow actual staff roles - exclude customer, owner, and admin roles
        self.fields['role'].queryset = Role.objects.filter(
            name__in=['customer_care', 'kitchen', 'bar', 'buffet', 'service', 'cashier']
        )
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError("Passwords don't match.")
        
        # SECURITY: Validate password strength using Django validators
        if password:
            try:
                validate_password(password)
            except DjangoValidationError as e:
                self.add_error('password', e.messages)
        
        return cleaned_data


class HappyHourPromotionForm(forms.ModelForm):
    DAYS_CHOICES = [
        ('1', 'Monday'),
        ('2', 'Tuesday'),
        ('3', 'Wednesday'),
        ('4', 'Thursday'),
        ('5', 'Friday'),
        ('6', 'Saturday'),
        ('7', 'Sunday'),
    ]
    
    days_selection = forms.MultipleChoiceField(
        choices=DAYS_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        label="Days of Week"
    )
    
    class Meta:
        model = HappyHourPromotion
        fields = ['name', 'description', 'discount_percentage', 'start_time', 'end_time', 
                 'days_selection', 'products', 'main_categories', 'sub_categories', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Happy Hour Special'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 
                                               'placeholder': 'Optional description of the promotion'}),
            'discount_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 
                                                          'min': '0.01', 'max': '99.99'}),
            'start_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'products': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
            'main_categories': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
            'sub_categories': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Promotion Name',
            'description': 'Description',
            'discount_percentage': 'Discount Percentage (%)',
            'start_time': 'Start Time',
            'end_time': 'End Time',
            'products': 'Specific Products',
            'main_categories': 'Main Categories',
            'sub_categories': 'Sub Categories',
            'is_active': 'Active',
        }
    
    def __init__(self, *args, **kwargs):
        owner = kwargs.pop('owner', None)
        super().__init__(*args, **kwargs)
        
        # Filter categories and products by owner
        if owner:
            self.fields['products'].queryset = Product.objects.filter(main_category__owner=owner)
            self.fields['main_categories'].queryset = MainCategory.objects.filter(owner=owner)
            self.fields['sub_categories'].queryset = SubCategory.objects.filter(main_category__owner=owner)
        
        # Pre-populate days_selection if editing existing promotion
        if self.instance.pk and self.instance.days_of_week:
            self.fields['days_selection'].initial = self.instance.days_of_week.split(',')
    
    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        products = cleaned_data.get('products')
        main_categories = cleaned_data.get('main_categories')
        sub_categories = cleaned_data.get('sub_categories')
        days_selection = cleaned_data.get('days_selection')
        
        # Validate that at least one target is selected
        if not any([products, main_categories, sub_categories]):
            raise forms.ValidationError(
                "Please select at least one product, category, or subcategory for this promotion."
            )
        
        # Validate that at least one day is selected
        if not days_selection:
            raise forms.ValidationError("Please select at least one day of the week.")
        
        return cleaned_data
    
    def save(self, commit=True):
        promotion = super().save(commit=False)
        
        # Convert days_selection to comma-separated string
        days_selection = self.cleaned_data.get('days_selection', [])
        promotion.days_of_week = ','.join(days_selection)
        
        if commit:
            promotion.save()
            self.save_m2m()
        
        return promotion
