import { dbExec, dbQuery } from './db';

// ── Helpers ─────────────────────────────────────────────────────────────────

const now = () => new Date().toISOString();
const newOfflineId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

// ── Sync Metadata ────────────────────────────────────────────────────────────

export const getSyncMeta = async (key) => {
  const rows = await dbQuery('SELECT value FROM sync_meta WHERE key = ?', [key]);
  return rows.length ? rows[0].value : null;
};

export const setSyncMeta = (key, value) =>
  dbExec(
    'INSERT INTO sync_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
    [key, value],
  );

// ── Categories & Products ────────────────────────────────────────────────────

export const saveCategories = async (categories) => {
  // ── 1. Save full JSON blob so getCategories can reconstruct nested structure offline ──
  await setSyncMeta('menu_json', JSON.stringify(categories));

  // ── 2. Also write individual rows into SQLite for any future query use ──
  const ts = now();
  for (const cat of categories) {
    await dbExec(
      `INSERT INTO categories (id, name, updated_at, synced_at)
       VALUES (?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at, synced_at = excluded.synced_at`,
      [cat.id, cat.name, ts, ts],
    );

    // Iterate subcategories → products (new API shape)
    for (const sub of cat.subcategories || []) {
      for (const product of sub.products || []) {
        await dbExec(
          `INSERT INTO products (
            id, name, description, price, current_price, is_available,
            available_in_stock, category_id, category_name, subcategory_name,
            station, image_url, updated_at, synced_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(id) DO UPDATE SET
            name = excluded.name, description = excluded.description,
            price = excluded.price, current_price = excluded.current_price,
            is_available = excluded.is_available,
            available_in_stock = excluded.available_in_stock,
            category_id = excluded.category_id,
            category_name = excluded.category_name,
            subcategory_name = excluded.subcategory_name,
            station = excluded.station,
            image_url = excluded.image_url,
            updated_at = excluded.updated_at,
            synced_at = excluded.synced_at`,
          [
            product.id, product.name, product.description || '',
            product.price, product.current_price,
            product.is_available ? 1 : 0,
            product.available_in_stock ?? null,
            cat.id, cat.name, sub.name || '',
            product.station || 'kitchen',
            product.image_url || '', product.updated_at || ts, ts,
          ],
        );
      }
    }
  }
  await setSyncMeta('menu_last_synced', ts);
};

export const getCategories = async () => {
  // Return full nested structure from JSON blob (set by saveCategories)
  const json = await getSyncMeta('menu_json');
  if (json) {
    try {
      return JSON.parse(json);
    } catch {
      // fall through to SQLite fallback
    }
  }

  // ── Fallback: reconstruct from SQLite products table ──
  const cats = await dbQuery('SELECT * FROM categories ORDER BY name');
  const products = await dbQuery('SELECT * FROM products WHERE is_available = 1 ORDER BY name');

  return cats.map((cat) => {
    // Group products by subcategory_name
    const subMap = {};
    products
      .filter((p) => p.category_id === cat.id)
      .forEach((p) => {
        const subName = p.subcategory_name || 'General';
        if (!subMap[subName]) subMap[subName] = { id: subName, name: subName, products: [] };
        subMap[subName].products.push({
          ...p,
          is_available: !!p.is_available,
          current_price: p.current_price || p.price,
          has_promotion: false,
          original_price: p.price,
          station: p.station || 'kitchen',
        });
      });
    return { ...cat, subcategories: Object.values(subMap) };
  });
};

export const getProducts = (categoryId = null) => {
  if (categoryId) {
    return dbQuery(
      'SELECT * FROM products WHERE category_id = ? AND is_available = 1 ORDER BY name',
      [categoryId],
    );
  }
  return dbQuery('SELECT * FROM products WHERE is_available = 1 ORDER BY name');
};

// ── Tables ───────────────────────────────────────────────────────────────────

