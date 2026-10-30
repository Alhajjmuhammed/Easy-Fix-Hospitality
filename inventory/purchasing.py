"""Suppliers & purchase orders: shared rules (ordering, receiving into stock, payments, sending)."""
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from .models import InventoryItem, InventoryRecord, PurchaseOrder, PurchaseOrderLine, Supplier, SupplierPayment

MAX_LINES = 100


def to_decimal(value, field, minimum=Decimal('0'), allow_zero=True):
    try:
        d = Decimal(str(value).strip().replace(',', ''))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f'Enter a valid {field}.')
    if not d.is_finite() or d >= Decimal('100000000'):
        raise ValidationError(f'Enter a valid {field}.')
    d = d.quantize(Decimal('0.01'))   # round first, so 0.001 counts as zero
    if d < minimum or (d == 0 and not allow_zero):
        raise ValidationError(f'Enter a valid {field}.')
    return d


def parse_date(value, field, required=False):
    if not value:
        if required:
            raise ValidationError(f'Enter the {field}.')
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f'Enter a valid {field}.')


def restaurant_name(owner):
    from restaurant.models_restaurant import Restaurant
    r = Restaurant.for_owner(owner)
    return r.name if r else (owner.restaurant_name or owner.username)


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

def save_supplier(owner, data, supplier=None):
    name = (data.get('name') or '').strip()[:200]
    if not name:
        raise ValidationError('Supplier name is required.')
    email = (data.get('email') or '').strip()[:254]
    if email:
        from django.core.validators import validate_email
        validate_email(email)
    dup = Supplier.objects.filter(owner=owner, name__iexact=name)
    if supplier is not None:
        dup = dup.exclude(pk=supplier.pk)
    if dup.exists():
        raise ValidationError('You already have a supplier with this name.')
    supplier = supplier or Supplier(owner=owner)
    supplier.name = name
    supplier.contact_person = (data.get('contact_person') or '').strip()[:120]
    supplier.phone = (data.get('phone') or '').strip()[:40]
    supplier.email = email
    supplier.address = (data.get('address') or '').strip()[:255]
    supplier.notes = (data.get('notes') or '').strip()[:2000]
    try:
        with transaction.atomic():
            supplier.save()
    except IntegrityError:  # same name saved at the same moment
        raise ValidationError('You already have a supplier with this name.')
    return supplier


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def _parse_lines(owner, item_ids, quantities, prices):
    if not (len(item_ids) == len(quantities) == len(prices)):
        raise ValidationError('The order form was not valid. Please reload the page.')
    items = {i.id: i for i in InventoryItem.objects.filter(owner=owner)}
    lines = []
    for item_id, qty, price in zip(item_ids, quantities, prices):
        if not (item_id or qty or price):
            continue                      # empty row
        try:
            item = items.get(int(item_id))
        except (TypeError, ValueError):
            item = None
        if item is None:
            raise ValidationError('Please choose an item for every line.')
        lines.append((item,
                      to_decimal(qty, f'quantity for {item.name}', allow_zero=False),
                      to_decimal(price or '0', f'price for {item.name}')))
    if not lines:
        raise ValidationError('Add at least one item to the order.')
    if len(lines) > MAX_LINES:
        raise ValidationError(f'An order can have at most {MAX_LINES} lines.')
    return lines


@transaction.atomic
def save_order(owner, user, data, item_ids, quantities, prices, order=None):
    """Create a new order (draft) or update an editable one."""
    try:
        supplier_id = int(data.get('supplier_id') or 0)
    except (TypeError, ValueError):
        supplier_id = 0
    supplier = Supplier.objects.filter(owner=owner, pk=supplier_id).first()
    if supplier is None or (not supplier.is_active and (order is None or order.supplier_id != supplier.id)):
        raise ValidationError('Please choose a supplier.')
    order_date = parse_date(data.get('order_date'), 'order date') or timezone.localdate()
    expected = parse_date(data.get('expected_date'), 'delivery date')
    if expected and expected < order_date:
        raise ValidationError('The delivery date cannot be before the order date.')
    lines = _parse_lines(owner, item_ids, quantities, prices)

    if order is None:
        order = _create_with_number(owner, supplier, user)
    else:
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if not order.is_editable:
            raise ValidationError('This order can no longer be changed.')
        order.supplier = supplier
        order.lines.all().delete()
    order.order_date = order_date
    order.expected_date = expected
    order.notes = (data.get('notes') or '').strip()[:2000]
    new_total = sum((qty * price for _, qty, price in lines), Decimal('0')).quantize(Decimal('0.01'))
    if order.paid_total > new_total:
        raise ValidationError(f'{order.paid_total} has already been paid on this order, so the total '
                              f'cannot go below that. Remove or change the payment first.')
    order.save()
    PurchaseOrderLine.objects.bulk_create([
        PurchaseOrderLine(order=order, item=item, quantity=qty, unit_price=price) for item, qty, price in lines])
    return order


