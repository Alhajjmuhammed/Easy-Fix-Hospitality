"""Web views for Staff Attendance management in admin panel."""

import json
from collections import defaultdict
from datetime import date, timedelta
from calendar import monthrange, Calendar

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from accounts.models import User
from cashier.views import _safe_csv
from .models import AttendanceQRToken, AttendanceRecord, Shift, AttendancePolicy


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_owner_and_restaurant(request):
    """Return (owner, current_restaurant) for the logged-in user.

    The restaurant picked in the session is used when the owner may access it; otherwise
    the owner's own restaurant (Restaurant.for_owner: the main restaurant for a main
    owner). The generic "first accessible restaurant" fallback would pick a branch,
    because branches sort first."""
    from restaurant.models_restaurant import Restaurant
    user = request.user
    owner = user.get_owner()
    if owner is None:
        return owner, None
    restaurant = None
    session = getattr(request, 'session', None)
    rid = session.get('selected_restaurant_id') if session is not None else None
    if rid and (user.is_main_owner() or user.is_branch_owner() or user.is_owner() or user.is_manager()):
        # selected_restaurant_id holds the selected location's OWNER user id (not a Restaurant
        # id): resolve it exactly like the admin panel does (honours selected_restaurant_pk)
        try:
            from admin_panel.restaurant_utils import get_restaurant_context
            selected = get_restaurant_context(user, rid, request).get('current_restaurant')
        except Exception:
            selected = None
        if selected is not None and selected.can_user_access(owner):
            restaurant = selected
    if restaurant is None:
        restaurant = Restaurant.for_owner(owner)
    return owner, restaurant


def _team_owner_ids(owner, restaurant):
    """Owner accounts whose staff records belong to this view. Staff records are saved
    under the staff member's own owner, so a branch's records sit under its branch owner
    (not under the main owner who may be viewing the branch)."""
    owners = {owner.id}
    if restaurant is not None:
        from .views_mobile import restaurant_team_owner_id
        team_owner_id = restaurant_team_owner_id(restaurant)
        if team_owner_id:
            owners.add(team_owner_id)
    return owners


def _records_for(owner, restaurant):
    """Attendance records of the selected restaurant (all of the owner's when none)."""
    qs = AttendanceRecord.objects.filter(owner_id__in=_team_owner_ids(owner, restaurant))
    if restaurant is not None:
        qs = qs.filter(restaurant=restaurant)
    return qs


def _require_can_manage(request):
    """Return True if the user may manage attendance (owner/manager/customer_care). else redirect."""
    u = request.user
    return u.is_any_owner() or u.is_manager() or u.is_customer_care()


def _require_owner_or_manager(request):
    u = request.user
    return u.is_any_owner() or u.is_manager()


# Roles whose attendance records are only visible to main owners / owners
_OWNER_ROLES = {'main_owner', 'branch_owner', 'owner'}


def _hide_owner_records(user):
    """Return True if this viewer should NOT see owner-level attendance records."""
    return not user.is_any_owner()


