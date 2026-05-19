from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.contrib.auth import get_user_model
from decimal import Decimal

User = get_user_model()

# Import Restaurant model for hierarchical management
from .models_restaurant import Restaurant

class TableInfo(models.Model):
    # Legacy owner field (will be deprecated)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tables', 
                             limit_choices_to={'role__name__in': ['owner', 'main_owner', 'branch_owner']}, 
                             null=True, blank=True)
    
    # New restaurant field for hierarchical management
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='tables',
                                  null=True, blank=True, help_text="Restaurant/branch this table belongs to")
    
    tbl_no = models.CharField(
        max_length=10,
        validators=[
            RegexValidator(
                regex=r'^[A-Za-z0-9\-_]+$',
                message='Table number can only contain letters, numbers, hyphens, and underscores.'
            )
        ],
        help_text="Unique table identifier (e.g., T1, A-01, VIP-1)"
    )
    capacity = models.IntegerField(
        default=4,
        validators=[
            MinValueValidator(1, message='Capacity must be at least 1.'),
            MaxValueValidator(50, message='Capacity cannot exceed 50.')
        ],
        help_text="Maximum seating capacity for this table"
    )
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Note: Meta class is defined after all methods (see below)
    
    def __str__(self):
        if self.restaurant:
            return f"Table {self.tbl_no} ({self.restaurant.name})"
        elif self.owner:
            return f"Table {self.tbl_no} ({self.owner.restaurant_name})"
        else:
            return f"Table {self.tbl_no}"
    
    def get_restaurant(self):
        """Get the restaurant for this table"""
        if self.restaurant:
            return self.restaurant
        elif self.owner and hasattr(self.owner, 'managed_restaurant') and self.owner.managed_restaurant.exists():
            return self.owner.managed_restaurant.first()
        return None
    
    def get_owner(self):
        """Get the owner for this table (backward compatibility)"""
        if self.restaurant:
            return self.restaurant.branch_owner or self.restaurant.main_owner
        return self.owner
    
    def get_tax_rate(self):
        """Get tax rate for this table from Restaurant or Owner"""
        from decimal import Decimal
        # Priority 1: Restaurant model
        if self.restaurant:
            return self.restaurant.tax_rate
        # Priority 2: Table's owner
        if self.owner and hasattr(self.owner, 'tax_rate'):
            return self.owner.tax_rate
        # Default fallback
        return Decimal('0.0800')
    
    def get_active_orders(self):
        """Get active orders for this table"""
        return self.orders.filter(
            status__in=['pending', 'confirmed', 'preparing', 'ready', 'served'],
            payment_status__in=['unpaid', 'partial']
        )
    
    def is_truly_available(self):
        """Check if table is truly available (no active orders)"""
        return self.is_available and not self.get_active_orders().exists()
    
    def get_occupying_order(self):
        """Get the current order occupying this table"""
        active_orders = self.get_active_orders()
        return active_orders.first() if active_orders.exists() else None
    
    class Meta:
        verbose_name = "Table Information"
        verbose_name_plural = "Tables Information"
        indexes = [
            models.Index(fields=['is_available']),
            models.Index(fields=['owner']),
            models.Index(fields=['restaurant']),
        ]
        constraints = [
            # Ensure either owner or restaurant is set
            models.CheckConstraint(
                check=models.Q(owner__isnull=False) | models.Q(restaurant__isnull=False),
                name='table_must_have_owner_or_restaurant'
            ),
            # Unique table numbers per owner (legacy)
            models.UniqueConstraint(
                fields=['owner', 'tbl_no'],
                condition=models.Q(owner__isnull=False),
                name='unique_table_per_owner'
            ),
            # Unique table numbers per restaurant (new system)
            models.UniqueConstraint(
                fields=['restaurant', 'tbl_no'],
                condition=models.Q(restaurant__isnull=False),
                name='unique_table_per_restaurant'
            ),
        ]

