const NOMINATIM_SEARCH  = 'https://nominatim.openstreetmap.org/search';
const NOMINATIM_REVERSE = 'https://nominatim.openstreetmap.org/reverse';
const UA = { 'User-Agent': 'RestaurantDeliveryApp/1.0' };

const TIMEOUT_MS = 10_000;

function fetchWithTimeout(url, options) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  return fetch(url, { ...options, signal: controller.signal })
    .finally(() => clearTimeout(timer));
}

export async function geocodeAddress(address) {
  if (!address || !address.trim()) return null;
  try {
    const url = `${NOMINATIM_SEARCH}?format=json&q=${encodeURIComponent(address.trim())}&limit=1`;
    const res = await fetchWithTimeout(url, { headers: UA });
    if (!res.ok) return null;
    const data = await res.json();
    if (data && data.length > 0) {
      return { lat: parseFloat(data[0].lat), lng: parseFloat(data[0].lon) };
    }
    return null;
  } catch {
    return null;
  }
}

export async function reverseGeocode(lat, lng) {
  try {
    const url = `${NOMINATIM_REVERSE}?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`;
    const res = await fetchWithTimeout(url, { headers: UA });
    if (!res.ok) return null;
    const data = await res.json();
    return data.display_name || null;
  } catch {
    return null;
  }
}
