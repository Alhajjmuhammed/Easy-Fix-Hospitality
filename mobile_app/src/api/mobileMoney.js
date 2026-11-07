import client from './client';

export const apiMobileMoneyInfo = (orderId) =>
  client.get(`/orders/${orderId}/mobile-money/`).then((r) => r.data);

// The server may wait on the provider twice (login + request): allow longer than the usual 15 s
export const apiMobileMoneyStart = (orderId, body) =>
  client.post(`/orders/${orderId}/mobile-money/`, body, { timeout: 30000 }).then((r) => r.data);

export const apiMobileMoneyStatus = (chargeId) =>
  client.get(`/mobile-money/${chargeId}/`).then((r) => r.data);
