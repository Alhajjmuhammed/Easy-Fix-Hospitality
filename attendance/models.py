import uuid
from datetime import timedelta, datetime, time

from django.conf import settings
from django.db import models
from django.utils import timezone


def _generate_token():
    return f"ATT-{uuid.uuid4().hex[:20].upper()}"


class AttendanceQRToken(models.Model):
    """One QR token per restaurant (or owner's single restaurant)."""
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_qr_tokens',
    )
    restaurant = models.OneToOneField(
        'restaurant.Restaurant',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='attendance_qr_token',
    )
    token = models.CharField(max_length=64, unique=True, default=_generate_token)
    created_at = models.DateTimeField(auto_now_add=True)
    regenerated_at = models.DateTimeField(auto_now=True)

    def regenerate(self):
        self.token = _generate_token()
        self.save()

    def __str__(self):
        rest = self.restaurant.name if self.restaurant else 'Main'
        return f"QR [{self.owner.username}] {rest}"


class Shift(models.Model):
    SHIFT_TYPES = [
        ('day',    'Day Shift'),
        ('night',  'Night Shift'),
        ('custom', 'Custom'),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shifts',
    )
    restaurant = models.ForeignKey(
        'restaurant.Restaurant',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='shifts',
    )
    name = models.CharField(max_length=100)
    shift_type = models.CharField(max_length=20, choices=SHIFT_TYPES, default='custom')
    start_time = models.TimeField(help_text='Expected check-in time')
    end_time = models.TimeField(help_text='Expected check-out time')
    grace_minutes = models.PositiveIntegerField(
        default=15,
        help_text='Minutes after start_time before staff is marked late',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}–{self.end_time:%H:%M})"


class AttendanceRecord(models.Model):
    VIA_CHOICES = [('mobile', 'Mobile'), ('web', 'Web')]

    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='managed_attendance',
        null=True,
    )
    restaurant = models.ForeignKey(
        'restaurant.Restaurant',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='attendance_records',
    )
    shift = models.ForeignKey(
        Shift,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='attendance_records',
    )
    date = models.DateField()
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    work_minutes = models.IntegerField(null=True, blank=True)
    is_late = models.BooleanField(default=False)
    late_minutes = models.IntegerField(default=0)
    is_overtime = models.BooleanField(default=False)
    overtime_minutes = models.IntegerField(default=0)
    check_in_via = models.CharField(max_length=10, choices=VIA_CHOICES, default='mobile')
    check_out_via = models.CharField(max_length=10, choices=VIA_CHOICES, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['staff', 'date']
        ordering = ['-date', '-check_in']

    def __str__(self):
        return f"{self.staff.username} — {self.date}"

    def compute_metrics(self):
        """Recalculate work_minutes, is_late, is_overtime after check-out."""
        if not self.check_in or not self.check_out:
            return
        delta = self.check_out - self.check_in
        self.work_minutes = max(0, int(delta.total_seconds() / 60))

        if self.shift:
            record_date = self.date
            tz = timezone.get_current_timezone()

            def aware(d, t):
                return timezone.make_aware(datetime.combine(d, t), tz)

            expected_in = aware(record_date, self.shift.start_time)
            late_threshold = expected_in + timedelta(minutes=self.shift.grace_minutes)

            if self.check_in > late_threshold:
                self.is_late = True
                self.late_minutes = int((self.check_in - late_threshold).total_seconds() / 60)

            expected_out = aware(record_date, self.shift.end_time)
            if self.shift.end_time < self.shift.start_time:
                expected_out += timedelta(days=1)

            if self.check_out > expected_out:
                self.is_overtime = True
                self.overtime_minutes = int((self.check_out - expected_out).total_seconds() / 60)
