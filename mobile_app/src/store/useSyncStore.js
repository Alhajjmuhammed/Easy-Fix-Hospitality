import { create } from 'zustand';
import NetInfo from '@react-native-community/netinfo';
import { apiSyncPush, apiSyncPull } from '../api/sync';
import { apiUpdateOrderStatus, apiOrderDetail } from '../api/orders';
import {
  getPendingOrders,
  getPendingPayments,
  getPendingBillRequests,
  markOrderSynced,
  markOrderError,
  markPaymentSynced,
  markPaymentError,
  markPaymentNotRecorded,
  markBillRequestSynced,
  markBillRequestError,
  saveCategories,
  saveTables,
  saveOrders,
  setSyncMeta,
  getPendingStatusChanges,
  markStatusChangeSynced,
  markStatusChangeError,
  countPendingQueue,
  deleteOfflineOrder,
  queueOwnerKey,
  getUnsyncedAppendStatuses,
  getSyncNotices,
  saveSyncNotices,
} from '../database/operations';
import { resetErrors } from '../utils/syncQueue';
import { dbQuery } from '../database/db';
import { isOnlineState } from '../utils/network';

// Server limits per /sync/push/ request (mobile_api/serializers.py SyncPushSerializer).
// A bigger request is refused as a whole, so the queue is sent in chunks within them.
export const SYNC_LIMITS = { orders: 50, payments: 100, bill_requests: 20 };

// Order workflow, used to tell whether a queued status change already happened.
const STATUS_RANK = ['pending', 'confirmed', 'preparing', 'ready', 'served', 'out_for_delivery', 'delivered'];
export const statusReached = (current, target) => {
  const c = STATUS_RANK.indexOf(current);
  const tgt = STATUS_RANK.indexOf(target);
  return c >= 0 && tgt >= 0 && c >= tgt;
};

const chunk = (arr, size) => {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
};

/** One kind of row, split into requests within the server limit. */
export const toChunks = (rows, kind) =>
  chunk(rows, SYNC_LIMITS[kind]).map((c) => ({ orders: [], payments: [], bill_requests: [], [kind]: c }));

// A whole request refused for a reason that is not about the rows themselves (session,
// rate limit, server down): leave the rows pending and try again later.
const isTransientStatus = (status) => status === 401 || status === 403 || status === 408 || status === 429 || status >= 500;

const serverMessage = (err) => {
  const d = err?.response?.data;
  if (d && typeof d === 'object') {
    if (typeof d.error === 'string') return d.error;
    if (typeof d.detail === 'string') return d.detail;
    const first = Object.entries(d)[0];
    if (first) return `${first[0]}: ${JSON.stringify(first[1]).slice(0, 120)}`;
  }
  return err?.message || 'Request failed';
};

const paymentPayload = (p, orderId) => ({
  offline_id: p.offline_id,
  order_id: orderId,
  amount: p.amount,
  payment_method: p.payment_method,
  reference_number: p.reference_number || '',
  notes: p.notes || '',
  // This build understands status 'not_recorded' (nothing owed): the server returns it
  // instead of an error that would be retried forever. Older builds don't send this.
  accepts_not_recorded: true,
});

// ── Session guard ────────────────────────────────────────────────────────────
// A sync works for the user who was logged in when it started. logout() cancels it
// (generation bump) and a different login changes the session key: the running sync then
// stops before its next request, leaving the rows pending for their own user. Results of a
// request already in flight are still applied (the server did record them).
let _generation = 0;
let _rerun = false;          // a sync was requested while one was running
const _token = () => {
  try { return require('./useAuthStore').useAuthStore.getState().token; } catch { return null; }
};
const _sessionKey = () => `${queueOwnerKey()}|${_token() || ''}`;

// ── Sync notices: kept in sync_meta until dismissed, tagged with their owner ─────────────
let _notices = null;         // every owner's notices (loaded once from sync_meta)
let _noticesFor = null;      // owner key whose notices are in the store
const _loadNotices = async () => {
  if (_notices === null) _notices = await getSyncNotices();
  return _notices;
};

