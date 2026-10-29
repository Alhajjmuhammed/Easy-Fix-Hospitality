import { Linking } from 'react-native';

/** Plain-text receipt — same lines as the web "Share on WhatsApp" (orders/share.py). */
export function buildReceiptText(order, restaurantName, format) {
  const lines = [`*${restaurantName || 'Restaurant'}*`, `Receipt - Order #${order.order_number || order.id}`];
  if (order.created_at) lines.push(new Date(order.created_at).toLocaleString());
  const tableNo = order.table_number && order.table_number !== 'N/A' ? order.table_number : null;
  lines.push(tableNo ? `Table ${tableNo}` : (order.order_type === 'delivery' ? 'Delivery' : order.order_type === 'pickup' ? 'Pickup' : ''));
  lines.push('');
  for (const item of order.items || []) {
    const amount = item.total_price ?? (parseFloat(item.unit_price || 0) * (item.quantity || 0));
    lines.push(`${item.quantity} x ${item.product_name || item.name || 'Item'} - ${format(amount)}`);
  }
  lines.push('');
  lines.push(`Subtotal: ${format(order.subtotal ?? order.total_amount ?? 0)}`);
  if (parseFloat(order.tax_amount) > 0) lines.push(`Tax: ${format(order.tax_amount)}`);
  if (parseFloat(order.delivery_fee) > 0) lines.push(`Delivery fee: ${format(order.delivery_fee)}`);
  const total = parseFloat(order.total ?? order.total_amount ?? 0);
  lines.push(`*Total: ${format(total)}*`);
  const paid = parseFloat(order.total_paid || 0);
  if (paid > 0) {
    lines.push(`Paid: ${format(paid)}`);
    if (total - paid > 0.004) lines.push(`Balance due: ${format(total - paid)}`);
  }
  lines.push('', 'Thank you!');
  return lines.filter((l, i) => l !== '' || lines[i - 1] !== '').join('\n');
}

/**
 * Open WhatsApp with the text filled in (free). A phone number is only used when it is in
 * international form (+255...), otherwise WhatsApp lets the user pick the contact.
 */
export async function shareOnWhatsApp(text, phone = '') {
  const p = String(phone || '').trim();
  const digits = p.startsWith('+') ? p.replace(/\D/g, '') : '';
  const target = digits.length >= 8 ? digits : '';
  await Linking.openURL(`https://wa.me/${target}?text=${encodeURIComponent(text)}`);
}