def _create_with_number(owner, supplier, user):
    for _ in range(5):
        number = (PurchaseOrder.objects.filter(owner=owner).aggregate(m=Max('number'))['m'] or 0) + 1
        try:
            with transaction.atomic():
                return PurchaseOrder.objects.create(owner=owner, number=number, supplier=supplier, created_by=user)
        except IntegrityError:
            continue  # someone else took this number at the same moment
    raise ValidationError('Could not create the order. Please try again.')


def _locked(order):
    return PurchaseOrder.objects.select_for_update().select_related('supplier').get(pk=order.pk)


@transaction.atomic
def mark_sent(order):
    order = _locked(order)
    if order.status != 'draft':
        raise ValidationError('Only draft orders can be marked as sent.')
    order.status, order.sent_at = 'sent', timezone.now()
    order.save(update_fields=['status', 'sent_at', 'updated_at'])
    return order


@transaction.atomic
def cancel(order):
    order = _locked(order)
    if order.status not in PurchaseOrder.EDITABLE or order.lines.filter(received_quantity__gt=0).exists():
        raise ValidationError('Only orders with nothing received yet can be cancelled.')
    if order.payments.exists():
        raise ValidationError('This order has payments. Remove them before cancelling.')
    order.status = 'cancelled'
    order.save(update_fields=['status', 'updated_at'])
    return order


@transaction.atomic
def close(order):
    """Part-delivered order where the rest is not coming."""
    order = _locked(order)
    if order.status != 'partial':
        raise ValidationError('Only part-received orders can be closed.')
    order.status = 'closed'
    order.save(update_fields=['status', 'updated_at'])
    return order


@transaction.atomic
def receive(order, quantities, user, note=''):
    """Book a delivery. `quantities` maps line id → quantity arriving now (≤ what is still due).
    Each received line adds stock to inventory at the order price."""
    order = _locked(order)
    if order.status not in PurchaseOrder.RECEIVABLE:
        raise ValidationError('This order cannot receive deliveries.')
    lines = {l.id: l for l in order.lines.select_for_update().select_related('item')}
    arriving = []
    for line_id, raw in quantities.items():
        if raw in (None, ''):
            continue
        line = lines.get(line_id)
        if line is None:
            raise ValidationError('The delivery form was not valid. Please reload the page.')
        qty = to_decimal(raw, f'quantity received for {line.item.name}')
        if qty == 0:
            continue
        if qty > line.remaining:
            raise ValidationError(f'{line.item.name}: only {line.remaining} still to be delivered.')
        arriving.append((line, qty))
    if not arriving:
        raise ValidationError('Enter the quantity that arrived for at least one item.')

    text = f'{order.code} from {order.supplier.name}'
    if note:
        text += f' — {note.strip()[:500]}'
    now = timezone.now()
    for line, qty in arriving:
        line.received_quantity += qty
        line.save(update_fields=['received_quantity'])
        InventoryRecord.objects.create(item=line.item, record_type='received', quantity_change=qty,
                                       unit_price=line.unit_price, notes=text, recorded_by=user,
                                       recorded_at=now, purchase_line=line)
    order.status = 'received' if all(l.remaining == 0 for l in lines.values()) else 'partial'
    if order.sent_at is None:
        order.sent_at = now
    order.save(update_fields=['status', 'sent_at', 'updated_at'])
    return order


@transaction.atomic
def add_payment(order, data, user):
    order = _locked(order)
    if order.status == 'cancelled':
        raise ValidationError('This order is cancelled.')
    amount = to_decimal(data.get('amount'), 'amount', allow_zero=False)
    limit = order.payable_total
    if order.paid_total + amount > limit:
        what = 'the value delivered' if order.is_finished else 'the order total'
        raise ValidationError(f'Payments cannot be more than {what} ({limit}).')
    method = data.get('method') or 'cash'
    if method not in dict(SupplierPayment.METHOD_CHOICES):
        raise ValidationError('Choose how it was paid.')
    paid_on = parse_date(data.get('paid_on'), 'payment date') or timezone.localdate()
    if paid_on > timezone.localdate():
        raise ValidationError('The payment date cannot be in the future.')
    return SupplierPayment.objects.create(order=order, amount=amount, method=method, paid_on=paid_on,
                                          reference=(data.get('reference') or '').strip()[:100], recorded_by=user)


@transaction.atomic
def delete_payment(order, payment_id):
    order = _locked(order)
    try:
        payment = order.payments.get(pk=int(payment_id))
    except (SupplierPayment.DoesNotExist, TypeError, ValueError):
        raise ValidationError('Payment not found.')
    payment.delete()


# ---------------------------------------------------------------------------
# Sending to the supplier
# ---------------------------------------------------------------------------

def _qty(d):
    return f'{d.normalize():f}' if d == d.to_integral() else f'{d:f}'


