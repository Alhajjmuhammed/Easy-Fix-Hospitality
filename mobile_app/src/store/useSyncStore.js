import { create } from 'zustand';
import NetInfo from '@react-native-community/netinfo';
import { apiSyncPush, apiSyncPull } from '../api/sync';
import { apiUpdateOrderStatus } from '../api/orders';
import {
  getPendingOrders,
  getPendingPayments,
  getPendingBillRequests,
  markOrderSynced,
  markOrderError,
  markPaymentSynced,
  markPaymentError,
  markBillRequestSynced,
  markBillRequestError,
  saveCategories,
  saveTables,
  saveOrders,
  setSyncMeta,
  getPendingStatusChanges,
  markStatusChangeSynced,
  markStatusChangeError,
} from '../database/operations';
import { resetErrors } from '../utils/syncQueue';
import { dbQuery } from '../database/db';

export const useSyncStore = create((set, get) => ({
  isSyncing: false,
  lastSyncTime: null,
  pendingCount: 0,
  syncErrors: [],

  // Called on logout — resets all state so next user starts clean
  reset: () => set({ isSyncing: false, lastSyncTime: null, pendingCount: 0, syncErrors: [] }),

  refreshPendingCount: async () => {
    try {
      const [orders, payments, billRequests] = await Promise.all([
        getPendingOrders(),
        getPendingPayments(),
        getPendingBillRequests(),
      ]);
      set({ pendingCount: orders.length + payments.length + billRequests.length });
    } catch {
      // best-effort
    }
  },

  triggerSync: async () => {
    // Atomically claim the sync lock before the first await so two callers
    // that both see isSyncing===false cannot both proceed past the guard.
    const claimed = !get().isSyncing;
    if (!claimed) return;
    set({ isSyncing: true });

    const netState = await NetInfo.fetch();
    if (!netState.isConnected) {
      set({ isSyncing: false });
      return;
    }
    set({ syncErrors: [] });
    try {
      // Reset error items from the previous cycle so they are retried automatically
      await resetErrors();

      // --- PUSH ---
      const [pendingOrders, pendingPayments, pendingBillRequests] =
        await Promise.all([
          getPendingOrders(),
          getPendingPayments(),
          getPendingBillRequests(),
        ]);

      if (
        pendingOrders.length ||
        pendingPayments.length ||
        pendingBillRequests.length
      ) {
        // Pre-filter orders: skip any with corrupted items_json
        const validOrders = [];
        for (const o of pendingOrders) {
          let items;
          try { items = JSON.parse(o.items_json); } catch (_) { items = null; }
          if (!Array.isArray(items)) {
            await markOrderError(o.offline_id, 'Corrupted order data — cannot sync');
            continue;
          }
          validOrders.push({ ...o, _parsedItems: items });
        }

        const payload = {
          orders: validOrders.map((o) => ({
            offline_id: o.offline_id,
            existing_order_id: o.existing_order_id ?? null,
            local_print: !!(o.local_print_fired),
            table_id: o.table_id ?? null,
            items: o._parsedItems,
            special_instructions: o.special_instructions || '',
            restaurant_id: o.restaurant_id,
            order_type: o.order_type || 'dine-in',
            delivery_address: o.delivery_address || '',
            delivery_phone: o.delivery_phone || '',
            delivery_lat: o.delivery_lat ?? null,
            delivery_lng: o.delivery_lng ?? null,
          })),
          payments: [],
          bill_requests: pendingBillRequests.map((b) => ({
            offline_id: b.offline_id,
            table_id: b.table_id,
          })),
        };

        // Resolve payments: regular server-order payments go straight in;
        // offline_order_ref payments need the server order ID — use already-synced
        // orders first, then fall back to this cycle's results after the push.
        const deferredPayments = []; // payments whose order is being synced this cycle
        for (const p of pendingPayments) {
          if (!p.offline_order_ref) {
            // Normal payment for a known server order
            payload.payments.push({
              offline_id: p.offline_id,
              order_id: p.order_id,
              amount: p.amount,
              payment_method: p.payment_method,
              reference_number: p.reference_number || '',
              notes: p.notes || '',
            });
          } else {
            // Payment for an offline order — check its sync state
            const rows = await dbQuery(
              'SELECT server_order_id, sync_status FROM offline_orders WHERE offline_id = ?',
              [p.offline_order_ref],
            );
            const orderRow = rows[0];
            if (orderRow && orderRow.sync_status === 'synced' && orderRow.server_order_id) {
              // Order already on server — include payment directly
              payload.payments.push({
                offline_id: p.offline_id,
                order_id: orderRow.server_order_id,
                amount: p.amount,
                payment_method: p.payment_method,
                reference_number: p.reference_number || '',
                notes: p.notes || '',
              });
            } else if (orderRow && orderRow.sync_status === 'error') {
              // Order permanently failed — mark payment as error so it is not
              // deferred forever. Staff must dismiss the order to resolve.
              await markPaymentError(
                p.offline_id,
                'Cannot sync: parent order failed to sync. Dismiss the order to resolve.',
              );
            } else {
              // Order not yet synced this cycle — defer until after push results arrive
              deferredPayments.push(p);
            }
          }
        }

        const { results = {} } = await apiSyncPush(payload);

        // Build map of offline_id → server_order_id from THIS cycle's order results
        const newlySynced = {};
        for (const r of results.orders || []) {
          if (r.status === 'created' || r.status === 'duplicate') {
            await markOrderSynced(r.offline_id, r.order_id, r.order_number);
            newlySynced[r.offline_id] = r.order_id;
          } else {
            await markOrderError(r.offline_id, r.error);
            set((s) => ({ syncErrors: [...s.syncErrors, { type: 'order', ...r }] }));
          }
        }
        for (const r of results.payments || []) {
          if (r.status === 'created' || r.status === 'duplicate') {
            await markPaymentSynced(r.offline_id, r.payment_id);
          } else {
            await markPaymentError(r.offline_id, r.error);
            set((s) => ({ syncErrors: [...s.syncErrors, { type: 'payment', ...r }] }));
          }
        }
        for (const r of results.bill_requests || []) {
          if (r.status === 'created' || r.status === 'duplicate') {
            await markBillRequestSynced(r.offline_id, r.bill_request_id);
          } else {
            await markBillRequestError(r.offline_id, r.error);
            set((s) => ({ syncErrors: [...s.syncErrors, { type: 'bill_request', ...r }] }));
          }
        }

        // Second pass: push payments that were waiting for this cycle's orders
        if (deferredPayments.length) {
          const resolvedNow = [];
          for (const p of deferredPayments) {
            const serverId = newlySynced[p.offline_order_ref];
            if (serverId) {
              resolvedNow.push({
                offline_id: p.offline_id,
                order_id: serverId,
                amount: p.amount,
                payment_method: p.payment_method,
                reference_number: p.reference_number || '',
                notes: p.notes || '',
              });
            }
            // else: order failed/skipped — payment picked up on next sync cycle
          }
          if (resolvedNow.length) {
            try {
              const { results: pmtResults = {} } = await apiSyncPush({
                orders: [],
                payments: resolvedNow,
                bill_requests: [],
              });
              for (const r of pmtResults.payments || []) {
                if (r.status === 'created' || r.status === 'duplicate') {
                  await markPaymentSynced(r.offline_id, r.payment_id);
                } else {
                  await markPaymentError(r.offline_id, r.error);
                  set((s) => ({ syncErrors: [...s.syncErrors, { type: 'payment', ...r }] }));
                }
              }
            } catch (err) {
              const isNetworkError = !err.response;
              if (!isNetworkError) {
                // Server/validation error — mark as error so staff can see it
                for (const p of resolvedNow) {
                  await markPaymentError(p.offline_id, 'Payment sync failed — tap to delete');
                }
              }
              // Network error: leave as pending so the next sync cycle retries automatically
            }
          }
        }
      }

      // --- SYNC PENDING STATUS CHANGES (from station offline updates) ---
      const pendingStatusChanges = await getPendingStatusChanges();
      for (const change of pendingStatusChanges) {
        try {
          await apiUpdateOrderStatus(change.order_id, change.new_status);
          await markStatusChangeSynced(change.id);
        } catch (e) {
          await markStatusChangeError(change.id);
        }
      }

      // --- PULL ---
      const pullData = await apiSyncPull();
      if (Array.isArray(pullData.categories)) await saveCategories(pullData.categories);
      if (Array.isArray(pullData.tables)) await saveTables(pullData.tables);
      if (Array.isArray(pullData.active_orders)) await saveOrders(pullData.active_orders);

      const now = new Date().toISOString();
      await setSyncMeta('last_sync', now);
      set({ lastSyncTime: now });

      await get().refreshPendingCount();
    } catch (err) {
      set((s) => ({ syncErrors: [...s.syncErrors, { type: 'network', error: err.message }] }));
    } finally {
      set({ isSyncing: false });
    }
  },
}));
