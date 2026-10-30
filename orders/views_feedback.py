"""Customer ratings (rate an order) and the staff feedback page (web)."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import get_owner_filter
from .models import Order
from .models_feedback import OrderRating
from . import feedback as svc


@login_required
def rate_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, ordered_by=request.user)
    existing = OrderRating.objects.filter(order=order).first()
    if existing is not None:
        messages.info(request, 'Thanks — you already rated this order.')
        return redirect('orders:order_detail', order_id=order.id)
    if not svc.can_rate(order, request.user):
        messages.error(request, 'This order can no longer be rated.')
        return redirect('orders:order_detail', order_id=order.id)
    form = {'food': '', 'delivery': '', 'comment': ''}
    if request.method == 'POST':
        form = {k: request.POST.get(k, '') for k in form}
        try:
            svc.submit_rating(order, request.user, form['food'], form['delivery'], form['comment'])
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        else:
            messages.success(request, 'Thank you for your feedback!')
            return redirect('orders:order_detail', order_id=order.id)
    return render(request, 'orders/rate_order.html', {'order': order, 'form': form})


def _feedback_owner(user):
    staff = user.is_any_owner() or (user.role is not None and user.role.name in svc.FEEDBACK_ROLES)
    if not staff or not user.has_feature('view_feedback'):
        raise PermissionDenied
    try:
        owner = get_owner_filter(user)
    except PermissionDenied:
        owner = None
    if owner is None:
        raise PermissionDenied
    return owner


def _base_template(user):
    return 'cashier_base.html' if (user.is_cashier() or user.is_customer_care()) else 'admin_panel/base.html'


@login_required
def feedback_list(request):
    try:
        owner = _feedback_owner(request.user)
    except PermissionDenied:
        messages.error(request, "You don't have permission to view customer feedback.")
        return redirect('restaurant:home')
    qs = svc.ratings_for_owner(owner).select_related('order', 'customer', 'replied_by')
    show = request.GET.get('show', '')
    if show == 'low':
        qs = qs.filter(Q(food_stars__lte=2) | Q(delivery_stars__lte=2))
    elif show == 'unreplied':
        qs = qs.filter(reply='')
    page = Paginator(qs.order_by('-created_at'), 30).get_page(request.GET.get('page'))
    base = svc.ratings_for_owner(owner)
    return render(request, 'orders/feedback_list.html', {
        'base_template': _base_template(request.user),
        'page': page,
        'show': show,
        'last30': svc.summary(base.filter(created_at__gte=timezone.now() - timedelta(days=30))),
        'all_time': svc.summary(base),
        'can_reply': request.user.has_feature('reply_feedback'),
    })


@login_required
@require_POST
def feedback_reply(request, rating_id):
    try:
        owner = _feedback_owner(request.user)
    except PermissionDenied:
        messages.error(request, "You don't have permission to view customer feedback.")
        return redirect('restaurant:home')
    if not request.user.has_feature('reply_feedback'):
        messages.error(request, "You don't have permission to reply to feedback.")
        return redirect('orders:feedback')
    rating = get_object_or_404(svc.ratings_for_owner(owner), pk=rating_id)
    try:
        svc.save_reply(rating, request.user, request.POST.get('reply'))
        messages.success(request, 'Reply sent to the customer.')
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
    return redirect(request.POST.get('next') if request.POST.get('next', '').startswith('/orders/feedback/')
                    else 'orders:feedback')
