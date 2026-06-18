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
      (offline_id, table_id, items_json, special_instructions, restaurant_id, total_amount, created_at, sync_status)
     VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')`,
    [
      offlineId,
      orderData.table_id,
      JSON.stringify(orderData.items),
      orderData.special_instructions || '',
      orderData.restaurant_id || null,
      orderData.total_amount || 0,
      createdAt,
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

// ── Security: clear all user-specific local data on logout ───────────────────
// Must be called every time a user logs out to prevent data leaking to the
// next user who logs in on the same device (different user, different restaurant).
export const clearAllUserData = async () => {
  // Delete all offline queued data — belongs to the previous user
  await dbExec('DELETE FROM offline_orders');
  await dbExec('DELETE FROM offline_payments');
  await dbExec('DELETE FROM offline_bill_requests');
  // Clear cached menu and table data — next user may belong to a different restaurant
  await dbExec("DELETE FROM sync_meta WHERE key IN ('menu_json', 'menu_last_synced', 'tables_last_synced')");
  await dbExec('DELETE FROM categories');
  await dbExec('DELETE FROM products');
  await dbExec('DELETE FROM tables');
};
