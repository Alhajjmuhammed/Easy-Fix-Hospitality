/**
 * syncQueue.js — helpers for managing the offline sync queue.
 *
 * These are thin wrappers over database/operations.js used by useSyncStore
 * to retry failed items and report queue depth.
 */

import {
  getPendingOrders,
  getPendingPayments,
  getPendingBillRequests,
  markOrderError,
  markPaymentError,
  getSyncMeta,
  setSyncMeta,
} from '../database/operations';

const MAX_RETRIES = 3;

/**
 * Returns total count of items waiting to sync.
 */
export async function getPendingCount() {
  const [orders, payments, billRequests] = await Promise.all([
    getPendingOrders(),
    getPendingPayments(),
    getPendingBillRequests(),
  ]);
  return orders.length + payments.length + billRequests.length;
}

/**
 * Returns true if any items have been in error state.
 */
export async function hasErrors() {
  const [orders, payments] = await Promise.all([
    getPendingOrders(),
    getPendingPayments(),
  ]);
  return (
    orders.some((o) => o.sync_status === 'error') ||
    payments.some((p) => p.sync_status === 'error')
  );
}

/**
 * Reset error items back to 'pending' so they will be re-tried on next sync.
 * Call this if the user taps "Retry Sync" in the UI.
 */
export async function resetErrors() {
  const { dbExec } = await import('../database/db');
  await dbExec(
    "UPDATE offline_orders SET sync_status='pending', sync_error=NULL WHERE sync_status='error'",
  );
  await dbExec(
    "UPDATE offline_payments SET sync_status='pending', sync_error=NULL WHERE sync_status='error'",
  );
}

/**
 * Returns time since the last successful sync in milliseconds,
 * or Infinity if it has never synced.
 */
export async function timeSinceLastSync() {
  const last = await getSyncMeta('last_sync');
  if (!last) return Infinity;
  return Date.now() - new Date(last).getTime();
}

/**
 * Persist the last successful sync timestamp.
 */
export async function recordSyncSuccess() {
  await setSyncMeta('last_sync', new Date().toISOString());
}
