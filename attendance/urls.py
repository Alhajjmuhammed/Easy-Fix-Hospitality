"""URL patterns for the attendance app web views (mounted under admin-panel/attendance/)."""

from django.urls import path
from . import views_web

app_name = 'attendance'

urlpatterns = [
    path('',              views_web.attendance_dashboard,     name='dashboard'),
    path('shifts/',       views_web.attendance_shifts,        name='shifts'),
    path('calendar/',     views_web.attendance_calendar,      name='calendar'),
    path('calendar/day/', views_web.attendance_day_records,   name='day_records'),
    path('day/',          views_web.attendance_day_detail,    name='day_detail'),
    path('reports/',      views_web.attendance_reports,       name='reports'),
    path('qr/',           views_web.attendance_qr,            name='qr'),
    path('qr/regenerate/',views_web.attendance_qr_regenerate, name='qr_regenerate'),
    path('checkin/',      views_web.attendance_web_checkin,   name='web_checkin'),
    path('checkin/qr-scan/', views_web.attendance_qr_web_scan, name='qr_web_scan'),
    path('policy/',       views_web.attendance_policy_toggle, name='policy_toggle'),
    path('my/',           views_web.attendance_my,            name='my'),
]
# Mobile API paths are registered directly in mobile_api/urls.py
