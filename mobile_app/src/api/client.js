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
    _cachedToken = await SecureStore.getItemAsync('auth_token');
    _cachedRestaurantId = await SecureStore.getItemAsync('restaurant_id');
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
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid — clear in-memory cache immediately so no
      // further requests go out with a bad token.
      clearClientAuth();
      // Trigger full logout so the app navigates to the login screen.
      // Use require() to avoid circular import (client ← authStore ← client).
      try {
        const { useAuthStore } = require('../store/useAuthStore');
        useAuthStore.getState().logout();
      } catch (_) {
        // Fallback: at minimum clear SecureStore so next app start re-auths
        SecureStore.deleteItemAsync('auth_token');
        SecureStore.deleteItemAsync('restaurant_id');
      }
    }
    return Promise.reject(error);
  },
);

export default client;
