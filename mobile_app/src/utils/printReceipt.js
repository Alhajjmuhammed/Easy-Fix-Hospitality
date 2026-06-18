/**
 * printReceipt.js
 *
 * Generates a styled HTML receipt and opens the native system print dialog
 * via expo-print. Works on any Android/iOS device with any paired printer
 * (Bluetooth, WiFi, USB) — no driver, no PC, no internet required.
 *
 * Usage:
 *   import { printReceiptLocal } from './printReceipt';
 *   await printReceiptLocal({ order, payment, restaurantName, currencySymbol });
 */

import * as Print from 'expo-print';

/**
 * Build a complete HTML receipt string.
 *
 * @param {object} opts
 * @param {object} opts.order           - Order object with items, totals, table_number
 * @param {object} [opts.payment]       - Payment object (optional — for payment receipts)
 * @param {string} opts.restaurantName  - Restaurant display name
 * @param {string} [opts.currencySymbol] - e.g. "TSh" or "$"
 * @returns {string} HTML string
 */
export function buildReceiptHtml({
  order,
  payment = null,
  restaurantName = 'Restaurant',
  currencySymbol = '',
}) {
  const fmt = (v) => {
    const n = parseFloat(v);
    return isNaN(n) ? '0.00' : n.toFixed(2);
  };

  const now = payment
    ? new Date(payment.created_at).toLocaleString()
    : new Date(order.created_at || Date.now()).toLocaleString();

  const orderNumber = order.order_number || order.id || '';
  const tableNumber = order.table_number || order.table_no || '';
  const items = order.items || order.order_items || [];

  // Build items rows
  const itemRows = items
    .map((item) => {
      const name = item.product_name || item.name || '';
      const qty = item.quantity || 1;
      const price = parseFloat(item.unit_price || item.price || 0);
      const total = parseFloat(item.total_price || price * qty);
      return `
        <tr>
          <td style="padding:4px 2px;">${qty}x ${name}</td>
          <td style="padding:4px 2px;text-align:right;">${currencySymbol}${fmt(total)}</td>
        </tr>`;
    })
    .join('');

  // Totals
  const subtotal = parseFloat(order.subtotal || order.total_amount || 0);
  const taxAmount = parseFloat(order.tax_amount || 0);
  const taxRate = parseFloat(order.tax_rate || 0);
  const discount = parseFloat(order.discount_amount || 0);
  const total = parseFloat(order.total ?? order.total_amount ?? 0);

  const discountRow =
    discount > 0
      ? `<tr><td style="color:#c0392b;">Discount</td><td style="text-align:right;color:#c0392b;">-${currencySymbol}${fmt(discount)}</td></tr>`
      : '';

  const taxRow =
    taxAmount > 0
      ? `<tr><td>Tax (${fmt(taxRate)}%)</td><td style="text-align:right;">${currencySymbol}${fmt(taxAmount)}</td></tr>`
      : '';

  // Payment section
  let paymentSection = '';
  if (payment) {
    const METHOD = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher' };
    const method = METHOD[payment.payment_method] || payment.payment_method || '';
    const amtPaid = parseFloat(payment.amount || 0);
    const change = amtPaid > total ? amtPaid - total : 0;
    const remaining = total > amtPaid ? total - amtPaid : 0;

    paymentSection = `
      <tr><td colspan="2"><hr style="border:none;border-top:1px dashed #999;margin:6px 0;"></td></tr>
      <tr><td>Method</td><td style="text-align:right;">${method}</td></tr>
      <tr><td>Amount Paid</td><td style="text-align:right;font-weight:bold;">${currencySymbol}${fmt(amtPaid)}</td></tr>
      ${change > 0 ? `<tr><td>Change</td><td style="text-align:right;">${currencySymbol}${fmt(change)}</td></tr>` : ''}
      ${remaining > 0 ? `<tr><td style="color:#e67e22;font-weight:bold;">Remaining</td><td style="text-align:right;color:#e67e22;font-weight:bold;">${currencySymbol}${fmt(remaining)}</td></tr>` : ''}
    `;
  }

  const receiptNum = payment
    ? `RECEIPT #${String(payment.id).padStart(6, '0')}`
    : `ORDER #${orderNumber}`;

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    @page { margin: 5mm; size: 80mm auto; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Courier New', Courier, monospace;
      font-size: 12px;
      color: #000;
      background: #fff;
      width: 72mm;
      margin: 0 auto;
    }
    .header { text-align: center; padding: 6px 0; border-bottom: 1px dashed #999; margin-bottom: 6px; }
    .header h1 { font-size: 15px; letter-spacing: 1px; text-transform: uppercase; }
    .header p  { font-size: 10px; color: #555; margin-top: 2px; }
    .receipt-no { text-align: center; font-size: 11px; font-weight: bold; margin-bottom: 4px; }
    .meta { font-size: 10px; margin-bottom: 6px; }
    .meta div { display: flex; justify-content: space-between; padding: 1px 0; }
    table { width: 100%; border-collapse: collapse; }
    thead th { font-size: 10px; text-transform: uppercase; border-bottom: 1px dashed #999; padding: 3px 2px; }
    td { font-size: 11px; vertical-align: top; }
    .totals td { padding: 2px; }
    .grand-total td { font-size: 13px; font-weight: bold; border-top: 1px solid #000; padding-top: 4px; margin-top: 4px; }
    .footer { text-align: center; margin-top: 8px; font-size: 10px; border-top: 1px dashed #999; padding-top: 6px; }
    hr { border: none; border-top: 1px dashed #999; margin: 6px 0; }
  </style>
</head>
<body>
  <div class="header">
    <h1>${restaurantName}</h1>
  </div>

  <div class="receipt-no">${receiptNum}</div>

  <div class="meta">
    <div><span>Date</span><span>${now}</span></div>
    <div><span>Order</span><span>#${orderNumber}</span></div>
    <div><span>Table</span><span>${tableNumber || 'Takeaway'}</span></div>
  </div>

  <hr>

  <!-- Items -->
  <table>
    <thead>
      <tr>
        <th style="text-align:left;">Item</th>
        <th style="text-align:right;">Total</th>
      </tr>
    </thead>
    <tbody>
      ${itemRows}
    </tbody>
  </table>

  <hr>

  <!-- Totals -->
  <table class="totals">
    <tbody>
      <tr><td>Subtotal</td><td style="text-align:right;">${currencySymbol}${fmt(subtotal)}</td></tr>
      ${discountRow}
      ${taxRow}
      ${paymentSection}
    </tbody>
  </table>
  <table class="totals" style="margin-top:4px;">
    <tbody class="grand-total">
      <tr><td><strong>TOTAL</strong></td><td style="text-align:right;"><strong>${currencySymbol}${fmt(total)}</strong></td></tr>
    </tbody>
  </table>

  <div class="footer">
    <p>Thank you for dining with us!</p>
    <p>Please come again</p>
  </div>
</body>
</html>`;
}

/**
 * Print a receipt using the native system print dialog.
 * Works offline, no server needed, any paired printer.
 *
 * @param {object} opts - Same as buildReceiptHtml options
 * @returns {Promise<boolean>} true if printed/sent, false if cancelled
 */
export async function printReceiptLocal(opts) {
  const html = buildReceiptHtml(opts);
  try {
    await Print.printAsync({ html, base64: false });
    return true;
  } catch (err) {
    // User cancelled = not an error
    if (err?.message?.includes('cancel') || err?.message?.includes('Cancel')) {
      return false;
    }
    throw err;
  }
}

// ─── Order Ticket (KOT/BOT) ───────────────────────────────────────────────────

/**
 * Build a plain-text style HTML order ticket for KOT/BOT.
 * No prices, no totals — just items, table number, and time.
 * Designed for kitchen / bar staff, 80mm thermal paper.
 */
export function buildOrderTicketHtml({ order, restaurantName = 'Restaurant', stationFilter = null }) {
  const STATION_TITLES = {
    kitchen: 'KOT \u2014 KITCHEN',
    bar:     'BOT \u2014 BAR',
    buffet:  'BUFFET ORDER',
    service: 'SERVICE ORDER',
  };
  const ticketTitle = (stationFilter && STATION_TITLES[stationFilter]) || 'ORDER TICKET';

  const now         = new Date(order.created_at || Date.now()).toLocaleString();
  const orderNumber = order.order_number || order.id || '';
  const tableNumber = order.table_number ?? order.table_no ?? '';
  const allItems    = order.items || order.order_items || [];
  const items       = stationFilter
    ? allItems.filter(i => (i.station || i.product?.station) === stationFilter)
    : allItems;
  const notes       = (order.special_instructions || '').trim();

  const itemRows = items.map((item) => {
    const name = item.product_name || item.name || '';
    const qty  = item.quantity || 1;
    const note = item.special_notes
      ? `<div class="note">&#8627; ${item.special_notes}</div>`
      : '';
    return `<tr><td class="qty">${qty}&times;</td><td class="item">${name}${note}</td></tr>`;
  }).join('');

  return `<!DOCTYPE html>
<html><head>
  <meta charset="UTF-8">
  <style>
    @page { margin: 5mm; size: 80mm auto; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Courier New', Courier, monospace; font-size: 13px; width: 72mm; margin: 0 auto; }
    .header { text-align: center; padding: 4px 0; border-bottom: 2px solid #000; margin-bottom: 6px; }
    .title  { font-size: 20px; font-weight: bold; letter-spacing: 2px; }
    .rest   { font-size: 11px; margin-top: 2px; }
    .meta   { font-size: 11px; margin-bottom: 6px; }
    .meta div { display: flex; justify-content: space-between; padding: 1px 0; }
    hr { border: none; border-top: 1px dashed #000; margin: 6px 0; }
    table { width: 100%; border-collapse: collapse; }
    .qty  { width: 30px; font-size: 16px; font-weight: bold; vertical-align: top; padding: 3px 4px 3px 0; }
    .item { font-size: 16px; font-weight: bold; padding: 3px 0; }
    .note { font-size: 11px; font-weight: normal; font-style: italic; color: #333; }
    .notes-section { font-size: 11px; font-style: italic; border-top: 1px dashed #000; margin-top: 6px; padding-top: 4px; }
  </style>
</head><body>
  <div class="header">
    <div class="title">${ticketTitle}</div>
    <div class="rest">${restaurantName}</div>
  </div>
  <div class="meta">
    <div><span>Order</span><span>#${orderNumber}</span></div>
    <div><span>Table</span><span>${tableNumber || 'Takeaway'}</span></div>
    <div><span>Time </span><span>${now}</span></div>
  </div>
  <hr>
  <table><tbody>${itemRows}</tbody></table>
  ${notes ? `<div class="notes-section">Notes: ${notes}</div>` : ''}
</body></html>`;
}

/**
 * Print an order ticket using the native system print dialog.
 * Works offline — no server needed.
 *
 * @param {object} opts - { order, restaurantName }
 * @returns {Promise<boolean>} true if sent, false if user cancelled
 */
export async function printTicketLocal(opts) {
  const html = buildOrderTicketHtml(opts);
  try {
    await Print.printAsync({ html, base64: false });
    return true;
  } catch (err) {
    if (err?.message?.includes('cancel') || err?.message?.includes('Cancel')) return false;
    throw err;
  }
}
