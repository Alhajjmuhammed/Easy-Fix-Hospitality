"""Weekly staff roster pages (planned under Attendance)."""
import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from cashier.views import _safe_csv
from .models import RosterEntry, RosterWeek, shift_minutes
from . import roster as svc


def _can_view(user):
    return (user.is_any_owner() or user.is_manager() or user.is_customer_care()) \
        and user.has_feature('view_attendance')


def _can_edit(user):
    return (user.is_any_owner() or user.is_manager()) and user.has_feature('manage_attendance')


def _week_url(team, start):
    return f"{reverse('attendance:roster')}?team={team.id}&week={start.isoformat()}"


@login_required
def roster_week(request):
    if not _can_view(request.user):
        messages.error(request, "You don't have permission to view the roster.")
        return redirect('attendance:my')
    team = svc.pick_team(request.user, request.GET.get('team'))
    if team is None:
        messages.error(request, 'You are not assigned to a restaurant.')
        return redirect('attendance:my')
    start = svc.parse_week(request.GET.get('week'))
    days = svc.week_dates(start)
    week = RosterWeek.objects.filter(owner=team, week_start=start).first()
    staff = list(svc.roster_staff(team, start))
    entries = {(e.staff_id, e.date): e for e in RosterEntry.objects
               .filter(staff__in=staff, date__range=(days[0], days[-1])).select_related('shift', 'week')}

    shifts = list(svc.shift_choices(team))
    # Keep shifts that are already on this roster selectable even if since made inactive
    known = {s.id for s in shifts}
    for e in entries.values():
        if e.shift_id and e.shift_id not in known and e.week.owner_id == team.id:
            known.add(e.shift_id)
            shifts.append(e.shift)

    rows, day_counts = [], [0] * 7
    for u in staff:
        cells, minutes = [], 0
        for i, d in enumerate(days):
            e = entries.get((u.id, d))
            if e is not None and e.week.owner_id != team.id:
                # Rostered by another restaurant of the business (e.g. moved branch): read-only here
                cells.append({'date': d, 'entry': None, 'value': '', 'elsewhere': True})
                continue
            if e is None:
                value = ''
            elif e.kind == 'shift':
                value = f'shift:{e.shift_id}' if e.shift_id else 'keep'   # 'keep' = shift was deleted
            else:
                value = e.kind
            if e is not None and e.kind == 'shift':
                minutes += e.minutes
                day_counts[i] += 1
            cells.append({'date': d, 'entry': e, 'value': value})
        rows.append({'user': u, 'cells': cells, 'minutes': minutes, 'hours': svc.fmt_minutes(minutes)})

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="roster_{start.isoformat()}.csv"'
        response.write('﻿')  # lets Excel show non-English names correctly
        writer = csv.writer(response)
        writer.writerow(['Staff', 'Role'] + [d.strftime('%a %d %b') for d in days] + ['Planned hours'])
        for row in rows:
            writer.writerow(
                [_safe_csv(row['user'].get_full_name() or row['user'].username),
                 _safe_csv(row['user'].role.name if row['user'].role else '')]
                + [_safe_csv('Other restaurant' if c.get('elsewhere') else _cell_text(c['entry']))
                   for c in row['cells']]
                + [row['hours']])
        return response

    return render(request, 'admin_panel/attendance_roster.html', {
        'team': team,
        'teams': svc.teams_for(request.user),
        'start': start,
        'days': days,
        'today': timezone.localdate(),
        'prev_week': (start - timedelta(days=7)).isoformat(),
        'next_week': (start + timedelta(days=7)).isoformat(),
        'this_week': svc.monday(timezone.localdate()).isoformat(),
        'week': week,
        'rows': rows,
        'day_counts': day_counts,
        'shifts': [{'id': s.id, 'name': s.name, 'start': s.start_time, 'end': s.end_time,
                    'minutes': shift_minutes(s)} for s in shifts],
        'can_edit': _can_edit(request.user),
        'total_hours': svc.fmt_minutes(sum(r['minutes'] for r in rows)),
    })


def _cell_text(entry):
    if entry is None:
        return ''
    if entry.kind != 'shift':
        return entry.get_kind_display()
    if entry.shift is None:
        return 'Shift removed'
    return f"{entry.shift.name} {entry.shift.start_time:%H:%M}-{entry.shift.end_time:%H:%M}"


@login_required
@require_POST
def roster_action(request):
    if not _can_edit(request.user):
        messages.error(request, "You don't have permission to change the roster.")
        return redirect('attendance:roster')
    team = svc.pick_team(request.user, request.POST.get('team'))
    if team is None:
        messages.error(request, 'You are not assigned to a restaurant.')
        return redirect('attendance:my')
    start = svc.parse_week(request.POST.get('week'))
    action = request.POST.get('action')
    try:
        if action == 'save':
            changed, skipped = svc.save_week(team, start, _cells_from_post(request.POST, start), request.user)
            messages.success(request, f'Roster saved ({changed} change{"s" if changed != 1 else ""}).'
                             if changed else 'No changes to save.')
            if skipped:
                messages.warning(request, f'{skipped} day{"s were" if skipped != 1 else " was"} not saved: '
                                          'the staff member left this team or is rostered at another restaurant.')
        elif action == 'publish':
            svc.publish_week(team, start, request.user)
            messages.success(request, 'Roster published. Staff have been notified.')
        elif action == 'unpublish':
            svc.unpublish_week(team, start)
            messages.success(request, 'Roster moved back to draft. Staff no longer see this week.')
        elif action == 'copy_last':
            n = svc.copy_previous_week(team, start, request.user)
            messages.success(request, f'Copied {n} day{"s" if n != 1 else ""} from last week.')
        else:
            messages.error(request, 'Unknown action.')
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
    except IntegrityError:
        # Someone else saved the same day at the same moment
        messages.error(request, 'Someone else changed this roster at the same time. Please check it and try again.')
    return redirect(_week_url(team, start))


def _cells_from_post(post, start):
    """Inputs are named c_<staff id>_<day index 0-6>."""
    days = svc.week_dates(start)
    cells = {}
    for key, value in post.items():
        if not key.startswith('c_'):
            continue
        parts = key.split('_')
        try:
            staff_id, idx = int(parts[1]), int(parts[2])
        except (IndexError, ValueError):
            raise ValidationError('The roster form was not valid. Please reload the page.')
        if not 0 <= idx < 7:
            raise ValidationError('The roster form was not valid. Please reload the page.')
        if value == 'keep':        # "Shift removed" left as it is
            continue
        cells[(staff_id, days[idx])] = value
    return cells
