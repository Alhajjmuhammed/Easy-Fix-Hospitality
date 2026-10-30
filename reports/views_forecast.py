"""Sales forecast page (owners and managers with View Reports)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from accounts.models import get_owner_filter
from . import forecast as svc


@login_required
def forecast(request):
    user = request.user
    if not (user.is_any_owner() or user.is_manager()) or not user.has_feature('view_reports'):
        messages.error(request, "You don't have permission to view the forecast.")
        return redirect('restaurant:home')
    try:
        owner = get_owner_filter(user)
    except PermissionDenied:
        owner = None
    if owner is None:
        messages.error(request, 'You are not assigned to a restaurant.')
        return redirect('restaurant:home')
    from inventory.views import _get_currency_symbol
    data = dict(svc.cached_build(owner))
    data['shopping'] = svc.shopping_list(owner, data['expected_qty'])      # live stock, never cached
    data['currency_symbol'] = _get_currency_symbol(owner, user)
    data['can_order'] = user.has_feature('manage_inventory')
    data['prefill'] = ','.join(f"{r['item'].id}:{r['buy']}" for r in data['shopping'])
    return render(request, 'reports/forecast.html', data)
