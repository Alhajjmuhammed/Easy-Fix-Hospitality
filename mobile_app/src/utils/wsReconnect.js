// WebSocket reconnect rules. No React Native imports (tested in Node).

// Close codes the server uses to refuse a connection for good (orders/consumers.py):
// 4000 not found / not allowed, 4001 not authenticated, 4002 bad request, 4003 forbidden.
// Reconnecting cannot fix these, it only hammers the server.
export const WS_FATAL_CLOSE_CODES = [4000, 4001, 4002, 4003];

/** Should a socket closed with `code` be reopened? 1000 = closed on purpose. */
export function shouldReconnect(code) {
  if (code === 1000) return false;
  return !WS_FATAL_CLOSE_CODES.includes(code);
}

/** Wait before reconnect attempt `attempt` (0-based): 2s, 4s, 8s … capped at 30s. */
export function reconnectDelay(attempt, baseMs = 2000, maxMs = 30000) {
  const n = Math.max(0, Math.floor(attempt || 0));
  return Math.min(maxMs, baseMs * 2 ** Math.min(n, 20));
}
