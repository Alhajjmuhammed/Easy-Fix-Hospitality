import client from './client';

export const apiOrders = (params = {}) =>
  client.get('/orders/', { params }).then((r) => r.data.orders);
export const apiOrderDetail = (orderId) =>
  client.get(`/orders/${orderId}/`).then((r) => r.data.order);
export const apiPlaceOrder = (data, localPrint = false) =>
  client.post('/orders/', data, localPrint ? { headers: { 'X-Local-Print': 'true' } } : {}).then((r) => r.data);
export const apiUpdateOrderStatus = (orderId, orderStatus) =>
  client.patch(`/orders/${orderId}/status/`, { status: orderStatus }).then((r) => r.data);
export const apiPrintBill = (orderId) =>
  client.post(`/orders/${orderId}/print-bill/`).then((r) => {
    const data = r.data;
    if (data && data.success === false) {
      return Promise.reject({ response: { data: { error: data.message || 'Print failed' } } });
    }
    return data;
  });
export const apiTransferTable = (orderId, targetTableId) =>
  client.post(`/orders/${orderId}/transfer/`, { target_table_id: targetTableId }).then((r) => r.data);
export const apiCancelOrder = (orderId, reason = '') =>
  client.post(`/orders/${orderId}/cancel/`, { reason }).then((r) => r.data);
export const apiAddItemsToOrder = (orderId, data, localPrint = false) =>
  client.post(`/orders/${orderId}/add-items/`, data, localPrint ? { headers: { 'X-Local-Print': 'true' } } : {}).then((r) => r.data);
export const apiActiveOrderForTable = (tableId) =>
  client.get(`/tables/${tableId}/active-order/`).then((r) => r.data.order);
export const apiActiveOrdersForTable = (tableId) =>
  client.get(`/tables/${tableId}/active-orders/`).then((r) => r.data.orders);
export const apiCancelOrderItem = (itemId, reason = '') =>
  client.post(`/orders/items/${itemId}/cancel/`, { reason }).then((r) => r.data);
