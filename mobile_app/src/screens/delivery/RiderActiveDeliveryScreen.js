import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { View, StyleSheet, Alert, Platform } from 'react-native';
import { Text, Button, Card, Chip, ActivityIndicator, Snackbar } from 'react-native-paper';
import { WebView } from 'react-native-webview';
import * as Location from 'expo-location';
import { useNavigation } from '@react-navigation/native';
import NetInfo from '@react-native-community/netinfo';
import { API_BASE_URL } from '../../config';
import { useAuthStore } from '../../store/useAuthStore';
import {
  apiTrackOrder,
  apiMarkPickedUp,
  apiMarkDelivered,
} from '../../api/delivery';

// Build the Leaflet HTML — shows rider position + destination pin
function buildMapHtml({ riderLat, riderLng, destLat, destLng, destAddress }) {
  const hasRider = riderLat != null && riderLng != null;
  const hasDest  = destLat  != null && destLng  != null;

  const centerLat = hasRider ? riderLat : (hasDest ? destLat : -1.286389);
  const centerLng = hasRider ? riderLng : (hasDest ? destLng : 36.817223);

  return `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body,#map { margin:0; padding:0; width:100%; height:100%; }
  #addr { position:absolute;bottom:10px;left:50%;transform:translateX(-50%);
          background:rgba(255,255,255,.93);padding:6px 14px;border-radius:20px;
          font-family:sans-serif;font-size:12px;color:#C62828;font-weight:600;
          box-shadow:0 2px 8px rgba(0,0,0,.2);z-index:1000;
          max-width:90%;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }
</style>
</head>
<body>
${hasDest ? `<div id="addr">📍 ${(destAddress || 'Delivery address').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')}</div>` : ''}
<div id="map"></div>
<script>
var map = L.map('map').setView([${centerLat}, ${centerLng}], 14);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 19,
}).addTo(map);

var riderIcon = L.divIcon({
  html: '<div style="background:#1565C0;color:#fff;border-radius:50%;width:40px;height:40px;display:flex;align-items:center;justify-content:center;font-size:20px;border:3px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35)">🏍</div>',
  className:'', iconAnchor:[20,20]
});
var destIcon = L.divIcon({
  html: '<div style="background:#C62828;color:#fff;border-radius:50% 50% 50% 0;width:40px;height:40px;display:flex;align-items:center;justify-content:center;font-size:20px;border:3px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35);transform:rotate(-45deg)"><span style="transform:rotate(45deg)">🏠</span></div>',
  className:'', iconAnchor:[20,40]
});

var riderMarker = null;
var destMarker  = null;

${hasRider ? `
riderMarker = L.marker([${riderLat}, ${riderLng}], {icon: riderIcon})
  .addTo(map).bindPopup('📍 You are here');
` : ''}

${hasDest ? `
destMarker = L.marker([${destLat}, ${destLng}], {icon: destIcon})
  .addTo(map).bindPopup(${JSON.stringify('🏠 ' + (destAddress || 'Delivery address'))});
destMarker.openPopup();
` : ''}

${hasRider && hasDest ? `
var bounds = L.latLngBounds([[${riderLat},${riderLng}],[${destLat},${destLng}]]);
map.fitBounds(bounds, { padding: [50, 50] });
` : ''}

function updateRider(lat, lng) {
  if (!riderMarker) {
    riderMarker = L.marker([lat, lng], {icon: riderIcon}).addTo(map).bindPopup('📍 You are here');
  } else {
    riderMarker.setLatLng([lat, lng]);
  }
  // Keep both markers visible
  if (destMarker) {
    var bounds = L.latLngBounds([riderMarker.getLatLng(), destMarker.getLatLng()]);
    map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
  } else {
    map.panTo([lat, lng]);
  }
}

