import client from './client';

export const apiOrderRating = (orderId) =>
  client.get(`/api/v1/orders/${orderId}/rating/`).then((r) => r.data);

export const apiRateOrder = (orderId, body) =>
  client.post(`/api/v1/orders/${orderId}/rating/`, body).then((r) => r.data);
