import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';

const PIN_KEY     = 'app_lock_pin';
const LOCKOUT_KEY = 'app_lock_lockout_until';
export const IDLE_MS = 30 * 60 * 1000; // 30 minutes

const MAX_ATTEMPTS = 5;
const LOCKOUT_MS   = 30 * 1000; // 30-second lockout after 5 wrong guesses

export const useLockStore = create((set, get) => ({
  isLocked: false,
  hasPin: false,
  failedAttempts: 0,
  lockedOutUntil: null, // timestamp (ms) when lockout expires

  /** Call on app start – checks if a PIN is already saved and restores any active lockout */
  loadPin: async () => {
    const pin = await SecureStore.getItemAsync(PIN_KEY);
    const rawLockout = await SecureStore.getItemAsync(LOCKOUT_KEY);
    const lockedOutUntil = rawLockout && Number(rawLockout) > Date.now() ? Number(rawLockout) : null;
    if (rawLockout && !lockedOutUntil) {
      await SecureStore.deleteItemAsync(LOCKOUT_KEY);
    }
    set({ hasPin: !!pin, lockedOutUntil });
  },

  /** Save a new 4-digit PIN and enable lock */
  setPin: async (pin) => {
    await SecureStore.setItemAsync(PIN_KEY, pin);
    set({ hasPin: true, failedAttempts: 0, lockedOutUntil: null });
  },

  /** Remove PIN — disables the lock feature */
  removePin: async () => {
    await SecureStore.deleteItemAsync(PIN_KEY);
    set({ hasPin: false, isLocked: false, failedAttempts: 0, lockedOutUntil: null });
  },

  /** Lock the screen immediately */
  lock: () => set({ isLocked: true }),

  /**
   * Verify PIN and unlock.
   * Returns { success: true } or { success: false, attemptsLeft, lockedOutUntil }.
   */
  unlock: async (pin) => {
    const { lockedOutUntil } = get();

    // Check active lockout
    if (lockedOutUntil && Date.now() < lockedOutUntil) {
      return { success: false, attemptsLeft: 0, lockedOutUntil };
    }

    const stored = await SecureStore.getItemAsync(PIN_KEY);
    if (stored === pin) {
      set({ isLocked: false, failedAttempts: 0, lockedOutUntil: null });
      await SecureStore.deleteItemAsync(LOCKOUT_KEY).catch(() => {});
      return { success: true };
    }

    // Atomically increment failedAttempts via functional set to prevent
    // concurrent unlock() calls both reading the same stale counter value.
    let captured = {};
    set((state) => {
      const newAttempts = state.failedAttempts + 1;
      const newLockout  = newAttempts >= MAX_ATTEMPTS ? Date.now() + LOCKOUT_MS : null;
      captured = { newAttempts, newLockout };
      return { failedAttempts: newLockout ? 0 : newAttempts, lockedOutUntil: newLockout };
    });
    const { newAttempts, newLockout } = captured;
    if (newLockout) {
      await SecureStore.setItemAsync(LOCKOUT_KEY, String(newLockout));
    }
    return {
      success: false,
      attemptsLeft: newLockout ? 0 : MAX_ATTEMPTS - newAttempts,
      lockedOutUntil: newLockout,
    };
  },
}));
