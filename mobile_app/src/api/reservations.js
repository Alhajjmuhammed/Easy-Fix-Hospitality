import client from './client';

// Customers: their own bookings. Staff: the restaurant's bookings for { date, status }.
export const apiReservations = (params = {}) =>
  client.get('/reservations/', { params }).then((r) => r.data);

// Customers: book at body.restaurant_id. Staff: add a booking at their restaurant.
export const apiCreateReservation = (body) =>
  client.post('/reservations/', body).then((r) => r.data);

export const apiReservationStatus = (id, status) =>
  client.post(`/reservations/${id}/status/`, { status }).then((r) => r.data);

export const apiReservationTable = (id, tableId) =>
  client.post(`/reservations/${id}/table/`, { table_id: tableId || null }).then((r) => r.data);

export const apiCancelReservation = (id) =>
  client.post(`/reservations/${id}/cancel/`).then((r) => r.data);
