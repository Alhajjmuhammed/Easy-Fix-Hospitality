"""
Attendance enforcement middleware.
When an owner enables 'require_checkin_before_work', staff who have not
checked in today are redirected to the attendance check-in page instead
of their work panels.  Default is OFF — no impact on current behaviour.
"""

import logging

from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


# Paths that should NEVER be blocked (even when enforcement is on)
_ALWAYS_ALLOWED = (
    '/accounts/',
    '/static/',
    '/media/',
    '/api/v1/',
    '/ws/',
    '/admin-panel/attendance/',
    '/health-check/',
    '/service-worker.js',
    '/rate-limited/',
    '/r/',
    '/menu-view/',
)

# Work-area paths that ARE subject to enforcement
_WORK_PATHS = (
    '/cashier/',
    '/waste-management/',
    '/inventory/',
    '/reports/',
    '/admin-panel/',   # covers manager/owner panel (attendance sub-path is already allowed above)
)


class AttendanceEnforcementMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_enforce(request):
            from .models import AttendanceRecord, AttendancePolicy
            user = request.user
            try:
                owner = user.get_owner()
                policy = AttendancePolicy.objects.get(owner=owner, require_checkin_before_work=True)
                today = timezone.localdate()
                checked_in = AttendanceRecord.objects.filter(
                    staff=user, date=today, check_in__isnull=False
                ).exists()
                if not checked_in:
                    checkin_url = reverse('attendance:web_checkin')
                    if request.path != checkin_url:
                        return redirect(checkin_url)
            except Exception as _e:
                logger.warning("Attendance enforcement error for %s: %s", user, _e, exc_info=True)
                pass  # fail open — never block staff due to a middleware bug

        return self.get_response(request)

    def _should_enforce(self, request):
        # Must be a real authenticated request
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return False
        # Owners bypass enforcement (they manage the system)
        if request.user.is_any_owner():
            return False
        path = request.path
        # Never block always-allowed paths
        for allowed in _ALWAYS_ALLOWED:
            if path.startswith(allowed):
                return False
        # Only enforce on known work paths
        for work in _WORK_PATHS:
            if path.startswith(work):
                return True
        return False