export const useSyncStore = create((set, get) => ({
  isSyncing: false,
  lastSyncTime: null,
  pendingCount: 0,
  // Problems of the last sync run (cleared when the next run starts).
  syncErrors: [],
  // Things the cashier must know about after a sync (price changed, item removed, payment
  // capped / not recorded, refused batch, refused status change). Kept until dismissed,
  // also across app restarts.
  syncWarnings: [],

  /** Cancel a running sync at its next step (logout, user switch). */
  cancelSync: () => { _generation += 1; _rerun = false; },

  // Called on logout — the next user starts clean. Does NOT clear isSyncing: a sync that is
  // still finishing keeps its lock (it stops at its next step), so no second sync can
  // overlap it; a sync asked for meanwhile runs right after it.
  reset: () => {
    get().cancelSync();
    _noticesFor = null;
    set({ lastSyncTime: null, pendingCount: 0, syncErrors: [], syncWarnings: [] });
  },

  /** Show the persisted notices of the logged-in user. */
  loadSyncWarnings: async () => {
    try {
      const key = queueOwnerKey();
      const all = await _loadNotices();
      _noticesFor = key;
      set({ syncWarnings: all.filter((n) => n.owner === key) });
    } catch {
      // best-effort
    }
  },

  /** Save a notice for `owner` (the user + restaurant whose sync produced it — a sync that
   *  finishes after a logout/login still files it under the user it ran for). It is shown
   *  only while that owner is logged in. */
  addSyncWarning: async (w, owner = queueOwnerKey()) => {
    if (!owner || owner.startsWith('null:')) return;   // nobody to file it under
    try {
      const all = await _loadNotices();
      _notices = [...all.filter((x) => !(x.key === w.key && x.owner === owner)),
        { ...w, owner, at: new Date().toISOString() }];
      await saveSyncNotices(_notices);
    } catch {
      // still shown for this session
    }
    if (owner === queueOwnerKey()) {
      set((s) => ({ syncWarnings: [...s.syncWarnings.filter((x) => x.key !== w.key), { ...w, owner }] }));
    }
  },
  dismissSyncWarning: async (key) => {
    const owner = queueOwnerKey();
    set((s) => ({ syncWarnings: s.syncWarnings.filter((x) => x.key !== key) }));
    try {
      _notices = (await _loadNotices()).filter((x) => !(x.key === key && x.owner === owner));
      await saveSyncNotices(_notices);
    } catch { /* best-effort */ }
  },
  clearSyncWarnings: async () => {
    const owner = queueOwnerKey();
    set({ syncWarnings: [] });
    try {
      _notices = (await _loadNotices()).filter((x) => x.owner !== owner);
      await saveSyncNotices(_notices);
    } catch { /* best-effort */ }
  },

  /** Delete a queued (unsynced) order and its queued payments. Refused while a sync runs:
   *  the sync may already be sending it, and the server would create an order the phone
   *  no longer knows about. Holds the sync lock so a sync cannot start halfway either. */
  deleteQueuedOrder: async (offlineId) => {
    if (get().isSyncing) {
      const err = new Error('Sync in progress – try again in a moment');
      err.code = 'SYNC_IN_PROGRESS';
      throw err;
    }
    set({ isSyncing: true });
    try {
      await deleteOfflineOrder(offlineId);
    } finally {
      set({ isSyncing: false });
      // A sync asked for while the delete held the lock runs now (same as triggerSync).
      if (_rerun) {
        _rerun = false;
        setTimeout(() => { get().triggerSync(); }, 0);
      }
    }
    await get().refreshPendingCount();
  },

  // Same rows the sync sends: orders, payments, bill requests AND station status changes.
  // Also (re)loads the persisted notices when the logged-in user changed.
  refreshPendingCount: async () => {
    try {
      set({ pendingCount: await countPendingQueue() });
    } catch {
      // best-effort
    }
    if (_noticesFor !== queueOwnerKey()) await get().loadSyncWarnings();
  },

  triggerSync: async () => {
    // Atomically claim the sync lock before the first await so two callers
    // that both see isSyncing===false cannot both proceed past the guard.
    if (get().isSyncing) { _rerun = true; return; }
    if (!_token()) return;                      // logged out: nothing of anyone is sent
    set({ isSyncing: true });
    _rerun = false;

    const generation = _generation;
    const session = _sessionKey();
    const ownerKey = queueOwnerKey();           // whose rows (and notices) this sync is about
    // false once this sync must stop: logout, or another user/restaurant/token is active
    const alive = () => generation === _generation && _sessionKey() === session;

    try {
      let online = false;
      try {
        online = isOnlineState(await NetInfo.fetch());
      } catch {
        online = false;
      }
      if (!online) return;

      set({ syncErrors: [] });
      const addError = (e) => set((s) => ({ syncErrors: [...s.syncErrors, e] }));
      const warn = (w) => get().addSyncWarning(w, ownerKey);

      // Each step has its own try: a failure in one never stops the others.
      // --- PUSH ---
      try {
        await get()._push(addError, warn, alive);
      } catch (err) {
        addError({ type: err.response ? 'push' : 'network', error: err.message });
      }

      // --- SYNC PENDING STATUS CHANGES (from station offline updates) ---
      try {
        await get()._replayStatusChanges(addError, warn, alive);
      } catch (err) {
        addError({ type: 'status_change', error: err.message });
      }

      // --- PULL ---
      try {
        if (alive()) {
          const pullData = await apiSyncPull();
          if (alive()) {
            if (Array.isArray(pullData.categories)) await saveCategories(pullData.categories);
            if (Array.isArray(pullData.tables)) await saveTables(pullData.tables);
            if (Array.isArray(pullData.active_orders)) await saveOrders(pullData.active_orders);

            const now = new Date().toISOString();
            await setSyncMeta('last_sync', now);
            set({ lastSyncTime: now });
          }
        }
      } catch (err) {
        addError({ type: err.response ? 'pull' : 'network', error: err.message });
      }
    } finally {
      await get().refreshPendingCount();
      set({ isSyncing: false });
      // Asked for while this one ran (e.g. another user logged in): run it now for them.
      if (_rerun) {
        _rerun = false;
        setTimeout(() => { get().triggerSync(); }, 0);
      }
    }
  },

  // ── push: ALL orders (new + added items) first, then payments, then bill requests ──
  // Orders go first so a payment never reaches an order whose offline-added items are not
  // on the server yet (it would be capped at the old total and the items refused as "paid").
  _push: async (addError, warn, alive = () => true) => {
    // Reset error items from the previous cycle so they are retried automatically
    await resetErrors();

    const [pendingOrders, pendingPayments, pendingBillRequests] = await Promise.all([
      getPendingOrders(),
      getPendingPayments(),
      getPendingBillRequests(),
    ]);
    if (!pendingOrders.length && !pendingPayments.length && !pendingBillRequests.length) return;

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
    const localOrders = Object.fromEntries(validOrders.map((o) => [o.offline_id, o]));

    const orderRows = validOrders.map((o) => ({
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
    }));
    const billRows = pendingBillRequests.map((b) => ({ offline_id: b.offline_id, table_id: b.table_id }));

    const newlySynced = {}; // offline_id → server_order_id from THIS cycle's order results

    const applyResults = async (results = {}) => {
      for (const r of results.orders || []) {
        if (r.status === 'created' || r.status === 'duplicate') {
          await markOrderSynced(r.offline_id, r.order_id, r.order_number);
          newlySynced[r.offline_id] = r.order_id;
          const local = localOrders[r.offline_id];
          const serverTotal = r.total_amount != null ? parseFloat(r.total_amount) : null;
          const totalChanged = r.status === 'created' && !local?.existing_order_id && local && serverTotal != null
            && Math.abs(serverTotal - (local.total_amount || 0)) > 0.01;
          if (r.status === 'created' && (r.warning || totalChanged)) {
            await warn({
              key: `order:${r.offline_id}`,
              kind: 'order',
              order_number: r.order_number,
              appended: !!local?.existing_order_id,
              local_total: local?.total_amount ?? null,
              server_total: totalChanged ? serverTotal : null,
              dropped: (r.dropped_item_ids || []).length,
              price_changes: (r.price_changes || []).length,
            });
          }
        } else {
          await markOrderError(r.offline_id, r.error);
          addError({ type: 'order', ...r });
        }
      }
      for (const r of results.payments || []) {
        if (r.status === 'created' || r.status === 'duplicate') {
          await markPaymentSynced(r.offline_id, r.payment_id);
          if (r.amount_recorded != null && r.difference != null) {
            await warn({
              key: `payment:${r.offline_id}`,
              kind: 'payment',
              order_number: r.order_number,
              requested: r.amount_requested,
              recorded: r.amount_recorded,
              difference: r.difference,
            });
          }
        } else if (r.status === 'not_recorded') {
          // Nothing was owed any more: finished, never retried; the cashier must settle it.
          await markPaymentNotRecorded(r.offline_id, r.warning);
          await warn({
            key: `payment:${r.offline_id}`,
            kind: 'payment_not_recorded',
            order_number: r.order_number,
            requested: r.amount_requested,
          });
        } else {
          await markPaymentError(r.offline_id, r.error);
          addError({ type: 'payment', ...r });
        }
      }
      for (const r of results.bill_requests || []) {
        if (r.status === 'created' || r.status === 'duplicate' || r.status === 'already_paid') {
          await markBillRequestSynced(r.offline_id, r.bill_request_id);
        } else {
          await markBillRequestError(r.offline_id, r.error);
          addError({ type: 'bill_request', ...r });
        }
      }
    };

    // Send chunks one by one. Returns false when this sync must stop (session changed,
    // network/server unavailable): the rows not sent stay pending for the next run.
    const sendChunks = async (chunks) => {
      for (const payload of chunks) {
        if (!alive()) return false;
        try {
          const { results = {} } = await apiSyncPush(payload);
          await applyResults(results);
        } catch (err) {
          const status = err.response?.status;
          if (!err.response || isTransientStatus(status)) {
            addError({ type: 'network', status: status || null, error: err.message });
            return false;
          }
          // The server refused the whole request (4xx). Mark its rows failed with the
          // reason so the cashier sees them as errors, not as "will sync automatically".
          const msg = `Server refused the sync (${status}): ${serverMessage(err)}`;
          for (const o of payload.orders) await markOrderError(o.offline_id, msg);
          for (const p of payload.payments) await markPaymentError(p.offline_id, msg);
          for (const b of payload.bill_requests) await markBillRequestError(b.offline_id, msg);
          const count = payload.orders.length + payload.payments.length + payload.bill_requests.length;
          addError({ type: 'batch', status, error: msg, count });
          await warn({ key: 'batch', kind: 'batch', status, error: serverMessage(err), count });
        }
      }
      return true;
    };

    // 1. Every order chunk — new orders and items added to server orders.
    if (!(await sendChunks(toChunks(orderRows, 'orders')))) return;
    if (!alive()) return;

    // 2. Payments. Resolve each one's server order now that this run's orders are in.
    const payRows = [];
    const direct = pendingPayments.filter((p) => !p.offline_order_ref);
    // A payment for a server order with items added offline that are not on the server
    // yet waits for them (it would be capped at the old total otherwise).
    const appendState = await getUnsyncedAppendStatuses(direct.map((p) => p.order_id));
    for (const p of pendingPayments) {
      if (!p.offline_order_ref) {
        const st = appendState[p.order_id];
        if (st === 'error') {
          await markPaymentError(p.offline_id,
            'Cannot sync: items added offline to this order failed to sync. Resolve them first.');
        } else if (st !== 'pending') {
          payRows.push(paymentPayload(p, p.order_id));
        } // 'pending': waits for the next run
        continue;
      }
      // Payment for an order made offline: needs that order's server id
      let serverId = newlySynced[p.offline_order_ref];
      if (!serverId) {
        const rows = await dbQuery(
          'SELECT server_order_id, sync_status FROM offline_orders WHERE offline_id = ?',
          [p.offline_order_ref],
        );
        const orderRow = rows[0];
        if (orderRow && orderRow.sync_status === 'synced' && orderRow.server_order_id) {
          serverId = orderRow.server_order_id;
        } else if (orderRow && orderRow.sync_status === 'error') {
          // Order failed — mark payment as error so it is not deferred forever.
          // Staff must dismiss the order to resolve.
          await markPaymentError(
            p.offline_id,
            'Cannot sync: parent order failed to sync. Dismiss the order to resolve.',
          );
          continue;
        }
      }
      if (serverId) payRows.push(paymentPayload(p, serverId));
      // else: order not synced yet — payment picked up on a later run
    }
    if (!(await sendChunks(toChunks(payRows, 'payments')))) return;

    // 3. Bill requests last (after payments, the same order the server uses inside one request).
    await sendChunks(toChunks(billRows, 'bill_requests'));
  },

  // ── replay station status changes made offline, in the order they were made ──
  _replayStatusChanges: async (addError, warn, alive = () => true) => {
    const pendingStatusChanges = await getPendingStatusChanges();
    for (const change of pendingStatusChanges) {
      if (!alive()) return;
      try {
        await apiUpdateOrderStatus(change.order_id, change.new_status);
        await markStatusChangeSynced(change.id);
      } catch (e) {
        // Network error: keep this one and the later ones pending, in order.
        if (!e.response || e.response.status === 401) break;
        // Refused. If the order is already in that status or later (e.g. the request
        // went through but the reply was lost, or someone else moved it on), it is done.
        let current = null;
        try {
          current = await apiOrderDetail(change.order_id);
        } catch (e2) {
          // Can't check now (network, server trouble): try again on a later run.
          if (!e2.response || isTransientStatus(e2.response.status)) break;
        }
        if (current && statusReached(current.status, change.new_status)) {
          await markStatusChangeSynced(change.id);
          continue;
        }
        if (isTransientStatus(e.response.status)) break; // server trouble: retry later
        // Any other refusal is permanent: never resent, shown to staff.
        const msg = serverMessage(e);
        await markStatusChangeError(change.id, msg);
        addError({ type: 'status_change', order_id: change.order_id, error: msg });
        await warn({
          key: `status:${change.id}`,
          kind: 'status',
          order_number: current?.order_number || String(change.order_id),
          new_status: change.new_status,
          error: msg,
        });
      }
    }
  },
}));

