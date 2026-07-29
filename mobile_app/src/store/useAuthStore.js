import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';
import { apiLogin, apiLogout, apiMe, apiRegister } from '../api/auth';
import { setClientAuth, clearClientAuth } from '../api/client';
import { clearAllUserData } from '../database/operations';

// Device must go online at least once every 15 days to continue working offline.
// If the grace period lapses, the session is cleared and the user must log in
// with an internet connection to get a fresh 15-day window.
const OFFLINE_GRACE_MS = 15 * 24 * 60 * 60 * 1000;

export const useAuthStore = create((set, get) => ({
  token: null,
  user: null,
  restaurantId: null,
  isLoading: false,
  error: null,

  /** Called on app start – restores persisted token */
  loadToken: async () => {
    const token = await SecureStore.getItemAsync('auth_token');
    const userJson = await SecureStore.getItemAsync('auth_user');
    const restaurantId = await SecureStore.getItemAsync('restaurant_id');
    const lastOnlineAt = await SecureStore.getItemAsync('last_online_at');

    if (token && userJson) {
      // Enforce 15-day offline grace period
      if (lastOnlineAt && Date.now() - Number(lastOnlineAt) > OFFLINE_GRACE_MS) {
        clearClientAuth();
        await SecureStore.deleteItemAsync('auth_token');
        await SecureStore.deleteItemAsync('auth_user');
        await SecureStore.deleteItemAsync('restaurant_id');
        await SecureStore.deleteItemAsync('last_online_at');
        set({
          error:
            'Your session has expired after 15 days offline. ' +
            'Please connect to the internet and sign in again.',
        });
        return;
      }

      // First launch after this feature was added — stamp now so the 15-day
      // window starts from today rather than retroactively locking everyone out.
      if (!lastOnlineAt) {
        await SecureStore.setItemAsync('last_online_at', String(Date.now()));
      }

      // Restore cached data immediately so the app can start
      set({
        token,
        user: JSON.parse(userJson),
        restaurantId: restaurantId ? Number(restaurantId) : null,
      });
      // Populate in-memory auth cache so API calls skip SecureStore reads
      setClientAuth(token, restaurantId);
      // Then silently refresh user profile from server (picks up logo, name changes, etc.)
      try {
        const res = await apiMe();
        const freshUser = res.data;
        await SecureStore.setItemAsync('auth_user', JSON.stringify(freshUser));
        await SecureStore.setItemAsync('last_online_at', String(Date.now()));
        set({ user: freshUser });
      } catch (_) {
        // Offline or token expired — keep cached data, logout will handle expiry
      }
    }
  },

  login: async (username, password) => {
    set({ isLoading: true, error: null });
    try {
      const res = await apiLogin(username, password);
      const { token, user } = res.data;

      await SecureStore.setItemAsync('auth_token', token);
      await SecureStore.setItemAsync('auth_user', JSON.stringify(user));
      await SecureStore.setItemAsync('last_online_at', String(Date.now()));

      setClientAuth(token, null);
      set({ token, user, isLoading: false });
      return { success: true, user };
    } catch (err) {
      let message;
      if (!err.response) {
        // No response = network unreachable (wrong IP or server not running)
        message = 'Cannot reach server. Check that the API_BASE_URL in config.js matches your machine\'s LAN IP (e.g. http://192.168.x.x:8000/api/v1) and Django is running.';
      } else {
        message = err.response?.data?.error || 'Login failed. Check your credentials.';
      }
      set({ isLoading: false, error: message });
      return { success: false, error: message };
    }
  },

  register: async (data) => {
    set({ isLoading: true, error: null });
    try {
      const res = await apiRegister(data);
      const { token, user } = res.data;
      const restaurantId = res.data.restaurant_id ? Number(res.data.restaurant_id) : null;
      await SecureStore.setItemAsync('auth_token', token);
      await SecureStore.setItemAsync('auth_user', JSON.stringify(user));
      await SecureStore.setItemAsync('last_online_at', String(Date.now()));
      if (restaurantId) await SecureStore.setItemAsync('restaurant_id', String(restaurantId));
      setClientAuth(token, restaurantId);
      set({ token, user, restaurantId, isLoading: false });
      return { success: true };
    } catch (err) {
      const message = err.response?.data?.error || 'Registration failed. Please try again.';
      set({ isLoading: false, error: message });
      return { success: false, error: message };
    }
  },

  logout: async () => {
    try { await apiLogout(); } catch (_) {}
    clearClientAuth();
    await SecureStore.deleteItemAsync('auth_token');
    await SecureStore.deleteItemAsync('auth_user');
    await SecureStore.deleteItemAsync('restaurant_id');
    await SecureStore.deleteItemAsync('last_online_at');
    // Clear cart from AsyncStorage and in-memory state — prevents next user
    // on this device seeing previous user's cart (data breach fix)
    const { useCartStore } = require('./useCartStore');
    useCartStore.getState().clearCart();
    // Reset sync pending count so next user sees 0, not previous user's count
    const { useSyncStore } = require('./useSyncStore');
    useSyncStore.getState().reset();
    // Clear all SQLite cached/offline data — menu, tables, offline orders/payments
    // belong to the previous user's restaurant and must not leak to next user
    try { await clearAllUserData(); } catch (_) {}
    set({ token: null, user: null, restaurantId: null });
  },

  /** Customers call this after scanning a QR / selecting a restaurant */
  setRestaurant: async (restaurantId) => {
    if (restaurantId === null || restaurantId === undefined) {
      await SecureStore.deleteItemAsync('restaurant_id');
      setClientAuth(get().token, null);
      set({ restaurantId: null });
    } else {
      await SecureStore.setItemAsync('restaurant_id', String(restaurantId));
      setClientAuth(get().token, restaurantId);
      set({ restaurantId });
    }
  },

  /** Silently re-fetch user profile from server — picks up restaurant name,
   *  logo, currency, tax rate changes without requiring a re-login.
   *  Uses a plain fetch with no axios interceptor so a 401 here does NOT
   *  trigger auto-logout (avoids logging out users on brief network issues). */
  refreshProfile: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const res = await apiMe();
      const freshUser = res.data;
      await SecureStore.setItemAsync('auth_user', JSON.stringify(freshUser));
      // Device is online — reset the 15-day offline grace period clock
      await SecureStore.setItemAsync('last_online_at', String(Date.now()));
      set({ user: freshUser });
    } catch (_) {
      // 401 is handled by the client.js response interceptor (triggers full logout).
      // All other errors (network down, 500, etc.) — ignore silently.
    }
  },

  isAuthenticated: () => !!get().token,
}));
