from django.http import HttpResponse
from django.test import TestCase, RequestFactory
from django.utils import timezone

from accounts.models import Role, User
from attendance.middleware import AttendanceEnforcementMiddleware
from attendance.models import AttendancePolicy, AttendanceRecord


def role(name):
    return Role.objects.get_or_create(name=name)[0]


class AttendanceMiddlewareTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('own', password='pw12345!x', role=role('main_owner'))
        self.cashier = User.objects.create_user('cash', password='pw12345!x', role=role('cashier'), owner=self.owner)
        self.calls = 0

    def _run(self, path='/cashier/', view=None):
        def get_response(request):
            self.calls += 1
            return view(request) if view else HttpResponse('page')
        req = RequestFactory().get(path)
        req.user = self.cashier
        return AttendanceEnforcementMiddleware(get_response)(req)

    def test_no_policy_allows_and_logs_nothing(self):
        with self.assertNoLogs('attendance.middleware', level='WARNING'):
            resp = self._run()
        self.assertEqual((resp.status_code, self.calls), (200, 1))

    def test_policy_switched_off_allows(self):
        AttendancePolicy.objects.create(owner=self.owner, require_checkin_before_work=False)
        resp = self._run()
        self.assertEqual((resp.status_code, self.calls), (200, 1))

    def test_policy_on_and_not_checked_in_redirects(self):
        AttendancePolicy.objects.create(owner=self.owner, require_checkin_before_work=True)
        resp = self._run()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.calls, 0)

    def test_policy_on_and_checked_in_allows(self):
        AttendancePolicy.objects.create(owner=self.owner, require_checkin_before_work=True)
        AttendanceRecord.objects.create(staff=self.cashier, owner=self.owner, date=timezone.localdate(),
                                        check_in=timezone.now())
        resp = self._run()
        self.assertEqual((resp.status_code, self.calls), (200, 1))

    def test_page_error_is_not_swallowed_or_run_twice(self):
        def broken(request):
            raise ValueError('page failed')
        with self.assertRaises(ValueError):
            self._run(view=broken)
        self.assertEqual(self.calls, 1)
