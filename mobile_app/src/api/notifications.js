import client from './client';

export const apiSavePushToken = (token) =>
  client.post('/auth/push-token/', { token }).then((r) => r.data);
