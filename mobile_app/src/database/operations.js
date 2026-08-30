import { dbExec, dbQuery, getDb } from './db';

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
  const ts = now();
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync(
      'INSERT INTO sync_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
      ['menu_json', JSON.stringify(categories)],
    );
    for (const cat of categories) {
      await db.runAsync(
        `INSERT INTO categories (id, name, updated_at, synced_at)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at, synced_at = excluded.synced_at`,
        [cat.id, cat.name, ts, ts],
      );
      for (const sub of cat.subcategories || []) {
        for (const product of sub.products || []) {
          await db.runAsync(
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
    await db.runAsync(
      'INSERT INTO sync_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
      ['menu_last_synced', ts],
    );
  });
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
  if (!tables || !tables.length) return;
  const ts = now();
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    for (const t of tables) {
      await db.runAsync(
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
  });
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
       order_type, delivery_address, delivery_phone, delivery_lat, delivery_lng, existing_order_id, tax_rate, local_print_fired)
     VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)`,
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
      orderData.existing_order_id ?? null,
      orderData.tax_rate ?? 0,
      orderData.local_print_fired ? 1 : 0,
    ],
  );
  return offlineId;
};

export const getPendingOrders = () =>
  dbQuery("SELECT * FROM offline_orders WHERE sync_status = 'pending' ORDER BY created_at");

export const updateOfflineOrderStatus = (offlineId, status) =>
  dbExec('UPDATE offline_orders SET status = ? WHERE offline_id = ?', [status, offlineId]);

export const updateCachedOrderStatus = (orderId, status) =>
  dbExec('UPDATE orders SET status = ? WHERE id = ?', [status, orderId]);

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
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync(
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
    // Also update the cached server order so that if the app restarts while offline
    // the payment status is not shown as stale (still 'unpaid').
    if (paymentData.order_id) {
      const rows = await db.getAllAsync(
        'SELECT total_amount, total_paid, balance_due, payments_json FROM orders WHERE id = ?',
        [paymentData.order_id],
      );
      if (rows.length) {
        const row = rows[0];
        const newTotalPaid = (row.total_paid || 0) + paymentData.amount;
        const newBalanceDue = Math.max(0, (row.total_amount || row.balance_due || 0) - newTotalPaid);
        const newStatus = newBalanceDue <= 0 ? 'paid' : newTotalPaid > 0 ? 'partial' : 'unpaid';
        let existingPayments = [];
        try { existingPayments = JSON.parse(row.payments_json || '[]'); } catch (_) {}
        const newPaymentEntry = {
          id: null,
          amount: paymentData.amount,
          payment_method: paymentData.payment_method,
          reference_number: paymentData.reference_number || '',
          notes: paymentData.notes || '',
          processed_by_name: null,
          created_at: now(),
        };
        const updatedPaymentsJson = JSON.stringify([...existingPayments, newPaymentEntry]);
        await db.runAsync(
          'UPDATE orders SET total_paid = ?, balance_due = ?, payment_status = ?, payments_json = ? WHERE id = ?',
          [newTotalPaid, newBalanceDue, newStatus, updatedPaymentsJson, paymentData.order_id],
        );
      }
    }
  });
  return offlineId;
};

/** Save a payment for an offline-pending order (no server order ID yet). */
export const saveOfflinePaymentForOfflineOrder = async (paymentData) => {
  const offlineId = newOfflineId();
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync(
      `INSERT INTO offline_payments
        (offline_id, offline_order_ref, order_id, order_number, amount, payment_method, reference_number, notes, created_at, sync_status)
       VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, 'pending')`,
      [
        offlineId,
        paymentData.offline_order_ref,
        paymentData.order_number || '(offline)',
        paymentData.amount,
        paymentData.payment_method,
        paymentData.reference_number || '',
        paymentData.notes || '',
        now(),
      ],
    );
    const orderRows = await db.getAllAsync(
      'SELECT total_amount, total_paid FROM offline_orders WHERE offline_id = ?',
      [paymentData.offline_order_ref],
    );
    if (orderRows.length) {
      const existing = orderRows[0];
      const newTotalPaid = (existing.total_paid || 0) + paymentData.amount;
      const balanceDue = Math.max(0, (existing.total_amount || 0) - newTotalPaid);
      const paymentStatus = balanceDue <= 0 ? 'paid' : newTotalPaid > 0 ? 'partial' : 'unpaid';
      await db.runAsync(
        'UPDATE offline_orders SET total_paid = ?, payment_status = ? WHERE offline_id = ?',
        [newTotalPaid, paymentStatus, paymentData.offline_order_ref],
      );
    }
  });
  return offlineId;
};

export const getPendingPayments = () =>
  dbQuery("SELECT * FROM offline_payments WHERE sync_status = 'pending' ORDER BY created_at");

export const getAllOfflinePayments = () =>
  dbQuery("SELECT * FROM offline_payments WHERE sync_status != 'synced' ORDER BY created_at DESC LIMIT 100");

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

export const markBillRequestError = (offlineId, errorMessage) =>
  dbExec(
    "UPDATE offline_bill_requests SET sync_status = 'error', error_message = ? WHERE offline_id = ?",
    [errorMessage || 'Sync failed', offlineId],
  );

export const deleteOfflineOrder = async (offlineId) => {
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync('DELETE FROM offline_payments WHERE offline_order_ref = ?', [offlineId]);
    await db.runAsync('DELETE FROM offline_orders WHERE offline_id = ?', [offlineId]);
  });
};

// ── Cached Orders (from server pull) ─────────────────────────────────────────

/**
 * Upsert a list of server orders into the local SQLite cache.
 * Called after every successful sync pull so the app can display orders offline.
 */
export const saveOrders = async (orders) => {
  const ts = now();
  const db = await getDb();
  await db.withTransactionAsync(async () => {

  // Upsert every order in the pulled list
  for (const o of orders) {
    await db.runAsync(
      `INSERT INTO orders (
         id, order_number, table_info, table_number,
         ordered_by_name, confirmed_by_name, status, payment_status,
         total_amount, subtotal, tax_amount, discount_amount, total,
         total_paid, balance_due, items_count,
         special_instructions, reason_if_cancelled,
         created_at, updated_at,
         items_json, payments_json,
         pending_bill_requested, pending_bill_requested_at,
         order_type, synced_at,
         delivery_address, delivery_phone, delivery_lat, delivery_lng
       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
         order_type                = excluded.order_type,
         synced_at                 = excluded.synced_at,
         delivery_address          = excluded.delivery_address,
         delivery_phone            = excluded.delivery_phone,
         delivery_lat              = excluded.delivery_lat,
         delivery_lng              = excluded.delivery_lng`,
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
        o.order_type || 'dine-in',
        ts,
        o.delivery_address || null,
        o.delivery_phone || null,
        o.delivery_lat ?? null,
        o.delivery_lng ?? null,
      ],
    );
  }

  // Prune orders that are no longer active (paid, cancelled, etc.).
  // Only prune when the server actually returned a non-empty list — if the list
  // is empty it just means no active orders right now; don't wipe the whole cache.
  // Uses IN-batches (max 500) instead of NOT IN to avoid SQLite's 999-variable limit.
  if (orders.length > 0) {
    const incomingIds = new Set(orders.map((o) => o.id));
    const existing = await db.getAllAsync('SELECT id FROM orders');
    const toDelete = existing.map((r) => r.id).filter((id) => !incomingIds.has(id));
    const BATCH = 500;
    for (let i = 0; i < toDelete.length; i += BATCH) {
      const batch = toDelete.slice(i, i + BATCH);
      const placeholders = batch.map(() => '?').join(',');
      await db.runAsync(`DELETE FROM orders WHERE id IN (${placeholders})`, batch);
    }
  }

  }); // end withTransactionAsync
};

/**
 * Upsert orders into the local cache without pruning anything.
 * Call this after every successful apiOrders() / apiOrderDetail() call so the
 * cache stays fresh even if a full sync hasn't run yet.
 */
export const cacheOrders = async (orders) => {
  if (!orders || !orders.length) return;
  const ts = now();
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    for (const o of orders) {
      await db.runAsync(
        `INSERT INTO orders (
           id, order_number, table_info, table_number,
           ordered_by_name, confirmed_by_name, status, payment_status,
           total_amount, subtotal, tax_amount, discount_amount, total,
           total_paid, balance_due, items_count,
           special_instructions, reason_if_cancelled,
           created_at, updated_at,
           items_json, payments_json,
           pending_bill_requested, pending_bill_requested_at,
           order_type, synced_at,
           delivery_address, delivery_phone, delivery_lat, delivery_lng
         ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
           order_type                = excluded.order_type,
           synced_at                 = excluded.synced_at,
           delivery_address          = excluded.delivery_address,
           delivery_phone            = excluded.delivery_phone,
           delivery_lat              = excluded.delivery_lat,
           delivery_lng              = excluded.delivery_lng`,
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
          o.order_type || 'dine-in',
          ts,
          o.delivery_address || null,
          o.delivery_phone || null,
          o.delivery_lat ?? null,
          o.delivery_lng ?? null,
        ],
      );
    }
  });
};

/** Parse a raw SQLite row back into the shape the screens expect. */
const _parseOrder = (row) => {
  let items = [], payments = [];
  try { items    = JSON.parse(row.items_json    || '[]'); } catch (_) {}
  try { payments = JSON.parse(row.payments_json || '[]'); } catch (_) {}
  return { ...row, items, payments, pending_bill_requested: !!row.pending_bill_requested };
};

/**
 * Return cached orders, optionally filtered by one or more statuses.
 * @param {string[]|null} statuses  e.g. ['pending','confirmed'] — null = all
 */
export const getOrders = async (statuses = null) => {
  let rows;
  if (statuses && statuses.length) {
    const placeholders = statuses.map(() => '?').join(',');
    rows = await dbQuery(
      `SELECT * FROM orders WHERE status IN (${placeholders}) ORDER BY created_at DESC LIMIT 1000`,
      statuses,
    );
  } else {
    rows = await dbQuery('SELECT * FROM orders ORDER BY created_at DESC LIMIT 1000');
  }
  return rows.map(_parseOrder);
};

/** Return a single cached order by server ID, or null if not found. */
export const getOrderById = async (id) => {
  const rows = await dbQuery('SELECT * FROM orders WHERE id = ?', [id]);
  return rows.length ? _parseOrder(rows[0]) : null;
};

/**
 * Get locally-queued (pending sync) orders as display-ready objects.
 * These are orders placed while offline that haven't synced to the server yet.
 * Call this alongside getOrders() and merge the results so staff can see
 * ALL orders — both cached server orders and unsynced local ones.
 */
export const getOfflinePendingOrders = async () => {
  const rows = await dbQuery(
    "SELECT * FROM offline_orders WHERE sync_status IN ('pending', 'error') ORDER BY created_at DESC"
  );

  if (!rows.length) return [];

  // ── 1. Parse all items_json upfront (avoid double-parsing) ────────────────
  const rowItems = rows.map(r => {
    try { return JSON.parse(r.items_json || '[]'); } catch { return []; }
  });

  // ── 2. Collect unique IDs for batch lookups ────────────────────────────────
  const allTableIds = [...new Set(rows.map(r => r.table_id).filter(Boolean))];
  const allProductIds = [...new Set(
    rowItems.flatMap(items => items.map(i => i.product_id).filter(Boolean))
  )];

  // ── 3. One query per lookup type (replaces N+1 per-row queries) ───────────
  let tableMap = {};
  if (allTableIds.length) {
    const placeholders = allTableIds.map(() => '?').join(',');
    const tableRows = await dbQuery(
      `SELECT id, tbl_no FROM tables WHERE id IN (${placeholders})`,
      allTableIds,
    );
    tableMap = Object.fromEntries(tableRows.map(r => [r.id, r.tbl_no]));
  }

  let productMap = {};
  if (allProductIds.length) {
    const placeholders = allProductIds.map(() => '?').join(',');
    const productRows = await dbQuery(
      `SELECT id, name, station FROM products WHERE id IN (${placeholders})`,
      allProductIds,
    );
    productMap = Object.fromEntries(productRows.map(r => [r.id, r]));
  }

  // ── 4. Batch-load all pending payments for offline orders (one query) ─────
  const allPayments = await dbQuery(
    "SELECT * FROM offline_payments WHERE sync_status = 'pending' ORDER BY created_at ASC", []
  );
  const paymentsByRef = {};
  for (const p of allPayments) {
    if (!paymentsByRef[p.offline_order_ref]) paymentsByRef[p.offline_order_ref] = [];
    paymentsByRef[p.offline_order_ref].push(p);
  }

  // ── 5. Build result using maps — no per-row DB calls ─────────────────────
  const result = [];
  for (let idx = 0; idx < rows.length; idx++) {
    const row = rows[idx];
    const rawItems = rowItems[idx];

    // Table number: look up from map instead of querying per row
    const tblNoVal = row.table_id ? tableMap[row.table_id] : undefined;
    const tableNumber = tblNoVal !== undefined ? String(tblNoVal) : 'N/A';

    // Enrich items with product names from the product map
    const items = rawItems.map(item => {
      const p = productMap[item.product_id] || null;
      return {
        ...item,
        name: p ? p.name : `Item #${item.product_id}`,
        station: item.station || (p ? p.station : null) || 'kitchen',
      };
    });

    // Read payment status directly from the offline_orders row — written by
    // saveOfflinePaymentForOfflineOrder so this always reflects current state.
    const totalPaid = row.total_paid || 0;
    const balanceDue = Math.max(0, (row.total_amount || 0) - totalPaid);
    const paymentStatus = row.payment_status || 'unpaid';

    // Compute subtotal/tax from stored tax_rate so receipt prints correctly.
    // total_amount is tax-inclusive: subtotal = total / (1 + taxRate)
    const taxRate = parseFloat(row.tax_rate) || 0;
    const computedSubtotal = taxRate > 0
      ? (row.total_amount || 0) / (1 + taxRate)
      : (row.total_amount || 0);
    const computedTax = (row.total_amount || 0) - computedSubtotal;

    // Use pre-loaded payment map (batch query above) — no per-row DB call
    const queuedPayments = (paymentsByRef[row.offline_id] || []).map((p) => ({
      id: p.offline_id,
      amount: p.amount,
      payment_method: p.payment_method,
      created_at: p.created_at,
      _is_offline: true,
    }));

    result.push({
      id: `offline_${row.offline_id}`,
      offline_id: row.offline_id,
      order_number: row.existing_order_id ? `(adding to #${row.existing_order_id})` : '(offline)',
      table_number: tableNumber,
      table_info: row.table_id || null,
      status: row.status || 'pending',
      payment_status: paymentStatus,
      total: row.total_amount || 0,
      total_amount: row.total_amount || 0,
      subtotal: computedSubtotal,
      balance_due: balanceDue,
      total_paid: totalPaid,
      tax_amount: computedTax,
      items_count: items.length,
      items,
      payments: queuedPayments,
      order_type: row.order_type || 'dine-in',
      delivery_address: row.delivery_address || '',
      created_at: row.created_at,
      updated_at: row.created_at,
      special_instructions: row.special_instructions || '',
      existing_order_id: row.existing_order_id || null,
      _is_offline_pending: true,
      _is_sync_error: row.sync_status === 'error',
      error_message: row.error_message || '',
    });
  }
  return result;
};