def _get_or_create_qr(owner, restaurant):
    """One QR per restaurant (the token's restaurant link is one-to-one). Look it up by
    the restaurant, whoever created it, and create it under the restaurant's own team
    owner (the branch owner for a branch) so the branch owner and branch staff can use it."""
    from django.db import IntegrityError
    if restaurant is None:
        try:
            qr, _ = AttendanceQRToken.objects.get_or_create(owner=owner, restaurant=None)
        except IntegrityError:
            qr = AttendanceQRToken.objects.filter(owner=owner, restaurant=None).first()
        return qr
    qr = AttendanceQRToken.objects.filter(restaurant=restaurant).first()
    if qr is not None:
        return qr
    from .views_mobile import restaurant_team_owner_id
    try:
        qr, _ = AttendanceQRToken.objects.get_or_create(
            restaurant=restaurant,
            defaults={'owner_id': restaurant_team_owner_id(restaurant) or owner.id},
        )
    except IntegrityError:
        qr = AttendanceQRToken.objects.filter(restaurant=restaurant).first()
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
    if not request.user.has_feature('view_attendance'):
        messages.error(request, "You don't have permission to access attendance.")
        return redirect('restaurant:owner_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)
    today = timezone.localdate()

    records_qs = _records_for(owner, restaurant).filter(
        date=today
    ).select_related('staff', 'staff__role', 'shift', 'restaurant').order_by('check_in')

    # Non-owner viewers (managers, cashiers, etc.) cannot see owner-level records
    if _hide_owner_records(request.user):
        records_qs = records_qs.exclude(staff__role__name__in=_OWNER_ROLES)

    records = [_record_to_dict(r) for r in records_qs]

    # Staff who haven't checked in yet — use all today's records (not restaurant-filtered)
    # so staff who checked in at another branch don't appear as absent
    staff_ids_present = AttendanceRecord.objects.filter(
        owner_id__in=_team_owner_ids(owner, restaurant), date=today, check_in__isnull=False
    ).values_list('staff_id', flat=True)
    # Build the absent query from the correct owner context
    if restaurant and restaurant.branch_owner:
        absent_owner = restaurant.branch_owner
    else:
        absent_owner = owner

    absent_staff_qs = User.objects.filter(
        owner=absent_owner, is_active=True, is_active_staff=True
    ).exclude(id__in=staff_ids_present).exclude(id=absent_owner.id)
    # Exclude customer/admin roles; also exclude owner-level roles for non-owner viewers
    EXCLUDED_ROLES = {'customer', 'administrator', 'main_owner', 'branch_owner', 'owner'}
    absent_staff = [
        u for u in absent_staff_qs
        if not u.role or u.role.name not in EXCLUDED_ROLES
    ]

    can_web_checkin = request.user.is_any_owner()

    policy = None
    if can_web_checkin:
        policy, _ = AttendancePolicy.objects.get_or_create(owner=request.user)

    context = {
        'today': today,
        'records': records,
        'absent_staff': absent_staff,
        'checked_in_count': sum(1 for r in records if r['check_in'] != '—'),
        'checked_out_count': sum(1 for r in records if r['check_out'] != '—'),
        'late_count': sum(1 for r in records if r['is_late']),
        'can_web_checkin': can_web_checkin,
        'policy': policy,
    }
    return render(request, 'admin_panel/attendance_dashboard.html', context)


@login_required
def attendance_shifts(request):
    """List, create, and edit shifts."""
    if not _require_owner_or_manager(request):
        messages.error(request, 'Access denied.')
        return redirect('admin_panel:admin_dashboard')
    if not request.user.has_feature('manage_attendance'):
        messages.error(request, "You don't have permission to manage attendance.")
        return redirect('restaurant:owner_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            name = request.POST.get('name', '').strip()
            shift_type = request.POST.get('shift_type', 'custom')
            start = request.POST.get('start_time', '')
            end = request.POST.get('end_time', '')
            try:
                grace = int(request.POST.get('grace_minutes', 15))
            except (TypeError, ValueError):
                grace = 15
            is_active = request.POST.get('is_active') in ('on', '1', 'true')
            if name and start and end:
                Shift.objects.create(
                    owner=owner,
                    restaurant=restaurant,
                    name=name,
                    shift_type=shift_type,
                    start_time=start,
                    end_time=end,
                    grace_minutes=grace,
                    is_active=is_active,
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
            try:
                shift.grace_minutes = int(request.POST.get('grace_minutes', shift.grace_minutes))
            except (TypeError, ValueError):
                pass
            shift.is_active = request.POST.get('is_active') in ('on', '1', 'true')
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
    if not request.user.has_feature('view_attendance'):
        messages.error(request, "You don't have permission to access attendance.")
        return redirect('restaurant:owner_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)

    today = timezone.localdate()
    try:
        year  = int(request.GET.get('year',  today.year))
        month = int(request.GET.get('month', today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month

    # Clamp month
    if month < 1: month = 12; year -= 1
    if month > 12: month = 1; year += 1

    _, days_in_month = monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)

    records_qs = _records_for(owner, restaurant).filter(
        date__range=(first_day, last_day)
    ).select_related('staff', 'staff__role', 'shift')
    if _hide_owner_records(request.user):
        records_qs = records_qs.exclude(staff__role__name__in=_OWNER_ROLES)

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
    if not request.user.has_feature('view_attendance'):
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)

    owner, restaurant = _get_owner_and_restaurant(request)
    day_str = request.GET.get('date')
    if not day_str:
        return JsonResponse({'error': 'date param required'}, status=400)

    records_qs = _records_for(owner, restaurant).filter(
        date=day_str
    ).select_related('staff', 'staff__role', 'shift', 'restaurant')
    if _hide_owner_records(request.user):
        records_qs = records_qs.exclude(staff__role__name__in=_OWNER_ROLES)

    return JsonResponse({'records': [_record_to_dict(r) for r in records_qs]})


@login_required
def attendance_qr(request):
    """Display and optionally regenerate the attendance QR code for the restaurant."""
    if not _require_owner_or_manager(request):
        messages.error(request, 'Access denied.')
        return redirect('admin_panel:admin_dashboard')
    if not request.user.has_feature('manage_attendance'):
        messages.error(request, "You don't have permission to manage attendance.")
        return redirect('restaurant:owner_dashboard')

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
    if not request.user.has_feature('manage_attendance'):
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)

    owner, restaurant = _get_owner_and_restaurant(request)
    qr_obj = _get_or_create_qr(owner, restaurant)
    qr_obj.regenerate()
    messages.success(request, 'Attendance QR code regenerated.')
    return redirect('attendance:qr')


# ─── staff-facing views ───────────────────────────────────────────────────────

@login_required
def attendance_web_checkin(request):
    """Web check-in/out — only owners may use click-based check-in; others must scan QR."""
    user = request.user
    can_web_checkin = user.is_any_owner()
    today = timezone.localdate()
    # Restaurant from the session, else the owner's own (main) restaurant
    owner, restaurant = _get_owner_and_restaurant(request)

    # Find appropriate shift
    from .views_mobile import _shift_for
    now_time = timezone.localtime().time()
    shift = _shift_for(user, owner, restaurant, now_time)

    try:
        record = AttendanceRecord.objects.get(staff=user, date=today)
    except AttendanceRecord.DoesNotExist:
        record = None

    if request.method == 'POST':
        if not can_web_checkin:
            messages.error(request, 'Please use the QR camera scanner on this page to check in or out.')
            return redirect('attendance:web_checkin')

        now = timezone.now()
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
                record.compute_lateness()  # known on arrival; check-out recomputes it
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
        'can_web_checkin': can_web_checkin,
    }
    return render(request, 'admin_panel/attendance_checkin.html', context)


@login_required
def attendance_my(request):
    """Staff views their own attendance history."""
    user = request.user
    today = timezone.localdate()

    # Default: current month
    try:
        year  = int(request.GET.get('year',  today.year))
        month = int(request.GET.get('month', today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month

    from_date = date(year, month, 1)
    _, days_in_month = monthrange(year, month)
    to_date = date(year, month, days_in_month)

    records = AttendanceRecord.objects.filter(
        staff=user, date__range=(from_date, to_date)
    ).select_related('shift', 'restaurant').order_by('-date')

    from .roster import upcoming_entries
    context = {
        'upcoming_shifts': upcoming_entries(user),
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


# ─── web QR scan (camera-based check-in from browser) ─────────────────────────

@csrf_protect
@login_required
def attendance_qr_web_scan(request):
    """
    Staff scan the restaurant QR code via their browser camera.
    POST: { qr_token } → JSON { success, action, message }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    from django.db import IntegrityError
    from .views_mobile import _shift_for

    token_str = (request.POST.get('qr_token') or '').strip()
    if not token_str:
        return JsonResponse({'error': 'qr_token is required'}, status=400)

    try:
        qr = AttendanceQRToken.objects.select_related('owner', 'restaurant').get(token=token_str)
    except AttendanceQRToken.DoesNotExist:
        return JsonResponse({'error': 'Invalid QR code. Please ask your manager for the correct QR.'}, status=404)

    user = request.user
    owner = user.get_owner()
    from .views_mobile import qr_allowed_for
    if not qr_allowed_for(user, owner, qr):
        return JsonResponse({'error': 'This QR code does not belong to your restaurant.'}, status=403)

    today = timezone.localdate()
    now = timezone.now()
    now_time = timezone.localtime().time()
    restaurant = qr.restaurant
    shift = _shift_for(user, owner, restaurant, now_time)

    try:
        record, created = AttendanceRecord.objects.get_or_create(
            staff=user, date=today,
            defaults={'owner': owner, 'restaurant': restaurant, 'shift': shift},
        )
    except IntegrityError:
        record = AttendanceRecord.objects.get(staff=user, date=today)
        created = False

    if not record.check_in:
        record.check_in = now
        record.check_in_via = 'web'
        if not record.shift:
            record.shift = shift
        record.compute_lateness()  # known on arrival; check-out recomputes it
        record.save()
        return JsonResponse({
            'success': True,
            'action': 'check_in',
            'message': f"Checked in at {timezone.localtime(now).strftime('%H:%M')}",
        })
    elif not record.check_out:
        record.check_out = now
        record.check_out_via = 'web'
        record.compute_metrics()
        record.save()
        return JsonResponse({
            'success': True,
            'action': 'check_out',
            'message': f"Checked out at {timezone.localtime(now).strftime('%H:%M')}",
        })
    else:
        return JsonResponse({
            'success': False,
            'action': 'already_done',
            'message': 'You have already completed your attendance for today.',
        })


# ─── day detail & reports ────────────────────────────────────────────────────

@login_required
def attendance_day_detail(request):
    """Full-page attendance report for a specific date."""
    if not _require_can_manage(request):
        messages.error(request, 'Access denied.')
        return redirect('admin_panel:admin_dashboard')
    if not request.user.has_feature('view_attendance'):
        messages.error(request, "You don't have permission to access attendance.")
        return redirect('restaurant:owner_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)
    today = timezone.localdate()

    day_str = request.GET.get('date', today.isoformat())
    try:
        day = date.fromisoformat(day_str)
    except ValueError:
        day = today

    records_qs = _records_for(owner, restaurant).filter(
        date=day
    ).select_related('staff', 'staff__role', 'shift', 'restaurant').order_by('check_in')
    if _hide_owner_records(request.user):
        records_qs = records_qs.exclude(staff__role__name__in=_OWNER_ROLES)

    records = [_record_to_dict(r) for r in records_qs]

    total_work_minutes = sum(r['work_minutes'] or 0 for r in records if r['work_minutes'])
    th, tm = divmod(total_work_minutes, 60)
    total_work_display = f"{th}h {tm}m" if th else (f"{tm}m" if tm else '—')

    absent_staff = []
    if not day > today:
        staff_ids_present = AttendanceRecord.objects.filter(
            owner_id__in=_team_owner_ids(owner, restaurant), date=day, check_in__isnull=False
        ).values_list('staff_id', flat=True)
        # Build the absent query from the correct owner context
        if restaurant and restaurant.branch_owner:
            absent_owner = restaurant.branch_owner
        else:
            absent_owner = owner

        absent_qs = User.objects.filter(
            owner=absent_owner, is_active=True, is_active_staff=True
        ).exclude(id__in=staff_ids_present).exclude(id=absent_owner.id)
        EXCLUDED_ROLES = {'customer', 'administrator', 'main_owner', 'branch_owner', 'owner'}
        absent_staff = [u for u in absent_qs if not u.role or u.role.name not in EXCLUDED_ROLES]

    prev_day = day - timedelta(days=1)
    next_day = day + timedelta(days=1)

    context = {
        'day': day,
        'day_label': day.strftime('%A, %B %d, %Y'),
        'records': records,
        'checked_in_count': sum(1 for r in records if r['check_in'] != '—'),
        'checked_out_count': sum(1 for r in records if r['check_out'] != '—'),
        'late_count': sum(1 for r in records if r['is_late']),
        'overtime_count': sum(1 for r in records if r['is_overtime']),
        'total_work_display': total_work_display,
        'absent_staff': absent_staff,
        'prev_day': prev_day.isoformat(),
        'next_day': next_day.isoformat(),
        'is_today': day == today,
        'is_future': day > today,
        'today': today,
    }
    return render(request, 'admin_panel/attendance_day_detail.html', context)


def _attendance_rate(owner, restaurant, records, date_from, date_to, today):
    """(rate %, days counted) for the report.

    - When a published roster has shifts in the range: shifts attended / shifts rostered.
      That is the only fair measure when people work different days (weekends included).
    - Otherwise: staff-days present / (team's active staff x every day in the range).
      All days count, because weekend attendance counts in the numerator too, and staff
      who never checked in are part of the team, so they lower the rate.
    Days after today are not counted (nobody can be present yet). Capped at 100%.
    Owner accounts are not staff and are left out.
    """
    from .models import RosterEntry
    from .roster import NOT_ROSTERED_ROLES
    end = min(date_to, today)
    if end < date_from:
        return 0, 0
    days = (end - date_from).days + 1
    if restaurant is not None:
        from .views_mobile import restaurant_team_owner_id
        team_owner_id = restaurant_team_owner_id(restaurant) or owner.id
    else:
        team_owner_id = owner.id

    present = {
        (r.staff_id, r.date) for r in records
        if r.check_in and r.date <= end
        and not (r.staff.role and r.staff.role.name in NOT_ROSTERED_ROLES)
    }
    rostered = set(
        RosterEntry.objects.filter(
            week__owner_id=team_owner_id, week__status='published', kind='shift',
            date__range=(date_from, end),
        ).values_list('staff_id', 'date')
    )
    if rostered:
        rate = len(present & rostered) / len(rostered) * 100
    else:
        staff_ids = set(
            User.objects.filter(owner_id=team_owner_id, is_active=True, is_active_staff=True)
            .exclude(role__name__in=NOT_ROSTERED_ROLES).exclude(pk=team_owner_id)
            .values_list('id', flat=True)
        )
        staff_ids |= {staff_id for staff_id, _ in present}
        rate = len(present) / (len(staff_ids) * days) * 100 if staff_ids else 0
    return round(min(rate, 100), 1), days


@login_required
def attendance_reports(request):
    """Attendance summary reports with date-range filtering."""
    if not _require_can_manage(request):
        messages.error(request, 'Access denied.')
        return redirect('admin_panel:admin_dashboard')
    if not request.user.has_feature('view_attendance'):
        messages.error(request, "You don't have permission to access attendance.")
        return redirect('restaurant:owner_dashboard')

    owner, restaurant = _get_owner_and_restaurant(request)
    today = timezone.localdate()

    try:
        date_from = date.fromisoformat(request.GET.get('date_from', ''))
    except ValueError:
        date_from = date(today.year, today.month, 1)
    try:
        date_to = date.fromisoformat(request.GET.get('date_to', ''))
    except ValueError:
        date_to = today

    if date_from > date_to:
        date_from, date_to = date_to, date_from

    records_qs = _records_for(owner, restaurant).filter(
        date__range=(date_from, date_to),
    ).select_related('staff', 'staff__role', 'shift')
    if _hide_owner_records(request.user):
        records_qs = records_qs.exclude(staff__role__name__in=_OWNER_ROLES)

    all_records = list(records_qs.order_by('date', 'check_in'))

    staff_map = {}
    for rec in all_records:
        sid = rec.staff_id
        if sid not in staff_map:
            staff_map[sid] = {
                'name': rec.staff.get_full_name() or rec.staff.username,
                'role': rec.staff.role.name if rec.staff.role else '—',
                'days_present': 0, 'days_late': 0,
                'total_minutes': 0, 'overtime_minutes': 0,
            }
        staff_map[sid]['days_present'] += 1
        if rec.is_late:
            staff_map[sid]['days_late'] += 1
        staff_map[sid]['total_minutes'] += rec.work_minutes or 0
        if rec.is_overtime:
            staff_map[sid]['overtime_minutes'] += rec.overtime_minutes

    staff_summary = []
    for data in staff_map.values():
        avg_mins = data['total_minutes'] // data['days_present'] if data['days_present'] else 0
        th, tm = divmod(data['total_minutes'], 60)
        ah, am = divmod(avg_mins, 60)
        oth, otm = divmod(data['overtime_minutes'], 60)
        staff_summary.append({
            **data,
            'on_time': data['days_present'] - data['days_late'],
            'total_display': f"{th}h {tm}m" if th else f"{tm}m",
            'avg_display': f"{ah}h {am}m" if ah else f"{am}m",
            'overtime_display': f"{oth}h {otm}m" if (oth or otm) else '—',
        })
    staff_summary.sort(key=lambda x: x['days_present'], reverse=True)

    daily_map = defaultdict(lambda: {'present': 0, 'late': 0, 'total_minutes': 0})
    for rec in all_records:
        daily_map[rec.date]['present'] += 1
        if rec.is_late:
            daily_map[rec.date]['late'] += 1
        daily_map[rec.date]['total_minutes'] += rec.work_minutes or 0

    daily_summary = []
    cur = date_from
    while cur <= date_to:
        d = daily_map[cur]
        h, m = divmod(d['total_minutes'], 60)
        daily_summary.append({
            'date': cur,
            'date_str': cur.isoformat(),
            'present': d['present'],
            'late': d['late'],
            'total_display': f"{h}h {m}m" if (h or m) else '—',
        })
        cur += timedelta(days=1)

    total_records = len(all_records)
    total_late = sum(1 for r in all_records if r.is_late)
    total_work_minutes = sum(r.work_minutes or 0 for r in all_records)
    th, tm = divmod(total_work_minutes, 60)
    total_staff = len(staff_map)
    attendance_rate, working_days = _attendance_rate(owner, restaurant, all_records, date_from, date_to, today)

    import csv
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="attendance_report_{date_from.isoformat()}_{date_to.isoformat()}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(['Staff Name', 'Role', 'Days Present', 'On Time', 'Late', 'Avg Hours', 'Total Hours'])
        for s in staff_summary:
            writer.writerow([
                _safe_csv(s['name']),
                _safe_csv(s['role']),
                s['days_present'],
                s['on_time'],
                s['days_late'],
                _safe_csv(s['avg_display']),
                _safe_csv(s['total_display']),
            ])
        return response

    context = {
        'date_from': date_from.isoformat(),
        'date_to': date_to.isoformat(),
        'total_records': total_records,
        'total_late': total_late,
        'total_work_display': f"{th}h {tm}m" if th else f"{tm}m" if tm else '0m',
        'total_staff': total_staff,
        'attendance_rate': attendance_rate,
        'working_days': working_days,
        'staff_summary': staff_summary,
        'daily_summary': daily_summary,
        'today': today,
    }
    return render(request, 'admin_panel/attendance_reports.html', context)


# ─── attendance policy (require check-in before work) ─────────────────────────

@login_required
@require_POST
def attendance_policy_toggle(request):
    """Owner toggles the 'require check-in before work' policy."""
    if not request.user.is_any_owner():
        return JsonResponse({'error': 'Access denied'}, status=403)

    owner = request.user
    policy, _ = AttendancePolicy.objects.get_or_create(owner=owner)
    value = request.POST.get('require_checkin_before_work') == '1'
    policy.require_checkin_before_work = value
    policy.save()
    return JsonResponse({'success': True, 'require_checkin_before_work': value})
