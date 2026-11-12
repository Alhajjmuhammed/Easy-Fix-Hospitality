/**
 * printer.js — Universal Print Engine
 * =====================================
 * Supports ALL printing scenarios with automatic smart fallback.
 *
 *  Mode 'auto'      → BT Classic SPP → Network → System dialog
 *  Mode 'bluetooth' → BT Classic SPP → (fail) returns false, NO system dialog
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
import { printReceiptLocal, printTicketLocal } from './printReceipt';
import { usePrinterStore, settingsReadyPromise } from '../store/usePrinterStore';

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

// Messages thrown to the screens (translated there with t()).
export const BT_MSG_OFF    = 'Bluetooth is off. Turn on Bluetooth and try again.';
export const BT_MSG_NO_CONNECT = 'Could not connect to the printer. Make sure it is switched on, has paper and is close to the phone.';
export const BT_MSG_DENIED = 'Bluetooth permission denied. Allow Nearby Devices in phone Settings → Apps → Easy Fix → Permissions.';

// One Bluetooth job at a time: the library keeps a single pending connect, so two prints
// at once (e.g. kitchen + bar tickets) could hang or interleave on the paper.
let _btQueue = Promise.resolve();
function runBtJob(fn) {
  const run = _btQueue.then(fn, fn);
  _btQueue = run.catch(() => {});
  return run;
}
const BT_CONNECT_TIMEOUT_MS = 15000;
function withTimeout(promise, ms, message) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); }),
  ]).finally(() => clearTimeout(timer));
}
/** Connect to the printer; an already-open connection to it is fine. */
async function connectOrThrow(BluetoothManager, address) {
  try {
    await withTimeout(BluetoothManager.connect(address), BT_CONNECT_TIMEOUT_MS, '__bt_timeout__');
  } catch (e) {
    const msg = String(e?.message || e).toLowerCase();
    if (msg.includes('already') || (msg.includes('connected') && !msg.includes('unable'))) return;
    if (msg.includes('__bt_timeout__')) {
      // Stop the half-open attempt now: otherwise its late failure would reject the NEXT
      // print's connect (the library keeps only one pending connect).
      try { await BluetoothManager.disconnect(address); } catch (_) {}
      await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error(BT_MSG_NO_CONNECT);
  }
}

/** Library results come as JSON strings or objects; return [{ address, name }]. */
function normalizeDevices(list) {
  const out = [];
  (Array.isArray(list) ? list : []).forEach((d) => {
    let o = d;
    if (typeof d === 'string') { try { o = JSON.parse(d); } catch (_) { o = null; } }
    if (o && o.address) out.push({ address: o.address, name: o.name || o.address });
  });
  return out;
}

/** Merge device lists, first occurrence wins, no duplicate addresses. */
export function mergeDevices(...lists) {
  const map = new Map();
  lists.flat().forEach((d) => { if (d && d.address && !map.has(d.address)) map.set(d.address, d); });
  return Array.from(map.values());
}

/**
 * Printers already paired in the phone's Bluetooth settings.
 * Needs no device search and no Location, so it works on every phone. A thermal
 * printer is normally paired once in phone Settings → Bluetooth (PIN 0000 or 1234).
 * Turns Bluetooth on first (Android asks the user).
 */
export async function getPairedPrinters() {
  const mod = loadBtEscPos();
  if (!mod) throw new Error('Bluetooth Classic not available on this build. Run: npx expo prebuild');
  if (!(await requestBluetoothPermissions())) throw new Error(BT_MSG_DENIED);
  let list;
  try {
    // Resolves with the paired devices once Bluetooth is on; rejects if the user keeps it off.
    list = await mod.BluetoothManager.enableBluetooth();
  } catch (_) {
    throw new Error(BT_MSG_OFF);
  }
  return normalizeDevices(list);
}

/**
 * Search for nearby printers that are not paired yet. Optional extra: Android only lets
 * the search start when Location is on and allowed (otherwise the library reports
 * "NOT_STARTED"). Never throws — returns { devices, started }.
 */
export async function discoverNearbyPrinters() {
  const mod = loadBtEscPos();
  if (!mod) return { devices: [], started: false };
  if (Platform.OS === 'android') {
    try {
      const loc = PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION;
      if (!(await PermissionsAndroid.check(loc))) await PermissionsAndroid.request(loc);
    } catch (_) { /* optional */ }
  }
  try {
    // Not in the print queue (a connect cancels the search itself). Android stops a search
    // by itself after ~12 s; the timeout only guards against a lost callback.
    const result = await withTimeout(mod.BluetoothManager.scanDevices(), 25000, 'scan timeout');
    const parsed = typeof result === 'string' ? JSON.parse(result) : (result || {});
    return { devices: mergeDevices(normalizeDevices(parsed.paired), normalizeDevices(parsed.found)), started: true };
  } catch (_) {
    return { devices: [], started: false };
  }
}

/**
 * Paired printers plus any nearby ones. Only fails when Bluetooth itself is
 * unavailable, off or not allowed — a failed nearby search just returns the paired list.
 */
export async function scanBluetoothDevices() {
  const paired = await getPairedPrinters();
  const { devices } = await discoverNearbyPrinters();
  return mergeDevices(paired, devices);
}

/**
 * True when this phone itself should print (Bluetooth printer / system dialog) instead of
 * sending the job to the server's Windows Print Client — used by the Reprint and station
 * Print buttons, online or offline. Network and Auto keep the Print Client for these
 * (Auto has the PC as its fallback when the Bluetooth printer is unreachable).
 */
export function prefersPhonePrinter() {
  const { mode } = usePrinterStore.getState();
  return mode === 'bluetooth' || mode === 'system';
}

/**
 * Connect to a BT Classic printer by MAC address.
 */
export function connectBluetoothPrinter(address) {
  return runBtJob(() => _connectBluetoothPrinterNow(address));
}

async function _connectBluetoothPrinterNow(address) {
  const mod = loadBtEscPos();
  if (!mod) throw new Error('Bluetooth Classic not available on this build.');

  // Runtime permissions required before connecting on Android 12+
  if (!(await requestBluetoothPermissions())) throw new Error(BT_MSG_DENIED);
  try {
    await mod.BluetoothManager.enableBluetooth();
  } catch (_) {
    throw new Error(BT_MSG_OFF);
  }
  await connectOrThrow(mod.BluetoothManager, address);
}

/**
 * Send a formatted receipt to a BT Classic ESC/POS printer silently.
 */
function printBtClassic(opts) {
  return runBtJob(() => _printBtClassicNow(opts));
}

async function _printBtClassicNow({ order, payment, restaurantName, currencySymbol, staffName = '', decimals = 2 }) {
  const mod = loadBtEscPos();
  if (!mod) throw new Error('BT Classic module not loaded');

  const { BluetoothEscposPrinter, BluetoothManager } = mod;
  const { bluetoothDevice } = usePrinterStore.getState();

  if (!bluetoothDevice?.address) {
    throw new Error('No Bluetooth printer selected. Go to Settings → Printer Settings to choose a printer.');
  }

  // Connect (an already-open connection is fine; gives up after 15 s)
  await connectOrThrow(BluetoothManager, bluetoothDevice.address);

  const sym = currencySymbol || '';
  const fmt = (v) => { const n = parseFloat(v); return isNaN(n) ? (0).toFixed(decimals) : n.toFixed(decimals); };
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
  if (!isBill) {
    const receiptRef = payment?.id
      ? `RECEIPT #${String(payment.id).padStart(6, '0')}`
      : `RECEIPT #------`;
    await BluetoothEscposPrinter.printText(`${receiptRef}\n\r`, { fonttype: 1 });
  } else {
    await BluetoothEscposPrinter.printText(`ORDER #${orderNum}\n\r`, { fonttype: 1 });
  }
  await BluetoothEscposPrinter.printerAlign(A.LEFT);
  await BluetoothEscposPrinter.printText(pad('Order:', `#${orderNum}`) + '\n\r', {});
  await BluetoothEscposPrinter.printText(pad('Table:', String(tableNo)) + '\n\r', {});
  await BluetoothEscposPrinter.printText(`Date : ${dateStr}\n\r`, {});
  if (staffName) await BluetoothEscposPrinter.printText(pad('Staff:', staffName) + '\n\r', {});
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});

  // Items
  await BluetoothEscposPrinter.printText(pad('ITEM', 'PRICE') + '\n\r', { fonttype: 1 });
  for (const item of items) {
    const name   = String(item.product_name || item.name || '').substring(0, W - 10);
    const qty    = item.quantity || 1;
    const price  = parseFloat(
      item.total_price ??
      (item.unit_price != null ? item.unit_price * qty : null) ??
      (item.price != null ? item.price * qty : 0)
    ) || 0;
    await BluetoothEscposPrinter.printText(pad(`${qty}x ${name}`, `${sym}${fmt(price)}`) + '\n\r', {});
  }
  await BluetoothEscposPrinter.printText(dash + '\n\r', {});

  // Totals
  await BluetoothEscposPrinter.printText(pad('Subtotal:', `${sym}${fmt(subtotal)}`) + '\n\r', {});
  if (discount > 0) await BluetoothEscposPrinter.printText(pad('Discount:', `-${sym}${fmt(discount)}`) + '\n\r', {});
  if (tax > 0)      await BluetoothEscposPrinter.printText(pad('Tax:', `${sym}${fmt(tax)}`) + '\n\r', {});
  const deliveryFee = parseFloat(order.delivery_fee ?? 0);
  if (deliveryFee > 0) await BluetoothEscposPrinter.printText(pad('Delivery fee:', `${sym}${fmt(deliveryFee)}`) + '\n\r', {});

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
    const METHOD_LABELS = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher', loyalty: 'Loyalty points' };
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
  const { data } = await client.post(`/orders/${orderId}/print-bill/`);
  if (data && data.success === false) throw new Error(data.message || 'Print failed');
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Print a receipt using the user's selected mode + smart fallback.
 *
 * Fallback chain:
 *   'auto'      → BT Classic SPP → Network (if orderId) → System dialog
 *   'bluetooth' → BT Classic SPP → (fail) returns false, NO system dialog
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
  payment        = null,
  restaurantName = '',
  currencySymbol = '',
  staffName      = '',
  decimals       = 2,
} = {}) {
  // Ensure persisted settings are applied before reading mode/device (cold-start race guard)
  await settingsReadyPromise;
  const { mode } = usePrinterStore.getState();

  // System dialog — works everywhere, use directly
  if (mode === 'system') {
    return printReceiptLocal({ order, payment, restaurantName, currencySymbol, staffName });
  }

  // Network mode — try server, fall back to system dialog
  if (mode === 'network') {
    if (orderId) {
      try {
        await printNetwork(orderId);
        return true;
      } catch (netErr) {
        if (__DEV__) console.warn('[Printer] Network failed → system dialog:', netErr?.message);
      }
    }
    return printReceiptLocal({ order, payment, restaurantName, currencySymbol, staffName });
  }

  // Bluetooth or Auto mode — try BT Classic SPP first
  if (mode === 'bluetooth' || mode === 'auto') {
    if (isBtClassicAvailable()) {
      try {
        await printBtClassic({ order, payment, restaurantName, currencySymbol, staffName, decimals });
        return true;
      } catch (btErr) {
        if (__DEV__) console.warn('[Printer] BT Classic failed → fallback:', btErr?.message);
      }
    } else {
      if (__DEV__) console.warn('[Printer] BT Classic not available (Expo Go or module missing)');
    }

    // Auto: also try network before giving up
    if (mode === 'auto' && orderId) {
      try {
        await printNetwork(orderId);
        return true;
      } catch (_) {}
    }

    // Strict bluetooth mode: never show native OS dialog — caller must handle failure
    if (mode === 'bluetooth') {
      if (__DEV__) console.warn('[Printer] Bluetooth mode: refusing native dialog fallback');
      return false;
    }

    return printReceiptLocal({ order, payment, restaurantName, currencySymbol, staffName });
  }

  // Catch-all fallback
  return printReceiptLocal({ order, payment, restaurantName, currencySymbol, staffName });
}

