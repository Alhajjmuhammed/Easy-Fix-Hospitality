import client from './client';

export const apiSyncPush = (data) => client.post('/sync/push/', data).then((r) => r.data);
export const apiSyncPull = () => client.get('/sync/pull/').then((r) => r.data);
