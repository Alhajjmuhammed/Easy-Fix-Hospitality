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
      table_id             INTEGER NOT NULL,
      items_json           TEXT    NOT NULL,
      special_instructions TEXT,
      restaurant_id        INTEGER,
      total_amount         REAL    DEFAULT 0,
      created_at           TEXT    NOT NULL,
      sync_status          TEXT    DEFAULT 'pending',
      server_order_id      INTEGER,
      server_order_number  TEXT,
      error_message        TEXT
    );

    CREATE TABLE IF NOT EXISTS offline_payments (
      id                INTEGER PRIMARY KEY AUTOINCREMENT,
      offline_id        TEXT    UNIQUE NOT NULL,
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
  `);

  // ── Schema migrations (safe to run on every start) ─────────────────────────
  // ALTER TABLE ADD COLUMN throws if the column already exists — we catch and
  // ignore that error so this is idempotent on new and existing installs.
  try {
    await db.runAsync(`ALTER TABLE products ADD COLUMN station TEXT DEFAULT 'kitchen'`);
  } catch (_) {
    // Column already exists — nothing to do
  }
};