class MainCategory(models.Model):
    # Legacy owner field (will be deprecated)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='main_categories',
                             limit_choices_to={'role__name__in': ['owner', 'main_owner', 'branch_owner']}, 
                             null=True, blank=True)
    
    # New restaurant field for hierarchical management
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='main_categories',
                                  null=True, blank=True, help_text="Restaurant/branch this category belongs to")
    
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Main Category"
        verbose_name_plural = "Main Categories"
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['owner']),
            models.Index(fields=['restaurant']),
        ]
        # Updated unique constraint to work with both owner and restaurant
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'name'],
                condition=models.Q(owner__isnull=False),
                name='unique_category_per_owner'
            ),
            models.UniqueConstraint(
                fields=['restaurant', 'name'], 
                condition=models.Q(restaurant__isnull=False),
                name='unique_category_per_restaurant'
            ),
            models.CheckConstraint(
                check=models.Q(owner__isnull=False) | models.Q(restaurant__isnull=False),
                name='category_must_have_owner_or_restaurant'
            ),
        ]
    
    def __str__(self):
        if self.restaurant:
            return f"{self.name} ({self.restaurant.name})"
        elif self.owner:
            return f"{self.name} ({self.owner.restaurant_name})"
        else:
            return self.name
    
    def get_restaurant(self):
        """Get the restaurant for this category"""
        if self.restaurant:
            return self.restaurant
        elif self.owner and hasattr(self.owner, 'managed_restaurant') and self.owner.managed_restaurant.exists():
            return self.owner.managed_restaurant.first()
        return None
    
    def get_owner(self):
        """Get the owner for this category (backward compatibility)"""
        if self.restaurant:
            return self.restaurant.branch_owner or self.restaurant.main_owner
        return self.owner

class SubCategory(models.Model):
    main_category = models.ForeignKey(MainCategory, on_delete=models.CASCADE, related_name='subcategories')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    @property
    def owner(self):
        """Get owner for backward compatibility"""
        return self.main_category.get_owner()
    
    @property
    def restaurant(self):
        """Get restaurant for this subcategory"""
        return self.main_category.get_restaurant()
    
    def __str__(self):
        if self.main_category.restaurant:
            return f"{self.main_category.name} - {self.name} ({self.main_category.restaurant.name})"
        elif self.main_category.owner:
            return f"{self.main_category.name} - {self.name} ({self.main_category.owner.restaurant_name})"
        else:
            return f"{self.main_category.name} - {self.name}"
    
    class Meta:
        verbose_name = "Sub Category"
        verbose_name_plural = "Sub Categories"
        unique_together = ['main_category', 'name']

