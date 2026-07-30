import * as SQLite from 'expo-sqlite';

// expo-sqlite v14 (Expo SDK 51) uses an async API.
// All functions are async; the old openDatabase/transaction/executeSql API is removed.

let _db = null;

export const getDb = async () => {
  if (!_db) {
    _db = await SQLite.openDatabaseAsync('easyfix.db');
  }
  return _db;
};

/** Execute a write statement (INSERT / UPDATE / DELETE / DDL) with optional params. */
export const dbExec = async (sql, params = []) => {
  const db = await getDb();
  return db.runAsync(sql, params);
};

/** Execute a SELECT and return all matching rows as plain objects. */
export const dbQuery = async (sql, params = []) => {
  const db = await getDb();
  return db.getAllAsync(sql, params);
};

/** Run all CREATE TABLE statements on first open. Safe to call repeatedly. */
export const initDatabase = async () => {
  const db = await getDb();

  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS categories (
      id          INTEGER PRIMARY KEY,
      name        TEXT    NOT NULL,
      updated_at  TEXT,
      synced_at   TEXT
    );

    CREATE TABLE IF NOT EXISTS products (
      id                  INTEGER PRIMARY KEY,
      name                TEXT    NOT NULL,
      description         TEXT,
      price               REAL    NOT NULL,
      current_price       REAL    NOT NULL,
      is_available        INTEGER DEFAULT 1,
      available_in_stock  INTEGER,
      category_id         INTEGER,
      category_name       TEXT,
      subcategory_name    TEXT,
      station             TEXT    DEFAULT 'kitchen',
      image_url           TEXT,
      updated_at          TEXT,
      synced_at           TEXT
    );

    CREATE TABLE IF NOT EXISTS tables (
      id           INTEGER PRIMARY KEY,
      tbl_no       TEXT    NOT NULL,
      display_name TEXT,
      is_available INTEGER DEFAULT 1,
      synced_at    TEXT
    );

    CREATE TABLE IF NOT EXISTS offline_orders (
      id                   INTEGER PRIMARY KEY AUTOINCREMENT,
      offline_id           TEXT    UNIQUE NOT NULL,
      table_id             INTEGER,
      items_json           TEXT    NOT NULL,
      special_instructions TEXT,
      restaurant_id        INTEGER,
      total_amount         REAL    DEFAULT 0,
      total_paid           REAL    DEFAULT 0,
      payment_status       TEXT    DEFAULT 'unpaid',
      created_at           TEXT    NOT NULL,
      sync_status          TEXT    DEFAULT 'pending',
      server_order_id      INTEGER,
      server_order_number  TEXT,
      error_message        TEXT,
      order_type           TEXT    DEFAULT 'dine-in',
      delivery_address     TEXT,
      delivery_phone       TEXT,
      delivery_lat         REAL,
      delivery_lng         REAL
    );

    CREATE TABLE IF NOT EXISTS offline_payments (
      id                INTEGER PRIMARY KEY AUTOINCREMENT,
      offline_id        TEXT    UNIQUE NOT NULL,
      offline_order_ref TEXT,
      order_id          INTEGER,
      order_number      TEXT,
      amount            REAL    NOT NULL,
      payment_method    TEXT    NOT NULL,
      reference_number  TEXT,
      notes             TEXT,
      created_at        TEXT    NOT NULL,
      sync_status       TEXT    DEFAULT 'pending',
      server_payment_id INTEGER,
      error_message     TEXT
    );

    CREATE TABLE IF NOT EXISTS offline_bill_requests (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      offline_id  TEXT    UNIQUE NOT NULL,
      table_id    INTEGER NOT NULL,
      created_at  TEXT    NOT NULL,
      sync_status TEXT    DEFAULT 'pending',
      server_id   INTEGER,
      error_message TEXT
    );

    CREATE TABLE IF NOT EXISTS sync_meta (
      key   TEXT PRIMARY KEY,
      value TEXT
    );

    CREATE TABLE IF NOT EXISTS orders (
      id                        INTEGER PRIMARY KEY,
      order_number              TEXT,
      table_info                INTEGER,
      table_number              TEXT,
      ordered_by_name           TEXT,
      confirmed_by_name         TEXT,
      status                    TEXT,
      payment_status            TEXT,
      total_amount              REAL,
      subtotal                  REAL,
      tax_amount                REAL,
      discount_amount           REAL,
      total                     REAL,
      total_paid                REAL,
      balance_due               REAL,
      items_count               INTEGER,
      special_instructions      TEXT,
      reason_if_cancelled       TEXT,
      created_at                TEXT,
      updated_at                TEXT,
      items_json                TEXT,
      payments_json             TEXT,
      pending_bill_requested    INTEGER DEFAULT 0,
      pending_bill_requested_at TEXT,
      synced_at                 TEXT
    );
  `);

  // ── Schema migrations (safe to run on every start) ─────────────────────────
  // ALTER TABLE ADD COLUMN throws if the column already exists — we catch and
  // ignore that error so this is idempotent on new and existing installs.
  try {
    await db.runAsync(`ALTER TABLE products ADD COLUMN station TEXT DEFAULT 'kitchen'`);
  } catch (_) {}

  // Migration: delivery/pickup fields for offline orders
  for (const stmt of [
    `ALTER TABLE offline_orders ADD COLUMN order_type TEXT DEFAULT 'dine-in'`,
    `ALTER TABLE offline_orders ADD COLUMN delivery_address TEXT`,
    `ALTER TABLE offline_orders ADD COLUMN delivery_phone TEXT`,
    `ALTER TABLE offline_orders ADD COLUMN delivery_lat REAL`,
    `ALTER TABLE offline_orders ADD COLUMN delivery_lng REAL`,
  ]) {
    try { await db.runAsync(stmt); } catch (_) {}
  }

  // Migration: offline_order_ref — links a queued payment to a queued order
  // (needed when staff pay an offline-pending order before it syncs)
  try { await db.runAsync(`ALTER TABLE offline_payments ADD COLUMN offline_order_ref TEXT`); } catch (_) {}

  // Migration: payment tracking columns on offline_orders so status survives re-reads
  for (const stmt of [
    `ALTER TABLE offline_orders ADD COLUMN total_paid REAL DEFAULT 0`,
    `ALTER TABLE offline_orders ADD COLUMN payment_status TEXT DEFAULT 'unpaid'`,
  ]) {
    try { await db.runAsync(stmt); } catch (_) {}
  }

  // Migration: add orders cache table for existing installs that pre-date this feature.
  // CREATE TABLE IF NOT EXISTS in the block above already handles fresh installs;
  // this covers the case where initDatabase was already called once before orders existed.
  try {
    await db.runAsync(`
      CREATE TABLE IF NOT EXISTS orders (
        id                        INTEGER PRIMARY KEY,
        order_number              TEXT,
        table_info                INTEGER,
        table_number              TEXT,
        ordered_by_name           TEXT,
        confirmed_by_name         TEXT,
        status                    TEXT,
        payment_status            TEXT,
        total_amount              REAL,
        subtotal                  REAL,
        tax_amount                REAL,
        discount_amount           REAL,
        total                     REAL,
        total_paid                REAL,
        balance_due               REAL,
        items_count               INTEGER,
        special_instructions      TEXT,
        reason_if_cancelled       TEXT,
        created_at                TEXT,
        updated_at                TEXT,
        items_json                TEXT,
        payments_json             TEXT,
        pending_bill_requested    INTEGER DEFAULT 0,
        pending_bill_requested_at TEXT,
        synced_at                 TEXT
      )
    `);
  } catch (_) {}
};