/**
 * Compute report statistics from locally cached data.
 * Used when offline and no server cache is available.
 * Returns an object shaped like the server's /reports/cashier/ response.
 */
export const getLocalReportStats = async () => {
  const [cachedOrders, offlinePending] = await Promise.all([
    getOrders(null),
    getOfflinePendingOrders(),
  ]);

  const allOrders = [...cachedOrders];
  const pendingOffline = offlinePending.filter((o) => !o._is_sync_error);

  const totalOrders = allOrders.length + pendingOffline.length;
  const totalRevenue = allOrders.reduce((s, o) => s + (o.total_amount || 0), 0)
    + pendingOffline.reduce((s, o) => s + (o.total_amount || 0), 0);
  const totalItems = allOrders.reduce((s, o) => s + (o.items_count || 0), 0)
    + pendingOffline.reduce((s, o) => s + (o.items_count || 0), 0);
  const avgOrderValue = totalOrders > 0 ? totalRevenue / totalOrders : 0;

  const paidOrders    = allOrders.filter((o) => o.payment_status === 'paid').length;
  const partialOrders = allOrders.filter((o) => o.payment_status === 'partial').length;
  const unpaidOrders  = allOrders.filter((o) => o.payment_status === 'unpaid').length
    + pendingOffline.length;

  // Build orders list for display (server orders only — offline pending shown separately)
  const orderList = allOrders.map((o) => ({
    id: o.id,
    order_number: o.order_number,
    table_number: o.table_number,
    status: o.status,
    payment_status: o.payment_status,
    total_amount: o.total_amount,
    items_count: o.items_count,
    created_at: o.created_at,
    ordered_by: o.ordered_by_name || '',
  }));

  return {
    stats: {
      total_orders: totalOrders,
      total_revenue: totalRevenue,
      total_items: totalItems,
      avg_order_value: avgOrderValue,
      paid_orders: paidOrders,
      partial_orders: partialOrders,
      unpaid_orders: unpaidOrders,
      my_total_collected: 0,
      my_payment_count: 0,
    },
    orders: orderList,
    my_payment_methods: [],
    top_products: [],
    _is_local: true,
  };
};

