import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, View, ActivityIndicator } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useAuthStore } from '../store/useAuthStore';
import { useLockStore, IDLE_MS } from '../store/useLockStore';
import LoginScreen from '../screens/auth/LoginScreen';
import RegisterScreen from '../screens/auth/RegisterScreen';
import CustomerNavigator from './CustomerNavigator';
import StaffNavigator from './StaffNavigator';
import RiderNavigator from './RiderNavigator';
import LockScreen from '../screens/LockScreen';

const Stack = createNativeStackNavigator();

export default function AppNavigator() {
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const { isLocked, hasPin, loadPin, lock, unlock } = useLockStore();
  const idleTimer = useRef(null);
  // Prevents a flash of the app UI before we know whether a PIN lock is needed
  const [pinLoaded, setPinLoaded] = useState(false);

  // Load persisted PIN setting once on mount
  useEffect(() => {
    loadPin().finally(() => setPinLoaded(true));
  }, []);

  // Idle-lock: reset timer on AppState change or any screen touch
  const resetIdleTimer = useCallback(() => {
    if (!token || !hasPin) return;
    clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(lock, IDLE_MS);
  }, [token, hasPin, lock]);

  useEffect(() => {
    if (!token || !hasPin) return;
    resetIdleTimer();
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') resetIdleTimer();
      else clearTimeout(idleTimer.current);
    });
    return () => { clearTimeout(idleTimer.current); sub.remove(); };
  }, [token, hasPin, resetIdleTimer]);

  const roleName = user?.role_name;
  // Treat missing/unknown role as customer to avoid accidentally granting staff access
  const isCustomer      = !token || !user || !roleName || roleName === 'customer';
  const isDeliveryRider = token && user && roleName === 'delivery_rider';

  // Block render until PIN is loaded — prevents brief flash of app UI before lock screen
  if (!pinLoaded) {
    return <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}><ActivityIndicator size="large" /></View>;
  }

  // Show lock screen as a full-screen overlay when PIN is set and screen is locked
  if (token && hasPin && isLocked) {
    return <LockScreen onUnlock={unlock} />;
  }

  return (
    <View style={{ flex: 1 }} onTouchStart={token && hasPin ? resetIdleTimer : undefined}>
      <NavigationContainer>
        <Stack.Navigator screenOptions={{ headerShown: false }}>
          {!token ? (
            <>
              <Stack.Screen name="Login" component={LoginScreen} />
              <Stack.Screen name="Register" component={RegisterScreen} />
            </>
          ) : isDeliveryRider ? (
            <Stack.Screen name="Rider" component={RiderNavigator} />
          ) : isCustomer ? (
            <Stack.Screen name="Customer" component={CustomerNavigator} />
          ) : (
            <Stack.Screen name="Staff" component={StaffNavigator} />
          )}
        </Stack.Navigator>
      </NavigationContainer>
    </View>
  );
}
