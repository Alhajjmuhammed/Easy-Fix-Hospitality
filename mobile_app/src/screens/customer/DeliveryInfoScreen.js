import React, { useState, useRef, useEffect, useMemo } from 'react';
import { View, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { Text, TextInput, Button, ActivityIndicator, Snackbar } from 'react-native-paper';
import { WebView } from 'react-native-webview';
import * as Location from 'expo-location';
import { useCartStore } from '../../store/useCartStore';
import { reverseGeocode } from '../../utils/geocoding';

function buildMapHtml(initLat, initLng) {
  return `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body,#map { margin:0;padding:0;width:100%;height:100%; }
  #pin {
    position:absolute;top:50%;left:50%;
    transform:translate(-50%, -100%);
    font-size:42px;z-index:1000;pointer-events:none;line-height:1;
  }
  #tip {
    position:absolute;bottom:12px;left:50%;transform:translateX(-50%);
    background:rgba(255,255,255,.93);padding:5px 16px;border-radius:20px;
    font-family:sans-serif;font-size:12px;color:#555;font-weight:600;
    box-shadow:0 2px 6px rgba(0,0,0,.25);z-index:1000;white-space:nowrap;
  }
</style>
</head>
<body>
<div id="pin">📍</div>
<div id="tip">Move the map to place the pin on your door</div>
<div id="map"></div>
<script>
var map = L.map('map', { zoomControl: true }).setView([${initLat}, ${initLng}], 17);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 19
}).addTo(map);

function sendCoords() {
  var c = map.getCenter();
  window.ReactNativeWebView.postMessage(JSON.stringify({ lat: c.lat, lng: c.lng }));
}

map.on('moveend', sendCoords);
sendCoords();
</script>
</body>
</html>`;
}

export default function DeliveryInfoScreen({ route, navigation }) {
  const { restaurant, orderType } = route.params;
  const { setRemoteOrder } = useCartStore();

  const [address, setAddress]   = useState('');
  const [phone,   setPhone]     = useState('');
  const [coords,  setCoords]    = useState(null);
  const [locating, setLocating] = useState(true);
  const [initPos, setInitPos]   = useState(null);
  const [snack,   setSnack]     = useState('');

  const reverseTimerRef = useRef(null);
  const mountedRef = useRef(true);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  // Must be before any early returns — hooks must run unconditionally
  // Only generates HTML once initPos is set; stable reference thereafter
  const mapSource = useMemo(
    () => initPos ? { html: buildMapHtml(initPos.lat, initPos.lng) } : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [initPos?.lat, initPos?.lng],
  );

  useEffect(() => {
    return () => clearTimeout(reverseTimerRef.current);
  }, []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (!mounted) return;
        if (status === 'granted') {
          const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
          if (!mounted) return;
          setInitPos({ lat: loc.coords.latitude, lng: loc.coords.longitude });
        } else {
          setInitPos({ lat: -1.286389, lng: 36.817223 });
        }
      } catch {
        if (!mounted) return;
        setInitPos({ lat: -1.286389, lng: 36.817223 });
      } finally {
        if (mounted) setLocating(false);
      }
    })();
    return () => { mounted = false; };
  }, []);

  const handleMapMessage = (e) => {
    try {
      const { lat, lng } = JSON.parse(e.nativeEvent.data);
      setCoords({ lat, lng });
      clearTimeout(reverseTimerRef.current);
      reverseTimerRef.current = setTimeout(async () => {
        try {
          const addr = await reverseGeocode(lat, lng);
          if (addr && mountedRef.current) setAddress(addr);
        } catch { /* ignore reverse geocode failures — address stays empty */ }
      }, 700);
    } catch {}
  };

  const handleContinue = () => {
    if (!coords) {
      setSnack('Please move the map to place the pin on your delivery location.');
      return;
    }
    if (!phone.trim()) {
      setSnack('Please enter your phone number so the rider can contact you.');
      return;
    }
    setRemoteOrder(
      restaurant.id,
      orderType,
      address.trim() || 'Pin location',
      phone.trim(),
      coords.lat,
      coords.lng,
    );
    navigation.navigate('Menu');
  };

  if (locating || !initPos) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#E65100" />
        <Text style={styles.locText}>Getting your location…</Text>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      {/* Map pin picker */}
      <View style={styles.mapContainer}>
        <WebView
          source={mapSource}
          style={styles.map}
          javaScriptEnabled
          originWhitelist={['*']}
          onMessage={handleMapMessage}
        />
      </View>

      {/* Details below the map */}
      <View style={styles.controls}>
        <Text variant="bodySmall" style={styles.hint}>
          Move the map so the 📍 pin lands on your door, then confirm below
        </Text>

        <TextInput
          label="Delivery Address"
          value={address}
          onChangeText={setAddress}
          mode="outlined"
          multiline
          numberOfLines={2}
          placeholder="Auto-filled from pin — tap to edit if needed"
          style={styles.input}
          left={<TextInput.Icon icon="map-marker" />}
        />

        <TextInput
          label="Phone Number *"
          value={phone}
          onChangeText={setPhone}
          mode="outlined"
          keyboardType="phone-pad"
          placeholder="+1 555 000 0000"
          style={styles.input}
          left={<TextInput.Icon icon="phone" />}
        />

        <Button
          mode="contained"
          icon="silverware-fork-knife"
          onPress={handleContinue}
          style={styles.continueBtn}
          contentStyle={styles.continueBtnContent}
          labelStyle={{ fontFamily: 'Poppins_700Bold', fontSize: 15 }}
        >
          Browse Menu
        </Button>

        <Button
          mode="outlined"
          icon="arrow-left"
          onPress={() => navigation.goBack()}
          style={styles.backBtn}
        >
          Back
        </Button>
      </View>

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {snack}
      </Snackbar>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  center:             { flex: 1, justifyContent: 'center', alignItems: 'center' },
  locText:            { marginTop: 12, fontFamily: 'Poppins_400Regular', color: '#666' },
  mapContainer:       { height: 300, borderBottomWidth: 1, borderBottomColor: '#ddd' },
  map:                { flex: 1 },
  controls:           { flex: 1, padding: 16, backgroundColor: '#fff' },
  hint:               { fontFamily: 'Poppins_400Regular', color: '#555', marginBottom: 10, textAlign: 'center' },
  input:              { marginBottom: 10, fontFamily: 'Poppins_400Regular' },
  continueBtn:        { marginTop: 4, borderRadius: 10, backgroundColor: '#E65100' },
  continueBtnContent: { paddingVertical: 4 },
  backBtn:            { marginTop: 8, borderColor: '#ccc' },
});
