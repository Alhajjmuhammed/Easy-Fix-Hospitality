/**
 * printer.js — Universal Print Engine
 * =====================================
 * Supports ALL printing scenarios with automatic smart fallback.
 *
 *  Mode 'auto'      → BT Classic SPP → Network → System dialog
 *  Mode 'bluetooth' → BT Classic SPP → (fail) System dialog
 *  Mode 'network'   → Server/Print Client → (fail) System dialog
 *  Mode 'system'    → Native OS print dialog (any paired printer, always works)
 *
 * Bluetooth Classic SPP (silent auto-print, no dialog):
 *   - Requires: npx expo prebuild  (bare workflow, NOT Expo Go)
 *   - Works with: any thermal POS printer paired via Android Bluetooth settings
 *   - iOS: BT Classic blocked by Apple → auto-falls back to system dialog
 *
 * System dialog:
 *   - Works everywhere: Expo Go, custom builds, Android, iOS
 *   - User selects any paired BT/WiFi/USB printer from the OS list
 *   - No driver needed — just pair the printer in device Settings
 *
 * Network:
 *   - Sends job to Django server → Print Client picks up → prints on Windows PC
 *   - Requires WiFi + Print Client running on a Windows machine
 */

import { Platform, PermissionsAndroid } from 'react-native';
import client from '../api/client';
import { printReceiptLocal, buildReceiptHtml, printTicketLocal } from './printReceipt';
import { usePrinterStore } from '../store/usePrinterStore';

// ─── BT Classic SPP helpers ──────────────────────────────────────────────────

// Module-level cache: undefined = not tried yet, null = unavailable, object = loaded
let _btModuleCache;

/**
 * Safely load react-native-bluetooth-escpos-printer.
 * In Expo Go the native modules are null — the library throws TypeError on init.
 * We cache the result so require() is only attempted ONCE; all subsequent calls
 * return the cached value instantly without triggering another throw.
 */
function loadBtEscPos() {
  if (_btModuleCache !== undefined) return _btModuleCache;
  try {
    const mod = require('@brooons/react-native-bluetooth-escpos-printer');
    // Guard: verify native modules actually loaded (not null stubs from Expo Go)
    if (!mod || !mod.BluetoothManager || !mod.BluetoothEscposPrinter) {
      _btModuleCache = null;
      return null;
    }
    _btModuleCache = mod;
    return mod;
  } catch (_) {
    // Expected in Expo Go — silently falls back to system dialog
    _btModuleCache = null;
    return null;
  }
}

/**
 * Check whether BT Classic printing is available on this device/build.
 */
export function isBtClassicAvailable() {
  const mod = loadBtEscPos();
  if (!mod) return false;
  try {
    return typeof mod.BluetoothManager?.scanDevices === 'function';
  } catch (_) {
    return false;
  }
}

/**
 * Request Bluetooth runtime permissions required on Android 12+ (API 31+).
 * On older Android, requests ACCESS_FINE_LOCATION which is needed for BT scanning.
 * On iOS, permissions are declared in Info.plist — no runtime request needed.
 * Returns true if permissions are granted, false otherwise.
 */
async function requestBluetoothPermissions() {
  if (Platform.OS !== 'android') return true;

  try {
    if (Platform.Version >= 31) {
      // Android 12+ — BLUETOOTH_SCAN and BLUETOOTH_CONNECT are runtime permissions
      const results = await PermissionsAndroid.requestMultiple([
        'android.permission.BLUETOOTH_SCAN',
        'android.permission.BLUETOOTH_CONNECT',
      ]);
      const scanGranted    = results['android.permission.BLUETOOTH_SCAN']    === PermissionsAndroid.RESULTS.GRANTED;
      const connectGranted = results['android.permission.BLUETOOTH_CONNECT'] === PermissionsAndroid.RESULTS.GRANTED;
      return scanGranted && connectGranted;
    } else {
      // Android 6–11 — location permission required for BT discovery
      const result = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
      );
      return result === PermissionsAndroid.RESULTS.GRANTED;
    }
  } catch (_) {
    return false;
  }
}

/**
 * Ask the OS to turn Bluetooth on (Android only — shows a system dialog).
 * Resolves when BT is enabled or the user dismisses the dialog.
 */
async function ensureBluetoothEnabled(BluetoothManager) {
  if (Platform.OS !== 'android') return;
  try {
    await BluetoothManager.enableBluetooth();
  } catch (_) {
    // User denied or BT already on — continue either way
  }
}