// ── Offline Status Changes ────────────────────────────────────────────────────

export async function saveOfflineStatusChange(orderId, newStatus) {
  await dbExec(
    "INSERT INTO offline_status_changes (order_id, new_status, sync_status) VALUES (?, ?, 'pending')",
    [orderId, newStatus],
  );
}

export async function getPendingStatusChanges() {
  return dbQuery(
    "SELECT * FROM offline_status_changes WHERE sync_status = 'pending' ORDER BY created_at ASC",
  );
}

export async function markStatusChangeSynced(id) {
  await dbExec(
    "UPDATE offline_status_changes SET sync_status = 'synced' WHERE id = ?",
    [id],
  );
}

export async function markStatusChangeError(id) {
  await dbExec(
    "UPDATE offline_status_changes SET sync_status = 'error' WHERE id = ?",
    [id],
  );
}

// ── Cached Delivery Assignments ───────────────────────────────────────────────

export async function cacheAssignments(assignments) {
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync('DELETE FROM cached_assignments');
    for (const a of assignments) {
      await db.runAsync(
        "INSERT OR REPLACE INTO cached_assignments (id, order_id, status, order_data, updated_at) VALUES (?, ?, ?, ?, datetime('now'))",
        [a.id, a.order?.id ?? null, a.status, JSON.stringify(a)],
      );
    }
  });
}

