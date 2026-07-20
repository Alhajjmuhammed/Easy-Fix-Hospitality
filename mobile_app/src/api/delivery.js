import client from './client';

export const apiRidersList = (onlyAvailable = false, global = false) =>
  client.get('/delivery/riders/', {
    params: {
      ...(onlyAvailable ? { available: '1' } : {}),
      ...(global ? { scope: 'global' } : {}),
    },
  }).then(r => r.data.riders);

export const apiAssignRider = (orderId, riderId) =>
  client.post('/delivery/assign/', { order_id: orderId, rider_id: riderId }).then(r => r.data);

export const apiAutoAssign = (orderId) =>
  client.post('/delivery/auto-assign/', { order_id: orderId }).then(r => r.data);

export const apiMyAssignments = () =>
  client.get('/delivery/assignments/').then(r => r.data);

export const apiTrackOrder = (orderId) =>
  client.get(`/delivery/${orderId}/track/`).then(r => r.data);

export const apiMarkPickedUp = (orderId) =>
  client.post(`/delivery/${orderId}/pickup/`).then(r => r.data);

export const apiMarkDelivered = (orderId) =>
  client.post(`/delivery/${orderId}/complete/`).then(r => r.data);

export const apiUpdateLocation = (lat, lng) =>
  client.post('/delivery/location/', { lat, lng }).then(r => r.data);

export const apiToggleAvailability = () =>
  client.post('/delivery/availability/').then(r => r.data);
