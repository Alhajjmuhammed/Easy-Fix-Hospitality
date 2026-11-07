import client from './client';

export const apiOrderLoyalty = (orderId) =>
  client.get(`/orders/${orderId}/loyalty/`).then((r) => r.data);

export const apiLinkLoyaltyCustomer = (orderId, phone) =>
  client.post(`/orders/${orderId}/loyalty/`, { phone }).then((r) => r.data);

export const apiMyPoints = () =>
  client.get('/loyalty/me/').then((r) => r.data);
