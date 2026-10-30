import client from './client';

export const apiMobileMoneyInfo = (orderId) =>
  client.get(`/api/v1/orders/${orderId}/mobile-money/`).then((r) => r.data);

export const apiMobileMoneyStart = (orderId, body) =>
  client.post(`/api/v1/orders/${orderId}/mobile-money/`, body).then((r) => r.data);

export const apiMobileMoneyStatus = (chargeId) =>
  client.get(`/api/v1/mobile-money/${chargeId}/`).then((r) => r.data);
