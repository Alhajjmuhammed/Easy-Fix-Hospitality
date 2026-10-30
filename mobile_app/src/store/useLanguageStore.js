import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'app_language';
const PENDING_KEY = 'app_language_pending';   // '1' = chosen here but not yet saved on the account
export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'sw', label: 'Kiswahili' },
];

/** The language chosen on this phone (remembered between app starts). */
export const useLanguageStore = create((set, get) => ({
  language: 'en',
  loaded: false,
  load: async () => {
    try {
      const saved = await AsyncStorage.getItem(KEY);
      set({ language: saved === 'sw' ? 'sw' : 'en', loaded: true });
    } catch {
      set({ loaded: true });
    }
  },
  setLanguage: async (language) => {
    const lang = language === 'sw' ? 'sw' : 'en';
    set({ language: lang });
    try { await AsyncStorage.multiSet([[KEY, lang], [PENDING_KEY, '1']]); } catch { /* still applies for this session */ }
    get().syncToServer();
  },
  /** Save a choice made on this phone to the account (used for notifications and SMS).
   *  Kept pending while logged out or offline; tried again after login and on app start. */
  syncToServer: async () => {
    try {
      if ((await AsyncStorage.getItem(PENDING_KEY)) !== '1') return;
      const { useAuthStore } = require('./useAuthStore');
      if (!useAuthStore.getState().token) return;
      const client = require('../api/client').default;
      await client.post('/api/v1/auth/language/', { language: get().language });
      await AsyncStorage.removeItem(PENDING_KEY);
    } catch { /* offline or older server: try again next time */ }
  },
}));
