import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';

const PIN_KEY = 'app_lock_pin';
export const IDLE_MS = 30 * 60 * 1000; // 30 minutes

export const useLockStore = create((set, get) => ({
  isLocked: false,
  hasPin: false,

  /** Call on app start – checks if a PIN is already saved */
  loadPin: async () => {
    const pin = await SecureStore.getItemAsync(PIN_KEY);
    set({ hasPin: !!pin });
  },

  /** Save a new 4-digit PIN and enable lock */
  setPin: async (pin) => {
    await SecureStore.setItemAsync(PIN_KEY, pin);
    set({ hasPin: true });
  },

  /** Remove PIN — disables the lock feature */
  removePin: async () => {
    await SecureStore.deleteItemAsync(PIN_KEY);
    set({ hasPin: false, isLocked: false });
  },

  /** Lock the screen immediately */
  lock: () => set({ isLocked: true }),

  /**
   * Verify PIN and unlock.
   * Returns true if correct, false if wrong.
   */
  unlock: async (pin) => {
    const stored = await SecureStore.getItemAsync(PIN_KEY);
    if (stored === pin) {
      set({ isLocked: false });
      return true;
    }
    return false;
  },
}));
