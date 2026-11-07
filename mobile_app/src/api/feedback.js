import client from './client';

export const apiOrderRating = (orderId) =>
  client.get(`/orders/${orderId}/rating/`).then((r) => r.data);

export const apiRateOrder = (orderId, body) =>
  client.post(`/orders/${orderId}/rating/`, body).then((r) => r.data);
