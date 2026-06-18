import React, { useEffect, useState, useRef, useCallback } from 'react';
import { View, StyleSheet, LogBox, AppState } from 'react-native';
import NetInfo from '@react-native-community/netinfo';

// Suppress known harmless warnings/errors that appear in Expo Go only.
// These features fall back gracefully (BT → system dialog, notifications → no-op).
LogBox.ignoreLogs([
  '[TypeError: Cannot set property',
  'Cannot set property \'DIRECTION\' of null',
  'expo-notifications: Android Push notifications',
  '`expo-notifications` functionality is not fully supported',
]);

import { Provider as PaperProvider, MD3LightTheme, ActivityIndicator, configureFonts } from 'react-native-paper';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useFonts } from 'expo-font';
import {
  Poppins_300Light,
  Poppins_400Regular,
  Poppins_500Medium,
  Poppins_600SemiBold,
  Poppins_700Bold,
} from '@expo-google-fonts/poppins';
import { initDatabase } from './src/database/db';
import { useAuthStore } from './src/store/useAuthStore';
import { useSyncStore } from './src/store/useSyncStore';
import { usePrinterStore } from './src/store/usePrinterStore';
import AppNavigator from './src/navigation/AppNavigator';
import { useNetworkSync } from './src/hooks/useNetworkSync';
import { usePushNotifications } from './src/hooks/usePushNotifications';
import { useLockStore, IDLE_MS } from './src/store/useLockStore';
import LockScreen from './src/screens/LockScreen';

const fontConfig = {
  displayLarge:   { fontFamily: 'Poppins_300Light' },
  displayMedium:  { fontFamily: 'Poppins_300Light' },
  displaySmall:   { fontFamily: 'Poppins_400Regular' },
  headlineLarge:  { fontFamily: 'Poppins_400Regular' },
  headlineMedium: { fontFamily: 'Poppins_400Regular' },
  headlineSmall:  { fontFamily: 'Poppins_400Regular' },
  titleLarge:     { fontFamily: 'Poppins_400Regular' },
  titleMedium:    { fontFamily: 'Poppins_500Medium' },
  titleSmall:     { fontFamily: 'Poppins_500Medium' },
  bodyLarge:      { fontFamily: 'Poppins_400Regular' },
  bodyMedium:     { fontFamily: 'Poppins_400Regular' },
  bodySmall:      { fontFamily: 'Poppins_400Regular' },
  labelLarge:     { fontFamily: 'Poppins_500Medium' },
  labelMedium:    { fontFamily: 'Poppins_500Medium' },
  labelSmall:     { fontFamily: 'Poppins_500Medium' },
};

const theme = {
  ...MD3LightTheme,
  colors: {
    ...MD3LightTheme.colors,
    primary: '#2c3e50',
    secondary: '#FF8F00',
  },
  fonts: configureFonts({ config: fontConfig }),
};

function AppContent() {
  const { token, loadToken, refreshProfile } = useAuthStore();
  const { refreshPendingCount } = useSyncStore();
  const { loadSettings: loadPrinterSettings } = usePrinterStore();
  const { isLocked, hasPin, loadPin, lock, unlock } = useLockStore();
  const [ready, setReady] = useState(false);

  // Tracks last touch time for foreground idle detection
  const lastActivityRef = useRef(Date.now());
  // Tracks when the app went to background
  const backgroundTimeRef = useRef(null);

  // Initialise SQLite, restore auth token, printer settings, and PIN state in parallel.
  useEffect(() => {
    (async () => {
      try { require('@brooons/react-native-bluetooth-escpos-printer'); } catch (_) {}
      await Promise.all([initDatabase(), loadToken(), loadPrinterSettings(), loadPin()]);
      await refreshPendingCount();
      setReady(true);
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Lock: background detection + profile refresh on foreground ────────────
  useEffect(() => {
    const sub = AppState.addEventListener('change', (nextState) => {
      if (nextState === 'background' || nextState === 'inactive') {
        backgroundTimeRef.current = Date.now();
      } else if (nextState === 'active') {
        if (backgroundTimeRef.current !== null && hasPin) {
          const elapsed = Date.now() - backgroundTimeRef.current;
          if (elapsed >= IDLE_MS) lock();
        }
        backgroundTimeRef.current = null;
        // Silently refresh user/restaurant data when app comes to foreground
        refreshProfile();
      }
    });
    return () => sub.remove();
  }, [hasPin, lock, refreshProfile]);

  // ── Refresh profile when device comes back online ────────────────────────────
  useEffect(() => {
    const unsub = NetInfo.addEventListener((state) => {
      if (state.isConnected && state.isInternetReachable) {
        refreshProfile();
      }
    });
    return () => unsub();
  }, [refreshProfile]);

  // ── Lock: foreground idle check every 60 s ──────────────────────────────────
  useEffect(() => {
    if (!hasPin) return;
    const interval = setInterval(() => {
      if (!isLocked && Date.now() - lastActivityRef.current >= IDLE_MS) {
        lock();
      }
    }, 60_000);
    return () => clearInterval(interval);
  }, [hasPin, isLocked, lock]);

  // Record user touch activity (resets idle timer)
  const recordActivity = useCallback(() => {
    lastActivityRef.current = Date.now();
  }, []);

  // Start network-sync listener once we know the auth state
  useNetworkSync();
  // Register for Expo push notifications (customers only)
  usePushNotifications();

  if (!ready) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  // Show lock screen when PIN is set and app is locked
  if (isLocked && hasPin) {
    return <LockScreen onUnlock={unlock} />;
  }

  return (
    <View style={{ flex: 1 }} onTouchStart={recordActivity}>
      <AppNavigator />
    </View>
  );
}

export default function App() {
  const [fontsLoaded] = useFonts({
    Poppins_300Light,
    Poppins_400Regular,
    Poppins_500Medium,
    Poppins_600SemiBold,
    Poppins_700Bold,
  });

  if (!fontsLoaded) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <SafeAreaProvider>
      <PaperProvider theme={theme}>
        <AppContent />
      </PaperProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
