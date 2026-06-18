import client from './client';

export const apiPayments = (params = {}) =>
  client.get('/payments/', { params }).then((r) => r.data.payments);
export const apiProcessPayment = (data) =>
  client.post('/payments/', data).then((r) => r.data);
export const apiVoidPayment = (paymentId, reason) =>
  client.post(`/payments/${paymentId}/void/`, { reason }).then((r) => r.data);
export const apiPaymentReceipt = (paymentId) =>
  client.get(`/payments/${paymentId}/receipt/`).then((r) => r.data);
export const apiReprintReceipt = (paymentId) =>
  client.post(`/payments/${paymentId}/reprint/`).then((r) => {
    const data = r.data;
    if (data && data.success === false) {
      return Promise.reject({ response: { data: { error: data.message || 'Reprint failed' } } });
    }
    return data;
  });
