import * as Print from 'expo-print';

// ─── Bill / Receipt ───────────────────────────────────────────────────────────

/**
 * Build HTML for a BILL (pre-payment) or RECEIPT (post-payment).
 * Matches the web's _generate_bill_content / _generate_receipt_content layout.
 *
 * @param {object} opts
 * @param {object} opts.order           - Order object with items, totals, table_number
 * @param {object} [opts.payment]       - Payment object — when null, prints as BILL
 * @param {string} opts.restaurantName  - Restaurant display name
 * @param {string} [opts.currencySymbol]
 * @param {string} [opts.staffName]     - "First Last" of the staff member (optional)
 */
export function buildReceiptHtml({
  order,
  payment = null,
  restaurantName = 'Restaurant',
  currencySymbol = '',
  staffName = '',
}) {
  const isBill = !payment;
  const fmt = (v) => { const n = parseFloat(v); return isNaN(n) ? '0.00' : n.toFixed(2); };

  const now = payment
    ? new Date(payment.created_at || Date.now()).toLocaleString()
    : new Date(order.created_at || Date.now()).toLocaleString();

  const orderNumber = order.order_number || order.id || '';
  const tableNumber = order.table_number || order.table_no || '';
  const items       = order.items || order.order_items || [];

  // Items rows — qty × name | price
  const itemRows = items.map((item) => {
    const name  = item.product_name || item.name || '';
    const qty   = item.quantity || 1;
    const price = parseFloat(item.unit_price || item.price || 0);
    const total = item.total_price != null ? parseFloat(item.total_price) : price * qty;
    return `<tr>
      <td style="padding:4px 2px;">${qty}x ${name}</td>
      <td style="padding:4px 2px;text-align:right;">${currencySymbol}${fmt(total)}</td>
    </tr>`;
  }).join('');

  // Totals
  const subtotal   = parseFloat(order.subtotal   || order.total_amount || 0);
  const taxAmount  = parseFloat(order.tax_amount  || 0);
  const taxRate    = parseFloat(order.tax_rate    || 0);
  const discount   = parseFloat(order.discount_amount || 0);
  const total      = parseFloat(order.total ?? order.total_amount ?? 0);
  const totalPaid  = parseFloat(order.total_paid  || 0);

  const discountRow = discount > 0
    ? `<tr><td style="color:#c0392b;">Discount</td><td style="text-align:right;color:#c0392b;">-${currencySymbol}${fmt(discount)}</td></tr>`
    : '';
  const taxRow = taxAmount > 0
    ? `<tr><td>Tax (${fmt(taxRate)}%)</td><td style="text-align:right;">${currencySymbol}${fmt(taxAmount)}</td></tr>`
    : '';

  // Bill: show partial payments if any
  const partialRows = isBill && totalPaid > 0
    ? `<tr><td>Amount Paid</td><td style="text-align:right;color:#2E7D32;">${currencySymbol}${fmt(totalPaid)}</td></tr>
       <tr><td style="font-weight:bold;color:#C62828;">BALANCE DUE</td>
           <td style="text-align:right;font-weight:bold;color:#C62828;">${currencySymbol}${fmt(Math.max(0, total - totalPaid))}</td></tr>`
    : '';

  // Receipt: payment details
  let paymentSection = '';
  if (payment) {
    const METHOD_LABELS = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher' };
    const methodLabel = METHOD_LABELS[payment.payment_method] || payment.payment_method || '';
    const amtPaid = parseFloat(payment.amount || 0);
    const change  = amtPaid > total ? amtPaid - total : 0;
    const remaining = total > amtPaid ? total - amtPaid : 0;

    paymentSection = `
      <tr><td colspan="2"><hr style="border:none;border-top:1px dashed #999;margin:6px 0;"></td></tr>
      <tr><td colspan="2" style="font-weight:bold;font-size:11px;padding:2px 0;">PAYMENT</td></tr>
      <tr><td>Method</td><td style="text-align:right;">${methodLabel}</td></tr>
      <tr><td>Amount Paid</td><td style="text-align:right;font-weight:bold;">${currencySymbol}${fmt(amtPaid)}</td></tr>
      ${change     > 0 ? `<tr><td>Change</td><td style="text-align:right;">${currencySymbol}${fmt(change)}</td></tr>` : ''}
      ${remaining  > 0 ? `<tr><td style="color:#e67e22;font-weight:bold;">Remaining</td><td style="text-align:right;color:#e67e22;font-weight:bold;">${currencySymbol}${fmt(remaining)}</td></tr>` : ''}
    `;
  }

  // Titles and footers — match web exactly
  const titleLine = isBill ? '** BILL **' : 'RECEIPT / TAX INVOICE';
  const refLine   = payment
    ? `RECEIPT #${payment.id ? String(payment.id).padStart(6, '0') : '------'}`
    : `ORDER #${orderNumber}`;
  const totalLabel  = isBill ? 'TOTAL DUE' : 'TOTAL';
  const footerHtml  = isBill
    ? `<p style="font-weight:bold;">*** THIS IS NOT A RECEIPT ***</p>
       <p>Payment required</p>
       <p style="margin-top:6px;">Thank you for dining with us!</p>`
    : `<p>Thank you for dining with us!</p>
       <p>Please come again</p>`;

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    @page { margin: 5mm; size: 80mm auto; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Courier New', Courier, monospace; font-size: 12px; color: #000; background: #fff; width: 72mm; margin: 0 auto; }
    .header    { text-align: center; padding: 6px 0; border-bottom: 1px dashed #999; margin-bottom: 4px; }
    .header h1 { font-size: 15px; letter-spacing: 1px; text-transform: uppercase; }
    .title-line { text-align: center; font-size: 13px; font-weight: bold; margin: 4px 0 2px; }
    .receipt-no { text-align: center; font-size: 11px; font-weight: bold; margin-bottom: 4px; }
    .meta       { font-size: 10px; margin-bottom: 6px; }
    .meta div   { display: flex; justify-content: space-between; padding: 1px 0; }
    table       { width: 100%; border-collapse: collapse; }
    thead th    { font-size: 10px; text-transform: uppercase; border-bottom: 1px dashed #999; padding: 3px 2px; }
    td          { font-size: 11px; vertical-align: top; }
    .totals td  { padding: 2px; }
    .grand-total td { font-size: 13px; font-weight: bold; border-top: 1px solid #000; padding-top: 4px; }
    .footer     { text-align: center; margin-top: 8px; font-size: 10px; border-top: 1px dashed #999; padding-top: 6px; }
    hr          { border: none; border-top: 1px dashed #999; margin: 6px 0; }
  </style>
</head>
<body>
  <div class="header"><h1>${restaurantName}</h1></div>
  <div class="title-line">${titleLine}</div>
  <div class="receipt-no">${refLine}</div>
  <div class="meta">
    <div><span>Date</span><span>${now}</span></div>
    <div><span>Order</span><span>#${orderNumber}</span></div>
    <div><span>Table</span><span>${tableNumber || 'Takeaway'}</span></div>
    ${staffName ? `<div><span>Staff</span><span>${staffName}</span></div>` : ''}
  </div>
  <hr>
  <table>
    <thead><tr><th style="text-align:left;">Item</th><th style="text-align:right;">Total</th></tr></thead>
    <tbody>${itemRows}</tbody>
  </table>
  <hr>
  <table class="totals">
    <tbody>
      <tr><td>Subtotal</td><td style="text-align:right;">${currencySymbol}${fmt(subtotal)}</td></tr>
      ${discountRow}
      ${taxRow}
      ${partialRows}
      ${paymentSection}
    </tbody>
  </table>
  <table class="totals" style="margin-top:4px;">
    <tbody class="grand-total">
      <tr><td><strong>${totalLabel}</strong></td><td style="text-align:right;"><strong>${currencySymbol}${fmt(total)}</strong></td></tr>
    </tbody>
  </table>
  <div class="footer">${footerHtml}</div>
</body>
</html>`;
}

/** Print bill or receipt via native system print dialog (works offline, any paired printer). */
export async function printReceiptLocal(opts) {
  const html = buildReceiptHtml(opts);
  try {
    await Print.printAsync({ html, base64: false });
    return true;
  } catch (err) {
    if (err?.message?.includes('cancel') || err?.message?.includes('Cancel')) return false;
    throw err;
  }
}

// ─── Order Tickets (KOT / BOT / Buffet / Service) ────────────────────────────

/**
 * Build HTML for a KOT, BOT, Buffet, or Service order ticket.
 * Matches web's _generate_kot_content / _generate_bot_content layout.
 * No prices — kitchen/bar/station staff only need item quantities.
 *
 * @param {object} opts
 * @param {object} opts.order          - Order object with items
 * @param {string} [opts.restaurantName]
 * @param {string|null} [opts.stationFilter] - 'kitchen'|'bar'|'buffet'|'service'|null
 * @param {string} [opts.orderedBy]    - "Name (Role)" of staff who placed the order
 */
export function buildOrderTicketHtml({ order, restaurantName = 'Restaurant', stationFilter = null, orderedBy = '' }) {
  const STATION_TITLES = {
    kitchen: 'KITCHEN ORDER TICKET (KOT)',
    bar:     'BAR ORDER TICKET (BOT)',
    buffet:  'BUFFET ORDER TICKET',
    service: 'SERVICE ORDER TICKET',
  };
  const SECTION_LABELS = {
    kitchen: 'KITCHEN ITEMS:',
    bar:     'BAR ITEMS:',
    buffet:  'BUFFET ITEMS:',
    service: 'SERVICE ITEMS:',
  };
  const STATION_FOOTER_NOTE = {
    kitchen: 'For kitchen preparation only',
    bar:     'For bar preparation only',
    buffet:  'For buffet station only',
    service: 'For service station only',
  };

  const ticketTitle  = (stationFilter && STATION_TITLES[stationFilter])      || 'ORDER TICKET';
  const sectionLabel = (stationFilter && SECTION_LABELS[stationFilter])       || 'ITEMS:';
  const footerNote   = (stationFilter && STATION_FOOTER_NOTE[stationFilter])  || 'For staff use only';

  const now         = new Date(order.created_at || Date.now()).toLocaleString();
  const orderNumber = order.order_number || order.id || '';
  const tableNumber = order.table_number ?? order.table_no ?? '';
  const allItems    = order.items || order.order_items || [];
  const items       = stationFilter
    ? allItems.filter(i => (i.station || i.product?.station || 'kitchen') === stationFilter)
    : allItems;
  const notes       = (order.special_instructions || '').trim();
  const totalItems  = items.length;
  const totalQty    = items.reduce((acc, i) => acc + (i.quantity || 1), 0);

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
    body      { font-family: 'Courier New', Courier, monospace; font-size: 13px; width: 72mm; margin: 0 auto; }
    .header   { text-align: center; padding: 4px 0; border-bottom: 2px solid #000; margin-bottom: 6px; }
    .title    { font-size: 15px; font-weight: bold; letter-spacing: 1px; }
    .rest     { font-size: 11px; margin-top: 2px; }
    .meta     { font-size: 11px; margin-bottom: 6px; }
    .meta div { display: flex; justify-content: space-between; padding: 1px 0; }
    .sec-lbl  { font-size: 11px; font-weight: bold; margin: 4px 0 2px; }
    hr        { border: none; border-top: 1px dashed #000; margin: 6px 0; }
    table     { width: 100%; border-collapse: collapse; }
    .qty      { width: 30px; font-size: 16px; font-weight: bold; vertical-align: top; padding: 3px 4px 3px 0; }
    .item     { font-size: 16px; font-weight: bold; padding: 3px 0; }
    .note     { font-size: 11px; font-weight: normal; font-style: italic; color: #333; }
    .notes-section { font-size: 11px; font-style: italic; border-top: 1px dashed #000; margin-top: 6px; padding-top: 4px; }
    .totals-row    { font-size: 11px; border-top: 1px dashed #000; margin-top: 6px; padding-top: 4px; }
    .footer        { text-align: center; font-size: 10px; border-top: 2px solid #000; margin-top: 6px; padding-top: 4px; }
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
    ${orderedBy ? `<div><span>By</span><span>${orderedBy}</span></div>` : ''}
  </div>
  <hr>
  <div class="sec-lbl">${sectionLabel}</div>
  <hr>
  <table><tbody>${itemRows}</tbody></table>
  ${notes ? `<div class="notes-section">Note: ${notes}</div>` : ''}
  <div class="totals-row">Total Items: ${totalItems} &nbsp;|&nbsp; Total Qty: ${totalQty}</div>
  <div class="footer">
    <p>${footerNote}</p>
    <p style="font-weight:bold;">NOT FOR BILLING</p>
  </div>
</body></html>`;
}

/** Print a KOT/BOT/Buffet/Service ticket via native system print dialog. */
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