export const saveTables = async (tables) => {
  const ts = now();
  for (const t of tables) {
    await dbExec(
      `INSERT INTO tables (id, tbl_no, display_name, is_available, synced_at)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         tbl_no = excluded.tbl_no,
         display_name = excluded.display_name,
         is_available = excluded.is_available,
         synced_at = excluded.synced_at`,
      [t.id, t.tbl_no, t.display_name || `Table ${t.tbl_no}`, t.is_available ? 1 : 0, ts],
    );
  }
};

export const getTables = () => dbQuery('SELECT * FROM tables ORDER BY tbl_no');

export const updateTableAvailability = (tableId, isAvailable) =>
  dbExec('UPDATE tables SET is_available = ? WHERE id = ?', [isAvailable ? 1 : 0, tableId]);

// ── Offline Orders ────────────────────────────────────────────────────────────

export const saveOfflineOrder = async (orderData) => {
  const offlineId = newOfflineId();
  const createdAt = now();
  await dbExec(
    `INSERT INTO offline_orders
      (offline_id, table_id, items_json, special_instructions, restaurant_id, total_amount, created_at, sync_status,
       order_type, delivery_address, delivery_phone, delivery_lat, delivery_lng)
     VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)`,
    [
      offlineId,
      orderData.table_id ?? null,
      JSON.stringify(orderData.items),
      orderData.special_instructions || '',
      orderData.restaurant_id || null,
      orderData.total_amount || 0,
      createdAt,
      orderData.order_type || 'dine-in',
      orderData.delivery_address || '',
      orderData.delivery_phone || '',
      orderData.delivery_lat ?? null,
      orderData.delivery_lng ?? null,
    ],
  );
  return offlineId;
};

export const getPendingOrders = () =>
  dbQuery("SELECT * FROM offline_orders WHERE sync_status = 'pending' ORDER BY created_at");

export const markOrderSynced = (offlineId, serverOrderId, serverOrderNumber) =>
  dbExec(
    "UPDATE offline_orders SET sync_status = 'synced', server_order_id = ?, server_order_number = ? WHERE offline_id = ?",
    [serverOrderId, serverOrderNumber, offlineId],
  );

export const markOrderError = (offlineId, error) =>
  dbExec(
    "UPDATE offline_orders SET sync_status = 'error', error_message = ? WHERE offline_id = ?",
    [error, offlineId],
  );

// ── Offline Payments ──────────────────────────────────────────────────────────

export const saveOfflinePayment = async (paymentData) => {
  const offlineId = newOfflineId();
  await dbExec(
    `INSERT INTO offline_payments
      (offline_id, order_id, order_number, amount, payment_method, reference_number, notes, created_at, sync_status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')`,
    [
      offlineId,
      paymentData.order_id || null,
      paymentData.order_number || '',
      paymentData.amount,
      paymentData.payment_method,
      paymentData.reference_number || '',
      paymentData.notes || '',
      now(),
    ],
  );
  return offlineId;
};

export const getPendingPayments = () =>
  dbQuery("SELECT * FROM offline_payments WHERE sync_status = 'pending' ORDER BY created_at");

export const markPaymentSynced = (offlineId, serverPaymentId) =>
  dbExec(
    "UPDATE offline_payments SET sync_status = 'synced', server_payment_id = ? WHERE offline_id = ?",
    [serverPaymentId, offlineId],
  );

export const markPaymentError = (offlineId, error) =>
  dbExec(
    "UPDATE offline_payments SET sync_status = 'error', error_message = ? WHERE offline_id = ?",
    [error, offlineId],
  );

// ── Offline Bill Requests ─────────────────────────────────────────────────────

export const saveOfflineBillRequest = async (tableId) => {
  const offlineId = newOfflineId();
  await dbExec(
    "INSERT INTO offline_bill_requests (offline_id, table_id, created_at, sync_status) VALUES (?, ?, ?, 'pending')",
    [offlineId, tableId, now()],
  );
  return offlineId;
};

export const getPendingBillRequests = () =>
  dbQuery("SELECT * FROM offline_bill_requests WHERE sync_status = 'pending' ORDER BY created_at");

