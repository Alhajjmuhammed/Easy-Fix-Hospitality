"""Web views for Staff Attendance management in admin panel."""

import json
from datetime import date, timedelta
from calendar import monthrange, Calendar

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from .models import AttendanceQRToken, AttendanceRecord, Shift


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_owner_and_restaurant(request):
    """Return (owner, current_restaurant) for the logged-in user."""
    user = request.user
    owner = user.get_owner()
    restaurant = None
    if hasattr(owner, 'get_current_restaurant'):
        restaurant = owner.get_current_restaurant(request)
    return owner, restaurant


def _require_can_manage(request):
    """Return True if the user may manage attendance (owner/manager/customer_care). else redirect."""
    u = request.user
    return u.is_any_owner() or u.is_manager() or u.is_customer_care()


def _require_owner_or_manager(request):
    u = request.user
    return u.is_any_owner() or u.is_manager()


def _get_or_create_qr(owner, restaurant):
    qr, _ = AttendanceQRToken.objects.get_or_create(
        owner=owner,
        restaurant=restaurant,
    )
    return qr


def _record_to_dict(rec):
    def fmt(dt):
        return timezone.localtime(dt).strftime('%H:%M') if dt else '—'

    wm = rec.work_minutes
    if wm is not None:
        h, m = divmod(wm, 60)
        work_display = f"{h}h {m}m" if h else f"{m}m"
    else:
        work_display = '—'

    return {
        'id': rec.id,
        'staff_name': rec.staff.get_full_name() or rec.staff.username,
        'staff_role': rec.staff.role.name if rec.staff.role else '—',
        'date': rec.date.isoformat(),
        'check_in': fmt(rec.check_in),
        'check_out': fmt(rec.check_out),
        'work_display': work_display,
        'work_minutes': wm,
        'is_late': rec.is_late,
        'late_minutes': rec.late_minutes,
        'is_overtime': rec.is_overtime,
        'overtime_minutes': rec.overtime_minutes,
        'check_in_via': rec.check_in_via,
        'shift_name': rec.shift.name if rec.shift else '—',
    }


# ─── owner/manager views ──────────────────────────────────────────────────────

