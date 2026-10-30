import client from './client';

export const apiOrderLoyalty = (orderId) =>
  client.get(`/api/v1/orders/${orderId}/loyalty/`).then((r) => r.data);

export const apiLinkLoyaltyCustomer = (orderId, phone) =>
  client.post(`/api/v1/orders/${orderId}/loyalty/`, { phone }).then((r) => r.data);

export const apiMyPoints = () =>
  client.get('/api/v1/loyalty/me/').then((r) => r.data);
