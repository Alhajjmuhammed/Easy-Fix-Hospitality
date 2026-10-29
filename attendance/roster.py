"""Weekly staff roster: shared rules for the web pages, the mobile API and attendance check-in."""
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from .models import RosterEntry, RosterWeek, Shift

# Roles that are never put on a roster (owners plan it, customers/admins are not staff)
NOT_ROSTERED_ROLES = ('customer', 'administrator', 'main_owner', 'branch_owner', 'owner')
UPCOMING_DAYS = 14


def monday(d):
    return d - timedelta(days=d.weekday())


def parse_week(value):
    """Monday of the week containing the ISO date `value`; this week when missing, invalid or absurd."""
    try:
        d = date.fromisoformat(value or '')
        if 2000 <= d.year <= 2100:
            return monday(d)
    except ValueError:
        pass
    return monday(timezone.localdate())


def week_dates(start):
    return [start + timedelta(days=i) for i in range(7)]


def fmt_minutes(minutes):
    h, m = divmod(minutes, 60)
    if not h:
        return f"{m}m" if m else '0h'
    return f"{h}h {m}m" if m else f"{h}h"


def teams_for(user):
    """[(team_owner, label)] the user may plan or view. Main owners also get each branch's team."""
    from restaurant.models_restaurant import Restaurant
    owner = user.get_owner()
    if owner is None:
        return []
    own = Restaurant.for_owner(owner)
    teams = [(owner, own.name if own else (owner.restaurant_name or owner.username))]
    if user.is_main_owner():
        branches = (Restaurant.objects.filter(main_owner=user, branch_owner__isnull=False)
                    .exclude(branch_owner=user).select_related('branch_owner').order_by('name'))
        seen = {owner.id}
        for r in branches:
            if r.branch_owner_id not in seen:
                seen.add(r.branch_owner_id)
                teams.append((r.branch_owner, r.name))
    return teams


def pick_team(user, team_id):
    """The requested team if the user may see it, else their own; None when the user has no team."""
    teams = teams_for(user)
    for team, _ in teams:
        if str(team.id) == str(team_id or ''):
            return team
    return teams[0][0] if teams else None


def roster_staff(team_owner, start=None):
    """Active staff of the team, plus anyone already rostered in that week (e.g. since deactivated)."""
    q = Q(owner=team_owner, is_active=True, is_active_staff=True)
    if start is not None:
        q |= Q(roster_entries__week__owner=team_owner, roster_entries__date__range=(start, start + timedelta(days=6)))
    return (User.objects.filter(q).exclude(role__name__in=NOT_ROSTERED_ROLES).exclude(pk=team_owner.pk)
            .select_related('role').distinct().order_by('first_name', 'last_name', 'username'))


def shift_choices(team_owner):
    """Active shifts the team can be put on: the team owner's own shifts, and shifts a main
    owner created for this team's restaurant. Shifts made for another branch are left out."""
    return (Shift.objects.filter(is_active=True)
            .filter(Q(owner=team_owner) | Q(restaurant__branch_owner=team_owner))
            .exclude(Q(restaurant__branch_owner__isnull=False) & ~Q(restaurant__branch_owner=team_owner))
            .order_by('start_time', 'name'))


def _parse_value(value, shifts_by_id):
    """'' → None (empty), 'off', 'leave', 'shift:<id>' → (kind, shift)."""
    value = (value or '').strip()
    if value == '':
        return None
    if value in ('off', 'leave'):
        return (value, None)
    if value.startswith('shift:'):
        try:
            shift = shifts_by_id.get(int(value[6:]))
        except ValueError:
            shift = None
        if shift is not None:
            return ('shift', shift)
    raise ValidationError('Please choose a valid shift.')


def _notify(staff_ids, title, body, start):
    from orders.push import notify_roster
    notify_roster(staff_ids, title, body, start)


@transaction.atomic
def save_week(team_owner, start, cells, user):
    """Apply the changed cells of the grid. `cells` maps (staff_id, date) → value; the page only
    sends cells the editor changed, so two people editing different cells don't overwrite each other.
    Cells for staff who left the team meanwhile, or days already rostered by another team, are
    skipped. Returns (changed, skipped). On a published week staff whose upcoming days changed
    are notified."""
    dates = set(week_dates(start))
    staff_ids = set(roster_staff(team_owner, start).values_list('id', flat=True))
    found = (RosterEntry.objects.select_for_update(of=('self',)).select_related('shift', 'week')
             .filter(staff_id__in=staff_ids, date__in=dates))
    existing, other_team = {}, set()
    for e in found:
        if e.week.owner_id == team_owner.id:
            existing[(e.staff_id, e.date)] = e
        else:
            other_team.add((e.staff_id, e.date))
    # Shifts already on the roster stay valid even if they were since made inactive
    shifts_by_id = {s.id: s for s in shift_choices(team_owner)}
    shifts_by_id.update({e.shift_id: e.shift for e in existing.values() if e.shift_id})

    planned, skipped = {}, 0
    for (staff_id, day), value in cells.items():
        if day not in dates:
            raise ValidationError('This day is not part of this roster.')
        if staff_id not in staff_ids or (staff_id, day) in other_team:
            skipped += 1
            continue
        planned[(staff_id, day)] = _parse_value(value, shifts_by_id)

    week, _ = RosterWeek.objects.get_or_create(owner=team_owner, week_start=start)
    changed, notify_ids, today = 0, set(), timezone.localdate()
    for key, want in planned.items():
        entry = existing.get(key)
        have = (entry.kind, entry.shift) if entry else None
        if have == want:
            continue
        if want is None:
            entry.delete()
        elif entry is None:
            RosterEntry.objects.create(week=week, staff_id=key[0], date=key[1], kind=want[0], shift=want[1])
        else:
            entry.kind, entry.shift = want
            entry.save()
        changed += 1
        if key[1] >= today:
            notify_ids.add(key[0])
    if changed:
        week.save(update_fields=['updated_at'])
    if week.is_published and notify_ids:
        _notify(notify_ids, 'Roster updated 📅',
                f'Your shifts for the week of {start:%a %d %b} have changed. Tap to see them.', start)
    return changed, skipped