@login_required
def attendance_dashboard(request):
    """Today's attendance overview for owner/manager."""
    if not _require_can_manage(request):
        messages.error(request, 'Access denied.')
        return redirect('admin_panel:admin_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)
    today = timezone.localdate()

    records_qs = AttendanceRecord.objects.filter(
        owner=owner, date=today
    ).select_related('staff', 'staff__role', 'shift', 'restaurant').order_by('check_in')

    if restaurant:
        records_qs = records_qs.filter(restaurant=restaurant)

    records = [_record_to_dict(r) for r in records_qs]

    # Staff who haven't checked in yet
    staff_ids_present = records_qs.values_list('staff_id', flat=True)
    absent_staff = User.objects.filter(
        owner=owner, is_active=True, is_active_staff=True
    ).exclude(id__in=staff_ids_present).exclude(id=owner.id)
    # Only show non-customer, non-admin roles
    EXCLUDED_ROLES = {'customer', 'administrator', 'main_owner', 'branch_owner', 'owner'}
    absent_staff = [
        u for u in absent_staff
        if not u.role or u.role.name not in EXCLUDED_ROLES
    ]

    context = {
        'today': today,
        'records': records,
        'absent_staff': absent_staff,
        'checked_in_count': sum(1 for r in records if r['check_in'] != '—'),
        'checked_out_count': sum(1 for r in records if r['check_out'] != '—'),
        'late_count': sum(1 for r in records if r['is_late']),
    }
    return render(request, 'admin_panel/attendance_dashboard.html', context)


@login_required
def attendance_shifts(request):
    """List, create, and edit shifts."""
    if not _require_owner_or_manager(request):
        messages.error(request, 'Access denied.')
        return redirect('admin_panel:admin_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            name = request.POST.get('name', '').strip()
            shift_type = request.POST.get('shift_type', 'custom')
            start = request.POST.get('start_time', '')
            end = request.POST.get('end_time', '')
            grace = int(request.POST.get('grace_minutes', 15))
            if name and start and end:
                Shift.objects.create(
                    owner=owner,
                    restaurant=restaurant,
                    name=name,
                    shift_type=shift_type,
                    start_time=start,
                    end_time=end,
                    grace_minutes=grace,
                )
                messages.success(request, f'Shift "{name}" created.')
            else:
                messages.error(request, 'Name, start time, and end time are required.')

        elif action == 'edit':
            shift_id = request.POST.get('shift_id')
            shift = get_object_or_404(Shift, id=shift_id, owner=owner)
            shift.name = request.POST.get('name', shift.name).strip()
            shift.shift_type = request.POST.get('shift_type', shift.shift_type)
            shift.start_time = request.POST.get('start_time', str(shift.start_time))
            shift.end_time = request.POST.get('end_time', str(shift.end_time))
            shift.grace_minutes = int(request.POST.get('grace_minutes', shift.grace_minutes))
            shift.is_active = request.POST.get('is_active') == 'on'
            shift.save()
            messages.success(request, f'Shift "{shift.name}" updated.')

        elif action == 'delete':
            shift_id = request.POST.get('shift_id')
            shift = get_object_or_404(Shift, id=shift_id, owner=owner)
            shift.delete()
            messages.success(request, 'Shift deleted.')

        return redirect('attendance:shifts')

    shifts = Shift.objects.filter(owner=owner).order_by('start_time')
    if restaurant:
        shifts = shifts.filter(restaurant=restaurant)

    return render(request, 'admin_panel/attendance_shifts.html', {'shifts': shifts})


@login_required
def attendance_calendar(request):
    """Monthly calendar showing daily attendance summary."""
    if not _require_can_manage(request):
        messages.error(request, 'Access denied.')
        return redirect('admin_panel:admin_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)

    today = timezone.localdate()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))

    # Clamp month
    if month < 1: month = 12; year -= 1
    if month > 12: month = 1; year += 1

    _, days_in_month = monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)

    records_qs = AttendanceRecord.objects.filter(
        owner=owner, date__range=(first_day, last_day)
    ).select_related('staff', 'shift')
    if restaurant:
        records_qs = records_qs.filter(restaurant=restaurant)

    # Group by date
    by_date = {}
    for r in records_qs:
        by_date.setdefault(r.date, []).append(r)

    # Build calendar weeks
    cal = Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    calendar_data = []
    for week in weeks:
        week_data = []
        for d in week:
            day_records = by_date.get(d, [])
            week_data.append({
                'date': d,
                'in_month': d.month == month,
                'is_today': d == today,
                'total': len(day_records),
                'present': sum(1 for r in day_records if r.check_in),
                'late': sum(1 for r in day_records if r.is_late),
            })
        calendar_data.append(week_data)

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    context = {
        'year': year,
        'month': month,
        'month_name': first_day.strftime('%B %Y'),
        'calendar_data': calendar_data,
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
    }
    return render(request, 'admin_panel/attendance_calendar.html', context)


@login_required
def attendance_day_records(request):
    """AJAX: return all attendance records for a given date as JSON."""
    if not _require_can_manage(request):
        return JsonResponse({'error': 'Access denied'}, status=403)

    owner, restaurant = _get_owner_and_restaurant(request)
    day_str = request.GET.get('date')
    if not day_str:
        return JsonResponse({'error': 'date param required'}, status=400)

    records_qs = AttendanceRecord.objects.filter(
        owner=owner, date=day_str
    ).select_related('staff', 'staff__role', 'shift', 'restaurant')
    if restaurant:
        records_qs = records_qs.filter(restaurant=restaurant)

    return JsonResponse({'records': [_record_to_dict(r) for r in records_qs]})


