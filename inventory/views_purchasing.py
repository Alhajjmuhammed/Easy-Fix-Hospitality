"""Suppliers & purchase order pages (under Inventory)."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import get_owner_filter
from .models import InventoryItem, PurchaseOrder, Supplier, SupplierPayment
from . import purchasing as svc
from .views import _get_currency_symbol, _require_inventory_access


def _owner(request, level='view'):
    """The owner whose purchasing data this user works on. Administrators have no restaurant here."""
    if not _require_inventory_access(request.user, level=level):
        raise PermissionDenied
    try:
        owner = get_owner_filter(request.user)
    except PermissionDenied:
        owner = None
    if owner is None:
        raise PermissionDenied
    return owner


def _guard(view):
    """Send users without access back to the dashboard instead of an error page."""
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except PermissionDenied:
            messages.error(request, "You don't have permission for purchasing.")
            return redirect('admin_panel:admin_dashboard')
    wrapped.__name__ = view.__name__
    wrapped.__doc__ = view.__doc__
    return wrapped


def _order(owner, pk):
    return get_object_or_404(PurchaseOrder.objects.select_related('supplier'), owner=owner, pk=pk)


def _int_or_404(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Http404


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@login_required
@_guard
def suppliers(request):
    owner = _owner(request)
    can_manage = _require_inventory_access(request.user, 'manage')
    if request.method == 'POST':
        if not can_manage:
            raise PermissionDenied
        action = request.POST.get('action')
        try:
            if action in ('add', 'edit'):
                supplier = None
                if action == 'edit':
                    supplier = get_object_or_404(Supplier, owner=owner, pk=_int_or_404(request.POST.get('supplier_id')))
                s = svc.save_supplier(owner, request.POST, supplier)
                messages.success(request, f'Supplier "{s.name}" saved.')
            elif action == 'toggle':
                s = get_object_or_404(Supplier, owner=owner, pk=_int_or_404(request.POST.get('supplier_id')))
                s.is_active = not s.is_active
                s.save(update_fields=['is_active'])
                messages.success(request, f'Supplier "{s.name}" {"reactivated" if s.is_active else "archived"}.')
            else:
                messages.error(request, 'Unknown action.')
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        return redirect('inventory:suppliers')

    rows = []
    currency = _get_currency_symbol(owner, request.user)
    for s in Supplier.objects.filter(owner=owner).order_by('-is_active', 'name'):
        orders = list(s.purchase_orders.exclude(status='cancelled').prefetch_related('lines', 'payments'))
        rows.append({'supplier': s, 'orders': len(orders),
                     'owed': sum((o.amount_owed for o in orders), Decimal('0.00'))})
    return render(request, 'inventory/suppliers.html', {
        'rows': rows, 'can_manage': can_manage, 'currency_symbol': currency,
    })


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

@login_required
@_guard
def po_list(request):
    owner = _owner(request)
    qs = PurchaseOrder.objects.filter(owner=owner).select_related('supplier').prefetch_related('lines', 'payments')
    status = request.GET.get('status', '')
    if status == 'open':
        qs = qs.filter(status__in=('draft', 'sent', 'partial'))
    elif status in dict(PurchaseOrder.STATUS_CHOICES):
        qs = qs.filter(status=status)
    supplier_id = request.GET.get('supplier', '')
    if supplier_id.isdigit():
        qs = qs.filter(supplier_id=int(supplier_id))
    payment = request.GET.get('payment', '')
    if payment in ('unpaid', 'partly_paid', 'paid'):
        # Payment status is worked out per order, so filter before limiting the list
        orders = [o for o in qs.exclude(status='cancelled') if o.payment_status == payment][:300]
    else:
        orders = list(qs[:300])

    open_orders = PurchaseOrder.objects.filter(owner=owner).exclude(status='cancelled').prefetch_related('lines', 'payments')
    return render(request, 'inventory/po_list.html', {
        'orders': orders,
        'suppliers': Supplier.objects.filter(owner=owner).order_by('name'),
        'status_choices': PurchaseOrder.STATUS_CHOICES,
        'filter_status': status, 'filter_supplier': supplier_id, 'filter_payment': payment,
        'total_owed': sum((o.amount_owed for o in open_orders), Decimal('0.00')),
        'can_manage': _require_inventory_access(request.user, 'manage'),
        'currency_symbol': _get_currency_symbol(owner, request.user),
    })


@login_required
@_guard
def po_form(request, pk=None):
    owner = _owner(request, 'manage')
    order = _order(owner, pk) if pk else None
    if order is not None and not order.is_editable:
        messages.error(request, 'This order can no longer be changed.')
        return redirect('inventory:po_detail', pk=order.pk)
    if request.method == 'POST':
        try:
            order = svc.save_order(owner, request.user, request.POST, request.POST.getlist('item_id'),
                                   request.POST.getlist('quantity'), request.POST.getlist('unit_price'), order)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
            lines = list(zip(request.POST.getlist('item_id'), request.POST.getlist('quantity'),
                             request.POST.getlist('unit_price')))
            return _render_form(request, owner, order, request.POST, lines)
        messages.success(request, f'{order.code} saved.')
        return redirect('inventory:po_detail', pk=order.pk)
    if order is not None:
        data = {'supplier_id': str(order.supplier_id), 'order_date': order.order_date.isoformat(),
                'expected_date': order.expected_date.isoformat() if order.expected_date else '', 'notes': order.notes}
        lines = [(str(l.item_id), f'{l.quantity.normalize():f}', f'{l.unit_price}') for l in order.lines.all()]
    else:
        data = {'supplier_id': request.GET.get('supplier', ''), 'order_date': timezone.localdate().isoformat()}
        lines = []
    return _render_form(request, owner, order, data, lines)


def _render_form(request, owner, order, data, lines):
    suppliers_qs = Supplier.objects.filter(owner=owner).filter(
        Q(is_active=True) | Q(pk=order.supplier_id if order else None)).order_by('name')
    items = InventoryItem.objects.filter(owner=owner).filter(
        Q(is_active=True) | Q(pk__in=[l[0] for l in lines if str(l[0]).isdigit()])).order_by('category', 'name')
    return render(request, 'inventory/po_form.html', {
        'order': order, 'data': data, 'lines': lines or [('', '', '')],
        'suppliers': suppliers_qs, 'items': items,
        'currency_symbol': _get_currency_symbol(owner, request.user),
    })


@login_required
@_guard
def po_detail(request, pk):
    owner = _owner(request)
    order = _order(owner, pk)
    currency = _get_currency_symbol(owner, request.user)
    can_manage = _require_inventory_access(request.user, 'manage')
    return render(request, 'inventory/po_detail.html', {
        'order': order,
        'lines': order.lines.select_related('item'),
        'payments': order.payments.select_related('recorded_by'),
        'can_manage': can_manage,
        'can_receive': can_manage and order.status in PurchaseOrder.RECEIVABLE,
        'currency_symbol': currency,
        'share_text': svc.share_text(order, currency),
        'email_ready': svc.email_configured(),
        'method_choices': SupplierPayment.METHOD_CHOICES,
        'today': timezone.localdate(),
    })


@login_required
@_guard
@require_POST
def po_action(request, pk):
    owner = _owner(request, 'manage')
    order = _order(owner, pk)
    action = request.POST.get('action')
    currency = _get_currency_symbol(owner, request.user)
    try:
        if action == 'send':
            svc.mark_sent(order)
            messages.success(request, f'{order.code} marked as sent.')
        elif action == 'email':
            svc.send_email(order, currency, request.user)
            messages.success(request, f'{order.code} emailed to {order.supplier.email}.')
        elif action == 'cancel':
            svc.cancel(order)
            messages.success(request, f'{order.code} cancelled.')
        elif action == 'close':
            svc.close(order)
            messages.success(request, f'{order.code} closed. Nothing more is expected from the supplier.')
        elif action == 'receive':
            quantities = {}
            for key, value in request.POST.items():
                if key.startswith('recv_'):
                    quantities[_int_or_404(key[5:])] = value
            order = svc.receive(order, quantities, request.user, request.POST.get('note', ''))
            messages.success(request, 'Delivery received and added to stock.'
                             if order.status == 'received' else 'Delivery received and added to stock. More is still due.')
        elif action == 'pay':
            svc.add_payment(order, request.POST, request.user)
            messages.success(request, 'Payment recorded.')
        elif action == 'delete_payment':
            svc.delete_payment(order, request.POST.get('payment_id'))
            messages.success(request, 'Payment removed.')
        else:
            messages.error(request, 'Unknown action.')
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
    return redirect('inventory:po_detail', pk=order.pk)


@login_required
@_guard
def po_pdf(request, pk):
    owner = _owner(request)
    order = _order(owner, pk)
    response = HttpResponse(svc.build_pdf(order, _get_currency_symbol(owner, request.user)),
                            content_type='application/pdf')
    disposition = 'attachment' if request.GET.get('download') else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="{order.code}.pdf"'
    return response
