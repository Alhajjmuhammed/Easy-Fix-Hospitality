"""
Restaurant model for hierarchical branch management.
Supports main owners with multiple branches based on subscription plans.
"""

from django.db import models
from django.contrib.auth import get_user_model
from decimal import Decimal
import uuid

User = get_user_model()


class Restaurant(models.Model):
    """
    Restaurant/Branch model for hierarchical management.
    Each restaurant can be either:
    1. Main restaurant (main_owner manages it)
    2. Branch (branch_owner manages it under main_owner)
    
    Subscription Plans:
    - SINGLE: Basic plan, no branches allowed
    - PRO: Premium plan, can create unlimited branches
    """
    
    # Subscription Plan Choices
    SUBSCRIPTION_PLANS = [
        ('SINGLE', 'Single Restaurant'),
        ('PRO', 'Pro Plan (Multi-Branch)'),
    ]
    
    # Basic Information
    name = models.CharField(
        max_length=200,
        help_text="Restaurant or branch name (e.g., 'Pizza Palace - Downtown')"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Description of this restaurant/branch"
    )
    
    address = models.TextField(
        help_text="Full address of this restaurant/branch"
    )
    
    # Subscription Plan
    subscription_plan = models.CharField(
        max_length=10,
        choices=SUBSCRIPTION_PLANS,
        default='SINGLE',
        help_text="Subscription plan that determines branch creation abilities"
    )
    
    # Hierarchical Ownership
    main_owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='owned_restaurants',
        limit_choices_to={'role__name': 'main_owner'},
        help_text="Main owner who controls this restaurant and its branches"
    )
    
    branch_owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='managed_restaurant',
        limit_choices_to={'role__name__in': ['main_owner', 'branch_owner']},
        null=True,
        blank=True,
        help_text="Branch manager (can be same as main_owner for main restaurant)"
    )
    
    # Restaurant Type
    is_main_restaurant = models.BooleanField(
        default=False,
        help_text="True if this is the main restaurant (not a branch)"
    )
    
    parent_restaurant = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='branches',
        help_text="Parent restaurant (only for branches)"
    )
    
    # QR Code and Access
    qr_code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique QR code for customer access"
    )
    
    # Financial Settings
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0800'),
        help_text="Tax rate as decimal (e.g., 0.0800 for 8%)"
    )
    
    # Currency configuration for restaurant/branch
    CURRENCY_CHOICES = [
        ('USD', 'USD - US Dollar ($)'),
        ('EUR', 'EUR - Euro (€)'),
        ('GBP', 'GBP - British Pound (£)'),
        ('KES', 'KES - Kenyan Shilling (KSh)'),
        ('TZS', 'TZS - Tanzanian Shilling (TSh)'),
        ('UGX', 'UGX - Ugandan Shilling (USh)'),
        ('RWF', 'RWF - Rwandan Franc (RF)'),
        ('ZAR', 'ZAR - South African Rand (R)'),
        ('NGN', 'NGN - Nigerian Naira (₦)'),
        ('GHS', 'GHS - Ghanaian Cedi (GH₵)'),
        ('INR', 'INR - Indian Rupee (₹)'),
        ('AED', 'AED - UAE Dirham (AED)'),
        ('SAR', 'SAR - Saudi Riyal (SAR)'),
        ('CNY', 'CNY - Chinese Yuan (¥)'),
        ('JPY', 'JPY - Japanese Yen (¥)'),
    ]
    
    CURRENCY_SYMBOLS = {
        'USD': '$',
        'EUR': '€',
        'GBP': '£',
        'KES': 'KSh',
        'TZS': 'TSh',
        'UGX': 'USh',
        'RWF': 'RF',
        'ZAR': 'R',
        'NGN': '₦',
        'GHS': 'GH₵',
        'INR': '₹',
        'AED': 'AED',
        'SAR': 'SAR',
        'CNY': '¥',
        'JPY': '¥',
    }
    
    currency_code = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default='USD',
        help_text="Currency for displaying prices in this restaurant/branch"
    )
    
    # Printing Configuration
    auto_print_kot = models.BooleanField(
        default=True,
        help_text="Auto-print Kitchen Order Tickets"
    )
    
    auto_print_bot = models.BooleanField(
        default=True,
        help_text="Auto-print Bar Order Tickets"
    )
    
    auto_print_buffet = models.BooleanField(
        default=True,
        help_text="Auto-print Buffet Order Tickets"
    )
    
    auto_print_service = models.BooleanField(
        default=True,
        help_text="Auto-print Service Order Tickets"
    )
    
    kitchen_printer_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Kitchen printer name (blank for auto-detect)"
    )
    
    bar_printer_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Bar printer name (blank for auto-detect)"
    )
    
    buffet_printer_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Buffet printer name (blank for auto-detect)"
    )
    
    service_printer_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Service printer name (blank for auto-detect)"
    )
    
    receipt_printer_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Receipt printer name (blank for auto-detect)"
    )
    
    # Status and Settings
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this restaurant/branch is active"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Restaurant"
        verbose_name_plural = "Restaurants"
        ordering = ['main_owner__username', 'is_main_restaurant', 'name']
        
        # Constraints
        constraints = [
            # Main restaurant cannot have parent
            models.CheckConstraint(
                check=~(models.Q(is_main_restaurant=True) & ~models.Q(parent_restaurant=None)),
                name='main_restaurant_no_parent'
            ),
            # Branch must have parent
            models.CheckConstraint(
                check=~(models.Q(is_main_restaurant=False) & models.Q(parent_restaurant=None)),
                name='branch_must_have_parent'
            ),
        ]
    
    def __str__(self):
        if self.is_main_restaurant:
            return f"{self.name} (Main)"
        else:
            return f"{self.name} (Branch of {self.parent_restaurant.name})"
    
    def save(self, *args, **kwargs):
        """Generate QR code if not exists"""
        if not self.qr_code:
            self.qr_code = f"REST-{uuid.uuid4().hex[:12].upper()}"
        
        # If main restaurant, set branch_owner to main_owner
        if self.is_main_restaurant and not self.branch_owner:
            self.branch_owner = self.main_owner
        
        # Validate parent relationship
        if self.is_main_restaurant:
            self.parent_restaurant = None
        
        super().save(*args, **kwargs)
    
    @property
    def display_name(self):
        """Get display name with branch indicator"""
        if self.is_main_restaurant:
            return f"{self.name}"
        else:
            return f"{self.name}"
    
    @property
    def full_hierarchy_name(self):
        """Get full hierarchical name"""
        if self.is_main_restaurant:
            return f"{self.name} (Main)"
        else:
            return f"{self.parent_restaurant.name} → {self.name}"
    
    def get_all_branches(self):
        """Get all branches under this restaurant (if main restaurant)"""
        if self.is_main_restaurant:
            return self.branches.filter(is_active=True)
        else:
            return Restaurant.objects.none()
    
    def get_main_restaurant(self):
        """Get the main restaurant for this branch"""
        if self.is_main_restaurant:
            return self
        else:
            return self.parent_restaurant
    
    def can_user_access(self, user):
        """Check if user can access this restaurant"""
        # Main owner can access all their restaurants
        if self.main_owner == user:
            return True
        
        # Branch owner can access their specific restaurant
        if self.branch_owner == user:
            return True
        
        # Staff can access their owner's restaurant
        if user.owner and (user.owner == self.main_owner or user.owner == self.branch_owner):
            return True
        
        return False
    
    def can_create_branches(self):
        """Check if this restaurant can create branches based on subscription plan"""
        return self.subscription_plan == 'PRO' and self.is_main_restaurant
    
    def get_subscription_display(self):
        """Get human-readable subscription plan name"""
        return dict(self.SUBSCRIPTION_PLANS).get(self.subscription_plan, 'Unknown')
    
    def get_remaining_branches_count(self):
        """Get remaining branches that can be created (unlimited for PRO)"""
        if self.subscription_plan == 'PRO':
            return 'Unlimited'
        else:
            return 0
    
    def upgrade_to_pro(self):
        """Upgrade restaurant to PRO plan"""
        if self.is_main_restaurant:
            self.subscription_plan = 'PRO'
            self.save(update_fields=['subscription_plan', 'updated_at'])
            return True
        return False
    
    def downgrade_to_single(self):
        """Downgrade restaurant to SINGLE plan (only if no branches exist)"""
        if self.is_main_restaurant and not self.branches.exists():
            self.subscription_plan = 'SINGLE'
            self.save(update_fields=['subscription_plan', 'updated_at'])
            return True
        return False

    def get_qr_url(self, request=None):
        """Get the URL for QR code access"""
        if request:
            base_url = request.build_absolute_uri('/')
            return f"{base_url}r/{self.qr_code}/"
        else:
            return f"https://hospitality.easyfixsoft.com/r/{self.qr_code}/"
    
    @property
    def tax_rate_percentage(self):
        """Get tax rate as percentage (e.g., 8.0 for 8%)"""
        return float(self.tax_rate * 100)
    
    def get_currency_symbol(self):
        """Get the currency symbol for this restaurant"""
        return self.CURRENCY_SYMBOLS.get(self.currency_code, '$')
    
    def get_currency_code_display(self):
        """Get the currency code"""
        return self.currency_code
    
    def format_currency(self, amount):
        """Format an amount with the correct currency symbol"""
        symbol = self.get_currency_symbol()
        try:
            amount = float(amount)
            # For currencies that typically use integer values
            if self.currency_code in ['KES', 'TZS', 'UGX', 'RWF', 'JPY']:
                return f"{symbol}{amount:,.0f}"
            return f"{symbol}{amount:,.2f}"
        except (TypeError, ValueError):
            return f"{symbol}0.00"
    
    @classmethod
    def get_accessible_restaurants(cls, user):
        """Get all restaurants accessible by the user"""
        if user.is_administrator():
            return cls.objects.all()
        elif user.role and user.role.name == 'main_owner':
            return cls.objects.filter(main_owner=user)
        elif user.role and user.role.name in ['branch_owner', 'owner']:
            return cls.objects.filter(
                models.Q(main_owner=user) | models.Q(branch_owner=user)
            )
        elif user.owner:
            # Staff can access restaurants managed by their owner
            return cls.objects.filter(
                models.Q(main_owner=user.owner) | models.Q(branch_owner=user.owner)
            )
        else:
            return cls.objects.none()