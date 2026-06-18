import client from './client';

export const apiBillRequests = () =>
  client.get('/bill-requests/').then((r) => r.data);
export const apiCreateBillRequest = (tableId) =>
  client.post('/bill-requests/', { table_id: tableId }).then((r) => r.data);
export const apiCompleteBillRequest = (requestId) =>
  client.post(`/bill-requests/${requestId}/complete/`).then((r) => r.data);