/**
 * Scan for paired + nearby Bluetooth devices.
 * Returns array of { address: string, name: string }.
 */
export async function scanBluetoothDevices() {
  const mod = loadBtEscPos();
  if (!mod) throw new Error('Bluetooth Classic not available on this build. Run: npx expo prebuild');

  // 1. Runtime permissions — required on Android 12+ before any BT operation
  const granted = await requestBluetoothPermissions();
  if (!granted) {
    throw new Error(
      'Bluetooth permission denied.\n\n' +
      'Go to phone Settings → Apps → Easy Fix → Permissions and allow Nearby Devices (Bluetooth).',
    );
  }

  const { BluetoothManager } = mod;

  // 2. Make sure Bluetooth is switched on
  await ensureBluetoothEnabled(BluetoothManager);

  // 3. Scan — library returns either a JSON string or a plain object depending on version
  const result = await BluetoothManager.scanDevices();
  const parsed = typeof result === 'string' ? JSON.parse(result) : result;
  const found  = Array.isArray(parsed.found)  ? parsed.found  : [];
  const paired = Array.isArray(parsed.paired) ? parsed.paired : [];

  // Merge found + paired, deduplicate by address
  const map = new Map();
  [...found, ...paired].forEach((d) => {
    if (d && d.address) map.set(d.address, { address: d.address, name: d.name || d.address });
  });
  return Array.from(map.values());
}

/**
 * Connect to a BT Classic printer by MAC address.
 */
export async function connectBluetoothPrinter(address) {
  const mod = loadBtEscPos();
  if (!mod) throw new Error('Bluetooth Classic not available on this build.');

  // Runtime permissions required before connecting on Android 12+
  const granted = await requestBluetoothPermissions();
  if (!granted) {
    throw new Error(
      'Bluetooth permission denied. Allow Nearby Devices in phone Settings → Apps → Permissions.',
    );
  }

  await ensureBluetoothEnabled(mod.BluetoothManager);
  await mod.BluetoothManager.connect(address);
}

/**
 * Send a formatted receipt to a BT Classic ESC/POS printer silently.
 */
