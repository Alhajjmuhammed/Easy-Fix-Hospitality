import { useEffect, useRef } from 'react';
import NetInfo from '@react-native-community/netinfo';
import { AppState } from 'react-native';
import { useSyncStore } from '../store/useSyncStore';
import { useAuthStore } from '../store/useAuthStore';
import { SYNC_INTERVAL_MS } from '../config';

/**
 * Registers a NetInfo listener and a periodic timer so the app syncs whenever
 * it comes back online or every SYNC_INTERVAL_MS milliseconds.
 * Call this once from App.js (while authenticated).
 */
export function useNetworkSync() {
  const triggerSync = useSyncStore((s) => s.triggerSync);
  const timerRef = useRef(null);
  const appStateRef = useRef(AppState.currentState);

  const isAuth = () => !!useAuthStore.getState().token;

  // Kick off sync when network becomes available
  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener((state) => {
      if (state.isConnected && isAuth()) {
        triggerSync();
      }
    });
    return () => unsubscribe();
  }, [triggerSync]);

  // Periodic sync every SYNC_INTERVAL_MS
  useEffect(() => {
    timerRef.current = setInterval(() => {
      if (isAuth()) triggerSync();
    }, SYNC_INTERVAL_MS);
    return () => clearInterval(timerRef.current);
  }, [triggerSync]);

  // Sync when the app comes back to the foreground
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (
        appStateRef.current.match(/inactive|background/) &&
        nextState === 'active' &&
        isAuth()
      ) {
        triggerSync();
      }
      appStateRef.current = nextState;
    });
    return () => subscription.remove();
  }, [triggerSync]);
}
