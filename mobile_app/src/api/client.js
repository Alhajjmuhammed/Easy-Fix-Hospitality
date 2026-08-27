import axios from 'axios';
import * as SecureStore from 'expo-secure-store';
import { API_BASE_URL } from '../config';

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// In-memory cache — avoids encrypted disk reads on every request (50-150ms each).
// Cleared on 401 so stale tokens are never used.
let _cachedToken = null;
let _cachedRestaurantId = null;

// Guard against two concurrent 401 responses both triggering logout() at the
// same time, which causes concurrent SQLite transactions and potential deadlock.
let _logoutInProgress = false;

export function setClientAuth(token, restaurantId) {
  _cachedToken = token;
  _cachedRestaurantId = restaurantId;
}

export function clearClientAuth() {
  _cachedToken = null;
  _cachedRestaurantId = null;
}

// Attach auth token to every request
client.interceptors.request.use(async (config) => {
  // Use in-memory cache first; fall back to SecureStore on first call
  if (!_cachedToken) {
    try {
      _cachedToken = await SecureStore.getItemAsync('auth_token');
      _cachedRestaurantId = await SecureStore.getItemAsync('restaurant_id');
    } catch {
      // SecureStore unavailable — proceed without auth; server will 401
    }
  }
  if (_cachedToken) {
    config.headers.Authorization = `Token ${_cachedToken}`;
  }
  if (_cachedRestaurantId) {
    config.headers['X-Restaurant-ID'] = _cachedRestaurantId;
  }
  return config;
});

// Global error interceptor
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      // Don't recurse: if logout itself returns 401 (no token), just reject.
      if (error.config?.url?.includes('/auth/logout/')) {
        return Promise.reject(error);
      }
      // Login failure (wrong credentials) returns 401 — not a session problem,
      // so don't wipe state; let the login screen show the error message.
      if (error.config?.url?.includes('/auth/login/')) {
        return Promise.reject(error);
      }
      // Token expired or invalid — clear in-memory cache immediately so no
      // further requests go out with a bad token.
      clearClientAuth();
      // Guard: two concurrent 401 responses must not both trigger logout(),
      // which would run concurrent SQLite transactions and risk deadlock.
      if (!_logoutInProgress) {
        _logoutInProgress = true;
        try {
          const { useAuthStore } = require('../store/useAuthStore');
          await useAuthStore.getState().logout();
        } catch (_) {
          // Fallback: at minimum clear SecureStore so next app start re-auths
          await Promise.all([
            SecureStore.deleteItemAsync('auth_token'),
            SecureStore.deleteItemAsync('restaurant_id'),
          ]).catch(() => {});
        } finally {
          _logoutInProgress = false;
        }
      }
    }
    if (error.response?.status === 403) {
      const msg = error.response?.data?.error || '';
      if (msg.includes('subscription') || msg.includes('Subscription')) {
        if (!_logoutInProgress) {
          _logoutInProgress = true;
          clearClientAuth();
          try {
            const { useAuthStore } = require('../store/useAuthStore');
            useAuthStore.getState().logout().finally(() => { _logoutInProgress = false; });
          } catch (_) {
            _logoutInProgress = false;
          }
        }
      }
    }
    return Promise.reject(error);
  },
);

export default client;