class Product(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()
    main_category = models.ForeignKey(MainCategory, on_delete=models.CASCADE, related_name='products')
    sub_category = models.ForeignKey(SubCategory, on_delete=models.CASCADE, related_name='products', null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    available_in_stock = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    is_available = models.BooleanField(default=True)
    preparation_time = models.IntegerField(help_text="Time in minutes", default=15)
    station = models.CharField(max_length=20, choices=[('kitchen', 'Kitchen'), ('bar', 'Bar'), ('buffet', 'Buffet'), ('service', 'Service')], default='kitchen', help_text="Assign to kitchen, bar, buffet, or service station")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    @property
    def owner(self):
        """Get owner for backward compatibility"""
        return self.main_category.get_owner()
    
    @property
    def restaurant(self):
        """Get restaurant for this product"""
        return self.main_category.get_restaurant()
    
    def __str__(self):
        if self.main_category.restaurant:
            return f"{self.name} ({self.main_category.restaurant.name})"
        elif self.main_category.owner:
            return f"{self.name} ({self.main_category.owner.restaurant_name})"
        else:
            return self.name
    
    def is_in_stock(self):
        return self.available_in_stock > 0 and self.is_available
    
    def get_image(self):
        """Get the category image for this product"""
        return self.main_category.image
    
    def get_current_price(self):
        """Get current price considering active Happy Hour promotions"""
        from django.utils import timezone
        
        # Get current time in the configured timezone
        now = timezone.localtime(timezone.now())
        current_day = str(now.weekday() + 1)  # Monday=1, Sunday=7
        current_time = now.time()
        
        # Get all potentially active promotions for this product
        potential_promotions = HappyHourPromotion.objects.filter(
            owner=self.owner,
            is_active=True,
            days_of_week__contains=current_day
        ).filter(
            models.Q(products=self) |
            models.Q(main_categories=self.main_category) |
            models.Q(sub_categories=self.sub_category)
        ).order_by('-discount_percentage')  # Get highest discount first
        
        # Check each promotion for time-based activation (handles cross-midnight)
        active_promotions = []
        for promotion in potential_promotions:
            if promotion.start_time <= promotion.end_time:
                # Normal case: start_time < end_time (same day)
                if promotion.start_time <= current_time <= promotion.end_time:
                    active_promotions.append(promotion)
            else:
                # Cross-midnight case: start_time > end_time
                if current_time >= promotion.start_time or current_time <= promotion.end_time:
                    active_promotions.append(promotion)
        
        if active_promotions:
            promotion = active_promotions[0]  # Highest discount first
            discount_amount = self.price * (promotion.discount_percentage / Decimal('100'))
            discounted_price = self.price - discount_amount
            return max(discounted_price, Decimal('0.01'))  # Ensure minimum price
        
        return self.price
    
    def get_active_promotion(self):
        """Get the currently active promotion for this product"""
        from django.utils import timezone
        
        # Get current time in the configured timezone
        now = timezone.localtime(timezone.now())
        current_day = str(now.weekday() + 1)  # Monday=1, Sunday=7
        current_time = now.time()
        
        # Get all potentially active promotions for this product
        potential_promotions = HappyHourPromotion.objects.filter(
            owner=self.owner,
            is_active=True,
            days_of_week__contains=current_day
        ).filter(
            models.Q(products=self) |
            models.Q(main_categories=self.main_category) |
            models.Q(sub_categories=self.sub_category)
        ).order_by('-discount_percentage')  # Get highest discount first
        
        # Check each promotion for time-based activation (handles cross-midnight)
        for promotion in potential_promotions:
            if promotion.start_time <= promotion.end_time:
                # Normal case: start_time < end_time (same day)
                if promotion.start_time <= current_time <= promotion.end_time:
                    return promotion
            else:
                # Cross-midnight case: start_time > end_time
                if current_time >= promotion.start_time or current_time <= promotion.end_time:
                    return promotion
                    
        return None
    
    def has_active_promotion(self):
        """Check if product has an active promotion"""
        return self.get_active_promotion() is not None
    
    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_available']),
            models.Index(fields=['main_category']),
            models.Index(fields=['station']),
        ]


class HappyHourPromotion(models.Model):
    DAYS_CHOICES = [
        ('1', 'Monday'),
        ('2', 'Tuesday'),
        ('3', 'Wednesday'),
        ('4', 'Thursday'),
        ('5', 'Friday'),
        ('6', 'Saturday'),
        ('7', 'Sunday'),
    ]
    
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='happy_hour_promotions',
                             limit_choices_to={'role__name__in': ['owner', 'main_owner', 'branch_owner']})
    name = models.CharField(max_length=100, help_text="e.g., 'Happy Hour Special', 'Weekend Discount'")
    description = models.TextField(blank=True, help_text="Optional description of the promotion")
    
    # Discount settings
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, 
                                            validators=[MinValueValidator(Decimal('0.01')), 
                                                      MaxValueValidator(Decimal('99.99'))],
                                            help_text="Discount percentage (1-99)")
    
    # Time settings
    start_time = models.TimeField(help_text="Start time for the promotion")
    end_time = models.TimeField(help_text="End time for the promotion")
    days_of_week = models.CharField(max_length=13, help_text="Comma-separated days (1=Mon, 7=Sun), e.g., '1,2,3,4,5' for weekdays")
    
    # Promotion targets - can apply to products, categories, or subcategories
    products = models.ManyToManyField(Product, blank=True, related_name='happy_hour_promotions',
                                     help_text="Specific products for this promotion")
    main_categories = models.ManyToManyField(MainCategory, blank=True, related_name='happy_hour_promotions',
                                           help_text="Main categories for this promotion")
    sub_categories = models.ManyToManyField(SubCategory, blank=True, related_name='happy_hour_promotions',
                                          help_text="Sub categories for this promotion")
    
    # Status and metadata
    is_active = models.BooleanField(default=True, help_text="Enable/disable this promotion")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} - {self.discount_percentage}% ({self.owner.restaurant_name})"
    
    def get_days_display(self):
        """Return human-readable days"""
        day_names = {
            '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu',
            '5': 'Fri', '6': 'Sat', '7': 'Sun'
        }
        if self.days_of_week:
            days = self.days_of_week.split(',')
            return ', '.join([day_names.get(day.strip(), day.strip()) for day in days])
        return 'No days selected'
    
    def is_currently_active(self):
        """Check if promotion is currently active based on time and day"""
        if not self.is_active:
            return False
            
        from django.utils import timezone
        
        # Get current time in the configured timezone
        now = timezone.localtime(timezone.now())
        current_day = str(now.weekday() + 1)  # Monday=1, Sunday=7
        current_time = now.time()
        
        # Check if current day is in promotion days
        if current_day not in self.days_of_week.split(','):
            return False
        
        # Check if current time is within promotion hours
        if self.start_time <= self.end_time:
            # Normal case: start_time < end_time (same day)
            return self.start_time <= current_time <= self.end_time
        else:
            # Cross-midnight case: start_time > end_time
            return current_time >= self.start_time or current_time <= self.end_time
    
    def get_affected_products_count(self):
        """Get count of products affected by this promotion"""
        from django.db.models import Q
        
        # Products directly selected
        direct_products = self.products.count()
        
        # Products from selected main categories
        category_products = Product.objects.filter(main_category__in=self.main_categories.all()).count()
        
        # Products from selected sub categories
        subcategory_products = Product.objects.filter(sub_category__in=self.sub_categories.all()).count()
        
        # Use Q objects to avoid double counting
        total_products = Product.objects.filter(
            Q(pk__in=self.products.all()) |
            Q(main_category__in=self.main_categories.all()) |
            Q(sub_category__in=self.sub_categories.all()),
            main_category__owner=self.owner
        ).distinct().count()
        
        return total_products
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Happy Hour Promotion"
        verbose_name_plural = "Happy Hour Promotions"