export async function getCachedAssignments() {
  const rows = await dbQuery(
    'SELECT order_data FROM cached_assignments ORDER BY updated_at DESC',
  );
  return rows
    .map((r) => {
      try {
        return JSON.parse(r.order_data);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

// ── Security: clear all user-specific local data on logout ───────────────────
// Must be called every time a user logs out to prevent data leaking to the
// next user who logs in on the same device (different user, different restaurant).
export const clearAllUserData = async () => {
  const db = await getDb();
  await db.withTransactionAsync(async () => {
    await db.runAsync('DELETE FROM offline_orders');
    await db.runAsync('DELETE FROM offline_payments');
    await db.runAsync('DELETE FROM offline_bill_requests');
    await db.runAsync(
      "DELETE FROM sync_meta WHERE key IN ('menu_json', 'menu_last_synced', 'tables_last_synced', 'last_sync', 'cashier_report_cache', 'cashier_report_cache_ts', 'cashier_report_cache_period', 'cc_report_cache', 'cc_report_cache_ts')"
    );
    await db.runAsync('DELETE FROM categories');
    await db.runAsync('DELETE FROM products');
    await db.runAsync('DELETE FROM tables');
    await db.runAsync('DELETE FROM orders');
    await db.runAsync('DELETE FROM offline_status_changes');
    await db.runAsync('DELETE FROM cached_assignments');
  });
};
