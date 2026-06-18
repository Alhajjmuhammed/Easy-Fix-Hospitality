import client from './client';

export const apiTables = () => client.get('/tables/').then((r) => r.data.tables);
export const apiTableDetail = (tableId) => client.get(`/tables/${tableId}/`).then((r) => r.data);