/**
 * True when a printReceipt() result means the printer could not be reached: strict
 * Bluetooth mode resolves false instead of opening the system dialog. In the other
 * modes false only means the user closed the system print dialog (nothing to report).
 */
export function isPrinterUnreachable(result) {
  return result === false && usePrinterStore.getState().mode === 'bluetooth';
}

// ─── BT Classic ticket (KOT/BOT — no prices, no cash drawer) ────────────────

function _printTicketBtClassic(opts) {
  return runBtJob(() => _printTicketBtClassicNow(opts));
}

async function _printTicketBtClassicNow({ order, restaurantName, stationFilter = null, orderedBy = '' }) {
  const mod = loadBtEscPos();
  if (!mod) throw new Error('BT Classic module not loaded');

  const { BluetoothEscposPrinter, BluetoothManager } = mod;
  const { bluetoothDevice } = usePrinterStore.getState();

  if (!bluetoothDevice?.address) {
    throw new Error('No Bluetooth printer selected. Go to Settings → Printer Settings.');
  }

  // Connect (an already-open connection is fine; gives up after 15 s)
  await connectOrThrow(BluetoothManager, bluetoothDevice.address);

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
    ? allItems.filter(i => (i.station || i.product?.station || 'kitchen') === stationFilter)
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
  if (orderedBy) await BluetoothEscposPrinter.printText(pad('By:', orderedBy) + '\n\r', {});
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

  // Notes / special instructions — strip offline dedup tags before printing
  const notes = (order.special_instructions || '').replace(/\[offline(?:-append)?:[^\]]*\]/g, '').trim();
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
 *   'bluetooth' → BT Classic SPP → error (no dialog — KOT/BOT shouldn't open UI on cashier's phone)
 *   'auto'      → BT Classic SPP → System dialog
 *   'network' / 'system' → System dialog
 *
 * @param {object} order          - Order object returned by the API
 * @param {string} restaurantName
 * @returns {Promise<boolean>}
 */
