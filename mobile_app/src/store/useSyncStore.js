import { create } from 'zustand';
import NetInfo from '@react-native-community/netinfo';
import { apiSyncPush, apiSyncPull } from '../api/sync';
import {
  getPendingOrders,
  getPendingPayments,
  getPendingBillRequests,
  markOrderSynced,
  markOrderError,
  markPaymentSynced,
  markPaymentError,
  markBillRequestSynced,
  saveCategories,
  saveTables,
  saveOrders,
  setSyncMeta,
} from '../database/operations';
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
    if (get().isSyncing) return;

    const netState = await NetInfo.fetch();
    if (!netState.isConnected) return;

    set({ isSyncing: true, syncErrors: [] });
    try {
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
        const payload = {
          orders: pendingOrders.map((o) => ({
            offline_id: o.offline_id,
            table_id: o.table_id ?? null,
            items: JSON.parse(o.items_json),
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
            // Payment for an offline order — check if already synced
            const rows = await dbQuery(
              "SELECT server_order_id FROM offline_orders WHERE offline_id = ? AND sync_status = 'synced'",
              [p.offline_order_ref],
            );
            if (rows.length && rows[0].server_order_id) {
              payload.payments.push({
                offline_id: p.offline_id,
                order_id: rows[0].server_order_id,
                amount: p.amount,
                payment_method: p.payment_method,
                reference_number: p.reference_number || '',
                notes: p.notes || '',
              });
            } else {
              // Order not yet synced — defer until after this push's order results arrive
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
                }
              }
            } catch { /* deferred payments will retry on next sync cycle */ }
          }
        }
      }

      // --- PULL ---
      const pullData = await apiSyncPull();
      if (pullData.categories) await saveCategories(pullData.categories);
      if (pullData.tables) await saveTables(pullData.tables);
      if (pullData.active_orders) await saveOrders(pullData.active_orders);

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
