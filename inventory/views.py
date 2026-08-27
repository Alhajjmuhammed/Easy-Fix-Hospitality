import csv
from io import BytesIO
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Abs, Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import mm

from accounts.models import get_owner_filter
from admin_panel.restaurant_utils import get_restaurant_context

from .models import InventoryCategory, InventoryItem, InventoryRecord, InventoryUnit


def _get_currency_symbol(owner, user):
    """Get the restaurant currency symbol for the given owner."""
    try:
        from restaurant.models_restaurant import Restaurant
        from django.db.models import Q as DQ
        target = owner if owner else user
        rest = Restaurant.objects.filter(
            DQ(main_owner=target) | DQ(branch_owner=target)
        ).first()
        return rest.get_currency_symbol() if rest else '$'
    except Exception:
        return '$'


def _require_inventory_access(user):
    """Return True if the user is allowed to access inventory pages."""
    return (
        user.is_owner()
        or user.is_main_owner()
        or user.is_branch_owner()
        or user.is_manager()
        or user.is_administrator()
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    if not _require_inventory_access(request.user):
        return redirect('admin_panel:admin_dashboard')

    owner = get_owner_filter(request.user)

    if owner:
        items_qs = InventoryItem.objects.filter(owner=owner, is_active=True)
    else:
        # administrator sees everything
        items_qs = InventoryItem.objects.filter(is_active=True).select_related('owner')

    # Annotate current stock from records in a single query to avoid N+1
    items_qs = items_qs.annotate(stock_total=Coalesce(Sum('records__quantity_change'), Value(0)))
    items_data = []
    low_stock_count = 0
    out_of_stock_count = 0
    for item in items_qs:
        stock = item.stock_total
        is_low = item.is_low_stock
        is_out = item.is_out_of_stock
        if is_low:
            low_stock_count += 1
        if is_out:
            out_of_stock_count += 1
        items_data.append({
            'item': item,
            'stock': stock,
            'is_low': is_low,
            'is_out': is_out,
        })

    # Recent records
    if owner:
        recent_records = InventoryRecord.objects.filter(
            item__owner=owner
        ).select_related('item', 'recorded_by')[:10]
    else:
        recent_records = InventoryRecord.objects.all().select_related('item', 'recorded_by')[:10]

    try:
        per_page = int(request.GET.get('per_page', 10))
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10
    paginator = Paginator(items_data, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    currency_symbol = _get_currency_symbol(owner, request.user)

    restaurant_context = get_restaurant_context(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'page_obj': page_obj,
        'recent_records': recent_records,
        'total_items': len(items_data),
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'per_page': per_page,
        'currency_symbol': currency_symbol,
        **restaurant_context,
    }
    return render(request, 'inventory/dashboard.html', context)


# ---------------------------------------------------------------------------
# Manage Items
# ---------------------------------------------------------------------------

@login_required
def manage_items(request):
    if not _require_inventory_access(request.user):
        return redirect('admin_panel:admin_dashboard')

    owner = get_owner_filter(request.user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            name = request.POST.get('name', '').strip()
            category = request.POST.get('category', '').strip()
            unit = request.POST.get('unit', '').strip()
            low_stock_threshold = request.POST.get('low_stock_threshold') or 5
            notes = request.POST.get('notes', '').strip()
            initial_stock_str = request.POST.get('initial_stock', '').strip()

            if not name:
                return JsonResponse({'success': False, 'error': 'Name is required.'})

            # Determine the item owner
            item_owner = owner if owner else request.user
            if InventoryItem.objects.filter(owner=item_owner, name__iexact=name).exists():
                return JsonResponse({'success': False, 'error': f'An item named "{name}" already exists.'})

            unit_price_str = request.POST.get('unit_price', '').strip()
            unit_price = None
            if unit_price_str:
                try:
                    unit_price = float(unit_price_str)
                    if unit_price < 0:
                        unit_price = None
                except (ValueError, TypeError):
                    pass

            item = InventoryItem.objects.create(
                owner=item_owner,
                name=name,
                category=category,
                unit=unit,
                low_stock_threshold=low_stock_threshold,
                unit_price=unit_price,
                notes=notes,
            )

            # Save initial stock as an Opening Stock record if provided
            if initial_stock_str:
                try:
                    initial_stock = float(initial_stock_str)
                    if initial_stock != 0:
                        InventoryRecord.objects.create(
                            item=item,
                            record_type='opening',
                            quantity_change=initial_stock,
                            notes='Initial stock',
                            recorded_by=request.user,
                        )
                except (ValueError, TypeError):
                    pass

            return JsonResponse({'success': True, 'item_id': item.id, 'name': item.name})

        elif action == 'edit':
            item_id = request.POST.get('item_id')
            item = _get_item_for_user(item_id, owner, request.user)
            if item is None:
                return JsonResponse({'success': False, 'error': 'Item not found.'})

            name = request.POST.get('name', '').strip()
            if not name:
                return JsonResponse({'success': False, 'error': 'Name is required.'})

            item.name = name
            item.category = request.POST.get('category', item.category)
            item.unit = request.POST.get('unit', item.unit)
            item.low_stock_threshold = request.POST.get('low_stock_threshold') or item.low_stock_threshold
            item.notes = request.POST.get('notes', '').strip()
            unit_price_str = request.POST.get('unit_price', '').strip()
            if unit_price_str:
                try:
                    up = float(unit_price_str)
                    item.unit_price = up if up >= 0 else None
                except (ValueError, TypeError):
                    pass
            else:
                item.unit_price = None
            item.save()
            return JsonResponse({'success': True})

        elif action == 'deactivate':
            item_id = request.POST.get('item_id')
            item = _get_item_for_user(item_id, owner, request.user)
            if item is None:
                return JsonResponse({'success': False, 'error': 'Item not found.'})
            item.is_active = False
            item.save()
            return JsonResponse({'success': True})

        elif action == 'reactivate':
            item_id = request.POST.get('item_id')
            if owner:
                item = InventoryItem.objects.filter(id=item_id, owner=owner).first()
            else:
                item = InventoryItem.objects.filter(id=item_id).first()
            if item is None:
                return JsonResponse({'success': False, 'error': 'Item not found.'})
            item.is_active = True
            item.save()
            return JsonResponse({'success': True})

        elif action == 'delete':
            item_id = request.POST.get('item_id')
            if owner:
                item = InventoryItem.objects.filter(id=item_id, owner=owner).first()
            else:
                item = InventoryItem.objects.filter(id=item_id).first()
            if item is None:
                return JsonResponse({'success': False, 'error': 'Item not found.'})
            item.delete()
            return JsonResponse({'success': True})

        return JsonResponse({'success': False, 'error': 'Unknown action.'})

    # GET
    show_inactive = request.GET.get('show_inactive') == '1'
    search = request.GET.get('search', '').strip()
    category_filter = request.GET.get('category_filter', '').strip()

    if owner:
        qs = InventoryItem.objects.filter(owner=owner)
    else:
        qs = InventoryItem.objects.all().select_related('owner')

    if not show_inactive:
        qs = qs.filter(is_active=True)

    if search:
        qs = qs.filter(name__icontains=search)

    if category_filter:
        qs = qs.filter(category__iexact=category_filter)

    qs = qs.annotate(stock_total=Coalesce(Sum('records__quantity_change'), Value(0)))
    items_data = [{'item': item, 'stock': item.stock_total} for item in qs]

    # Managed lists from InventoryCategory / InventoryUnit
    item_owner = owner if owner else request.user
    categories = InventoryCategory.objects.filter(owner=item_owner)
    units      = InventoryUnit.objects.filter(owner=item_owner)

    try:
        per_page = int(request.GET.get('per_page', 10))
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10
    paginator = Paginator(items_data, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    currency_symbol = _get_currency_symbol(owner, request.user)

    restaurant_context = get_restaurant_context(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'page_obj': page_obj,
        'total_items': paginator.count,
        'categories': categories,
        'units': units,
        'show_inactive': show_inactive,
        'per_page': per_page,
        'search': search,
        'category_filter': category_filter,
        'currency_symbol': currency_symbol,
        **restaurant_context,
    }
    return render(request, 'inventory/items.html', context)


# ---------------------------------------------------------------------------
# Add Record
# ---------------------------------------------------------------------------

@login_required
def add_record(request):
    if not _require_inventory_access(request.user):
        return redirect('admin_panel:admin_dashboard')

    owner = get_owner_filter(request.user)

    if owner:
        items_qs = InventoryItem.objects.filter(owner=owner, is_active=True).order_by('category', 'name')
    else:
        items_qs = InventoryItem.objects.filter(is_active=True).order_by('category', 'name').select_related('owner')

    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        record_type = request.POST.get('record_type')
        quantity_str = request.POST.get('quantity', '').strip()
        notes = request.POST.get('notes', '').strip()

        # Optional cost tracking
        unit_price_str = request.POST.get('unit_price', '').strip()
        record_unit_price = None
        if unit_price_str:
            try:
                p = float(unit_price_str)
                if p >= 0:
                    record_unit_price = p
            except (ValueError, TypeError):
                pass

        errors = []

        item = _get_item_for_user(item_id, owner, request.user)
        if item is None:
            errors.append('Invalid item selected.')

        try:
            quantity = float(quantity_str)
            if quantity == 0:
                errors.append('Quantity cannot be zero.')
        except (ValueError, TypeError):
            errors.append('Enter a valid quantity.')
            quantity = None

        valid_types = [k for k, _ in InventoryRecord.RECORD_TYPE_CHOICES]
        if record_type not in valid_types:
            errors.append('Invalid record type.')

        if errors:
            _rc = get_restaurant_context(request.user, request.session.get('current_restaurant_id'), request)
            context = {
                'items': items_qs,
                'record_type_choices': InventoryRecord.RECORD_TYPE_CHOICES,
                'errors': errors,
                'form_data': request.POST,
                **_rc,
            }
            return render(request, 'inventory/record.html', context)

        # Stock-out types automatically negate the quantity
        stock_out_types = ['used', 'waste', 'returned']
        if record_type in stock_out_types and quantity > 0:
            quantity = -quantity

        InventoryRecord.objects.create(
            item=item,
            record_type=record_type,
            quantity_change=quantity,
            unit_price=record_unit_price,
            notes=notes,
            recorded_by=request.user,
        )
        return redirect('inventory:history')

    _rc = get_restaurant_context(request.user, request.session.get('current_restaurant_id'), request)
    context = {
        'items': items_qs,
        'record_type_choices': InventoryRecord.RECORD_TYPE_CHOICES,
        'currency_symbol': _get_currency_symbol(owner, request.user),
        **_rc,
    }
    return render(request, 'inventory/record.html', context)


# ---------------------------------------------------------------------------
# History / Report
# ---------------------------------------------------------------------------

@login_required
def history(request):
    if not _require_inventory_access(request.user):
        return redirect('admin_panel:admin_dashboard')

    owner = get_owner_filter(request.user)

    if owner:
        records_qs = InventoryRecord.objects.filter(
            item__owner=owner
        ).select_related('item', 'recorded_by')
        items_qs = InventoryItem.objects.filter(owner=owner)
    else:
        records_qs = InventoryRecord.objects.all().select_related('item', 'recorded_by', 'item__owner')
        items_qs = InventoryItem.objects.all().select_related('owner')

    # Filters
    item_id = request.GET.get('item_id')
    record_type = request.GET.get('record_type')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if item_id:
        records_qs = records_qs.filter(item_id=item_id)
    if record_type:
        records_qs = records_qs.filter(record_type=record_type)
    if date_from:
        try:
            records_qs = records_qs.filter(recorded_at__date__gte=date_from)
        except Exception:
            pass
    if date_to:
        try:
            records_qs = records_qs.filter(recorded_at__date__lte=date_to)
        except Exception:
            pass

    currency_symbol = _get_currency_symbol(owner, request.user)

    # Aggregations: cost = unit_price × |quantity_change| for each record
    # NOTE: unit_price alone (ignoring quantity) gives wrong totals — must multiply
    _cost_expr = ExpressionWrapper(
        Abs(F('quantity_change')) * F('unit_price'),
        output_field=DecimalField(max_digits=14, decimal_places=2)
    )
    total_spent = (
        records_qs.exclude(record_type='returned')
        .exclude(unit_price__isnull=True)
        .aggregate(t=Sum(_cost_expr))['t'] or 0
    )
    total_refunds = (
        records_qs.filter(record_type='returned')
        .exclude(unit_price__isnull=True)
        .aggregate(t=Sum(_cost_expr))['t'] or 0
    )
    net_cost = total_spent - total_refunds

    # CSV export
    if request.GET.get('export') == 'csv':
        return _export_csv(records_qs, currency_symbol, total_spent, total_refunds, net_cost)

    # PDF export
    if request.GET.get('export') == 'pdf':
        return _export_pdf(records_qs, currency_symbol, total_spent, total_refunds, net_cost,
                           date_from, date_to)

    # Only pass non-zero values to template
    total_spent = total_spent if total_spent else None
    total_refunds = total_refunds if total_refunds else None
    net_cost = net_cost if net_cost else None

    try:
        per_page = int(request.GET.get('per_page', 50))
        if per_page not in [10, 25, 50, 100]:
            per_page = 50
    except (ValueError, TypeError):
        per_page = 50
    paginator = Paginator(records_qs, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    restaurant_context = get_restaurant_context(request.user, request.session.get('current_restaurant_id'), request)

    context = {
        'page_obj': page_obj,
        'items': items_qs,
        'record_type_choices': InventoryRecord.RECORD_TYPE_CHOICES,
        'filter_item_id': item_id,
        'filter_record_type': record_type,
        'filter_date_from': date_from,
        'filter_date_to': date_to,
        'per_page': per_page,
        'currency_symbol': currency_symbol,
        'total_spent': total_spent,
        'total_refunds': total_refunds,
        'net_cost': net_cost,
        **restaurant_context,
    }
    return render(request, 'inventory/history.html', context)


# ---------------------------------------------------------------------------
# AJAX helpers
# ---------------------------------------------------------------------------

@login_required
def item_detail_ajax(request, item_id):
    """Return JSON with item info and current stock for quick lookup."""
    owner = get_owner_filter(request.user)
    item = _get_item_for_user(item_id, owner, request.user)
    if item is None:
        return JsonResponse({'error': 'Not found'}, status=404)
    return JsonResponse({
        'id': item.id,
        'name': item.name,
        'unit': item.unit,
        'unit_display': item.unit,
        'current_stock': float(item.current_stock),
        'unit_price': float(item.unit_price) if item.unit_price is not None else None,
    })


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_item_for_user(item_id, owner, user):
    """Fetch an InventoryItem enforcing owner scope."""
    if not item_id:
        return None
    try:
        item_id = int(item_id)
        if owner:
            return InventoryItem.objects.get(id=item_id, owner=owner)
        else:
            return InventoryItem.objects.get(id=item_id)
    except (InventoryItem.DoesNotExist, ValueError, TypeError):
        return None


def _export_csv(records_qs, currency_symbol='$', total_spent=0, total_refunds=0, net_cost=0):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="inventory_history_{timezone.now():%Y%m%d}.csv"'
    writer = csv.writer(response)
    # Summary header
    writer.writerow(['INVENTORY COST SUMMARY'])
    writer.writerow(['Total Spent', f'{currency_symbol}{total_spent:.2f}'])
    writer.writerow(['Total Refunds', f'{currency_symbol}{total_refunds:.2f}'])
    net_sign = '-' if net_cost < 0 else ''
    writer.writerow(['Net Cost', f'{net_sign}{currency_symbol}{abs(net_cost):.2f}'])
    writer.writerow([])
    writer.writerow(['Date', 'Item', 'Type', 'Qty Change', 'Unit', 'Cost / Refund', 'Notes', 'Recorded By'])
    for r in records_qs:
        if r.unit_price is not None:
            if r.record_type == 'returned':
                cost_str = f"+{currency_symbol}{float(r.unit_price):.2f} (Refund)"
            else:
                cost_str = f"-{currency_symbol}{float(r.unit_price):.2f}"
        else:
            cost_str = ''
        writer.writerow([
            r.recorded_at.strftime('%Y-%m-%d %H:%M'),
            r.item.name,
            r.get_record_type_display(),
            r.quantity_change,
            r.item.unit,
            cost_str,
            r.notes,
            r.recorded_by.username if r.recorded_by else '',
        ])
    return response


def _export_pdf(records_qs, currency_symbol='$', total_spent=0, total_refunds=0, net_cost=0,
                date_from=None, date_to=None):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="inventory_history_{timezone.now():%Y%m%d}.pdf"'

    buffer = BytesIO()
    # Portrait A4 — rows grow tall automatically when notes are long
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm)
    elements = []
    styles = getSampleStyleSheet()

    # Styles
    title_style = ParagraphStyle('InvTitle', parent=styles['Heading1'], fontSize=18,
                                 spaceAfter=4, alignment=1, textColor=colors.HexColor('#1e3a5f'))
    subtitle_style = ParagraphStyle('InvSub', parent=styles['Normal'], fontSize=9,
                                    spaceAfter=14, alignment=1, textColor=colors.grey)
    section_style = ParagraphStyle('InvSection', parent=styles['Heading2'], fontSize=11,
                                   spaceAfter=6, textColor=colors.HexColor('#1e3a5f'))
    # Cell styles — small text that wraps
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=8, leading=10)
    cell_green = ParagraphStyle('CellGreen', parent=cell_style, textColor=colors.HexColor('#16a34a'))
    cell_red = ParagraphStyle('CellRed', parent=cell_style, textColor=colors.HexColor('#dc2626'))
    cell_muted = ParagraphStyle('CellMuted', parent=cell_style, textColor=colors.HexColor('#94a3b8'))
    header_cell_style = ParagraphStyle('HeaderCell', parent=styles['Normal'], fontSize=8,
                                       leading=10, textColor=colors.white,
                                       fontName='Helvetica-Bold')

    # ── Title ──────────────────────────────────────────────────────────────
    elements.append(Paragraph('INVENTORY HISTORY REPORT', title_style))
    if date_from or date_to:
        date_desc = f"Period: {date_from or '—'} &nbsp;to&nbsp; {date_to or '—'}"
    else:
        date_desc = f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}"
    elements.append(Paragraph(date_desc, subtitle_style))
    elements.append(Spacer(1, 3*mm))

    # ── Cost Summary ───────────────────────────────────────────────────────
    elements.append(Paragraph('Cost Summary', section_style))
    net_sign = '-' if net_cost < 0 else ''
    net_display = f"{net_sign}{currency_symbol}{abs(net_cost):.2f}"
    net_color = colors.HexColor('#16a34a') if net_cost < 0 else colors.HexColor('#1e3a5f')

    # Portrait usable width = 210 - 18 - 18 = 174mm; summary 3-col centred
    sum_w = 174 * mm / 3
    summary_data = [
        [Paragraph('TOTAL SPENT', ParagraphStyle('sh', parent=styles['Normal'], fontSize=8,
                    fontName='Helvetica-Bold', textColor=colors.HexColor('#64748b'), alignment=1)),
         Paragraph('TOTAL REFUNDS', ParagraphStyle('sh2', parent=styles['Normal'], fontSize=8,
                    fontName='Helvetica-Bold', textColor=colors.HexColor('#64748b'), alignment=1)),
         Paragraph('NET COST', ParagraphStyle('sh3', parent=styles['Normal'], fontSize=8,
                    fontName='Helvetica-Bold', textColor=colors.HexColor('#64748b'), alignment=1))],
        [Paragraph(f"{currency_symbol}{total_spent:.2f}",
                   ParagraphStyle('sv', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold',
                                  textColor=colors.HexColor('#dc2626'), alignment=1)),
         Paragraph(f"{currency_symbol}{total_refunds:.2f}",
                   ParagraphStyle('sv2', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold',
                                  textColor=colors.HexColor('#16a34a'), alignment=1)),
         Paragraph(net_display,
                   ParagraphStyle('sv3', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold',
                                  textColor=net_color, alignment=1))],
        [Paragraph('Money paid to suppliers',
                   ParagraphStyle('sd', parent=styles['Normal'], fontSize=7,
                                  textColor=colors.HexColor('#94a3b8'), alignment=1)),
         Paragraph('Money returned by suppliers',
                   ParagraphStyle('sd2', parent=styles['Normal'], fontSize=7,
                                  textColor=colors.HexColor('#94a3b8'), alignment=1)),
         Paragraph('Spent minus refunds',
                   ParagraphStyle('sd3', parent=styles['Normal'], fontSize=7,
                                  textColor=colors.HexColor('#94a3b8'), alignment=1))],
    ]
    summary_table = Table(summary_data, colWidths=[sum_w, sum_w, sum_w])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#e2e8f0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 5*mm))

    # ── Records Table ──────────────────────────────────────────────────────
    elements.append(Paragraph('Transaction Records', section_style))

    # Column widths — total must equal 174mm (portrait A4 with 18mm margins each side)
    # Date(28) + Item(28) + Type(28) + Qty(12) + Unit(18) + Cost(28) + Notes(32) = 174
    col_widths = [28*mm, 28*mm, 28*mm, 12*mm, 18*mm, 28*mm, 32*mm]

    header_row = [
        Paragraph('Date', header_cell_style),
        Paragraph('Item', header_cell_style),
        Paragraph('Type', header_cell_style),
        Paragraph('Qty', ParagraphStyle('hc', parent=header_cell_style, alignment=1)),
        Paragraph('Unit', header_cell_style),
        Paragraph('Cost / Refund', header_cell_style),
        Paragraph('Notes', header_cell_style),
    ]
    data = [header_row]

    records_list = list(records_qs)
    for r in records_list:
        if r.unit_price is not None:
            if r.record_type == 'returned':
                cost_p = Paragraph(f"+{currency_symbol}{float(r.unit_price):.2f} (Refund)", cell_green)
            else:
                cost_p = Paragraph(f"-{currency_symbol}{float(r.unit_price):.2f}", cell_red)
        else:
            cost_p = Paragraph('—', cell_muted)

        data.append([
            Paragraph(r.recorded_at.strftime('%Y-%m-%d %H:%M'), cell_style),
            Paragraph(r.item.name, cell_style),
            Paragraph(r.get_record_type_display(), cell_style),
            Paragraph(str(r.quantity_change),
                      ParagraphStyle('qc', parent=cell_style, alignment=1)),
            Paragraph(r.item.unit, cell_style),
            cost_p,
            Paragraph(r.notes or '—', cell_muted if not r.notes else cell_style),
        ])

    records_table = Table(data, colWidths=col_widths, repeatRows=1)
    # Build row backgrounds (alternating)
    row_bg_cmds = []
    for i in range(1, len(data)):
        bg = colors.white if i % 2 == 1 else colors.HexColor('#f8fafc')
        row_bg_cmds.append(('BACKGROUND', (0, i), (-1, i), bg))

    records_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a5f')),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ] + row_bg_cmds))

    elements.append(records_table)

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response


# ---------------------------------------------------------------------------
# Manage Categories & Units (Settings)
# ---------------------------------------------------------------------------

@login_required
def manage_settings(request):
    """CRUD for the owner's custom inventory categories and units."""
    if not _require_inventory_access(request.user):
        return redirect('admin_panel:admin_dashboard')

    owner = get_owner_filter(request.user)
    item_owner = owner if owner else request.user

    if request.method == 'POST':
        kind   = request.POST.get('kind')      # 'category' or 'unit'
        action = request.POST.get('action')    # 'add', 'edit', 'delete'

        if kind == 'category':
            Model = InventoryCategory
        elif kind == 'unit':
            Model = InventoryUnit
        else:
            return JsonResponse({'success': False, 'error': 'Invalid kind.'})

        if action == 'add':
            name = request.POST.get('name', '').strip()
            if not name:
                return JsonResponse({'success': False, 'error': 'Name is required.'})
            if Model.objects.filter(owner=item_owner, name__iexact=name).exists():
                return JsonResponse({'success': False, 'error': f'"{name}" already exists.'})
            obj = Model.objects.create(owner=item_owner, name=name)
            return JsonResponse({'success': True, 'id': obj.id, 'name': obj.name})

        elif action == 'edit':
            obj_id = request.POST.get('id')
            name   = request.POST.get('name', '').strip()
            if not name:
                return JsonResponse({'success': False, 'error': 'Name is required.'})
            try:
                obj = Model.objects.get(id=obj_id, owner=item_owner)
            except Model.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Not found.'})
            if Model.objects.filter(owner=item_owner, name__iexact=name).exclude(id=obj_id).exists():
                return JsonResponse({'success': False, 'error': f'"{name}" already exists.'})
            old_name = obj.name
            obj.name = name
            obj.save()
            # Keep existing items in sync if the name was renamed
            if kind == 'category':
                InventoryItem.objects.filter(owner=item_owner, category=old_name).update(category=name)
            else:
                InventoryItem.objects.filter(owner=item_owner, unit=old_name).update(unit=name)
            return JsonResponse({'success': True})

        elif action == 'delete':
            obj_id = request.POST.get('id')
            try:
                obj = Model.objects.get(id=obj_id, owner=item_owner)
            except Model.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Not found.'})
            # Count items still using this value
            if kind == 'category':
                in_use = InventoryItem.objects.filter(owner=item_owner, category=obj.name).count()
            else:
                in_use = InventoryItem.objects.filter(owner=item_owner, unit=obj.name).count()
            obj.delete()
            return JsonResponse({'success': True, 'in_use': in_use})

        return JsonResponse({'success': False, 'error': 'Unknown action.'})

    # GET
    if owner:
        categories = InventoryCategory.objects.filter(owner=owner)
        units      = InventoryUnit.objects.filter(owner=owner)
    else:
        categories = InventoryCategory.objects.all().select_related('owner')
        units      = InventoryUnit.objects.all().select_related('owner')

    # Bulk-aggregate item counts to avoid N+1 queries (2 queries total instead of N)
    cat_counts = dict(
        InventoryItem.objects.filter(owner=item_owner)
        .values('category')
        .annotate(n=Count('id'))
        .values_list('category', 'n')
    )
    unit_counts = dict(
        InventoryItem.objects.filter(owner=item_owner)
        .values('unit')
        .annotate(n=Count('id'))
        .values_list('unit', 'n')
    )

    cat_data = [{'obj': cat, 'in_use': cat_counts.get(cat.name, 0)} for cat in categories]
    unit_data = [{'obj': unit, 'in_use': unit_counts.get(unit.name, 0)} for unit in units]

    restaurant_context = get_restaurant_context(request.user, request.session.get('current_restaurant_id'), request)

    return render(request, 'inventory/settings.html', {
        'cat_data': cat_data,
        'unit_data': unit_data,
        **restaurant_context,
    })