class Event(models.Model):
    """
    Event/Banquet model for tracking special events with fixed price per person (PAX).
    Available for all subscription plans: SINGLE, Branch, and PRO.
    """
    
    EVENT_TYPE_CHOICES = [
        ('wedding', 'Wedding'),
        ('corporate', 'Corporate Event'),
        ('birthday', 'Birthday Party'),
        ('anniversary', 'Anniversary'),
        ('graduation', 'Graduation'),
        ('conference', 'Conference'),
        ('seminar', 'Seminar'),
        ('cocktail', 'Cocktail Party'),
        ('buffet', 'Buffet Event'),
        ('private_dining', 'Private Dining'),
        ('holiday', 'Holiday Event'),
        ('other', 'Other'),
    ]
    
    EVENT_STATUS_CHOICES = [
        ('inquiry', 'Inquiry'),
        ('pending', 'Pending Confirmation'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('deposit_paid', 'Deposit Paid'),
        ('partially_paid', 'Partially Paid'),
        ('fully_paid', 'Fully Paid'),
        ('refunded', 'Refunded'),
    ]
    
    # Owner/Restaurant relationship
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='events',
        limit_choices_to={'role__name__in': ['owner', 'main_owner', 'branch_owner']},
        help_text="Restaurant owner managing this event"
    )
    
    # Event Details
    title = models.CharField(
        max_length=200,
        help_text="Event title (e.g., 'Smith Wedding Reception')"
    )
    
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPE_CHOICES,
        default='other',
        help_text="Type of event"
    )
    
    description = models.TextField(
        blank=True,
        help_text="Additional details about the event"
    )
    
    # Date and Time
    event_date = models.DateField(
        help_text="Date of the event"
    )
    
    start_time = models.TimeField(
        help_text="Event start time"
    )
    
    end_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Event end time (optional)"
    )
    
    # PAX and Pricing
    total_pax = models.PositiveIntegerField(
        help_text="Total number of guests/persons"
    )
    
    price_per_pax = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price per person"
    )
    
    # Contact Information
    contact_name = models.CharField(
        max_length=100,
        help_text="Client/organizer name"
    )
    
    contact_phone = models.CharField(
        max_length=20,
        help_text="Client phone number"
    )
    
    contact_email = models.EmailField(
        blank=True,
        help_text="Client email address (optional)"
    )
    
    # Payment Tracking
    deposit_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Deposit amount received"
    )
    
    amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total amount paid so far"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=EVENT_STATUS_CHOICES,
        default='inquiry',
        help_text="Current status of the event"
    )
    
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='unpaid',
        help_text="Payment status"
    )
    
    # Additional Notes
    special_requirements = models.TextField(
        blank=True,
        help_text="Dietary requirements, setup instructions, etc."
    )
    
    internal_notes = models.TextField(
        blank=True,
        help_text="Internal notes (not visible to client)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='events_created',
        help_text="User who created this event"
    )
    
    class Meta:
        ordering = ['-event_date', '-start_time']
        verbose_name = "Event"
        verbose_name_plural = "Events"
        indexes = [
            models.Index(fields=['event_date']),
            models.Index(fields=['status']),
            models.Index(fields=['owner', 'event_date']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.event_date} ({self.total_pax} PAX)"
    
    @property
    def total_amount(self):
        """Calculate total event cost"""
        return self.total_pax * self.price_per_pax
    
    @property
    def balance_due(self):
        """Calculate remaining balance"""
        return self.total_amount - self.amount_paid
    
    @property
    def deposit_percentage(self):
        """Calculate deposit as percentage of total"""
        if self.total_amount > 0:
            return (self.deposit_amount / self.total_amount) * 100
        return Decimal('0.00')
    
    @property
    def payment_percentage(self):
        """Calculate payment progress as percentage"""
        if self.total_amount > 0:
            return (self.amount_paid / self.total_amount) * 100
        return Decimal('0.00')
    
    @property
    def is_upcoming(self):
        """Check if event is upcoming"""
        from django.utils import timezone
        today = timezone.now().date()
        return self.event_date >= today and self.status not in ['completed', 'cancelled']
    
    @property
    def is_today(self):
        """Check if event is today"""
        from django.utils import timezone
        return self.event_date == timezone.now().date()
    
    @property
    def is_past(self):
        """Check if event date has passed"""
        from django.utils import timezone
        return self.event_date < timezone.now().date()
    
    def get_status_color(self):
        """Get Bootstrap color class for status"""
        colors = {
            'inquiry': 'secondary',
            'pending': 'warning',
            'confirmed': 'info',
            'in_progress': 'primary',
            'completed': 'success',
            'cancelled': 'danger',
        }
        return colors.get(self.status, 'secondary')
    
    def get_payment_status_color(self):
        """Get Bootstrap color class for payment status"""
        colors = {
            'unpaid': 'danger',
            'deposit_paid': 'warning',
            'partially_paid': 'info',
            'fully_paid': 'success',
            'refunded': 'secondary',
        }
        return colors.get(self.payment_status, 'secondary')
    
    def update_payment_status(self):
        """Auto-update payment status based on amounts"""
        if self.amount_paid <= 0:
            self.payment_status = 'unpaid'
        elif self.amount_paid >= self.total_amount:
            self.payment_status = 'fully_paid'
        elif self.amount_paid == self.deposit_amount and self.deposit_amount > 0:
            self.payment_status = 'deposit_paid'
        else:
            self.payment_status = 'partially_paid'
    
    def save(self, *args, **kwargs):
        # Auto-update payment status
        self.update_payment_status()
        super().save(*args, **kwargs)
