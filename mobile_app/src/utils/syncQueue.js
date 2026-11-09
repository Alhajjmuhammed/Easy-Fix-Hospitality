/**
 * syncQueue.js — helpers for managing the offline sync queue.
 *
 * These are thin wrappers over database/operations.js used by useSyncStore
 * to retry failed items and report queue depth.
 */

import { countPendingQueue } from '../database/operations';
import { dbExec, dbQuery } from '../database/db';

/**
 * Returns total count of items waiting to sync for the logged-in user
 * (orders, payments, bill requests and station status changes) — the same
 * number as the pending badge (useSyncStore.refreshPendingCount).
 */
export async function getPendingCount() {
  return countPendingQueue();
}

/**
 * Returns true if any items have been in error state.
 */
export async function hasErrors() {
  const [errOrders, errPayments, errBillReqs, errStatusChanges] = await Promise.all([
    dbQuery("SELECT 1 FROM offline_orders WHERE sync_status='error' LIMIT 1"),
    dbQuery("SELECT 1 FROM offline_payments WHERE sync_status='error' LIMIT 1"),
    dbQuery("SELECT 1 FROM offline_bill_requests WHERE sync_status='error' LIMIT 1"),
    dbQuery("SELECT 1 FROM offline_status_changes WHERE sync_status IN ('error', 'failed') LIMIT 1"),
  ]);
  return errOrders.length > 0 || errPayments.length > 0 || errBillReqs.length > 0 || errStatusChanges.length > 0;
}

/**
 * Reset error items back to 'pending' so they will be re-tried on next sync.
 * Called at the start of every sync and if the user taps "Retry Sync" in the UI.
 *
 * Station status changes refused by the server are 'failed' (permanent) and are NOT
 * reset — resending them would be refused again on every sync. Only the old 'error'
 * state (written by earlier builds) is reset, so those rows get one more try under
 * the new rules (already-in-that-status counts as done).
 */
export async function resetErrors() {
  await dbExec(
    "UPDATE offline_orders SET sync_status='pending', error_message=NULL WHERE sync_status='error'",
  );
  await dbExec(
    "UPDATE offline_payments SET sync_status='pending', error_message=NULL WHERE sync_status='error'",
  );
  await dbExec(
    "UPDATE offline_bill_requests SET sync_status='pending', error_message=NULL WHERE sync_status='error'",
  );
  await dbExec(
    "UPDATE offline_status_changes SET sync_status='pending' WHERE sync_status='error'",
  );
}
