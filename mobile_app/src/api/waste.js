import client from './client';

export const apiRecordWaste = (data) =>
  client.post('/waste/', data).then((r) => r.data);

export const apiWasteLogs = () =>
  client.get('/waste/').then((r) => r.data);
