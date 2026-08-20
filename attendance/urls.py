"""URL patterns for the attendance app (both mobile API and web)."""

from django.urls import path
from . import views_web, views_mobile

app_name = 'attendance'

# urlpatterns = web views (the include in urls.py mounts this under admin-panel/attendance/)
urlpatterns = web_urlpatterns = [
    path('',                  views_web.attendance_dashboard,     name='dashboard'),
    path('shifts/',           views_web.attendance_shifts,        name='shifts'),
    path('calendar/',         views_web.attendance_calendar,      name='calendar'),
    path('calendar/day/',     views_web.attendance_day_records,   name='day_records'),
    path('qr/',               views_web.attendance_qr,            name='qr'),
    path('qr/regenerate/',    views_web.attendance_qr_regenerate, name='qr_regenerate'),
    path('checkin/',          views_web.attendance_web_checkin,   name='web_checkin'),
    path('my/',               views_web.attendance_my,            name='my'),
]

# Mobile API views (mounted under api/v1/attendance/)
mobile_urlpatterns = [
    path('scan/',    views_mobile.attendance_scan,    name='mobile_scan'),
    path('confirm/', views_mobile.attendance_confirm, name='mobile_confirm'),
    path('my/',      views_mobile.attendance_my,      name='mobile_my'),
    path('status/',  views_mobile.attendance_status,  name='mobile_status'),
]
