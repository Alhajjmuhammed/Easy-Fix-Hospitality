"""Table reservations: staff management page and customer booking pages (web)."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import get_owner_filter
from .models import TableInfo
from .models_reservation import Reservation, reservations_for_owner
from .models_restaurant import Restaurant
from . import reservations as svc


def _is_staff(user):
    return (user.is_owner() or user.is_main_owner() or user.is_branch_owner() or user.is_manager()
            or user.is_cashier() or user.is_customer_care())


def _staff_owner(request):
    """(owner, error_redirect). Staff without a restaurant or permission get a redirect."""
    user = request.user
    if not _is_staff(user) or not (user.has_feature('view_reservations') or user.has_feature('manage_reservations')):
        messages.error(request, "You don't have permission to view reservations.")
        return None, redirect('restaurant:home')
    try:
        owner = get_owner_filter(user)
    except PermissionDenied:
        owner = None
    if owner is None:
        messages.error(request, 'You are not assigned to a restaurant.')
        return None, redirect('restaurant:home')
    return owner, None


def _base_template(user):
    return 'cashier_base.html' if (user.is_cashier() or user.is_customer_care()) else 'admin_panel/base.html'


def _owner_restaurants(owner):
    return Restaurant.objects.filter(Q(branch_owner=owner) | Q(main_owner=owner)).order_by('-is_main_restaurant', 'name')


@login_required
def manage_reservations(request):
    owner, denied = _staff_owner(request)
    if denied:
        return denied
    can_manage = request.user.has_feature('manage_reservations')
    restaurants = list(_owner_restaurants(owner))

    if request.method == 'POST':
        if not can_manage:
            messages.error(request, "You don't have permission to add reservations.")
            return redirect('restaurant:manage_reservations')
        restaurant = next((r for r in restaurants if str(r.id) == request.POST.get('restaurant_id', '')), None) \
            or (restaurants[0] if len(restaurants) == 1 else None)
        if restaurant is None:
            messages.error(request, 'Please choose the restaurant for this booking.')
            return redirect('restaurant:manage_reservations')
        table = None
        if request.POST.get('table_id'):
            table = TableInfo.objects.filter(id=request.POST['table_id'], restaurant=restaurant).first()
        try:
            start = svc.parse_start(request.POST.get('date'), request.POST.get('time'))
            res, warnings = svc.create_reservation(
                restaurant, name=request.POST.get('name'), phone=request.POST.get('phone'),
                email=request.POST.get('email', ''), party_size=request.POST.get('party_size'),
                start=start, notes=request.POST.get('notes', ''), table=table,
                created_by=request.user, source='staff', staff=True,
            )
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
            return redirect('restaurant:manage_reservations')
        messages.success(request, f'Reservation added for {res.name}.')
        for w in warnings:
            messages.warning(request, w)
        return redirect(f"{reverse('restaurant:manage_reservations')}?date={timezone.localtime(res.start):%Y-%m-%d}")

    today = timezone.localdate()
    try:
        day = timezone.datetime.strptime(request.GET.get('date', ''), '%Y-%m-%d').date()
    except ValueError:
        day = today
    status_filter = request.GET.get('status', 'active')

    qs = reservations_for_owner(owner).select_related('table', 'restaurant', 'customer').filter(start__date=day)
    if status_filter == 'active':
        qs = qs.filter(status__in=Reservation.ACTIVE_STATUSES)
    elif status_filter in dict(Reservation.STATUS_CHOICES):
        qs = qs.filter(status=status_filter)
    tables_by_restaurant = {
        r.id: list(TableInfo.objects.filter(restaurant=r).order_by('tbl_no')) for r in restaurants
    }
    rows = [{'res': r, 'warnings': r.warnings() if r.is_active else [],
             'tables': tables_by_restaurant.get(r.restaurant_id, []),
             'next_statuses': [(s, dict(Reservation.STATUS_CHOICES)[s]) for s in Reservation.STAFF_TRANSITIONS[r.status]]}
            for r in qs]

    pending_upcoming = reservations_for_owner(owner).filter(status='pending', start__gte=timezone.now()) \
        .select_related('restaurant').order_by('start')[:20]
    return render(request, 'restaurant/reservations_manage.html', {
        'base_template': _base_template(request.user),
        'rows': rows,
        'day': day,
        'today': today,
        'prev_day': day - timedelta(days=1),
        'next_day': day + timedelta(days=1),
        'status_filter': status_filter,
        'status_choices': Reservation.STATUS_CHOICES,
        'pending_upcoming': pending_upcoming,
        'restaurants': restaurants,
        'single_restaurant_tables': tables_by_restaurant.get(restaurants[0].id, []) if len(restaurants) == 1 else [],
        'can_manage': can_manage,
    })


@login_required
@require_POST
def reservation_action(request, pk):
    owner, denied = _staff_owner(request)
    if denied:
        return denied
    res = get_object_or_404(reservations_for_owner(owner), pk=pk)
    back = f"{reverse('restaurant:manage_reservations')}?date={timezone.localtime(res.start):%Y-%m-%d}"
    if not request.user.has_feature('manage_reservations'):
        messages.error(request, "You don't have permission to change reservations.")
        return redirect(back)
    action = request.POST.get('action')
    try:
        if action == 'status':
            res = svc.change_status(res, request.POST.get('status', ''), request.user)
            messages.success(request, f'{res.name}: {res.get_status_display()}.')
        elif action == 'table':
            table = None
            if request.POST.get('table_id'):
                table = get_object_or_404(TableInfo, id=request.POST['table_id'], restaurant=res.restaurant)
            for w in svc.assign_table(res, table, request.user):
                messages.warning(request, w)
            messages.success(request, f'{res.name}: table {"set to " + table.tbl_no if table else "cleared"}.')
        elif action == 'notes':
            res.staff_notes = (request.POST.get('staff_notes') or '').strip()[:1000]
            res.save(update_fields=['staff_notes', 'updated_at'])
            messages.success(request, 'Notes saved.')
        else:
            messages.error(request, 'Unknown action.')
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
    return redirect(back)


# ---------------------------------------------------------------------------
# Customer pages
# ---------------------------------------------------------------------------

def _bookable_restaurant(restaurant_id):
    restaurant = get_object_or_404(Restaurant, id=restaurant_id, is_active=True, reservations_enabled=True)
    owner = restaurant.branch_owner or restaurant.main_owner
    if owner is None or not owner.is_active:  # blocked/expired subscriptions deactivate the owner
        from django.http import Http404
        raise Http404
    return restaurant


@login_required
def book_table(request, restaurant_id):
    restaurant = _bookable_restaurant(restaurant_id)
    if not request.user.is_customer():
        messages.info(request, 'Staff add bookings from the Reservations page.')
        return redirect('restaurant:manage_reservations')
    form = {
        'name': request.user.get_full_name() or request.user.username,
        'phone': getattr(request.user, 'phone_number', '') or '',
        'party_size': 2, 'date': '', 'time': '', 'notes': '',
    }
    if request.method == 'POST':
        form.update({k: request.POST.get(k, '') for k in ('name', 'phone', 'party_size', 'date', 'time', 'notes')})
        try:
            start = svc.parse_start(form['date'], form['time'])
            res, _ = svc.create_reservation(
                restaurant, name=form['name'], phone=form['phone'], email=request.user.email or '',
                party_size=form['party_size'], start=start, notes=form['notes'],
                customer=request.user, created_by=request.user, source='web',
            )
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        else:
            if res.status == 'confirmed':
                messages.success(request, f'Your table at {restaurant.name} is confirmed.')
            else:
                messages.success(request, f'Booking request sent to {restaurant.name}. You will be notified when they confirm.')
            return redirect('restaurant:my_reservations')
    return render(request, 'restaurant/book_table.html', {
        'restaurant': restaurant,
        'form': form,
        'min_date': timezone.localdate().isoformat(),
        'max_date': (timezone.localdate() + svc.MAX_AHEAD).isoformat(),
    })


@login_required
def my_reservations(request):
    now = timezone.now()
    qs = Reservation.objects.filter(customer=request.user).select_related('restaurant', 'table')
    return render(request, 'restaurant/my_reservations.html', {
        'upcoming': qs.filter(start__gte=now - timedelta(hours=3)).exclude(status__in=('completed', 'no_show')).order_by('start'),
        'past': qs.filter(Q(start__lt=now - timedelta(hours=3)) | Q(status__in=('completed', 'no_show'))).order_by('-start')[:20],
    })


@login_required
@require_POST
def cancel_my_reservation(request, pk):
    res = get_object_or_404(Reservation, pk=pk, customer=request.user)
    try:
        svc.customer_cancel(res, request.user)
        messages.success(request, 'Your reservation was cancelled.')
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
    return redirect('restaurant:my_reservations')
