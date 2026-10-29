from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .models_restaurant import Restaurant


class Reservation(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('declined', 'Declined'),
        ('cancelled', 'Cancelled'),
        ('seated', 'Seated'),
        ('completed', 'Completed'),
        ('no_show', 'No-show'),
    ]
    # Bookings that still hold a table at their time
    ACTIVE_STATUSES = ('pending', 'confirmed', 'seated')
    # Allowed status changes by staff
    STAFF_TRANSITIONS = {
        'pending':   ('confirmed', 'declined', 'cancelled'),
        'confirmed': ('seated', 'no_show', 'cancelled'),
        'seated':    ('completed',),
        'declined':  (),
        'cancelled': (),
        'completed': (),
        'no_show':   (),
    }
    SOURCE_CHOICES = [('web', 'Website'), ('app', 'Mobile app'), ('staff', 'Staff')]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='reservations')
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reservations', help_text='Customer account (empty for bookings taken by phone/walk-in)')
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    party_size = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    start = models.DateTimeField(help_text='Reservation date and time')
    duration_minutes = models.PositiveSmallIntegerField(
        default=120, validators=[MinValueValidator(15), MaxValueValidator(720)])
    table = models.ForeignKey('restaurant.TableInfo', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='reservations')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, help_text='Request from the customer')
    staff_notes = models.TextField(blank=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='staff')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='reservations_created')
    status_changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                          blank=True, related_name='reservations_updated')
    status_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start']
        indexes = [
            models.Index(fields=['restaurant', 'start']),
            models.Index(fields=['status']),
            models.Index(fields=['customer', 'start']),
        ]

    def __str__(self):
        return f"{self.name} x{self.party_size} @ {timezone.localtime(self.start):%Y-%m-%d %H:%M} ({self.get_status_display()})"

    @property
    def end(self):
        return self.start + timedelta(minutes=self.duration_minutes)

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    def can_customer_cancel(self):
        return self.status in ('pending', 'confirmed') and self.start > timezone.now()

    def overlapping_conflicts(self):
        """Other active bookings for the same table whose time overlaps this one."""
        if not self.table_id:
            return []
        # Durations are capped at 12h, so only bookings starting in the previous 24h can overlap.
        candidates = Reservation.objects.filter(
            table_id=self.table_id, status__in=self.ACTIVE_STATUSES,
            start__lt=self.end, start__gt=self.start - timedelta(hours=24),
        ).exclude(pk=self.pk)
        return [r for r in candidates if r.end > self.start]

    def warnings(self):
        """Human-readable warnings for staff (never blocking)."""
        out = []
        for other in self.overlapping_conflicts():
            out.append(
                f"Table {self.table.tbl_no} is already booked for {other.name} "
                f"({timezone.localtime(other.start):%H:%M}–{timezone.localtime(other.end):%H:%M})."
            )
        if self.table_id and self.table.capacity and self.party_size > self.table.capacity:
            out.append(f"Party of {self.party_size} is larger than table {self.table.tbl_no} (seats {self.table.capacity}).")
        return out


def reservations_for_owner(owner):
    """Reservations visible to staff of this owner account (same scope rule as orders/tables)."""
    return Reservation.objects.filter(Q(restaurant__branch_owner=owner) | Q(restaurant__main_owner=owner))
