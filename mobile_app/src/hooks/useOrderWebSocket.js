/**
 * useOrderWebSocket
 *
 * Connects to the Django Channels WebSocket for a specific order and calls
 * `onUpdate(data)` whenever a `status_update` message arrives.
 *
 * Authentication: passes the DRF token as ?token=<key> in the URL so the
 * backend's TokenAuthMiddleware can authenticate the connection.
 *
 * Reconnect strategy:
 *   - Exponential backoff: 2s → 4s → 8s → … capped at 30s.
 *   - Does NOT reconnect on auth rejection (codes 4001 / 4003).
 *
 * Fallback polling: if WebSocket support is unavailable or the first
 * connection fails immediately, the caller retains its own polling interval
 * (reduced to 60 s as a safety net in OrderTrackingScreen).
 */

import { useEffect, useRef, useCallback } from 'react';
import * as SecureStore from 'expo-secure-store';
import { API_BASE_URL } from '../config';

// Derive ws(s):// base from http(s):// API_BASE_URL — strip /api/v1 suffix.
// e.g. 'http://192.168.0.238:8000/api/v1' → 'ws://192.168.0.238:8000'
const WS_BASE = API_BASE_URL
  .replace(/^https/, 'wss')
  .replace(/^http/, 'ws')
  .replace(/\/api\/v1\/?$/, '');

const MAX_BACKOFF_MS = 30_000;

export function useOrderWebSocket(orderId, onUpdate) {
  const wsRef         = useRef(null);
  const reconnectRef  = useRef(null);
  const backoffRef    = useRef(2_000);
  const mountedRef    = useRef(true);

  const cleanup = useCallback(() => {
    clearTimeout(reconnectRef.current);
    if (wsRef.current) {
      wsRef.current.onopen    = null;
      wsRef.current.onmessage = null;
      wsRef.current.onerror   = null;
      wsRef.current.onclose   = null;
      wsRef.current.close(1000);
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback(async () => {
    if (!mountedRef.current) return;
    cleanup();

    let token;
    try {
      token = await SecureStore.getItemAsync('auth_token');
    } catch {
      return; // SecureStore unavailable — fall back to polling only
    }
    if (!mountedRef.current || !token) return;

    const url = `${WS_BASE}/ws/order/${orderId}/?token=${encodeURIComponent(token)}`;

    let ws;
    try {
      ws = new WebSocket(url);
    } catch {
      return; // WebSocket constructor failed (very unusual)
    }
    wsRef.current = ws;

    ws.onopen = () => {
      // Reset backoff on successful connection
      backoffRef.current = 2_000;
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        // Consumer sends type: 'status_update' for order progress events
        // and type: 'order_status' for the initial state on connect.
        if (
          data.type === 'status_update' ||
          data.type === 'order_status_update' ||
          data.type === 'order_status'
        ) {
          onUpdate(data);
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onerror = () => {
      // onerror is always followed by onclose — let onclose handle reconnect
    };

    ws.onclose = (event) => {
      if (!mountedRef.current) return;
      // 4001 = not authenticated, 4003 = forbidden — do not retry
      if (event.code === 4001 || event.code === 4003) return;
      // Normal closure (1000) from our own cleanup — do not retry
      if (event.code === 1000) return;

      const delay = backoffRef.current;
      backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS);
      reconnectRef.current = setTimeout(connect, delay);
    };
  }, [orderId, onUpdate, cleanup]);

  useEffect(() => {
    mountedRef.current = true;
    backoffRef.current = 2_000;
    connect();
    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [connect, cleanup]);
}
