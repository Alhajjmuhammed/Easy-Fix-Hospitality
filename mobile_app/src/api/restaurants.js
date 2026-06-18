import client from './client';

export const apiRestaurants = () =>
  client.get('/restaurants/').then((r) => r.data.restaurants);

/**
 * Resolve a physical QR code string to a restaurant object.
 * Returns { id, name, description, address, logo_url } on success.
 * Throws an axios error (response.data.error has the message) on failure.
 */
export const apiRestaurantByQR = (code) =>
  client.get('/restaurants/scan/', { params: { code } }).then((r) => r.data.restaurant);
