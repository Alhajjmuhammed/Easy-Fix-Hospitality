import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'app_language';
export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'sw', label: 'Kiswahili' },
];

/** The language chosen on this phone (remembered between app starts). */
export const useLanguageStore = create((set) => ({
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
    try { await AsyncStorage.setItem(KEY, lang); } catch { /* still applies for this session */ }
  },
}));
