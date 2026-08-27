import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  View, FlatList, StyleSheet, Image, RefreshControl, Modal, TouchableOpacity,
} from 'react-native';
import {
  Text, Card, Button, ActivityIndicator, Snackbar, Searchbar, useTheme,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { apiRestaurants, apiRestaurantByQR } from '../../api/restaurants';
import { useAuthStore } from '../../store/useAuthStore';

export default function RestaurantSelectorScreen({ navigation }) {
  const theme = useTheme();
  const { setRestaurant, restaurantId } = useAuthStore();

  const [restaurants, setRestaurants] = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [refreshing,  setRefreshing]  = useState(false);
  const [search,      setSearch]      = useState('');
  const [snack,       setSnack]       = useState('');

  // QR scanner state
  const [scannerOpen,  setScannerOpen]  = useState(false);
  const [scanLoading,  setScanLoading]  = useState(false);
  const [permission,   requestPermission] = useCameraPermissions();
  const scannedRef = useRef(false);   // prevent duplicate scans
  const mountedRef = useRef(true);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await apiRestaurants();
      if (!mountedRef.current) return;
      setRestaurants(data || []);
    } catch {
      if (mountedRef.current) setSnack('Could not load restaurants. Check your connection.');
    } finally {
      if (mountedRef.current) { setLoading(false); setRefreshing(false); }
    }
  }, []);

  useEffect(() => {
    // If a restaurant was already chosen (persisted), skip straight to ordering
    if (restaurantId) {
      navigation.replace('TableSelection');
      return;
    }
    load();
  }, []);  // only run once on mount

  const handleSelect = (restaurant) => {
    // Remote-order restaurants go to order type selection (delivery / pickup).
    // QR-scanned restaurants go straight to table selection.
    navigation.navigate('OrderType', { restaurant });
  };

  // ── QR scan handler ───────────────────────────────────────────────────
  const openScanner = async () => {
    if (!permission?.granted) {
      const result = await requestPermission();
      if (!result.granted) {
        setSnack('Camera permission is required to scan QR codes.');
        return;
      }
    }
    scannedRef.current = false;
    setScannerOpen(true);
  };

  const handleQRScanned = async ({ data }) => {
    if (scannedRef.current || scanLoading) return;
    scannedRef.current = true;
    setScanLoading(true);
    try {
      // Extract the QR code string — the physical QR URL is like
      // https://hospitality.easyfixsoft.com/r/<qr_code>/
      // so strip to just the code portion if a full URL was encoded
      let code = data.trim();
      const urlMatch = code.match(/\/r\/([^/]+)\/?$/);
      if (urlMatch) code = urlMatch[1];

      const restaurant = await apiRestaurantByQR(code);
      if (!mountedRef.current) return;
      setScannerOpen(false);
      await setRestaurant(restaurant.id);
      navigation.replace('TableSelection');
    } catch (err) {
      if (!mountedRef.current) return;
      const msg = err?.response?.data?.error || 'QR code not recognised. Please try again.';
      setSnack(msg);
      scannedRef.current = false;  // allow retry
    } finally {
      if (mountedRef.current) setScanLoading(false);
    }
  };

  // Only show restaurants that allow remote ordering in the list.
  // QR scan (inside restaurant) is the path for dine-in.
  const filtered = restaurants.filter((r) =>
    r.allow_remote_orders && (
      r.name.toLowerCase().includes(search.toLowerCase()) ||
      (r.address || '').toLowerCase().includes(search.toLowerCase())
    )
  );

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#2c3e50" />
        <Text variant="bodyMedium" style={styles.loadingText}>Loading restaurants…</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <MaterialCommunityIcons name="silverware-fork-knife" size={32} color="#2c3e50" />
        <Text variant="headlineSmall" style={styles.title}>Order from Anywhere</Text>
        <Text variant="bodyMedium" style={styles.subtitle}>Browse restaurants that accept delivery &amp; pickup orders</Text>

        {/* QR Scan button */}
        <Button
          mode="contained"
          icon="qrcode-scan"
          onPress={openScanner}
          style={styles.qrButton}
          contentStyle={styles.qrButtonContent}
          labelStyle={styles.qrButtonLabel}
        >
          Scan QR Code
        </Button>
      </View>

      <Searchbar
        placeholder="Search restaurants…"
        value={search}
        onChangeText={setSearch}
        style={styles.searchbar}
        inputStyle={{ fontFamily: 'Poppins_400Regular' }}
      />

      <FlatList
        data={filtered}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); load(true); }}
          />
        }
        ListEmptyComponent={() => (
          <View style={styles.center}>
            <MaterialCommunityIcons name="store-off-outline" size={52} color="#ccc" />
            <Text variant="bodyLarge" style={styles.emptyText}>
              {search ? 'No restaurants match your search' : 'No restaurants accepting remote orders right now'}
            </Text>
          </View>
        )}
        renderItem={({ item }) => (
          <Card style={styles.card} onPress={() => handleSelect(item)}>
            <Card.Content style={styles.cardContent}>
              {/* Logo or initials */}
              {item.logo_url ? (
                <Image source={{ uri: item.logo_url }} style={styles.logo} />
              ) : (
                <View style={styles.logoPlaceholder}>
                  <Text style={styles.logoInitials}>
                    {item.name.slice(0, 2).toUpperCase()}
                  </Text>
                </View>
              )}

              <View style={styles.info}>
                <Text variant="titleMedium" style={styles.name} numberOfLines={1}>
                  {item.name}
                </Text>
                {item.address ? (
                  <View style={styles.addressRow}>
                    <MaterialCommunityIcons name="map-marker-outline" size={13} color="#888" />
                    <Text variant="bodySmall" style={styles.address} numberOfLines={1}>
                      {item.address}
                    </Text>
                  </View>
                ) : null}
                {item.description ? (
                  <Text variant="bodySmall" style={styles.description} numberOfLines={2}>
                    {item.description}
                  </Text>
                ) : null}
                <View style={styles.badgeRow}>
                  <View style={styles.badge}><Text style={styles.badgeText}>Delivery</Text></View>
                  <View style={styles.badge}><Text style={styles.badgeText}>Pickup</Text></View>
                </View>
              </View>

              <MaterialCommunityIcons name="chevron-right" size={24} color="#2c3e50" />
            </Card.Content>
          </Card>
        )}
      />

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={4000}>
        {snack}
      </Snackbar>

      {/* ── QR Camera Modal ─────────────────────────────────────────── */}
      <Modal
        visible={scannerOpen}
        animationType="slide"
        onRequestClose={() => setScannerOpen(false)}
      >
        <View style={styles.scannerContainer}>
          <CameraView
            style={styles.camera}
            facing="back"
            barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
            onBarcodeScanned={handleQRScanned}
          />

          {/* Viewfinder overlay */}
          <View style={styles.overlay} pointerEvents="none">
            <View style={styles.viewfinder} />
          </View>

          {/* Loading indicator while resolving */}
          {scanLoading && (
            <View style={styles.scanLoadingBox}>
              <ActivityIndicator color="#fff" size="large" />
              <Text style={styles.scanLoadingText}>Looking up restaurant…</Text>
            </View>
          )}

          {/* Instructions */}
          <View style={styles.scanInstructions}>
            <MaterialCommunityIcons name="qrcode-scan" size={22} color="#fff" />
            <Text style={styles.scanInstructionsText}>
              Point the camera at the restaurant QR code
            </Text>
          </View>

          {/* Close button */}
          <TouchableOpacity style={styles.closeBtn} onPress={() => setScannerOpen(false)}>
            <MaterialCommunityIcons name="close-circle" size={40} color="#fff" />
          </TouchableOpacity>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container:       { flex: 1, backgroundColor: '#F5F5F5' },
  center:          { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 32 },
  header:          { alignItems: 'center', paddingVertical: 24, paddingHorizontal: 16, backgroundColor: '#fff' },
  title:           { fontFamily: 'Poppins_700Bold', color: '#2c3e50', marginTop: 8 },
  subtitle:        { fontFamily: 'Poppins_400Regular', color: '#666', marginTop: 4 },
  loadingText:     { marginTop: 12, color: '#666', fontFamily: 'Poppins_400Regular' },
  qrButton:        { marginTop: 16, borderRadius: 10, backgroundColor: '#2c3e50' },
  qrButtonContent: { paddingVertical: 4, paddingHorizontal: 8 },
  qrButtonLabel:   { fontFamily: 'Poppins_700Bold', fontSize: 14 },
  searchbar:       { margin: 12, borderRadius: 10, elevation: 2 },
  list:            { paddingHorizontal: 12, paddingBottom: 24 },
  card:            { marginBottom: 10, borderRadius: 12, elevation: 2 },
  cardContent:     { flexDirection: 'row', alignItems: 'center' },
  logo:            { width: 54, height: 54, borderRadius: 10, marginRight: 12 },
  logoPlaceholder: {
    width: 54, height: 54, borderRadius: 10, marginRight: 12,
    backgroundColor: '#2c3e50', justifyContent: 'center', alignItems: 'center',
  },
  logoInitials:    { color: '#fff', fontSize: 18, fontFamily: 'Poppins_700Bold' },
  info:            { flex: 1, marginRight: 8 },
  name:            { fontFamily: 'Poppins_700Bold', color: '#2c3e50' },
  addressRow:      { flexDirection: 'row', alignItems: 'center', marginTop: 2 },
  address:         { color: '#888', marginLeft: 3, flex: 1 },
  description:     { color: '#666', marginTop: 3, fontFamily: 'Poppins_400Regular' },
  badgeRow:        { flexDirection: 'row', gap: 6, marginTop: 6 },
  badge:           { backgroundColor: '#E8F5E9', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  badgeText:       { color: '#2E7D32', fontSize: 11, fontFamily: 'Poppins_600SemiBold' },
  emptyText:       { color: '#999', marginTop: 12, textAlign: 'center', fontFamily: 'Poppins_400Regular' },

  // ── Scanner ────────────────────────────────────────────────────────────
  scannerContainer: { flex: 1, backgroundColor: '#000' },
  camera:           { flex: 1 },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'center',
    alignItems: 'center',
  },
  viewfinder: {
    width: 240,
    height: 240,
    borderWidth: 3,
    borderColor: '#fff',
    borderRadius: 16,
    backgroundColor: 'transparent',
  },
  scanLoadingBox: {
    position: 'absolute',
    top: '50%',
    alignSelf: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.7)',
    padding: 20,
    borderRadius: 12,
  },
  scanLoadingText: { color: '#fff', marginTop: 10, fontFamily: 'Poppins_400Regular' },
  scanInstructions: {
    position: 'absolute',
    bottom: 100,
    left: 0,
    right: 0,
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 24,
  },
  scanInstructionsText: {
    color: '#fff',
    fontSize: 14,
    fontFamily: 'Poppins_400Regular',
    textAlign: 'center',
    textShadowColor: '#000',
    textShadowRadius: 4,
  },
  closeBtn: {
    position: 'absolute',
    top: 48,
    right: 20,
  },
});
