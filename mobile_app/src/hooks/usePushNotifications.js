import { useEffect } from 'react';
import { Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
import { useAuthStore } from '../store/useAuthStore';
import { apiSavePushToken } from '../api/notifications';
import { navigationRef } from '../navigation/navigationRef';

// expo-notifications remote push is not supported in Expo Go (SDK 53+).
// Only initialise the handler when running in a real/dev build.
const IS_EXPO_GO = Constants.appOwnership === 'expo';

const STATION_ROLES = ['kitchen', 'bar', 'buffet', 'service'];

if (!IS_EXPO_GO) {
  Notifications.setNotificationHandler({
    handleNotification: async (notification) => {
      // Staff with the app open already see new orders live on their dashboard:
      // play the sound but skip the banner.
      const isNewOrder = notification?.request?.content?.data?.kind === 'new_order';
      return {
        shouldShowAlert: !isNewOrder,
        shouldShowBanner: !isNewOrder,
        shouldShowList: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      };
    },
  });
}

/** Where a tapped notification should take each role. */
function targetFor(role, data) {
  const orderId = data?.orderId;
  if (role === 'customer') {
    return orderId
      ? ['Customer', { screen: 'MyOrders', params: { screen: 'OrderTracking', params: { orderId } } }]
      : ['Customer', { screen: 'MyOrders' }];
  }
  if (role === 'delivery_rider') return ['Rider', { screen: 'Deliveries' }];
  if (STATION_ROLES.includes(role)) return ['Staff', { screen: 'Dashboard' }];
  if (role === 'customer_care') return ['Staff', { screen: 'Dashboard' }];
  // cashier, manager, owners
  return orderId
    ? ['Staff', { screen: 'Dashboard', params: { screen: 'OrderDetail', params: { orderId } } }]
    : ['Staff', { screen: 'Dashboard' }];
}

let lastHandledId = null;

function openFromNotification(response) {
  const id = response?.notification?.request?.identifier;
  if (id && id === lastHandledId) return;
  lastHandledId = id;
  const data = response?.notification?.request?.content?.data;
  const role = useAuthStore.getState().user?.role_name;
  if (!data || !role) return;
  const [name, params] = targetFor(role, data);
  // The navigator may not be mounted yet (cold start, PIN lock screen) — retry briefly.
  let tries = 0;
  const attempt = () => {
    if (navigationRef.isReady()) {
      try { navigationRef.navigate(name, params); } catch { /* route not in this role's navigator */ }
    } else if (tries++ < 40) {
      setTimeout(attempt, 500);
    }
  };
  attempt();
}

/**
 * Registers the device for push notifications for any logged-in user and opens
 * the relevant screen when a notification is tapped. No-op inside Expo Go.
 */
export function usePushNotifications() {
  const authToken = useAuthStore((s) => s.token);
  const userId = useAuthStore((s) => s.user?.id);

  useEffect(() => {
    if (IS_EXPO_GO || !authToken || !userId) return;
    let cancelled = false;

    (async () => {
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('orders', {
          name: 'Order Updates',
          importance: Notifications.AndroidImportance.MAX,
          sound: 'default',
          vibrationPattern: [0, 250, 250, 250],
        });
      }

      const { status: existing } = await Notifications.getPermissionsAsync();
      const { status } = existing === 'granted'
        ? { status: existing }
        : await Notifications.requestPermissionsAsync();
      if (status !== 'granted' || cancelled) return;

      try {
        const projectId = Constants.expoConfig?.extra?.eas?.projectId;
        const tokenData = await Notifications.getExpoPushTokenAsync({ projectId });
        if (!cancelled) await apiSavePushToken(tokenData.data);
      } catch {
        // No push credentials in this environment (e.g. simulator) — app works without push.
      }
    })();

    // App was launched by tapping a notification while it was closed
    Notifications.getLastNotificationResponseAsync()
      .then((response) => { if (response && !cancelled) openFromNotification(response); })
      .catch(() => {});

    const sub = Notifications.addNotificationResponseReceivedListener(openFromNotification);

    return () => {
      cancelled = true;
      sub.remove();
    };
  }, [authToken, userId]);
}
