// API base URL – set EXPO_PUBLIC_API_URL in your .env file to override.
// For local development change the fallback to your PC's LAN IP.
export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL ||
  'https://hospitality.easyfixsoft.com/api/v1'; // production VPS

export const SYNC_INTERVAL_MS = 10 * 60 * 1000; // 10 minutes background sync
export const MENU_STALE_THRESHOLD_MS = 60 * 60 * 1000; // warn if menu > 1 hour old
