import NetInfo from '@react-native-community/netinfo';

/**
 * One rule for "online" across the app: a network is connected AND the internet
 * is not known to be unreachable. `isInternetReachable` is null while NetInfo is
 * still probing, so only an explicit `false` ("connected to Wi-Fi but no internet")
 * counts as offline. Using plain `isConnected` treated a dead Wi-Fi as online,
 * so actions were sent (and failed) instead of being queued.
 */
export const isOnlineState = (state) =>
  !!(state && state.isConnected && state.isInternetReachable !== false);

/** Current online state (false if NetInfo itself fails). */
export const isOnline = async () => {
  try {
    return isOnlineState(await NetInfo.fetch());
  } catch {
    return false;
  }
};

/** An axios error without a server response: timeout, DNS, dropped connection. */
export const isNetworkError = (err) => !!err && !err.response;

/** A client-made id for an action, reused for its retries and its offline-queue copy
 *  so the server can recognise a repeat and never apply it twice. */
export const newClientId = (prefix) =>
  `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
