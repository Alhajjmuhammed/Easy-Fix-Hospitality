import { useEffect, useRef } from 'react';
import { Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
import { useAuthStore } from '../store/useAuthStore';
import { apiSavePushToken } from '../api/notifications';

// expo-notifications remote push is not supported in Expo Go (SDK 53+).
// Only initialise the handler when running in a real/dev build.
const IS_EXPO_GO = Constants.appOwnership === 'expo';

if (!IS_EXPO_GO) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

/**
 * Registers the device for Expo push notifications (customers only) and
 * optionally navigates to the order when the user taps a notification.
 * No-ops silently when running inside Expo Go.
 *
 * @param {import('@react-navigation/native').NavigationContainerRef|null} navigationRef
 */
export function usePushNotifications(navigationRef = null) {
  const { token: authToken, user } = useAuthStore();
  const responseListener = useRef(null);

  useEffect(() => {
    // Remote push is unavailable in Expo Go — skip entirely to avoid warnings
    if (IS_EXPO_GO) return;

    // Only register for logged-in customers
    if (!authToken || !user || user.role_name !== 'customer') return;

    let cancelled = false;

    (async () => {
      // Android 13+ requires a dedicated channel
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('orders', {
          name: 'Order Updates',
          importance: Notifications.AndroidImportance.MAX,
          sound: 'default',
          vibrationPattern: [0, 250, 250, 250],
        });
      }

      // Request permission
      const { status: existing } = await Notifications.getPermissionsAsync();
      const { status } =
        existing === 'granted'
          ? { status: existing }
          : await Notifications.requestPermissionsAsync();

      if (status !== 'granted' || cancelled) return;

      // Get Expo push token and save to backend
      try {
        const tokenData = await Notifications.getExpoPushTokenAsync();
        if (!cancelled) {
          await apiSavePushToken(tokenData.data);
        }
      } catch {
        // Push token unavailable in this environment (e.g. simulator without credentials)
      }
    })();

    // Handle notification tap → navigate to MyOrders
    responseListener.current = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        const orderId = response.notification.request.content.data?.orderId;
        if (orderId && navigationRef?.current) {
          navigationRef.current.navigate('Customer', {
            screen: 'MyOrders',
          });
        }
      },
    );

    return () => {
      cancelled = true;
      if (responseListener.current) {
        Notifications.removeNotificationSubscription(responseListener.current);
        responseListener.current = null;
      }
    };
  }, [authToken, user]); // eslint-disable-line react-hooks/exhaustive-deps
}
