import client from './client';

// A push can carry up to 50 orders + 100 payments; give it more than the default 15 s.
// Resending after a timeout is safe: every row carries an offline_id the server de-duplicates.
export const SYNC_PUSH_TIMEOUT_MS = 60000;

export const apiSyncPush = (data) =>
  client.post('/sync/push/', data, { timeout: SYNC_PUSH_TIMEOUT_MS }).then((r) => r.data);
export const apiSyncPull = () => client.get('/sync/pull/').then((r) => r.data);