export const markBillRequestSynced = (offlineId, serverId) =>
  dbExec(
    "UPDATE offline_bill_requests SET sync_status = 'synced', server_id = ? WHERE offline_id = ?",
    [serverId, offlineId],
  );

// ── Cached Orders (from server pull) ─────────────────────────────────────────

/**
 * Upsert a list of server orders into the local SQLite cache.
 * Called after every successful sync pull so the app can display orders offline.
 */
export const saveOrders = async (orders) => {
  const ts = now();

  // Upsert every order in the pulled list
  for (const o of orders) {
    await dbExec(
      `INSERT INTO orders (
         id, order_number, table_info, table_number,
         ordered_by_name, confirmed_by_name, status, payment_status,
         total_amount, subtotal, tax_amount, discount_amount, total,
         total_paid, balance_due, items_count,
         special_instructions, reason_if_cancelled,
         created_at, updated_at,
         items_json, payments_json,
         pending_bill_requested, pending_bill_requested_at,
         synced_at
       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(id) DO UPDATE SET
         order_number              = excluded.order_number,
         table_info                = excluded.table_info,
         table_number              = excluded.table_number,
         ordered_by_name           = excluded.ordered_by_name,
         confirmed_by_name         = excluded.confirmed_by_name,
         status                    = excluded.status,
         payment_status            = excluded.payment_status,
         total_amount              = excluded.total_amount,
         subtotal                  = excluded.subtotal,
         tax_amount                = excluded.tax_amount,
         discount_amount           = excluded.discount_amount,
         total                     = excluded.total,
         total_paid                = excluded.total_paid,
         balance_due               = excluded.balance_due,
         items_count               = excluded.items_count,
         special_instructions      = excluded.special_instructions,
         reason_if_cancelled       = excluded.reason_if_cancelled,
         created_at                = excluded.created_at,
         updated_at                = excluded.updated_at,
         items_json                = excluded.items_json,
         payments_json             = excluded.payments_json,
         pending_bill_requested    = excluded.pending_bill_requested,
         pending_bill_requested_at = excluded.pending_bill_requested_at,
         synced_at                 = excluded.synced_at`,
      [
        o.id,
        o.order_number || '',
        o.table_info || null,
        o.table_number || 'N/A',
        o.ordered_by_name || '',
        o.confirmed_by_name || null,
        o.status || '',
        o.payment_status || '',
        o.total_amount ?? 0,
        o.subtotal ?? 0,
        o.tax_amount ?? 0,
        o.discount_amount ?? 0,
        o.total ?? 0,
        o.total_paid ?? 0,
        o.balance_due ?? 0,
        o.items_count ?? 0,
        o.special_instructions || '',
        o.reason_if_cancelled || '',
        o.created_at || ts,
        o.updated_at || ts,
        JSON.stringify(o.items || []),
        JSON.stringify(o.payments || []),
        o.pending_bill_requested ? 1 : 0,
        o.pending_bill_requested_at || null,
        ts,
      ],
    );
  }

  // Prune orders that are no longer active (paid, cancelled, etc.).
  // Only prune when the server actually returned a non-empty list — if the list
  // is empty it just means no active orders right now; don't wipe the whole cache.
  if (orders.length > 0) {
    const ids = orders.map((o) => o.id);
    const placeholders = ids.map(() => '?').join(',');
    await dbExec(`DELETE FROM orders WHERE id NOT IN (${placeholders})`, ids);
  }
};

/**
 * Upsert orders into the local cache without pruning anything.
 * Call this after every successful apiOrders() / apiOrderDetail() call so the
 * cache stays fresh even if a full sync hasn't run yet.
 */
