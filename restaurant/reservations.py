"""
Reservation rules shared by the website and the mobile API, so both behave identically.
"""
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models_reservation import Reservation

MIN_NOTICE = timedelta(minutes=15)   # customers can't book a table for "right now"
MAX_AHEAD = timedelta(days=90)
MAX_PARTY = 100
MAX_ACTIVE_PER_CUSTOMER = 5         # upcoming pending/confirmed bookings per customer per restaurant


def _restaurant_owner(restaurant):
    return restaurant.branch_owner or restaurant.main_owner


def tables_for_restaurant(restaurant):
    """Tables of this restaurant, including older tables linked only to the owner account."""
    from django.db.models import Q
    from .models import TableInfo
    return TableInfo.objects.filter(
        Q(restaurant=restaurant) | Q(restaurant__isnull=True, owner=_restaurant_owner(restaurant))
    ).order_by('tbl_no')


def table_belongs(table, restaurant):
    if table.restaurant_id:
        return table.restaurant_id == restaurant.id
    owner = _restaurant_owner(restaurant)
    return owner is not None and table.owner_id == owner.id


def module_enabled(restaurant):
    """False when the system admin switched reservations off in Module Access."""
    for owner in {restaurant.branch_owner, restaurant.main_owner} - {None}:
        try:
            if owner.subscription.disabled_features.filter(slug='view_reservations').exists():
                return False
        except Exception:
            continue  # no subscription record → no restriction (same rule as User.has_feature)
    return True


def open_for_bookings(restaurant):
    """Customers may book here right now (setting on, module allowed, restaurant open)."""
    return (restaurant.reservations_enabled and module_enabled(restaurant)
            and restaurant.open_owner() is not None)


def parse_start(date_str, time_str):
    """'2026-11-02' + '19:30' in the restaurant's local time → aware datetime."""
    try:
        naive = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        raise ValidationError('Please choose a valid date and time.')
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _clean_text(value, max_len):
    return (str(value or '').strip())[:max_len]


def create_reservation(restaurant, *, name, phone, party_size, start, email='', notes='',
                       customer=None, created_by=None, source='staff', table=None, staff=False):
    """
    Validate and create a booking. Customer bookings follow the restaurant's auto-confirm
    setting; bookings entered by staff are confirmed straight away.
    Returns (reservation, warnings). Raises ValidationError with a user-facing message.
    """
    name = _clean_text(name, 120)
    phone = _clean_text(phone, 30)
    if not name:
        raise ValidationError('Please enter the name for the booking.')
    if not phone:
        raise ValidationError('Please enter a phone number.')
    try:
        party_size = int(party_size)
    except (TypeError, ValueError):
        raise ValidationError('Please enter the number of people.')
    if not 1 <= party_size <= MAX_PARTY:
        raise ValidationError(f'Number of people must be between 1 and {MAX_PARTY}.')

    now = timezone.now()
    if not staff:
        if not open_for_bookings(restaurant):
            raise ValidationError('This restaurant is not taking reservations right now.')
        if start < now + MIN_NOTICE:
            raise ValidationError('Please choose a time at least 15 minutes from now.')
        if customer is not None:
            mine = Reservation.objects.filter(customer=customer, restaurant=restaurant,
                                              status__in=('pending', 'confirmed'), start__gte=now)
            if mine.filter(start=start).exists():
                raise ValidationError('You already have a booking at this time.')
            if mine.count() >= MAX_ACTIVE_PER_CUSTOMER:
                raise ValidationError(f'You can have at most {MAX_ACTIVE_PER_CUSTOMER} upcoming bookings here. '
                                      'Please cancel one first.')
    elif start < now - timedelta(hours=12):
        raise ValidationError('That time is in the past.')
    if start > now + MAX_AHEAD:
        raise ValidationError('Bookings can be made up to 90 days ahead.')
    if table is not None and not table_belongs(table, restaurant):
        raise ValidationError('That table belongs to another restaurant.')

    status = 'confirmed' if (staff or restaurant.reservations_auto_confirm) else 'pending'
    res = Reservation(
        restaurant=restaurant, customer=customer, name=name, phone=phone,
        email=_clean_text(email, 254), party_size=party_size, start=start,
        duration_minutes=restaurant.reservation_duration_minutes or 120,
        table=table, status=status, notes=_clean_text(notes, 1000),
        source=source, created_by=created_by,
    )
    res.full_clean(exclude=['customer', 'table', 'created_by', 'status_changed_by'])
    res.save()
    _notify_new(res)
    if status == 'confirmed' and customer is not None and not staff:
        _notify_customer(res)
    elif status == 'confirmed' and staff:
        # Booked by phone / at the counter: a confirmation text (when the restaurant switched it on)
        from orders.sms import reservation_changed  # never raises
        reservation_changed(res)
    return res, res.warnings()


def change_status(res, new_status, by_user):
    """Staff status change following Reservation.STAFF_TRANSITIONS."""
    with transaction.atomic():
        res = Reservation.objects.select_for_update().get(pk=res.pk)
        if new_status not in Reservation.STAFF_TRANSITIONS.get(res.status, ()):
            raise ValidationError(
                f'A {res.get_status_display().lower()} reservation cannot be changed to '
                f'{dict(Reservation.STATUS_CHOICES).get(new_status, new_status).lower()}.')
        res.status = new_status
        res.status_changed_by = by_user
        res.status_changed_at = timezone.now()
        res.save(update_fields=['status', 'status_changed_by', 'status_changed_at', 'updated_at'])
    if new_status in ('confirmed', 'declined', 'cancelled'):
        _notify_customer(res)
    return res


def assign_table(res, table, by_user=None):
    """Assign (or clear with table=None) a table. Returns warnings (never blocks)."""
    if table is not None and not table_belongs(table, res.restaurant):
        raise ValidationError('That table belongs to another restaurant.')
    if not res.is_active:
        raise ValidationError('Tables can only be assigned to pending, confirmed or seated bookings.')
    res.table = table
    res.save(update_fields=['table', 'updated_at'])
    return res.warnings()


def customer_cancel(res, user):
    """Customer cancels their own pending/confirmed booking before it starts."""
    with transaction.atomic():
        res = Reservation.objects.select_for_update().get(pk=res.pk)
        if res.customer_id != user.id:
            raise ValidationError('Reservation not found.')
        if not res.can_customer_cancel():
            raise ValidationError('This reservation can no longer be cancelled.')
        res.status = 'cancelled'
        res.status_changed_by = user
        res.status_changed_at = timezone.now()
        res.save(update_fields=['status', 'status_changed_by', 'status_changed_at', 'updated_at'])
    try:
        from orders.push import notify_reservation_cancelled_by_customer
        notify_reservation_cancelled_by_customer(res)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Cancel push failed for reservation %s', res.pk, exc_info=True)
    return res


def _notify_new(res):
    try:
        from orders.push import notify_new_reservation
        notify_new_reservation(res)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('New-reservation push failed for %s', res.pk, exc_info=True)


def _notify_customer(res):
    try:
        from orders.push import notify_reservation_status
        notify_reservation_status(res)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Reservation status push failed for %s', res.pk, exc_info=True)
    from orders.sms import reservation_changed  # never raises
    reservation_changed(res)