export async function printOrderTicket(order, restaurantName = '', stationFilter = null, orderedBy = '') {
  await settingsReadyPromise;
  const { mode } = usePrinterStore.getState();
  const opts = { order, restaurantName, stationFilter, orderedBy };

  if (mode === 'bluetooth') {
    // Strict BT mode: no system-dialog fallback for KOT/BOT tickets.
    // Kitchen/bar staff shouldn't have a print dialog appear on the cashier's phone.
    if (!isBtClassicAvailable()) return false;
    await _printTicketBtClassic(opts); // throws on failure — caller catches
    return true;
  }

  if (mode === 'auto') {
    if (isBtClassicAvailable()) {
      try {
        await _printTicketBtClassic(opts);
        return true;
      } catch (btErr) {
        if (__DEV__) console.warn('[Printer] Ticket BT failed (silent — no native dialog for KOT/BOT):', btErr?.message);
      }
    }
    // Auto mode: KOT/BOT never fall back to the native OS dialog.
    // Showing a print dialog interrupts the waiter mid-order. The order
    // is already saved (offline queue or server); this is only the local print.
    return false;
  }

  // Network / system modes only → system dialog (explicit receipt/bill prints, not auto KOT/BOT)
  return printTicketLocal(opts);
}

// Re-export for screens that use them directly
export { printReceiptLocal as printReceiptSystem } from './printReceipt';
export { buildReceiptHtml }                        from './printReceipt';
