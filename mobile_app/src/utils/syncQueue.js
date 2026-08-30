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
import { dbExec, dbQuery } from '../database/db';

/**
 * Returns total count of items waiting to sync.
 */
export async function getPendingCount() {
  const [orders, payments, billRequests] = await Promise.all([
    getPendingOrders().catch(() => []),
    getPendingPayments().catch(() => []),
    getPendingBillRequests().catch(() => []),
  ]);
  return orders.length + payments.length + billRequests.length;
}

/**
 * Returns true if any items have been in error state.
 */
export async function hasErrors() {
  const [errOrders, errPayments] = await Promise.all([
    dbQuery("SELECT 1 FROM offline_orders WHERE sync_status='error' LIMIT 1"),
    dbQuery("SELECT 1 FROM offline_payments WHERE sync_status='error' LIMIT 1"),
  ]);
  return errOrders.length > 0 || errPayments.length > 0;
}

/**
 * Reset error items back to 'pending' so they will be re-tried on next sync.
 * Call this if the user taps "Retry Sync" in the UI.
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

