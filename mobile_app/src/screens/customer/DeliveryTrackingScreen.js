import React, { useState, useEffect, useRef, useCallback } from 'react';
import { View, StyleSheet } from 'react-native';
import { Text, Card, Chip, ActivityIndicator, Snackbar, Banner } from 'react-native-paper';
import { WebView } from 'react-native-webview';
import { useAuthStore } from '../../store/useAuthStore';
import { apiTrackOrder } from '../../api/delivery';
import { API_BASE_URL } from '../../config';

// Build the Leaflet map HTML — shows moving rider + customer's home pin
function buildMapHtml({ riderLat, riderLng, riderName, vehicle, destLat, destLng, destAddress }) {
  const hasRider = riderLat != null && riderLng != null;
  const hasDest  = destLat  != null && destLng  != null;
  const centerLat = hasRider ? riderLat : (hasDest ? destLat : -1.286389);
  const centerLng = hasRider ? riderLng : (hasDest ? destLng : 36.817223);

  const vehicleEmoji = { motorcycle: '🏍', bicycle: '🚲', car: '🚗', foot: '🚶' };
  const emoji = vehicleEmoji[vehicle] || '🏍';

  return `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body,#map { margin:0;padding:0;width:100%;height:100%; }
  #info { position:absolute;top:10px;left:50%;transform:translateX(-50%);
          background:rgba(255,255,255,.92);padding:6px 14px;border-radius:20px;
          font-family:sans-serif;font-size:13px;font-weight:600;color:#1565C0;
          box-shadow:0 2px 8px rgba(0,0,0,.2);z-index:1000;white-space:nowrap; }
</style>
</head>
<body>
<div id="info">${emoji} ${riderName || 'Rider'} is on the way!</div>
<div id="map"></div>
<script>
var map = L.map('map').setView([${centerLat}, ${centerLng}], 14);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 19
}).addTo(map);

var riderIcon = L.divIcon({
  html: '<div style="background:#1565C0;color:#fff;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;font-size:22px;border:3px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35)">${emoji}</div>',
  className:'', iconAnchor:[22,22]
});
var homeIcon = L.divIcon({
  html: '<div style="background:#C62828;color:#fff;border-radius:50% 50% 50% 0;width:44px;height:44px;display:flex;align-items:center;justify-content:center;font-size:22px;border:3px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35);transform:rotate(-45deg)"><span style="transform:rotate(45deg)">🏠</span></div>',
  className:'', iconAnchor:[22,44]
});

var riderMarker = null;
var homeMarker  = null;

${hasRider ? `
riderMarker = L.marker([${riderLat}, ${riderLng}], {icon: riderIcon})
  .addTo(map).bindPopup('${riderName || 'Rider'}').openPopup();
` : ''}

${hasDest ? `
homeMarker = L.marker([${destLat}, ${destLng}], {icon: homeIcon})
  .addTo(map).bindPopup(${JSON.stringify('🏠 ' + (destAddress || 'Your address'))});
` : ''}

${hasRider && hasDest ? `
map.fitBounds(L.latLngBounds([[${riderLat},${riderLng}],[${destLat},${destLng}]]), { padding:[60,60] });
` : ''}

function moveRider(lat, lng) {
  if (!riderMarker) {
    riderMarker = L.marker([lat, lng], {icon: riderIcon}).addTo(map).bindPopup('${riderName || 'Rider'}');
  } else {
    riderMarker.setLatLng([lat, lng]);
  }
  // Keep both markers in view
  if (homeMarker) {
    map.fitBounds(L.latLngBounds([riderMarker.getLatLng(), homeMarker.getLatLng()]), { padding:[60,60], maxZoom:16 });
  } else {
    map.panTo([lat, lng]);
  }
}

function handleMsg(e) {
  try {
    var d = JSON.parse(e.data);
    if (d.type === 'location_update') moveRider(d.lat, d.lng);
    if (d.type === 'delivered') {
      document.getElementById('info').textContent = '✅ Delivered!';
      document.getElementById('info').style.color = '#2E7D32';
    }
  } catch(err) {}
}
document.addEventListener('message', handleMsg);
window.addEventListener('message', handleMsg);
</script>
</body>
</html>`;
}

const STATUS_COLOR = {
  out_for_delivery: '#1565C0',
  delivered:        '#2E7D32',
  assigned:         '#1565C0',
  picked_up:        '#6A1B9A',
};