async function printBtClassic({ order, payment, restaurantName, currencySymbol }) {
  const mod = loadBtEscPos();
  if (!mod) throw new Error('BT Classic module not loaded');

  const { BluetoothEscposPrinter, BluetoothManager } = mod;
  const { bluetoothDevice } = usePrinterStore.getState();

  if (!bluetoothDevice?.address) {
    throw new Error('No Bluetooth printer selected. Go to Settings → Printer Settings to choose a printer.');
  }

  // Connect (ignores "already connected" errors)
  try {
    await BluetoothManager.connect(bluetoothDevice.address);
  } catch (e) {
    const msg = String(e).toLowerCase();
    if (!msg.includes('already') && !msg.includes('connected')) throw e;
  }

  const sym = currencySymbol || '';
  const fmt = (v) => { const n = parseFloat(v); return isNaN(n) ? '0.00' : n.toFixed(2); };
  const W   = 32; // 58mm paper = 32 chars; change to 48 for 80mm
  const pad = (l, r, w = W) => l + ' '.repeat(Math.max(1, w - l.length - r.length)) + r;
  const dash = '─'.repeat(W);

  const items    = order.items || order.order_items || [];
  const total    = parseFloat(order.total ?? order.total_amount ?? 0);
  const subtotal = parseFloat(order.subtotal ?? total);
  const tax      = parseFloat(order.tax_amount ?? 0);
  const discount = parseFloat(order.discount_amount ?? 0);

  const isBill = !payment;
  const A = BluetoothEscposPrinter.ALIGN;

  await BluetoothEscposPrinter.printerInit();

  // Header
  await BluetoothEscposPrinter.printerAlign(A.CENTER);
  await BluetoothEscposPrinter.printText(restaurantName.toUpperCase() + '\n\r', { fonttype: 1, widthtimes: 1, heigthtimes: 1 });
  await BluetoothEscposPrinter.printText((isBill ? '** BILL **' : 'RECEIPT / TAX INVOICE') + '\n\r', { fonttype: 1 });
  await BluetoothEscposPrinter.printerAlign(A.LEFT);
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});

  // Order reference line
  const orderNum = order.order_number || order.id || '';
  const tableNo  = order.table_number ?? order.table_no ?? 'Takeaway';
  const dateStr  = new Date((payment?.created_at || order.created_at || Date.now())).toLocaleString();
  await BluetoothEscposPrinter.printerAlign(A.CENTER);
  if (!isBill && payment?.id) {
    await BluetoothEscposPrinter.printText(`RECEIPT #${String(payment.id).padStart(6, '0')}\n\r`, { fonttype: 1 });
  } else {
    await BluetoothEscposPrinter.printText(`ORDER #${orderNum}\n\r`, { fonttype: 1 });
  }
  await BluetoothEscposPrinter.printerAlign(A.LEFT);
  await BluetoothEscposPrinter.printText(pad('Order:', `#${orderNum}`) + '\n\r', {});
  await BluetoothEscposPrinter.printText(pad('Table:', String(tableNo)) + '\n\r', {});
  await BluetoothEscposPrinter.printText(`Date : ${dateStr}\n\r`, {});
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});

  // Items
  await BluetoothEscposPrinter.printText(pad('ITEM', 'PRICE') + '\n\r', { fonttype: 1 });
  for (const item of items) {
    const name   = String(item.product_name || item.name || '').substring(0, W - 10);
    const qty    = item.quantity || 1;
    const price  = parseFloat(item.total_price ?? item.unit_price * qty ?? 0);
    await BluetoothEscposPrinter.printText(pad(`${qty}x ${name}`, `${sym}${fmt(price)}`) + '\n\r', {});
  }
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});

  // Totals
  await BluetoothEscposPrinter.printText(pad('Subtotal:', `${sym}${fmt(subtotal)}`) + '\n\r', {});
  if (discount > 0) await BluetoothEscposPrinter.printText(pad('Discount:', `-${sym}${fmt(discount)}`) + '\n\r', {});
  if (tax > 0)      await BluetoothEscposPrinter.printText(pad('Tax:', `${sym}${fmt(tax)}`) + '\n\r', {});

  // Bill: partial payment rows
  const totalPaid = parseFloat(order.total_paid || 0);
  if (isBill && totalPaid > 0) {
    await BluetoothEscposPrinter.printText(pad('Amount Paid:', `${sym}${fmt(totalPaid)}`) + '\n\r', {});
    await BluetoothEscposPrinter.printText(pad('BALANCE DUE:', `${sym}${fmt(Math.max(0, total - totalPaid))}`) + '\n\r', { fonttype: 1 });
  }

  await BluetoothEscposPrinter.printText(dash + '\n\r', {});
  const totalLabel = isBill ? 'TOTAL DUE:' : 'TOTAL:';
  await BluetoothEscposPrinter.printText(pad(totalLabel, `${sym}${fmt(total)}`) + '\n\r', { fonttype: 1, widthtimes: 1, heigthtimes: 1 });

  // Receipt: payment section
  if (!isBill && payment) {
    await BluetoothEscposPrinter.printText(dash + '\n\r', {});
    const METHOD_LABELS = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher' };
    const methodLabel = METHOD_LABELS[payment.payment_method] || payment.payment_method || '';
    const amtPaid = parseFloat(payment.amount || 0);
    const change  = amtPaid > total ? amtPaid - total : 0;
    await BluetoothEscposPrinter.printText(pad('Payment:', methodLabel) + '\n\r', {});
    await BluetoothEscposPrinter.printText(pad('Amount Paid:', `${sym}${fmt(amtPaid)}`) + '\n\r', { fonttype: 1 });
    if (change > 0) await BluetoothEscposPrinter.printText(pad('Change:', `${sym}${fmt(change)}`) + '\n\r', {});
  }

  // Footer
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});
  await BluetoothEscposPrinter.printerAlign(A.CENTER);
  if (isBill) {
    await BluetoothEscposPrinter.printText('*** THIS IS NOT A RECEIPT ***\n\r', { fonttype: 1 });
    await BluetoothEscposPrinter.printText('Payment required\n\r', {});
    await BluetoothEscposPrinter.printText('Thank you for dining with us!\n\r', {});
  } else {
    await BluetoothEscposPrinter.printText('Thank you for dining with us!\n\r', {});
    await BluetoothEscposPrinter.printText('Please come again\n\r', {});
  }
  await BluetoothEscposPrinter.printText('\n\r\n\r\n\r', {});

  await BluetoothEscposPrinter.printAndFeed(3);
  try { await BluetoothEscposPrinter.cutOnePoint(); } catch (_) {}

  // Cash drawer kick after receipt (ESC p 0 25 250)
  if (!isBill) {
    try {
      const ESC_P = `\x1B\x70\x00\x19\xFA`;
      await BluetoothEscposPrinter.printText(ESC_P, {});
    } catch (_) { /* cash drawer is optional */ }
  }
}