document.addEventListener('message', function(e) {
  try { var m = JSON.parse(e.data); if (m.type === 'rider_location') updateRider(m.lat, m.lng); } catch(err) {}
});
window.addEventListener('message', function(e) {
  try { var m = JSON.parse(e.data); if (m.type === 'rider_location') updateRider(m.lat, m.lng); } catch(err) {}
});
</script>
</body>
</html>`;
}

export default function RiderActiveDeliveryScreen({ route }) {
  const { assignmentOrderId } = route.params;
  const navigation = useNavigation();
  const { token }  = useAuthStore();

  const [assignment, setAssignment] = useState(null);
  const [loading, setLoading]       = useState(true);
  const [loadError, setLoadError]   = useState(false);
  const [actioning, setActioning]   = useState(false);
  const [snack, setSnack]           = useState('');
  const [riderPos, setRiderPos]     = useState(null);
  const [destCoords, setDestCoords] = useState(null);

  const webViewRef  = useRef(null);
  const wsRef       = useRef(null);
  const locSubRef   = useRef(null);

  // ── Load assignment data ─────────────────────────────────────────────────
  const loadAssignment = useCallback(async () => {
    try {
      const data = await apiTrackOrder(assignmentOrderId);
      setAssignment(data);
      setLoadError(false);
      const lat = data?.assignment?.delivery_lat;
      const lng = data?.assignment?.delivery_lng;
      if (lat != null && lng != null) setDestCoords({ lat, lng });
    } catch {
      setLoadError(true);
      setSnack('Could not load delivery details');
    } finally {
      setLoading(false);
    }
  }, [assignmentOrderId]);

  useEffect(() => { loadAssignment(); }, [loadAssignment]);

  // Stable mapHtml — depends only on the initial API values, NOT riderPos.
  // Live GPS updates go through injectJavaScript so the WebView never reloads.
  const mapHtml = useMemo(() => {
    const a = assignment?.assignment;
    return buildMapHtml({
      riderLat: assignment?.rider_lat ?? null,
      riderLng: assignment?.rider_lng ?? null,
      destLat:  destCoords?.lat ?? null,
      destLng:  destCoords?.lng ?? null,
      destAddress: a?.delivery_address ?? '',
    });
  }, [assignment, destCoords]);

  // ── Location tracking ────────────────────────────────────────────────────
  useEffect(() => {
    let active = true;

    async function startTracking() {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setSnack('Location permission denied — tracking disabled');
        return;
      }

      // Connect WebSocket for live location push
      const wsUrl = API_BASE_URL
        .replace(/^https/, 'wss')
        .replace(/^http/, 'ws')
        .replace(/\/api\/v1\/?$/, '');
      const ws = new WebSocket(`${wsUrl}/ws/delivery/${assignmentOrderId}/?token=${encodeURIComponent(token)}`);
      wsRef.current = ws;

      // Subscribe to GPS updates
      const sub = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.High, distanceInterval: 10, timeInterval: 5000 },
        (loc) => {
          if (!active) return;
          const { latitude: lat, longitude: lng } = loc.coords;
          setRiderPos({ lat, lng });

          // Push to map
          webViewRef.current?.injectJavaScript(
            `updateRider(${lat}, ${lng}); true;`
          );

          // Send via WebSocket if open
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'location_update', lat, lng }));
          }
        }
      );
      locSubRef.current = sub;
    }

    startTracking();

    return () => {
      active = false;
      locSubRef.current?.remove();
      wsRef.current?.close();
    };
  }, [assignmentOrderId, token]);

  // ── Actions ──────────────────────────────────────────────────────────────
  const handlePickedUp = async () => {
    const net = await NetInfo.fetch();
    if (!net.isConnected) { setSnack('No internet — connect to mark as picked up'); return; }
    setActioning(true);
    try {
      await apiMarkPickedUp(assignmentOrderId);
      setSnack('Marked as picked up!');
      loadAssignment();
    } catch (e) {
      setSnack(e.response?.data?.error || 'Could not update status');
    } finally {
      setActioning(false);
    }
  };

  const handleDelivered = async () => {
    const net = await NetInfo.fetch();
    if (!net.isConnected) { setSnack('No internet — connect to mark as delivered'); return; }
    Alert.alert(
      'Confirm Delivery',
      'Mark this order as delivered?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delivered',
          style: 'default',
          onPress: async () => {
            setActioning(true);
            try {
              await apiMarkDelivered(assignmentOrderId);
              setSnack('Delivery complete!');
              setTimeout(() => navigation.goBack(), 1500);
            } catch (e) {
              setSnack(e.response?.data?.error || 'Could not complete delivery');
            } finally {
              setActioning(false);
            }
          },
        },
      ]
    );
  };

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }

  if (!assignment || loadError) {
    return (
      <View style={styles.center}>
        <Text style={{ fontFamily: 'Poppins_400Regular', color: '#757575', marginBottom: 16 }}>
          Could not load delivery details
        </Text>
        <Button mode="outlined" icon="refresh" onPress={loadAssignment}>
          Retry
        </Button>
      </View>
    );
  }

  const a = assignment.assignment;

  const statusColor = { assigned: '#1565C0', picked_up: '#6A1B9A', delivered: '#2E7D32' };
  const col = statusColor[a?.status] || '#757575';

  return (
    <View style={styles.screen}>
      {/* Info strip */}
      <Card style={styles.infoCard}>
        <Card.Content>
          <View style={styles.row}>
            <Text variant="titleMedium" style={styles.bold}>Order #{a?.order_number}</Text>
            <Chip compact style={{ backgroundColor: col + '22' }} textStyle={{ color: col, fontFamily: 'Poppins_600SemiBold', fontSize: 11 }}>
              {a?.status_display}
            </Chip>
          </View>
          <Text variant="bodySmall" style={styles.addrText}>📍 {a?.delivery_address || 'No address'}</Text>
          <Text variant="bodySmall" style={styles.meta}>Customer: {a?.customer_name}</Text>
          <Text variant="bodySmall" style={styles.meta}>Phone: {a?.delivery_phone || 'N/A'}</Text>
        </Card.Content>
      </Card>

      {/* Map */}
      <WebView
        ref={webViewRef}
        source={{ html: mapHtml }}
        style={styles.map}
        javaScriptEnabled
        originWhitelist={['*']}
      />

      {/* Action buttons */}
      <View style={styles.actions}>
        {a?.status === 'assigned' && (
          <Button
            mode="contained"
            style={[styles.actionBtn, { backgroundColor: '#6A1B9A' }]}
            labelStyle={{ fontFamily: 'Poppins_700Bold' }}
            loading={actioning}
            disabled={actioning}
            icon="package-up"
            onPress={handlePickedUp}
          >
            Picked Up from Restaurant
          </Button>
        )}
        {a?.status === 'picked_up' && (
          <Button
            mode="contained"
            style={[styles.actionBtn, { backgroundColor: '#2E7D32' }]}
            labelStyle={{ fontFamily: 'Poppins_700Bold' }}
            loading={actioning}
            disabled={actioning}
            icon="check-circle"
            onPress={handleDelivered}
          >
            Mark as Delivered
          </Button>
        )}
        {a?.status === 'delivered' && (
          <Button
            mode="outlined"
            style={styles.actionBtn}
            labelStyle={{ fontFamily: 'Poppins_600SemiBold' }}
            icon="arrow-left"
            onPress={() => navigation.goBack()}
          >
            Back to Dashboard
          </Button>
        )}
      </View>

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>{snack}</Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  screen:    { flex: 1, backgroundColor: '#F5F5F5' },
  center:    { flex: 1, justifyContent: 'center', alignItems: 'center' },
  infoCard:  { margin: 10, borderRadius: 12 },
  row:       { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  bold:      { fontFamily: 'Poppins_700Bold' },
  addrText:  { fontFamily: 'Poppins_400Regular', color: '#424242', marginVertical: 2 },
  meta:      { fontFamily: 'Poppins_400Regular', color: '#757575', fontSize: 12 },
  map:       { flex: 1, marginHorizontal: 0 },
  actions:   { padding: 12, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: '#E0E0E0' },
  actionBtn: { borderRadius: 10 },
});
