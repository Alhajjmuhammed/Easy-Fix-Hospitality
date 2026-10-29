import datetime
import sys
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Feature, Role, RestaurantSubscription, User
from attendance.models import AttendanceQRToken, AttendanceRecord, RosterEntry, RosterWeek, Shift
from attendance import roster as svc
from attendance.views_mobile import _shift_for
from restaurant.models_restaurant import Restaurant

if sys.version_info >= (3, 14):  # Django 4.2 test client can't copy template contexts on 3.14
    import django.test.client as _dtc
    _dtc.store_rendered_templates = lambda *a, **k: None


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class RosterTests(TestCase):
    def setUp(self):
        self.push = mock.patch('orders.push.send_push')
        self.sent = self.push.start()
        self.addCleanup(self.push.stop)
        mk = lambda u, r, **kw: User.objects.create_user(u, password='pw12345!x', role=role(r), **kw)
        self.main = mk('main', 'main_owner', restaurant_name='Main R')
        self.manager = mk('mgr', 'manager', owner=self.main)
        self.cook = mk('cook', 'kitchen', owner=self.main, first_name='Ali', expo_push_token='ExponentPushToken[cook]')
        self.cashier = mk('cash', 'cashier', owner=self.main, first_name='Amina', expo_push_token='ExponentPushToken[cash]')
        self.cc = mk('cc', 'customer_care', owner=self.main)
        self.other_owner = mk('oth', 'main_owner', restaurant_name='Other R')
        self.stranger = mk('str', 'kitchen', owner=self.other_owner)
        self.r = Restaurant.objects.create(name='Main R', address='a', main_owner=self.main, branch_owner=self.main,
                                           is_main_restaurant=True, qr_code='QRMAIN')
        today = timezone.localdate()
        for o in (self.main, self.other_owner):
            RestaurantSubscription.objects.create(restaurant_owner=o, subscription_start_date=today,
                                                  subscription_end_date=today + datetime.timedelta(days=30))
        self.morning = Shift.objects.create(owner=self.main, name='Morning', start_time='08:00', end_time='16:00')
        self.night = Shift.objects.create(owner=self.main, name='Night', start_time='22:00', end_time='06:00')
        self.foreign = Shift.objects.create(owner=self.other_owner, name='Theirs', start_time='09:00', end_time='17:00')
        self.today = today
        self.this_week = svc.monday(today)
        self.next_week = self.this_week + datetime.timedelta(days=7)

    # ---------- helpers ----------
    def _post(self, user, action='save', week=None, team=None, **cells):
        self.client.force_login(user)
        data = {'action': action, 'week': (week or self.next_week).isoformat()}
        if team:
            data['team'] = team.id
        data.update(cells)
        return self.client.post('/admin-panel/attendance/roster/action/', data)

    def _api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _my(self, user):
        return self._api(user).get('/api/v1/attendance/roster/my/').json()['entries']

    def _tokens_sent(self):
        return [sorted(c.args[0]) for c in self.sent.call_args_list]

    # ---------- planning ----------
    def test_draft_is_hidden_until_published_then_staff_notified(self):
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.morning.id}',
                                    f'c_{self.cook.id}_1': 'off',
                                    f'c_{self.cashier.id}_2': 'leave'})
        self.assertEqual(RosterEntry.objects.count(), 3)
        self.assertEqual(RosterWeek.objects.get().status, 'draft')
        self.sent.assert_not_called()
        self.assertEqual(self._my(self.cook), [])  # draft: invisible to staff

        self._post(self.manager, action='publish')
        self.assertEqual(RosterWeek.objects.get().status, 'published')
        self.assertEqual(self._tokens_sent(), [['ExponentPushToken[cash]', 'ExponentPushToken[cook]']])
        if (self.next_week - self.today).days < svc.UPCOMING_DAYS:
            mine = self._my(self.cook)
            self.assertEqual([(e['kind'], e['start_time']) for e in mine], [('shift', '08:00'), ('off', None)])

    def test_publish_empty_week_is_refused(self):
        resp = self._post(self.main, action='publish')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(RosterWeek.objects.filter(status='published').exists())

    def test_changes_after_publish_notify_only_affected_staff(self):
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.morning.id}',
                                    f'c_{self.cashier.id}_0': f'shift:{self.morning.id}'})
        self._post(self.manager, action='publish')
        self.sent.reset_mock()
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.night.id}',
                                    f'c_{self.cashier.id}_0': f'shift:{self.morning.id}'})  # cashier unchanged
        self.assertEqual(self._tokens_sent(), [['ExponentPushToken[cook]']])
        self.sent.reset_mock()
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.night.id}'})  # nothing changed
        self.sent.assert_not_called()

    def test_changing_past_days_does_not_notify(self):
        last_week = self.this_week - datetime.timedelta(days=7)
        self._post(self.manager, week=last_week, **{f'c_{self.cook.id}_0': 'off'})
        self._post(self.manager, week=last_week, action='publish')
        self.sent.reset_mock()
        self._post(self.manager, week=last_week, **{f'c_{self.cook.id}_0': 'leave'})
        self.assertEqual(RosterEntry.objects.get().kind, 'leave')
        self.sent.assert_not_called()

    def test_clearing_a_cell_removes_it(self):
        self._post(self.manager, **{f'c_{self.cook.id}_3': 'off'})
        self._post(self.manager, **{f'c_{self.cook.id}_3': ''})
        self.assertFalse(RosterEntry.objects.exists())

    def test_invalid_input_changes_nothing(self):
        bad = [
            {f'c_{self.cook.id}_0': f'shift:{self.foreign.id}'},       # another restaurant's shift
            {f'c_{self.cook.id}_9': 'off'},                             # day out of range
            {f'c_{self.cook.id}_x': 'off'},                             # garbage
            {f'c_{self.cook.id}_0': 'shift:abc'},
            {f'c_{self.cook.id}_0': 'holiday'},
        ]
        for cells in bad:
            cells[f'c_{self.cashier.id}_1'] = 'off'                    # a valid cell in the same request
            resp = self._post(self.manager, **cells)
            self.assertEqual(resp.status_code, 302, cells)
            self.assertFalse(RosterEntry.objects.exists(), cells)

    def test_staff_outside_team_are_skipped_not_saved(self):
        self._post(self.manager, **{f'c_{self.stranger.id}_0': 'off',     # another restaurant's staff
                                    f'c_{self.main.id}_0': 'off',         # owners are not rostered
                                    f'c_{self.cashier.id}_1': 'off'})
        self.assertEqual(list(RosterEntry.objects.values_list('staff_id', flat=True)), [self.cashier.id])
        page = self.client.get(f'/admin-panel/attendance/roster/?week={self.next_week}').content.decode()
        self.assertIn('2 days were not saved', page)

    def test_only_posted_cells_change(self):
        """Two editors: B saves Tuesday, then A (old page) saves Monday only → Tuesday survives."""
        self._post(self.manager, **{f'c_{self.cook.id}_1': f'shift:{self.morning.id}'})
        self._post(self.main, **{f'c_{self.cook.id}_0': 'off'})
        self.assertEqual(RosterEntry.objects.count(), 2)

    def test_deleted_shift_cell_is_kept_by_unrelated_save(self):
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.night.id}'})
        self.night.delete()
        page = self.client.get(f'/admin-panel/attendance/roster/?week={self.next_week}').content.decode()
        self.assertIn('<option value="keep" selected>Shift removed</option>', page)
        self._post(self.manager, **{f'c_{self.cook.id}_0': 'keep', f'c_{self.cook.id}_1': 'off'})
        self.assertEqual(RosterEntry.objects.count(), 2)

    def test_day_rostered_by_another_team_is_not_taken_over(self):
        bown = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'), owner=self.main)
        Restaurant.objects.create(name='Branch R', address='b', main_owner=self.main, branch_owner=bown,
                                  is_main_restaurant=False, parent_restaurant=self.r, qr_code='QRBR')
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.morning.id}'})
        self._post(self.manager, action='publish')
        User.objects.filter(pk=self.cook.pk).update(owner=bown)             # cook moves to the branch
        self.client.force_login(self.main)
        page = self.client.get(f'/admin-panel/attendance/roster/?team={bown.id}&week={self.next_week}').content.decode()
        self.assertIn('Other restaurant', page)
        self.assertNotIn(f'name="c_{self.cook.id}_0"', page)
        self._post(self.main, team=bown, **{f'c_{self.cook.id}_0': 'off', f'c_{self.cook.id}_1': 'off'})
        monday = RosterEntry.objects.get(staff=self.cook, date=self.next_week)
        self.assertEqual((monday.kind, monday.week.owner, monday.week.status), ('shift', self.main, 'published'))
        self.assertEqual(RosterEntry.objects.get(staff=self.cook, date=self.next_week + datetime.timedelta(days=1))
                         .week.owner, bown)

    def test_simultaneous_save_shows_message_not_error(self):
        from django.db import IntegrityError
        with mock.patch('attendance.roster.save_week', side_effect=IntegrityError('dup')):
            resp = self._post(self.manager, **{f'c_{self.cook.id}_0': 'off'})
        self.assertEqual(resp.status_code, 302)

    def test_unpublish_notifies_and_past_publish_does_not(self):
        self._post(self.manager, **{f'c_{self.cook.id}_0': 'off'})
        self._post(self.manager, action='publish')
        self.sent.reset_mock()
        self._post(self.manager, action='unpublish')
        self.assertEqual(self._tokens_sent(), [['ExponentPushToken[cook]']])
        self.assertIn('withdrawn', self.sent.call_args.args[1])
        self.sent.reset_mock()
        last_week = self.this_week - datetime.timedelta(days=7)
        self._post(self.manager, week=last_week, **{f'c_{self.cook.id}_0': 'off'})
        self._post(self.manager, week=last_week, action='publish')
        self.assertEqual(RosterWeek.objects.get(week_start=last_week).status, 'published')
        self.sent.assert_not_called()

    def test_odd_inputs(self):
        full = Shift.objects.create(owner=self.main, name='Full', start_time='07:00', end_time='07:00')
        full.refresh_from_db()
        from attendance.models import shift_minutes
        self.assertEqual(shift_minutes(full), 24 * 60)
        self.assertEqual(svc.parse_week('0001-01-01'), self.this_week)
        self.assertEqual(svc.parse_week('9999-12-31'), self.this_week)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get('/admin-panel/attendance/roster/?week=9999-12-31').status_code, 200)
        self.assertEqual(self._post(self.manager, week=datetime.date(9999, 12, 27)).status_code, 302)
        csv_bytes = self.client.get('/admin-panel/attendance/roster/?export=csv').content
        self.assertTrue(csv_bytes.startswith('﻿'.encode('utf-8')))

    def test_inactive_shift_already_on_roster_stays_valid(self):
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.morning.id}'})
        Shift.objects.filter(pk=self.morning.pk).update(is_active=False)
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.morning.id}', f'c_{self.cook.id}_1': 'off'})
        self.assertEqual(RosterEntry.objects.count(), 2)
        page = self.client.get(f'/admin-panel/attendance/roster/?week={self.next_week}').content.decode()
        self.assertIn('Morning 08:00', page)

    def test_copy_last_week_fills_only_empty_days(self):
        self._post(self.manager, week=self.this_week, **{f'c_{self.cook.id}_0': f'shift:{self.morning.id}',
                                                         f'c_{self.cook.id}_1': f'shift:{self.morning.id}'})
        self._post(self.manager, **{f'c_{self.cook.id}_1': 'off'})
        self._post(self.manager, action='copy_last')
        next_entries = {e.date.weekday(): e.kind for e in RosterEntry.objects.filter(date__gte=self.next_week)}
        self.assertEqual(next_entries, {0: 'shift', 1: 'off'})       # Tuesday kept as 'off'
        resp = self._post(self.manager, action='copy_last')          # nothing left to copy
        self.assertEqual(RosterEntry.objects.filter(date__gte=self.next_week).count(), 2)
        self.assertEqual(resp.status_code, 302)

    def test_unpublish_hides_week_again(self):
        self._post(self.manager, week=self.this_week, **{f'c_{self.cook.id}_{self.today.weekday()}': f'shift:{self.night.id}'})
        self._post(self.manager, week=self.this_week, action='publish')
        self.assertEqual(len(self._my(self.cook)), 1)
        self._post(self.manager, week=self.this_week, action='unpublish')
        self.assertEqual(self._my(self.cook), [])
        self.assertEqual(RosterWeek.objects.get().status, 'draft')

    # ---------- hours / export / page ----------
    def test_hours_including_overnight_and_csv(self):
        self._post(self.manager, **{f'c_{self.cook.id}_0': f'shift:{self.morning.id}',
                                    f'c_{self.cook.id}_1': f'shift:{self.night.id}',
                                    f'c_{self.cook.id}_2': 'leave'})
        page = self.client.get(f'/admin-panel/attendance/roster/?week={self.next_week}').content.decode()
        self.assertIn(f'id="hours-{self.cook.id}">16h<', page)
        csv_text = self.client.get(f'/admin-panel/attendance/roster/?week={self.next_week}&export=csv').content.decode()
        self.assertIn('Ali', csv_text)
        self.assertIn('Night 22:00-06:00', csv_text)
        self.assertIn('On leave', csv_text)
        ali = next(l for l in csv_text.splitlines() if l.startswith('Ali'))
        self.assertTrue(ali.endswith(',16h'), ali)

    def test_other_restaurant_cannot_be_viewed_by_team_param(self):
        self.client.force_login(self.main)
        page = self.client.get(f'/admin-panel/attendance/roster/?team={self.other_owner.id}').content.decode()
        self.assertIn('Ali', page)
        self.assertNotIn(f'c_{self.stranger.id}_', page)
        self.assertNotIn('Theirs', page)
        self._post(self.main, team=self.other_owner, **{f'c_{self.cook.id}_0': 'off'})
        self.assertEqual(RosterWeek.objects.get().owner, self.main)  # saved to own team, not theirs

    def test_main_owner_plans_branch_team(self):
        bown = User.objects.create_user('bown', password='pw12345!x', role=role('branch_owner'), owner=self.main)
        branch = Restaurant.objects.create(name='Branch R', address='b', main_owner=self.main, branch_owner=bown,
                                           is_main_restaurant=False, parent_restaurant=self.r, qr_code='QRBR')
        waiter = User.objects.create_user('waiter', password='pw12345!x', role=role('service'), owner=bown,
                                          first_name='Bakari')
        branch_shift = Shift.objects.create(owner=self.main, restaurant=branch, name='BranchLate',
                                            start_time='12:00', end_time='20:00')
        self.assertEqual([t.id for t, _ in svc.teams_for(self.main)], [self.main.id, bown.id])
        self.assertNotIn(branch_shift, list(svc.shift_choices(self.main)))   # not offered to the main team
        self.assertIn(branch_shift, list(svc.shift_choices(bown)))
        self.client.force_login(self.main)
        page = self.client.get(f'/admin-panel/attendance/roster/?team={bown.id}').content.decode()
        self.assertIn('Bakari', page)
        self.assertNotIn('Ali', page)
        self._post(self.main, team=bown, **{f'c_{waiter.id}_0': f'shift:{branch_shift.id}'})
        self.assertEqual(RosterEntry.objects.get().week.owner, bown)
        self.assertEqual(svc.teams_for(self.manager)[0][0], self.main)  # manager: own team only
        self.assertEqual(len(svc.teams_for(self.manager)), 1)

    # ---------- permissions ----------
    def test_permissions(self):
        self.client.force_login(self.cashier)  # no view_attendance by default
        self.assertEqual(self.client.get('/admin-panel/attendance/roster/').status_code, 302)
        self._post(self.cashier, **{f'c_{self.cook.id}_0': 'off'})
        self._post(self.cc, **{f'c_{self.cook.id}_0': 'off'})   # customer care: view only
        self.assertFalse(RosterEntry.objects.exists())
        self.client.force_login(self.cc)
        page = self.client.get('/admin-panel/attendance/roster/')
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('Save roster', page.content.decode())
        self.client.force_login(self.manager)
        self.assertIn('Save roster', self.client.get('/admin-panel/attendance/roster/').content.decode())

    def test_module_access_switch_blocks_roster(self):
        Feature.objects.get_or_create(slug='view_attendance', defaults={'name': 'View Attendance'})
        Feature.objects.get_or_create(slug='manage_attendance', defaults={'name': 'Manage Attendance'})
        self.main.subscription.disabled_features.add(*Feature.objects.filter(
            slug__in=['view_attendance', 'manage_attendance']))
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get('/admin-panel/attendance/roster/').status_code, 302)
        self._post(self.manager, **{f'c_{self.cook.id}_0': 'off'})
        self.assertFalse(RosterEntry.objects.exists())

    def test_roster_api_requires_login(self):
        self.assertIn(APIClient().get('/api/v1/attendance/roster/my/').status_code, (401, 403))

    # ---------- attendance uses the roster ----------
    def test_check_in_uses_published_roster_shift(self):
        idx = self.today.weekday()
        self._post(self.manager, week=self.this_week, **{f'c_{self.cook.id}_{idx}': f'shift:{self.night.id}'})
        noon = datetime.time(12, 0)
        self.assertEqual(_shift_for(self.cook, self.main, None, noon), self.morning)   # draft: by time of day
        self._post(self.manager, week=self.this_week, action='publish')
        self.assertEqual(_shift_for(self.cook, self.main, None, noon), self.night)     # published: roster wins
        self.assertEqual(_shift_for(self.cashier, self.main, None, noon), self.morning)  # not rostered: unchanged

        qr = AttendanceQRToken.objects.create(owner=self.main, restaurant=None)
        r = self._api(self.cook).post('/api/v1/attendance/confirm/', {'qr_token': qr.token, 'action': 'check_in'},
                                      format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(AttendanceRecord.objects.get(staff=self.cook).shift, self.night)

    def test_off_day_falls_back_to_time_of_day(self):
        idx = self.today.weekday()
        self._post(self.manager, week=self.this_week, **{f'c_{self.cook.id}_{idx}': 'off'})
        self._post(self.manager, week=self.this_week, action='publish')
        self.assertEqual(_shift_for(self.cook, self.main, None, datetime.time(9, 0)), self.morning)

    def test_deleted_shift_does_not_break_anything(self):
        idx = self.today.weekday()
        self._post(self.manager, week=self.this_week, **{f'c_{self.cook.id}_{idx}': f'shift:{self.night.id}'})
        self._post(self.manager, week=self.this_week, action='publish')
        self.night.delete()
        self.assertEqual(_shift_for(self.cook, self.main, None, datetime.time(9, 0)), self.morning)
        self.client.force_login(self.manager)
        page = self.client.get('/admin-panel/attendance/roster/')
        self.assertEqual(page.status_code, 200)
        self.client.force_login(self.cook)
        self.assertIn('Shift to be confirmed', self.client.get('/admin-panel/attendance/my/').content.decode())
        self.assertEqual(self._my(self.cook)[0]['start_time'], None)

    def test_my_attendance_page_shows_upcoming_shifts(self):
        idx = self.today.weekday()
        self._post(self.manager, week=self.this_week, **{f'c_{self.cook.id}_{idx}': f'shift:{self.morning.id}'})
        self._post(self.manager, week=self.this_week, action='publish')
        self.client.force_login(self.cook)
        page = self.client.get('/admin-panel/attendance/my/').content.decode()
        self.assertIn('My Upcoming Shifts', page)
        self.assertIn('08:00–16:00', page)

    def test_attendance_history_bad_page_param(self):
        self.assertEqual(self._api(self.cook).get('/api/v1/attendance/my/?page=abc').status_code, 200)