export default function DeliveryTrackingScreen({ route }) {
  const { orderId } = route.params;
  const { token }   = useAuthStore();

  const [trackData, setTrackData]   = useState(null);
  const [loading, setLoading]       = useState(true);
  const [snack, setSnack]           = useState('');
  const [delivered, setDelivered]   = useState(false);
  const [destCoords, setDestCoords] = useState(null);

  const webViewRef = useRef(null);
  const wsRef      = useRef(null);

  // ── Initial load ─────────────────────────────────────────────────────────
  const loadTrack = useCallback(async () => {
    try {
      const data = await apiTrackOrder(orderId);
      setTrackData(data);
      if (data.assignment?.status === 'delivered') setDelivered(true);
      const lat = data?.assignment?.delivery_lat;
      const lng = data?.assignment?.delivery_lng;
      if (lat != null && lng != null) setDestCoords({ lat, lng });
    } catch {
      setSnack('Could not load tracking info');
    } finally {
      setLoading(false);
    }
  }, [orderId]);

  useEffect(() => { loadTrack(); }, [loadTrack]);

  // ── WebSocket: receive live location from rider ───────────────────────────
  useEffect(() => {
    if (!token) return;

    const wsUrl = API_BASE_URL
      .replace(/^https/, 'wss')
      .replace(/^http/, 'ws')
      .replace(/\/api\/v1\/?$/, '');

    const ws = new WebSocket(`${wsUrl}/ws/delivery/${orderId}/?token=${encodeURIComponent(token)}`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);

        if (msg.type === 'location_update' || msg.type === 'location_broadcast') {
          const { lat, lng } = msg;
          // Update map
          webViewRef.current?.injectJavaScript(
            `moveRider(${lat}, ${lng}); true;`
          );
        }

        if (msg.type === 'delivery_status' && msg.status === 'delivered') {
          setDelivered(true);
          webViewRef.current?.injectJavaScript(
            `document.getElementById('info').textContent='✅ Delivered!';
             document.getElementById('info').style.color='#2E7D32'; true;`
          );
          loadTrack();
        }

        if (msg.type === 'snapshot') {
          // Initial snapshot from server
          if (msg.lat && msg.lng) {
            webViewRef.current?.injectJavaScript(
              `moveRider(${msg.lat}, ${msg.lng}); true;`
            );
          }
        }
      } catch { /* ignore parse errors */ }
    };

    ws.onerror = () => setSnack('Live tracking disconnected — auto-refreshing');

    // Fallback poll every 15 s when WS is unavailable
    const poll = setInterval(loadTrack, 15_000);

    return () => {
      ws.close();
      clearInterval(poll);
    };
  }, [orderId, token, loadTrack]);

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }

  if (!trackData) {
    return (
      <View style={styles.center}>
        <Text style={{ fontFamily: 'Poppins_400Regular', color: '#757575' }}>
          No tracking data available
        </Text>
      </View>
    );
  }

  const a     = trackData.assignment;
  const rider = a?.rider;
  const col   = STATUS_COLOR[a?.status] || '#757575';

  const mapHtml = buildMapHtml({
    riderLat: trackData.rider_lat,
    riderLng: trackData.rider_lng,
    riderName: rider?.name,
    vehicle: rider?.vehicle,
    destLat: destCoords?.lat ?? null,
    destLng: destCoords?.lng ?? null,
    destAddress: a?.delivery_address,
  });

  return (
    <View style={styles.screen}>
      {/* Delivered banner */}
      {delivered && (
        <Banner
          visible
          icon="check-circle"
          actions={[]}
          style={{ backgroundColor: '#E8F5E9' }}
        >
          Your order has been delivered! Enjoy your meal.
        </Banner>
      )}

      {/* Status header */}
      <Card style={styles.statusCard}>
        <Card.Content>
          <View style={styles.row}>
            <Text variant="titleMedium" style={styles.bold}>
              Order #{a?.order_number}
            </Text>
            <Chip
              compact
              style={{ backgroundColor: col + '22' }}
              textStyle={{ color: col, fontFamily: 'Poppins_600SemiBold', fontSize: 11 }}
            >
              {a?.status_display || 'Out for Delivery'}
            </Chip>
          </View>

          {rider && (
            <View style={styles.riderRow}>
              <Text variant="bodySmall" style={styles.riderLabel}>Rider</Text>
              <Text variant="bodyMedium" style={styles.riderName}>
                {rider.name}  ·  {rider.vehicle_display}
              </Text>
              {rider.phone ? (
                <Text variant="bodySmall" style={styles.meta}>📞 {rider.phone}</Text>
              ) : null}
            </View>
          )}

          <Text variant="bodySmall" style={styles.meta}>
            📍 {a?.delivery_address || 'Your delivery address'}
          </Text>
        </Card.Content>
      </Card>

      {/* Live map */}
      <WebView
        ref={webViewRef}
        source={{ html: mapHtml }}
        style={styles.map}
        javaScriptEnabled
        originWhitelist={['*']}
      />

      {/* Live indicator */}
      {!delivered && (
        <View style={styles.liveBar}>
          <View style={styles.liveDot} />
          <Text style={styles.liveText}>LIVE  ·  Map updates in real time</Text>
        </View>
      )}

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={4000}>{snack}</Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  screen:      { flex: 1, backgroundColor: '#F5F5F5' },
  center:      { flex: 1, justifyContent: 'center', alignItems: 'center' },
  statusCard:  { margin: 10, borderRadius: 12 },
  row:         { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 },
  bold:        { fontFamily: 'Poppins_700Bold' },
  riderRow:    { marginVertical: 4 },
  riderLabel:  { fontFamily: 'Poppins_400Regular', color: '#9E9E9E', fontSize: 11 },
  riderName:   { fontFamily: 'Poppins_600SemiBold', color: '#2c3e50' },
  meta:        { fontFamily: 'Poppins_400Regular', color: '#757575', fontSize: 12, marginTop: 2 },
  map:         { flex: 1 },
  liveBar:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
                 paddingVertical: 8, backgroundColor: '#fff',
                 borderTopWidth: 1, borderTopColor: '#E0E0E0', gap: 6 },
  liveDot:     { width: 8, height: 8, borderRadius: 4, backgroundColor: '#F44336' },
  liveText:    { fontFamily: 'Poppins_600SemiBold', fontSize: 12, color: '#424242' },
});
