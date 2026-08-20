"""Mobile API views for staff attendance (scan, confirm, my records, status)."""

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import AttendanceQRToken, AttendanceRecord, Shift


def _best_shift(owner, restaurant, now_time):
    """Return the Shift whose window best covers now_time, else None."""
    shifts = Shift.objects.filter(owner=owner, is_active=True)
    if restaurant:
        shifts = shifts.filter(restaurant=restaurant)
    for shift in shifts:
        if shift.start_time <= shift.end_time:
            if shift.start_time <= now_time <= shift.end_time:
                return shift
        else:
            if now_time >= shift.start_time or now_time <= shift.end_time:
                return shift
    # Fall back to any active shift for owner
    return shifts.first()


def _record_to_dict(rec):
    def fmt(dt):
        return dt.isoformat() if dt else None

    def mins_to_hm(m):
        if m is None:
            return None
        h, rem = divmod(m, 60)
        return f"{h}h {rem}m" if h else f"{rem}m"

    return {
        'id': rec.id,
        'date': rec.date.isoformat(),
        'check_in': fmt(rec.check_in),
        'check_out': fmt(rec.check_out),
        'work_minutes': rec.work_minutes,
        'work_hours_display': mins_to_hm(rec.work_minutes),
        'is_late': rec.is_late,
        'late_minutes': rec.late_minutes,
        'is_overtime': rec.is_overtime,
        'overtime_minutes': rec.overtime_minutes,
        'check_in_via': rec.check_in_via,
        'check_out_via': rec.check_out_via,
        'shift_name': rec.shift.name if rec.shift else None,
        'restaurant_name': rec.restaurant.name if rec.restaurant else None,
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def attendance_scan(request):
    """
    Validate QR token and return what action the staff should take.
    Body: { qr_token: "ATT-..." }
    Response: { action: "check_in"|"check_out", restaurant_name, shift, today_record }
    """
    token_str = (request.data.get('qr_token') or '').strip()
    if not token_str:
        return Response({'error': 'qr_token is required'}, status=400)

    try:
        qr = AttendanceQRToken.objects.select_related('owner', 'restaurant').get(token=token_str)
    except AttendanceQRToken.DoesNotExist:
        return Response({'error': 'Invalid QR code'}, status=404)

    user = request.user
    owner = user.get_owner()

    if qr.owner != owner:
        return Response({'error': 'This QR code does not belong to your restaurant'}, status=403)

    today = timezone.localdate()
    now_time = timezone.localtime().time()
    restaurant = qr.restaurant
    shift = _best_shift(owner, restaurant, now_time)

    try:
        record = AttendanceRecord.objects.get(staff=user, date=today)
        if record.check_out:
            action = 'already_done'
        else:
            action = 'check_out'
    except AttendanceRecord.DoesNotExist:
        record = None
        action = 'check_in'

    return Response({
        'action': action,
        'restaurant_name': restaurant.name if restaurant else owner.restaurant_name,
        'restaurant_id': restaurant.id if restaurant else None,
        'shift': {
            'id': shift.id,
            'name': shift.name,
            'start_time': shift.start_time.strftime('%H:%M'),
            'end_time': shift.end_time.strftime('%H:%M'),
        } if shift else None,
        'today_record': _record_to_dict(record) if record else None,
        'current_time': timezone.localtime().strftime('%H:%M'),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def attendance_confirm(request):
    """
    Confirm and record the attendance action.
    Body: { qr_token: "ATT-...", action: "check_in"|"check_out" }
    """
    token_str = (request.data.get('qr_token') or '').strip()
    action = (request.data.get('action') or '').strip()

    if not token_str or action not in ('check_in', 'check_out'):
        return Response({'error': 'qr_token and action (check_in/check_out) are required'}, status=400)

    try:
        qr = AttendanceQRToken.objects.select_related('owner', 'restaurant').get(token=token_str)
    except AttendanceQRToken.DoesNotExist:
        return Response({'error': 'Invalid QR code'}, status=404)

    user = request.user
    owner = user.get_owner()
    if qr.owner != owner:
        return Response({'error': 'QR code does not belong to your restaurant'}, status=403)

    today = timezone.localdate()
    now = timezone.now()
    now_time = timezone.localtime().time()
    restaurant = qr.restaurant
    shift = _best_shift(owner, restaurant, now_time)

    record, created = AttendanceRecord.objects.get_or_create(
        staff=user,
        date=today,
        defaults={
            'owner': owner,
            'restaurant': restaurant,
            'shift': shift,
        },
    )

    if action == 'check_in':
        if record.check_in:
            return Response({'error': 'Already checked in today'}, status=400)
        record.check_in = now
        record.check_in_via = 'mobile'
        if not record.shift:
            record.shift = shift
        record.save()
        return Response({
            'success': True,
            'message': f"Checked in at {timezone.localtime(now).strftime('%H:%M')}",
            'record': _record_to_dict(record),
        })

    else:  # check_out
        if not record.check_in:
            return Response({'error': 'Not checked in yet today'}, status=400)
        if record.check_out:
            return Response({'error': 'Already checked out today'}, status=400)
        record.check_out = now
        record.check_out_via = 'mobile'
        record.compute_metrics()
        record.save()
        return Response({
            'success': True,
            'message': f"Checked out at {timezone.localtime(now).strftime('%H:%M')}",
            'record': _record_to_dict(record),
        })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def attendance_my(request):
    """Return paginated attendance records for the authenticated staff member."""
    user = request.user
    records = AttendanceRecord.objects.filter(staff=user).select_related('shift', 'restaurant')

    # Optional date-range filter
    from_date = request.query_params.get('from')
    to_date = request.query_params.get('to')
    if from_date:
        records = records.filter(date__gte=from_date)
    if to_date:
        records = records.filter(date__lte=to_date)

    # Pagination: 30 per page
    from django.core.paginator import Paginator
    page_num = int(request.query_params.get('page', 1))
    paginator = Paginator(records, 30)
    page = paginator.get_page(page_num)

    return Response({
        'count': paginator.count,
        'num_pages': paginator.num_pages,
        'page': page_num,
        'results': [_record_to_dict(r) for r in page.object_list],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def attendance_status(request):
    """Return today's check-in status for the authenticated user."""
    today = timezone.localdate()
    try:
        record = AttendanceRecord.objects.select_related('shift', 'restaurant').get(
            staff=request.user, date=today
        )
        return Response({
            'checked_in': record.check_in is not None,
            'checked_out': record.check_out is not None,
            'record': _record_to_dict(record),
        })
    except AttendanceRecord.DoesNotExist:
        return Response({'checked_in': False, 'checked_out': False, 'record': None})