// ─── Network printing ─────────────────────────────────────────────────────────

async function printNetwork(orderId) {
  await client.post(`/orders/${orderId}/print-bill/`);
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Print a receipt using the user's selected mode + smart fallback.
 *
 * Fallback chain:
 *   'auto'      → BT Classic SPP → Network (if orderId) → System dialog
 *   'bluetooth' → BT Classic SPP → System dialog
 *   'network'   → Network → System dialog
 *   'system'    → System dialog (no fallback needed)
 *
 * @param {{
 *   orderId?: number,
 *   order: object,
 *   payment?: object,
 *   restaurantName?: string,
 *   currencySymbol?: string,
 * }} params
 * @returns {Promise<boolean>} true = printed successfully, false = user cancelled dialog
 */
export async function printReceipt({
  orderId,
  order,
  payment       = null,
  restaurantName = '',
  currencySymbol = '',
} = {}) {
  const { mode } = usePrinterStore.getState();

  // System dialog — works everywhere, use directly
  if (mode === 'system') {
    return printReceiptLocal({ order, payment, restaurantName, currencySymbol });
  }

  // Network mode — try server, fall back to system dialog
  if (mode === 'network') {
    if (orderId) {
      try {
        await printNetwork(orderId);
        return true;
      } catch (netErr) {
        console.warn('[Printer] Network failed → system dialog:', netErr?.message);
      }
    }
    return printReceiptLocal({ order, payment, restaurantName, currencySymbol });
  }

  // Bluetooth or Auto mode — try BT Classic SPP first
  if (mode === 'bluetooth' || mode === 'auto') {
    if (isBtClassicAvailable()) {
      try {
        await printBtClassic({ order, payment, restaurantName, currencySymbol });
        return true;
      } catch (btErr) {
        console.warn('[Printer] BT Classic failed → fallback:', btErr?.message);
      }
    } else {
      console.warn('[Printer] BT Classic not available (Expo Go or module missing)');
    }

    // Auto: also try network before giving up
    if (mode === 'auto' && orderId) {
      try {
        await printNetwork(orderId);
        return true;
      } catch (_) {}
    }

    return printReceiptLocal({ order, payment, restaurantName, currencySymbol });
  }

  // Catch-all fallback
  return printReceiptLocal({ order, payment, restaurantName, currencySymbol });
}

// ─── BT Classic ticket (KOT/BOT — no prices, no cash drawer) ────────────────

async function _printTicketBtClassic({ order, restaurantName, stationFilter = null }) {
  const mod = loadBtEscPos();
  if (!mod) throw new Error('BT Classic module not loaded');

  const { BluetoothEscposPrinter, BluetoothManager } = mod;
  const { bluetoothDevice } = usePrinterStore.getState();

  if (!bluetoothDevice?.address) {
    throw new Error('No Bluetooth printer selected. Go to Settings → Printer Settings.');
  }

  // Connect (ignores "already connected" errors)
  try {
    await BluetoothManager.connect(bluetoothDevice.address);
  } catch (e) {
    const msg = String(e).toLowerCase();
    if (!msg.includes('already') && !msg.includes('connected')) throw e;
  }

  const BT_STATION_TITLES = {
    kitchen: 'KITCHEN ORDER TICKET (KOT)',
    bar:     'BAR ORDER TICKET (BOT)',
    buffet:  'BUFFET ORDER TICKET',
    service: 'SERVICE ORDER TICKET',
  };
  const BT_STATION_FOOTER = {
    kitchen: 'For kitchen preparation only',
    bar:     'For bar preparation only',
    buffet:  'For buffet station only',
    service: 'For service station only',
  };
  const ticketTitle = (stationFilter && BT_STATION_TITLES[stationFilter]) || 'ORDER TICKET';
  const footerNote  = (stationFilter && BT_STATION_FOOTER[stationFilter]) || 'For staff use only';

  const W   = 32; // 58mm = 32 chars; change to 48 for 80mm
  const pad = (l, r, w = W) => l + ' '.repeat(Math.max(1, w - l.length - r.length)) + r;
  const dash = '-'.repeat(W);
  const allItems = order.items || order.order_items || [];
  const items = stationFilter
    ? allItems.filter(i => (i.station || i.product?.station) === stationFilter)
    : allItems;
  const A = BluetoothEscposPrinter.ALIGN;

  await BluetoothEscposPrinter.printerInit();

  // Header
  await BluetoothEscposPrinter.printerAlign(A.CENTER);
  await BluetoothEscposPrinter.printText(ticketTitle + '\n\r', { fonttype: 1, widthtimes: 1, heigthtimes: 1 });
  await BluetoothEscposPrinter.printText(restaurantName.toUpperCase() + '\n\r', {});
  await BluetoothEscposPrinter.printerAlign(A.LEFT);
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});

  // Order info
  const orderNum = order.order_number || order.id || '';
  const tableNo  = order.table_number ?? order.table_no ?? 'Takeaway';
  const timeStr  = new Date(order.created_at || Date.now()).toLocaleTimeString();
  await BluetoothEscposPrinter.printText(pad('Order:', `#${orderNum}`) + '\n\r', {});
  await BluetoothEscposPrinter.printText(pad('Table:', String(tableNo)) + '\n\r', {});
  await BluetoothEscposPrinter.printText(`Time : ${timeStr}\n\r`, {});
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});

  // Items — bold, no prices
  for (const item of items) {
    const name = String(item.product_name || item.name || '').substring(0, W - 5);
    const qty  = item.quantity || 1;
    await BluetoothEscposPrinter.printText(`${qty}x  ${name}\n\r`, { fonttype: 1 });
    if (item.special_notes) {
      await BluetoothEscposPrinter.printText(`  -> ${item.special_notes}\n\r`, {});
    }
  }

  // Notes / special instructions
  const notes = (order.special_instructions || '').trim();
  if (notes) {
    await BluetoothEscposPrinter.printText(dash + '\n\r', {});
    await BluetoothEscposPrinter.printText(`Notes: ${notes}\n\r`, {});
  }

  // Totals line + station footer
  const totalItems = items.length;
  const totalQty   = items.reduce((acc, i) => acc + (i.quantity || 1), 0);
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});
  await BluetoothEscposPrinter.printText(`Total Items: ${totalItems} | Total Qty: ${totalQty}\n\r`, {});
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});
  await BluetoothEscposPrinter.printerAlign(A.CENTER);
  await BluetoothEscposPrinter.printText(footerNote + '\n\r', {});
  await BluetoothEscposPrinter.printText('NOT FOR BILLING\n\r', { fonttype: 1 });

  // Feed and cut — NO cash drawer (KOT/BOT don't open the drawer)
  await BluetoothEscposPrinter.printText('\n\r\n\r\n\r', {});
  await BluetoothEscposPrinter.printAndFeed(3);
  try { await BluetoothEscposPrinter.cutOnePoint(); } catch (_) {}
}

