/**
 * usePrinterStore.js
 *
 * Persists printer configuration across app restarts.
 *
 * Modes:
 *  'auto'      — try BT Classic SPP → if unavailable try Network → fallback System dialog
 *  'bluetooth' — silent direct print via BT Classic SPP (requires custom build, not Expo Go)
 *  'network'   — send job to server → Print Client on Windows PC
 *  'system'    — native OS print dialog (works with any paired printer, no build needed)
 */

import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = '@printer_settings_v1';

export const usePrinterStore = create((set, get) => ({
  /** One of: 'auto' | 'bluetooth' | 'network' | 'system' */
  mode: 'auto',

  /** { address: string, name: string } — the paired BT Classic device to use */
  bluetoothDevice: null,

  /** If true, auto-print receipt immediately after payment (no tap needed) */
  autoPrintAfterPayment: true,

  /**
   * If true, mobile prints an ORDER TICKET (KOT/BOT) locally via BT or system
   * dialog immediately after order placement. The server's auto_print_order()
   * is skipped so PrintJob rows are NOT queued (avoids DB clutter on restaurants
   * without a Windows Print Client).
   * Default false = current behaviour — server queue handles KOT/BOT.
   */
  localKotBot: false,

  /** Load persisted settings on app start */
  loadSettings: async () => {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        set({
          mode:                  saved.mode                  ?? 'auto',
          bluetoothDevice:       saved.bluetoothDevice       ?? null,
          autoPrintAfterPayment: saved.autoPrintAfterPayment ?? true,
          localKotBot:           saved.localKotBot           ?? false,
        });
      }
    } catch (_) {}
  },

  /** Persist a partial settings update */
  saveSettings: async (updates) => {
    const next = { ...get(), ...updates };
    set(updates);
    try {
      await AsyncStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          mode:                  next.mode,
          bluetoothDevice:       next.bluetoothDevice,
          autoPrintAfterPayment: next.autoPrintAfterPayment,
          localKotBot:           next.localKotBot,
        }),
      );
    } catch (_) {}
  },
}));
