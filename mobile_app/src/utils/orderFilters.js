// Order list helpers shared by the staff screens. No React Native imports (tested in Node).

const pad = (n) => String(n).padStart(2, '0');

/** 'YYYY-MM-DD' of `d` in the phone's local time zone (same as DateTimeChips isoDate). */
export const localIsoDate = (d = new Date()) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** True when the ISO timestamp falls on today's local date. */
export function isLocalToday(iso, now = new Date()) {
  if (!iso) return false;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return false;
  return localIsoDate(d) === localIsoDate(now);
}

/** Orders still being worked on. */
export const IN_PROGRESS_STATUSES = ['pending', 'confirmed', 'preparing', 'ready', 'out_for_delivery'];
/** Finished for the kitchen but the bill may still be open. */
export const FINISHED_STATUSES = ['served', 'delivered'];

/** Cashier "Active": in progress, or served/delivered and not fully paid. */
export function isActiveOrder(o) {
  if (!o) return false;
  if (IN_PROGRESS_STATUSES.includes(o.status)) return true;
  return FINISHED_STATUSES.includes(o.status) && o.payment_status !== 'paid';
}

/** Merge order lists from several requests: one row per id, newest first. */
export function mergeOrders(...lists) {
  const seen = new Map();
  for (const list of lists) {
    for (const o of list || []) {
      if (o && o.id != null && !seen.has(o.id)) seen.set(o.id, o);
    }
  }
  const time = (o) => { const t = new Date(o.created_at || 0).getTime(); return isNaN(t) ? 0 : t; };
  return [...seen.values()].sort((a, b) => time(b) - time(a));
}