/**
 * Print an order ticket (KOT/BOT) using the user's selected mode.
 *
 * Called right after order placement when `localKotBot` is enabled in
 * Printer Settings. Does NOT open the cash drawer. No prices — kitchen
 * and bar staff only need to see item quantities.
 *
 * Fallback chain:
 *   'auto' / 'bluetooth' → BT Classic SPP → System dialog
 *   'network' / 'system' → System dialog
 *
 * @param {object} order          - Order object returned by the API
 * @param {string} restaurantName
 * @returns {Promise<boolean>}
 */
export async function printOrderTicket(order, restaurantName = '', stationFilter = null) {
  const { mode } = usePrinterStore.getState();
  const opts = { order, restaurantName, stationFilter };

  // Bluetooth / Auto → try BT Classic first, fall back to system dialog
  if (mode === 'bluetooth' || mode === 'auto') {
    if (isBtClassicAvailable()) {
      try {
        await _printTicketBtClassic(opts);
        return true;
      } catch (btErr) {
        console.warn('[Printer] Ticket BT failed → system dialog:', btErr?.message);
      }
    }
  }

  // Network mode: server queue already handles KOT/BOT when X-Local-Print is NOT set;
  // if we reach here it means server queue is skipped, so system dialog is the fallback.
  return printTicketLocal(opts);
}

// Re-export for screens that use them directly
export { printReceiptLocal as printReceiptSystem } from './printReceipt';
export { buildReceiptHtml }                        from './printReceipt';