def share_text(order, currency):
    lines = [f'Purchase order {order.code} — {restaurant_name(order.owner)}',
             f'To: {order.supplier.name}',
             f'Date: {order.order_date:%d %b %Y}']
    if order.expected_date:
        lines.append(f'Please deliver by: {order.expected_date:%d %b %Y}')
    lines.append('')
    for l in order.lines.all():
        unit = f' {l.item.unit}' if l.item.unit else ''
        lines.append(f'• {l.item.name}: {_qty(l.quantity)}{unit} × {currency}{l.unit_price:,.2f} = {currency}{l.line_total:,.2f}')
    lines += ['', f'Total: {currency}{order.ordered_total:,.2f}']
    if order.notes:
        lines += ['', order.notes]
    return '\n'.join(lines)


def build_pdf(order, currency):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=order.code)
    styles = getSampleStyleSheet()
    h = ParagraphStyle('poH', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1e3a5f'))
    small = ParagraphStyle('poS', parent=styles['Normal'], fontSize=9, leading=12)
    cell = ParagraphStyle('poC', parent=styles['Normal'], fontSize=9, leading=11)
    right = ParagraphStyle('poR', parent=cell, alignment=2)
    head = ParagraphStyle('poHd', parent=cell, textColor=colors.white, fontName='Helvetica-Bold')
    s = order.supplier
    e = lambda v: escape(str(v or ''))

    els = [Paragraph('PURCHASE ORDER', h),
           Paragraph(f'<b>{e(restaurant_name(order.owner))}</b>', small),
           Spacer(1, 4 * mm)]
    info = [[Paragraph(f'<b>Order:</b> {order.code}<br/><b>Date:</b> {order.order_date:%d %b %Y}'
                       + (f'<br/><b>Deliver by:</b> {order.expected_date:%d %b %Y}' if order.expected_date else ''), small),
             Paragraph(f'<b>Supplier:</b> {e(s.name)}'
                       + (f'<br/>{e(s.contact_person)}' if s.contact_person else '')
                       + (f'<br/>{e(s.phone)}' if s.phone else '')
                       + (f'<br/>{e(s.email)}' if s.email else '')
                       + (f'<br/>{e(s.address)}' if s.address else ''), small)]]
    t = Table(info, colWidths=[87 * mm, 87 * mm])
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    els += [t, Spacer(1, 6 * mm)]

    rows = [[Paragraph(x, head) for x in ('Item', 'Unit', 'Qty', 'Unit price', 'Total')]]
    for l in order.lines.all():
        rows.append([Paragraph(e(l.item.name), cell), Paragraph(e(l.item.unit), cell),
                     Paragraph(_qty(l.quantity), right), Paragraph(f'{e(currency)}{l.unit_price:,.2f}', right),
                     Paragraph(f'{e(currency)}{l.line_total:,.2f}', right)])
    rows.append(['', '', '', Paragraph('<b>Total</b>', right),
                 Paragraph(f'<b>{e(currency)}{order.ordered_total:,.2f}</b>', right)])
    t = Table(rows, colWidths=[70 * mm, 24 * mm, 20 * mm, 30 * mm, 30 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a5f')),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#e2e8f0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    els.append(t)
    if order.notes:
        els += [Spacer(1, 6 * mm), Paragraph('<b>Notes</b>', small),
                Paragraph(e(order.notes).replace('\n', '<br/>'), small)]
    doc.build(els)
    return buf.getvalue()


def email_configured():
    backend = getattr(settings, 'EMAIL_BACKEND', '')
    if backend.endswith('smtp.EmailBackend'):
        return bool(getattr(settings, 'EMAIL_HOST_USER', '') and getattr(settings, 'EMAIL_HOST_PASSWORD', ''))
    return bool(backend)


def send_email(order, currency, user):
    """Email the PDF to the supplier. Marks a draft as sent."""
    from django.core.mail import EmailMessage
    if not order.supplier.email:
        raise ValidationError('This supplier has no email address. Add one on the Suppliers page.')
    if not email_configured():
        raise ValidationError('Email is not set up on this system yet. Use PDF or Share text instead.')
    name = restaurant_name(order.owner)
    msg = EmailMessage(
        subject=f'Purchase order {order.code} from {name}',
        body=f'Hello {order.supplier.contact_person or order.supplier.name},\n\n'
             f'Please find attached our purchase order {order.code}.\n\n{share_text(order, currency)}\n\n'
             f'Thank you,\n{name}',
        to=[order.supplier.email],
        reply_to=[user.email] if user.email else None,
    )
    msg.attach(f'{order.code}.pdf', build_pdf(order, currency), 'application/pdf')
    try:
        # Short timeout: an unreachable mail server must not hang the web worker
        from django.core.mail import get_connection
        msg.connection = get_connection(timeout=15)
        msg.send(fail_silently=False)
    except Exception as exc:  # SMTP down, wrong password, bad address…
        raise ValidationError(f'The email could not be sent ({exc.__class__.__name__}). Please try again later.')
    if order.status == 'draft':
        mark_sent(order)