export const cacheOrders = async (orders) => {
  if (!orders || !orders.length) return;
  const ts = now();
  for (const o of orders) {
    await dbExec(
      `INSERT INTO orders (
         id, order_number, table_info, table_number,
         ordered_by_name, confirmed_by_name, status, payment_status,
         total_amount, subtotal, tax_amount, discount_amount, total,
         total_paid, balance_due, items_count,
         special_instructions, reason_if_cancelled,
         created_at, updated_at,
         items_json, payments_json,
         pending_bill_requested, pending_bill_requested_at,
         synced_at
       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(id) DO UPDATE SET
         order_number              = excluded.order_number,
         table_info                = excluded.table_info,
         table_number              = excluded.table_number,
         ordered_by_name           = excluded.ordered_by_name,
         confirmed_by_name         = excluded.confirmed_by_name,
         status                    = excluded.status,
         payment_status            = excluded.payment_status,
         total_amount              = excluded.total_amount,
         subtotal                  = excluded.subtotal,
         tax_amount                = excluded.tax_amount,
         discount_amount           = excluded.discount_amount,
         total                     = excluded.total,
         total_paid                = excluded.total_paid,
         balance_due               = excluded.balance_due,
         items_count               = excluded.items_count,
         special_instructions      = excluded.special_instructions,
         reason_if_cancelled       = excluded.reason_if_cancelled,
         created_at                = excluded.created_at,
         updated_at                = excluded.updated_at,
         items_json                = excluded.items_json,
         payments_json             = excluded.payments_json,
         pending_bill_requested    = excluded.pending_bill_requested,
         pending_bill_requested_at = excluded.pending_bill_requested_at,
         synced_at                 = excluded.synced_at`,
      [
        o.id,
        o.order_number || '',
        o.table_info || null,
        o.table_number || 'N/A',
        o.ordered_by_name || '',
        o.confirmed_by_name || null,
        o.status || '',
        o.payment_status || '',
        o.total_amount ?? 0,
        o.subtotal ?? 0,
        o.tax_amount ?? 0,
        o.discount_amount ?? 0,
        o.total ?? 0,
        o.total_paid ?? 0,
        o.balance_due ?? 0,
        o.items_count ?? 0,
        o.special_instructions || '',
        o.reason_if_cancelled || '',
        o.created_at || ts,
        o.updated_at || ts,
        JSON.stringify(o.items || []),
        JSON.stringify(o.payments || []),
        o.pending_bill_requested ? 1 : 0,
        o.pending_bill_requested_at || null,
        ts,
      ],
    );
  }
};

/** Parse a raw SQLite row back into the shape the screens expect. */
const _parseOrder = (row) => ({
  ...row,
  items:                   JSON.parse(row.items_json || '[]'),
  payments:                JSON.parse(row.payments_json || '[]'),
  pending_bill_requested:  !!row.pending_bill_requested,
});

/**
 * Return cached orders, optionally filtered by one or more statuses.
 * @param {string[]|null} statuses  e.g. ['pending','confirmed'] — null = all
 */
export const getOrders = async (statuses = null) => {
  let rows;
  if (statuses && statuses.length) {
    const placeholders = statuses.map(() => '?').join(',');
    rows = await dbQuery(
      `SELECT * FROM orders WHERE status IN (${placeholders}) ORDER BY created_at DESC`,
      statuses,
    );
  } else {
    rows = await dbQuery('SELECT * FROM orders ORDER BY created_at DESC');
  }
  return rows.map(_parseOrder);
};

/** Return a single cached order by server ID, or null if not found. */
export const getOrderById = async (id) => {
  const rows = await dbQuery('SELECT * FROM orders WHERE id = ?', [id]);
  return rows.length ? _parseOrder(rows[0]) : null;
};

// ── Security: clear all user-specific local data on logout ───────────────────
// Must be called every time a user logs out to prevent data leaking to the
// next user who logs in on the same device (different user, different restaurant).
export const clearAllUserData = async () => {
  // Delete all offline queued data — belongs to the previous user
  await dbExec('DELETE FROM offline_orders');
  await dbExec('DELETE FROM offline_payments');
  await dbExec('DELETE FROM offline_bill_requests');
  // Clear cached server data — next user may belong to a different restaurant
  await dbExec("DELETE FROM sync_meta WHERE key IN ('menu_json', 'menu_last_synced', 'tables_last_synced')");
  await dbExec('DELETE FROM categories');
  await dbExec('DELETE FROM products');
  await dbExec('DELETE FROM tables');
  await dbExec('DELETE FROM orders');
};