@login_required
def attendance_qr(request):
    """Display and optionally regenerate the attendance QR code for the restaurant."""
    if not _require_owner_or_manager(request):
        messages.error(request, 'Access denied.')
        return redirect('admin_panel:admin_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)
    qr_obj = _get_or_create_qr(owner, restaurant)

    # Generate QR image as data URI
    import qrcode
    import io, base64
    img = qrcode.make(qr_obj.token)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_data_uri = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    context = {
        'qr_token': qr_obj.token,
        'qr_data_uri': qr_data_uri,
        'restaurant_name': restaurant.name if restaurant else owner.restaurant_name,
        'regenerated_at': qr_obj.regenerated_at,
    }
    return render(request, 'admin_panel/attendance_qr.html', context)


@login_required
@require_POST
def attendance_qr_regenerate(request):
    """Regenerate the attendance QR token."""
    if not _require_owner_or_manager(request):
        return JsonResponse({'error': 'Access denied'}, status=403)

    owner, restaurant = _get_owner_and_restaurant(request)
    qr_obj = _get_or_create_qr(owner, restaurant)
    qr_obj.regenerate()
    messages.success(request, 'Attendance QR code regenerated.')
    return redirect('attendance:qr')


# ─── staff-facing views ───────────────────────────────────────────────────────

@login_required
def attendance_web_checkin(request):
    """Staff can check in or check out via the web browser."""
    user = request.user
    today = timezone.localdate()
    now = timezone.now()
    now_time = timezone.localtime().time()
    owner = user.get_owner()

    # Try to determine restaurant from session
    restaurant = None
    if hasattr(owner, 'get_current_restaurant'):
        restaurant = owner.get_current_restaurant(request)

    # Find appropriate shift
    from .views_mobile import _best_shift
    shift = _best_shift(owner, restaurant, now_time)

    try:
        record = AttendanceRecord.objects.get(staff=user, date=today)
    except AttendanceRecord.DoesNotExist:
        record = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'check_in':
            if record and record.check_in:
                messages.warning(request, 'You have already checked in today.')
            else:
                record, _ = AttendanceRecord.objects.get_or_create(
                    staff=user, date=today,
                    defaults={'owner': owner, 'restaurant': restaurant, 'shift': shift},
                )
                record.check_in = now
                record.check_in_via = 'web'
                if not record.shift:
                    record.shift = shift
                record.save()
                messages.success(request, f"Checked in at {timezone.localtime(now).strftime('%H:%M')}.")

        elif action == 'check_out':
            if not record or not record.check_in:
                messages.warning(request, 'You have not checked in yet today.')
            elif record.check_out:
                messages.warning(request, 'You have already checked out today.')
            else:
                record.check_out = now
                record.check_out_via = 'web'
                record.compute_metrics()
                record.save()
                messages.success(request, f"Checked out at {timezone.localtime(now).strftime('%H:%M')}.")

        return redirect('attendance:web_checkin')

    # Reload after potential POST
    try:
        record = AttendanceRecord.objects.select_related('shift').get(staff=user, date=today)
    except AttendanceRecord.DoesNotExist:
        record = None

    context = {
        'today': today,
        'record': record,
        'shift': shift,
        'current_time': timezone.localtime().strftime('%H:%M'),
    }
    return render(request, 'admin_panel/attendance_checkin.html', context)


@login_required
def attendance_my(request):
    """Staff views their own attendance history."""
    user = request.user
    today = timezone.localdate()

    # Default: current month
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))

    from_date = date(year, month, 1)
    _, days_in_month = monthrange(year, month)
    to_date = date(year, month, days_in_month)

    records = AttendanceRecord.objects.filter(
        staff=user, date__range=(from_date, to_date)
    ).select_related('shift', 'restaurant').order_by('-date')

    context = {
        'records': records,
        'year': year,
        'month': month,
        'month_name': from_date.strftime('%B %Y'),
        'prev_year': year if month > 1 else year - 1,
        'prev_month': month - 1 if month > 1 else 12,
        'next_year': year if month < 12 else year + 1,
        'next_month': month + 1 if month < 12 else 1,
        'today': today,
    }
    return render(request, 'admin_panel/attendance_my.html', context)