@transaction.atomic
def publish_week(team_owner, start, user):
    week = RosterWeek.objects.select_for_update().filter(owner=team_owner, week_start=start).first()
    staff_ids = set(week.entries.values_list('staff_id', flat=True)) if week else set()
    if not staff_ids:
        raise ValidationError('Add at least one shift before publishing.')
    if week.is_published:
        raise ValidationError('This week is already published.')
    week.status, week.published_at, week.published_by = 'published', timezone.now(), user
    week.save()
    upcoming = _upcoming_staff(week)
    if upcoming:  # nobody is told about a week that is already over
        _notify(upcoming, 'Your roster is ready 📅',
                f'Your shifts for the week of {start:%a %d %b} are published. Tap to see them.', start)
    return week


def _upcoming_staff(week):
    return set(week.entries.filter(date__gte=timezone.localdate()).values_list('staff_id', flat=True))


@transaction.atomic
def unpublish_week(team_owner, start):
    """Back to draft: staff stop seeing the week and check-in stops using it."""
    week = RosterWeek.objects.select_for_update().filter(owner=team_owner, week_start=start).first()
    if week is None or not week.is_published:
        raise ValidationError('This week is not published.')
    week.status = 'draft'
    week.save(update_fields=['status', 'updated_at'])
    upcoming = _upcoming_staff(week)
    if upcoming:
        _notify(upcoming, 'Roster withdrawn',
                f'Your shifts for the week of {start:%a %d %b} are being changed. You will be notified again.', start)


@transaction.atomic
def copy_previous_week(team_owner, start, user):
    """Fill the empty cells of this week from last week. Filled cells are never overwritten."""
    prev = start - timedelta(days=7)
    staff_ids = set(roster_staff(team_owner, start).values_list('id', flat=True))
    taken = set(RosterEntry.objects.filter(staff_id__in=staff_ids, date__range=(start, start + timedelta(days=6)))
                .values_list('staff_id', 'date'))
    source = RosterEntry.objects.filter(week__owner=team_owner, week__week_start=prev, staff_id__in=staff_ids) \
        .exclude(kind='shift', shift__isnull=True)
    week, _ = RosterWeek.objects.get_or_create(owner=team_owner, week_start=start)
    created, today = [], timezone.localdate()
    for e in source:
        day = e.date + timedelta(days=7)
        if (e.staff_id, day) in taken:
            continue
        created.append(RosterEntry(week=week, staff_id=e.staff_id, date=day, kind=e.kind, shift_id=e.shift_id))
    RosterEntry.objects.bulk_create(created)
    if not created:
        raise ValidationError('Nothing to copy: last week is empty or this week is already filled.')
    week.save(update_fields=['updated_at'])
    notify_ids = {e.staff_id for e in created if e.date >= today}
    if week.is_published and notify_ids:
        _notify(notify_ids, 'Roster updated 📅',
                f'Your shifts for the week of {start:%a %d %b} have changed. Tap to see them.', start)
    return len(created)


def rostered_shift(user, day):
    """The shift this person is rostered for on `day` in a published week, else None."""
    entry = (RosterEntry.objects.filter(staff=user, date=day, kind='shift', week__status='published',
                                        shift__isnull=False)
             .select_related('shift').first())
    return entry.shift if entry else None


def upcoming_entries(user, days=UPCOMING_DAYS):
    """This person's published roster from today for `days` days."""
    today = timezone.localdate()
    return (RosterEntry.objects.filter(staff=user, week__status='published',
                                       date__range=(today, today + timedelta(days=days - 1)))
            .select_related('shift').order_by('date'))


def entry_to_dict(entry):
    shift = entry.shift if entry.kind == 'shift' else None
    return {
        'date': entry.date.isoformat(),
        'kind': entry.kind,
        'kind_display': entry.get_kind_display(),
        'shift_name': shift.name if shift else None,
        'start_time': shift.start_time.strftime('%H:%M') if shift else None,
        'end_time': shift.end_time.strftime('%H:%M') if shift else None,
    }
