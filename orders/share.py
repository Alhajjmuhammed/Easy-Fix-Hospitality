"""Plain-text receipt for sharing on WhatsApp (free: opens WhatsApp with the text filled in)."""
import re
from decimal import Decimal
from urllib.parse import quote

from django.db.models import Sum
from django.utils import timezone


def _restaurant_name(order):
    table = order.table_info
    if table is not None and table.restaurant_id:
        return table.restaurant.name
    owner = order.get_owner()
    return (owner.restaurant_name or owner.username) if owner else 'Restaurant'


def receipt_share_text(order, currency_symbol, use_decimals=True):
    def money(value):
        amount = Decimal(str(value or 0))
        return f"{currency_symbol}{amount:,.2f}" if use_decimals else f"{currency_symbol}{amount:,.0f}"

    lines = [f"*{_restaurant_name(order)}*", f"Receipt - Order #{order.order_number}"]
    lines.append(timezone.localtime(order.created_at).strftime('%d/%m/%Y %H:%M'))
    if order.table_info_id:
        lines.append(f"Table {order.table_info.tbl_no}")
    else:
        lines.append(order.get_order_type_display())
    lines.append('')
    for item in order.order_items.select_related('product'):
        name = item.product.name if item.product else 'Item'
        lines.append(f"{item.quantity} x {name} - {money(item.get_subtotal())}")
    lines.append('')
    lines.append(f"Subtotal: {money(order.get_subtotal())}")
    tax = order.get_tax_amount()
    if tax > 0:
        lines.append(f"Tax: {money(tax)}")
    if order.delivery_fee and order.delivery_fee > 0:
        lines.append(f"Delivery fee: {money(order.delivery_fee)}")
    total = order.get_total()
    lines.append(f"*Total: {money(total)}*")
    paid = order.payments.filter(is_voided=False).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    if paid > 0:
        lines.append(f"Paid: {money(paid)}")
        if total - paid > 0:
            lines.append(f"Balance due: {money(total - paid)}")
    lines.append('')
    lines.append('Thank you!')
    return '\n'.join(lines)


def whatsapp_url(text, phone=''):
    """wa.me link. A phone is only used when given in international form (+255...); otherwise
    WhatsApp opens and the user picks the contact."""
    digits = ''
    phone = (phone or '').strip()
    if phone.startswith('+'):
        digits = re.sub(r'\D', '', phone)
    return f"https://wa.me/{digits}?text={quote(text)}" if len(digits) >= 8 else f"https://wa.me/?text={quote(text)}"
