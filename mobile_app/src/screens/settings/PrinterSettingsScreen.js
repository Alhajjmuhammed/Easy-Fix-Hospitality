/**
 * PrinterSettingsScreen.js
 *
 * Lets staff choose a print mode and (for Bluetooth mode) scan and pair
 * with a thermal printer directly from the app.
 *
 * Modes explained on-screen:
 *  Auto       — tries BT → network → system dialog
 *  Bluetooth  — silent direct print to a paired thermal printer (requires custom build)
 *  Network    — sends job to server → Print Client on Windows PC
 *  System     — native OS print dialog (works with any printer, always available)
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  FlatList,
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Platform,
  TextInput,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

import { usePrinterStore }      from '../../store/usePrinterStore';
import { useAuthStore }         from '../../store/useAuthStore';
import { useLockStore }         from '../../store/useLockStore';

// ─── Shared banner helpers (same as DashboardScreen) ─────────────────────────
function stringToColor(str = '') {
  const PALETTE = ['#2c3e50', '#AD1457', '#6A1B9A', '#00838F', '#2E7D32', '#E65100', '#4527A0', '#37474F'];
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  return PALETTE[Math.abs(hash) % PALETTE.length];
}
function nameInitials(name = '') {
  return name.split(' ').filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
}
function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}
function RestaurantBanner({ user }) {
  const restaurantName = user?.restaurant_name || 'Restaurant';
  const logoUrl        = user?.restaurant_logo_url || null;
  const staffFirstName = user?.first_name || user?.username || 'there';
  const color          = stringToColor(restaurantName);
  const initials       = nameInitials(restaurantName);
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  return (
    <View style={[bannerStyles.wrapper, { backgroundColor: color }]}>
      <View style={[bannerStyles.circle1, { backgroundColor: 'rgba(255,255,255,0.08)' }]} />
      <View style={[bannerStyles.circle2, { backgroundColor: 'rgba(255,255,255,0.06)' }]} />
      {logoUrl ? (
        <Image source={{ uri: logoUrl }} style={bannerStyles.logoImage} resizeMode="cover" />
      ) : (
        <View style={bannerStyles.logoCircle}>
          <Text style={bannerStyles.logoInitials}>{initials}</Text>
        </View>
      )}
      <Text style={bannerStyles.restaurantName} numberOfLines={1}>{restaurantName}</Text>
      <Text style={bannerStyles.greeting}>{getGreeting()}, {staffFirstName}!</Text>
      <Text style={bannerStyles.date}>{today}</Text>
    </View>
  );
}
const bannerStyles = StyleSheet.create({
  wrapper: {
    marginHorizontal: -16, marginTop: -16, marginBottom: 20,
    paddingTop: 32, paddingBottom: 36,
    alignItems: 'center',
    borderBottomLeftRadius: 28, borderBottomRightRadius: 28,
    overflow: 'hidden',
  },
  circle1: { position: 'absolute', width: 180, height: 180, borderRadius: 90, top: -60, right: -40 },
  circle2: { position: 'absolute', width: 120, height: 120, borderRadius: 60, bottom: -30, left: -20 },
  logoImage: {
    width: 80, height: 80, borderRadius: 20,
    borderWidth: 3, borderColor: 'rgba(255,255,255,0.5)', marginBottom: 12,
  },
  logoCircle: {
    width: 80, height: 80, borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    borderWidth: 3, borderColor: 'rgba(255,255,255,0.5)',
    alignItems: 'center', justifyContent: 'center', marginBottom: 12,
  },
  logoInitials: { color: '#fff', fontFamily: 'Poppins_700Bold', fontSize: 30, lineHeight: 36 },
  restaurantName: {
    color: '#fff', fontFamily: 'Poppins_700Bold', fontSize: 22,
    lineHeight: 28, textAlign: 'center', paddingHorizontal: 24,
  },
  greeting: { color: 'rgba(255,255,255,0.85)', fontFamily: 'Poppins_400Regular', fontSize: 13, marginTop: 4, textAlign: 'center' },
  date:     { color: 'rgba(255,255,255,0.65)', fontFamily: 'Poppins_400Regular', fontSize: 11, marginTop: 2, textAlign: 'center' },
});
import {
  isBtClassicAvailable,
  scanBluetoothDevices,
  connectBluetoothPrinter,
  printReceipt,
}                               from '../../utils/printer';

// ─── Mode definitions ─────────────────────────────────────────────────────────

const MODES = [
  {
    key:   'auto',
    label: 'Auto (Recommended)',
    icon:  'flash',
    desc:  'Tries Bluetooth → Network → System dialog automatically.',
  },
  {
    key:   'bluetooth',
    label: 'Bluetooth (Silent)',
    icon:  'bluetooth',
    desc:  'Prints silently to a paired Bluetooth thermal printer. Requires custom build — will fall back to System dialog in Expo Go.',
  },
  {
    key:   'network',
    label: 'Network (Print Client)',
    icon:  'desktop-outline',
    desc:  'Sends job to server. Requires a Windows PC running the Print Client on the same network.',
  },
  {
    key:   'system',
    label: 'System Dialog',
    icon:  'print-outline',
    desc:  'Opens the OS print dialog. Works with any paired Bluetooth, WiFi, or USB printer. No PC needed.',
  },
];

// ─── Component ────────────────────────────────────────────────────────────────

export default function PrinterSettingsScreen() {
  const { mode, bluetoothDevice, autoPrintAfterPayment, localKotBot, saveSettings } = usePrinterStore();
  const user = useAuthStore((s) => s.user);
  const restaurantName = user?.restaurant_name || '';
  const currencySymbol = user?.currency_symbol || '';

  const { hasPin, setPin, removePin } = useLockStore();
  const [scanning, setScanning]       = useState(false);
  const [btDevices, setBtDevices]     = useState([]);
  const [connecting, setConnecting]   = useState(null); // address being connected
  const [testPrinting, setTestPrinting] = useState(false);
  const [btAvailable, setBtAvailable] = useState(false);

  // PIN setup state
  const [showPinForm, setShowPinForm] = useState(false);
  const [newPin, setNewPin]           = useState('');
  const [confirmPin, setConfirmPin]   = useState('');
  const [pinError, setPinError]       = useState('');

  const handleSavePin = useCallback(async () => {
    if (!/^\d{4}$/.test(newPin)) {
      setPinError('PIN must be exactly 4 digits.');
      return;
    }
    if (newPin !== confirmPin) {
      setPinError('PINs do not match.');
      return;
    }
    await setPin(newPin);
    setShowPinForm(false);
    setNewPin('');
    setConfirmPin('');
    setPinError('');
    Alert.alert('PIN Set', 'Screen lock is now active. The app will lock after 30 minutes of inactivity.');
  }, [newPin, confirmPin, setPin]);

  const handleRemovePin = useCallback(() => {
    Alert.alert(
      'Remove PIN',
      'This will disable the screen lock. Are you sure?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: async () => {
            await removePin();
            Alert.alert('PIN Removed', 'Screen lock has been disabled.');
          },
        },
      ],
    );
  }, [removePin]);

  useEffect(() => {
    setBtAvailable(isBtClassicAvailable());
  }, []);

  // ── BT scan ──────────────────────────────────────────────────────────────

  const handleScan = useCallback(async () => {
    if (!btAvailable) {
      Alert.alert(
        'Custom Build Required',
        'Silent Bluetooth printing requires a custom app build.\n\n' +
        'Run the following commands in your mobile_app/ folder:\n\n' +
        '  npx expo prebuild\n' +
        '  npx expo run:android\n\n' +
        'In the meantime, "System Dialog" mode works with any paired printer.',
      );
      return;
    }
    try {
      setScanning(true);
      setBtDevices([]);
      const devices = await scanBluetoothDevices();
      setBtDevices(devices);
      if (devices.length === 0) {
        Alert.alert('No Devices Found', 'Make sure your printer is on and paired in Android Bluetooth settings.');
      }
    } catch (err) {
      Alert.alert('Scan Failed', err?.message || 'Unknown error');
    } finally {
      setScanning(false);
    }
  }, [btAvailable]);

  // ── Connect to a device ───────────────────────────────────────────────────

  const handleConnect = useCallback(async (device) => {
    try {
      setConnecting(device.address);
      await connectBluetoothPrinter(device.address);
      await saveSettings({ bluetoothDevice: device });
      Alert.alert('Connected', `Printer "${device.name}" is ready.`);
    } catch (err) {
      Alert.alert('Connection Failed', err?.message || 'Could not connect to printer.');
    } finally {
      setConnecting(null);
    }
  }, [saveSettings]);

  // ── Test print ────────────────────────────────────────────────────────────

  const handleTestPrint = useCallback(async () => {
    setTestPrinting(true);
    try {
      const demoOrder = {
        id:            'TEST',
        order_number:  'TEST-001',
        table_number:  '1',
        created_at:    new Date().toISOString(),
        subtotal:      '10.00',
        tax_amount:    '1.50',
        total:         '11.50',
        items: [
          { product_name: 'Grilled Chicken', quantity: 1, total_price: '8.00' },
          { product_name: 'Soft Drink',      quantity: 2, total_price: '3.00' },
        ],
      };
      await printReceipt({
        order:          demoOrder,
        restaurantName: restaurantName || 'My Restaurant',
        currencySymbol: currencySymbol || '$',
      });
    } catch (err) {
      Alert.alert('Test Print Failed', err?.message || 'Could not print.');
    } finally {
      setTestPrinting(false);
    }
  }, [restaurantName, currencySymbol]);

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.scroll}>

        {/* Banner — same as Dashboard */}
        <RestaurantBanner user={user} />

        {/* ── Mode Selector ── */}
        <Text style={styles.sectionLabel}>PRINT MODE</Text>
        {MODES.map((m) => {
          const active = mode === m.key;
          return (
            <TouchableOpacity
              key={m.key}
              style={[styles.modeCard, active && styles.modeCardActive]}
              onPress={() => saveSettings({ mode: m.key })}
              activeOpacity={0.7}
            >
              <View style={styles.modeRow}>
                <Ionicons
                  name={m.icon}
                  size={22}
                  color={active ? '#fff' : '#4CAF50'}
                  style={styles.modeIcon}
                />
                <View style={styles.modeText}>
                  <Text style={[styles.modeLabel, active && styles.modeLabelActive]}>
                    {m.label}
                  </Text>
                  <Text style={[styles.modeDesc, active && styles.modeDescActive]}>
                    {m.desc}
                  </Text>
                </View>
                {active && (
                  <Ionicons name="checkmark-circle" size={22} color="#fff" />
                )}
              </View>
            </TouchableOpacity>
          );
        })}

        {/* ── Bluetooth Device (only relevant for bluetooth / auto modes) ── */}
        {(mode === 'bluetooth' || mode === 'auto') && (
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>BLUETOOTH PRINTER</Text>

            {bluetoothDevice ? (
              <View style={styles.connectedDevice}>
                <Ionicons name="bluetooth" size={18} color="#4CAF50" />
                <View style={{ marginLeft: 8, flex: 1 }}>
                  <Text style={styles.deviceName}>{bluetoothDevice.name}</Text>
                  <Text style={styles.deviceAddress}>{bluetoothDevice.address}</Text>
                </View>
                <TouchableOpacity onPress={() => saveSettings({ bluetoothDevice: null })}>
                  <Ionicons name="close-circle" size={22} color="#e53935" />
                </TouchableOpacity>
              </View>
            ) : (
              <Text style={styles.noDevice}>No printer selected</Text>
            )}

            {!btAvailable && (
              <View style={styles.infoBox}>
                <Ionicons name="information-circle-outline" size={18} color="#1565C0" />
                <Text style={styles.infoText}>
                  Silent Bluetooth printing requires a custom build and old architecture.{'\n'}
                  After running <Text style={styles.code}>npx expo prebuild</Text>, open{'\n'}
                  <Text style={styles.code}>android/gradle.properties</Text> and set:{'\n'}
                  <Text style={styles.code}>newArchEnabled=false</Text>{'\n'}
                  Then run <Text style={styles.code}>npx expo run:android</Text>.{'\n\n'}
                  Until then, Auto mode falls back to System dialog automatically.
                </Text>
              </View>
            )}

            <TouchableOpacity
              style={[styles.scanBtn, scanning && styles.btnDisabled]}
              onPress={handleScan}
              disabled={scanning}
            >
              {scanning ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <>
                  <Ionicons name="search" size={16} color="#fff" style={{ marginRight: 6 }} />
                  <Text style={styles.btnText}>Scan for Printers</Text>
                </>
              )}
            </TouchableOpacity>

            {btDevices.length > 0 && (
              <FlatList
                data={btDevices}
                keyExtractor={(d) => d.address}
                scrollEnabled={false}
                style={styles.deviceList}
                renderItem={({ item }) => {
                  const isSelected  = bluetoothDevice?.address === item.address;
                  const isConnecting = connecting === item.address;
                  return (
                    <TouchableOpacity
                      style={[styles.deviceItem, isSelected && styles.deviceItemSelected]}
                      onPress={() => handleConnect(item)}
                      disabled={isConnecting}
                    >
                      <Ionicons
                        name={isSelected ? 'bluetooth' : 'bluetooth-outline'}
                        size={18}
                        color={isSelected ? '#4CAF50' : '#555'}
                      />
                      <View style={{ marginLeft: 10, flex: 1 }}>
                        <Text style={styles.deviceName}>{item.name}</Text>
                        <Text style={styles.deviceAddress}>{item.address}</Text>
                      </View>
                      {isConnecting ? (
                        <ActivityIndicator size="small" color="#4CAF50" />
                      ) : isSelected ? (
                        <Text style={styles.selectedTag}>Active</Text>
                      ) : (
                        <Text style={styles.connectTag}>Connect</Text>
                      )}
                    </TouchableOpacity>
                  );
                }}
              />
            )}
          </View>
        )}

        {/* ── Auto-Print Toggle ── */}
        <Text style={styles.sectionLabel}>OPTIONS</Text>
        <TouchableOpacity
          style={styles.toggleRow}
          onPress={() => saveSettings({ autoPrintAfterPayment: !autoPrintAfterPayment })}
          activeOpacity={0.7}
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.toggleLabel}>Auto-print after payment</Text>
            <Text style={styles.toggleDesc}>
              Automatically print receipt when a payment is completed (no tap needed).
            </Text>
          </View>
          <View style={[styles.toggle, autoPrintAfterPayment && styles.toggleOn]}>
            <View style={[styles.toggleThumb, autoPrintAfterPayment && styles.toggleThumbOn]} />
          </View>
        </TouchableOpacity>

        {/* ── Local KOT/BOT Toggle ── */}
        <TouchableOpacity
          style={styles.toggleRow}
          onPress={() => saveSettings({ localKotBot: !localKotBot })}
          activeOpacity={0.7}
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.toggleLabel}>Print KOT / BOT from phone</Text>
            <Text style={styles.toggleDesc}>
              Print kitchen & bar order tickets directly from this device (via Bluetooth or
              system dialog) when an order is placed. Turn off to use the Windows Print Client
              queue instead.
            </Text>
          </View>
          <View style={[styles.toggle, localKotBot && styles.toggleOn]}>
            <View style={[styles.toggleThumb, localKotBot && styles.toggleThumbOn]} />
          </View>
        </TouchableOpacity>

        {/* ── Test Print ── */}
        <Text style={styles.sectionLabel}>TEST</Text>
        <TouchableOpacity
          style={[styles.testBtn, testPrinting && styles.btnDisabled]}
          onPress={handleTestPrint}
          disabled={testPrinting}
        >
          {testPrinting ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="print" size={18} color="#fff" style={{ marginRight: 8 }} />
              <Text style={styles.btnText}>Print Test Receipt</Text>
            </>
          )}
        </TouchableOpacity>
        <Text style={styles.testNote}>
          Uses the currently selected mode. If Bluetooth or Network fails, it will open
          the system print dialog instead.
        </Text>

        {/* ── Screen Lock / PIN ── */}
        <Text style={styles.sectionLabel}>SCREEN LOCK</Text>
        <View style={styles.pinCard}>
          <View style={styles.pinRow}>
            <Ionicons
              name={hasPin ? 'lock-closed' : 'lock-open-outline'}
              size={22}
              color={hasPin ? '#4CAF50' : '#888'}
              style={{ marginRight: 12 }}
            />
            <View style={{ flex: 1 }}>
              <Text style={styles.pinLabel}>
                {hasPin ? 'PIN Lock Enabled' : 'PIN Lock Disabled'}
              </Text>
              <Text style={styles.pinDesc}>
                {hasPin
                  ? 'App locks after 30 min of inactivity.'
                  : 'Set a 4-digit PIN to lock the app when idle.'}
              </Text>
            </View>
          </View>

          {!showPinForm ? (
            <View style={styles.pinActions}>
              <TouchableOpacity
                style={styles.pinBtn}
                onPress={() => { setShowPinForm(true); setPinError(''); setNewPin(''); setConfirmPin(''); }}
              >
                <Text style={styles.pinBtnText}>{hasPin ? 'Change PIN' : 'Set PIN'}</Text>
              </TouchableOpacity>
              {hasPin && (
                <TouchableOpacity style={[styles.pinBtn, styles.pinBtnDanger]} onPress={handleRemovePin}>
                  <Text style={[styles.pinBtnText, { color: '#e53935' }]}>Remove PIN</Text>
                </TouchableOpacity>
              )}
            </View>
          ) : (
            <View style={styles.pinForm}>
              <TextInput
                style={styles.pinInput}
                placeholder="New 4-digit PIN"
                keyboardType="numeric"
                maxLength={4}
                secureTextEntry
                value={newPin}
                onChangeText={(t) => { setNewPin(t.replace(/\D/g, '')); setPinError(''); }}
              />
              <TextInput
                style={styles.pinInput}
                placeholder="Confirm PIN"
                keyboardType="numeric"
                maxLength={4}
                secureTextEntry
                value={confirmPin}
                onChangeText={(t) => { setConfirmPin(t.replace(/\D/g, '')); setPinError(''); }}
              />
              {!!pinError && <Text style={styles.pinErrorText}>{pinError}</Text>}
              <View style={styles.pinActions}>
                <TouchableOpacity style={styles.pinBtn} onPress={handleSavePin}>
                  <Text style={styles.pinBtnText}>Save PIN</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.pinBtn, { backgroundColor: '#f5f5f5' }]}
                  onPress={() => { setShowPinForm(false); setPinError(''); }}
                >
                  <Text style={[styles.pinBtnText, { color: '#555' }]}>Cancel</Text>
                </TouchableOpacity>
              </View>
            </View>
          )}
        </View>

      </ScrollView>
    </SafeAreaView>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  safe:   { flex: 1, backgroundColor: '#f5f5f5' },
  scroll: { padding: 16, paddingBottom: 40 },

  sectionLabel: {
    fontSize:      11,
    fontWeight:    '700',
    color:         '#888',
    letterSpacing: 1.2,
    marginTop:     20,
    marginBottom:  8,
  },

  // Mode cards
  modeCard: {
    backgroundColor: '#fff',
    borderRadius:     10,
    padding:          14,
    marginBottom:     8,
    borderWidth:      2,
    borderColor:      'transparent',
  },
  modeCardActive: {
    backgroundColor: '#4CAF50',
    borderColor:     '#388E3C',
  },
  modeRow:   { flexDirection: 'row', alignItems: 'flex-start' },
  modeIcon:  { marginTop: 2, marginRight: 12 },
  modeText:  { flex: 1 },
  modeLabel: { fontSize: 15, fontWeight: '600', color: '#1a1a1a' },
  modeLabelActive: { color: '#fff' },
  modeDesc:  { fontSize: 12, color: '#666', marginTop: 3 },
  modeDescActive: { color: 'rgba(255,255,255,0.85)' },

  // Bluetooth section
  section:    { marginTop: 4 },
  connectedDevice: {
    flexDirection:   'row',
    alignItems:      'center',
    backgroundColor: '#E8F5E9',
    borderRadius:    8,
    padding:         12,
    marginBottom:    10,
  },
  noDevice: { color: '#888', fontSize: 13, marginBottom: 10 },

  infoBox: {
    flexDirection:   'row',
    backgroundColor: '#E3F2FD',
    borderRadius:    8,
    padding:         12,
    marginBottom:    12,
    alignItems:      'flex-start',
  },
  infoText: { flex: 1, marginLeft: 8, fontSize: 12, color: '#1565C0', lineHeight: 18 },
  code: { fontFamily: Platform.OS === 'ios' ? 'Courier New' : 'monospace', fontWeight: '600' },

  scanBtn: {
    flexDirection:   'row',
    alignItems:      'center',
    justifyContent:  'center',
    backgroundColor: '#1565C0',
    borderRadius:    8,
    padding:         13,
    marginBottom:    10,
  },

  deviceList:  { marginTop: 4 },
  deviceItem: {
    flexDirection:   'row',
    alignItems:      'center',
    backgroundColor: '#fff',
    borderRadius:    8,
    padding:         12,
    marginBottom:    6,
    borderWidth:     1,
    borderColor:     '#eee',
  },
  deviceItemSelected: { borderColor: '#4CAF50', backgroundColor: '#F1F8E9' },
  deviceName:    { fontSize: 14, fontWeight: '600', color: '#1a1a1a' },
  deviceAddress: { fontSize: 11, color: '#888', marginTop: 2 },
  selectedTag:   { fontSize: 12, color: '#4CAF50', fontWeight: '700' },
  connectTag:    { fontSize: 12, color: '#1565C0', fontWeight: '600' },

  // Auto-print toggle
  toggleRow: {
    flexDirection:   'row',
    alignItems:      'center',
    backgroundColor: '#fff',
    borderRadius:    10,
    padding:         14,
    marginBottom:    8,
  },
  toggleLabel: { fontSize: 15, fontWeight: '600', color: '#1a1a1a' },
  toggleDesc:  { fontSize: 12, color: '#666', marginTop: 3 },
  toggle: {
    width:           50,
    height:          28,
    borderRadius:    14,
    backgroundColor: '#ccc',
    justifyContent:  'center',
    padding:          2,
    marginLeft:       12,
  },
  toggleOn:    { backgroundColor: '#4CAF50' },
  toggleThumb: {
    width:           24,
    height:          24,
    borderRadius:    12,
    backgroundColor: '#fff',
    shadowColor:     '#000',
    shadowOpacity:   0.2,
    shadowRadius:    2,
    elevation:       2,
  },
  toggleThumbOn: { alignSelf: 'flex-end' },

  // Test button
  testBtn: {
    flexDirection:   'row',
    alignItems:      'center',
    justifyContent:  'center',
    backgroundColor: '#FF9800',
    borderRadius:    8,
    padding:         14,
  },
  btnText:    { color: '#fff', fontWeight: '700', fontSize: 15 },
  btnDisabled: { opacity: 0.5 },
  testNote: {
    fontSize:   12,
    color:      '#888',
    marginTop:   8,
    lineHeight:  18,
    textAlign:  'center',
  },

  // PIN lock section
  pinCard: {
    backgroundColor: '#fff',
    borderRadius:    10,
    padding:         14,
    marginBottom:    8,
  },
  pinRow: {
    flexDirection: 'row',
    alignItems:    'flex-start',
    marginBottom:  12,
  },
  pinLabel: { fontSize: 15, fontWeight: '600', color: '#1a1a1a' },
  pinDesc:  { fontSize: 12, color: '#666', marginTop: 3 },
  pinActions: {
    flexDirection: 'row',
    gap:           8,
  },
  pinBtn: {
    flex:            1,
    alignItems:      'center',
    justifyContent:  'center',
    backgroundColor: '#2c3e50',
    borderRadius:    8,
    paddingVertical: 10,
  },
  pinBtnDanger: {
    backgroundColor: '#fff',
    borderWidth:     1,
    borderColor:     '#e53935',
  },
  pinBtnText:  { color: '#fff', fontWeight: '700', fontSize: 14 },
  pinForm: { marginTop: 4 },
  pinInput: {
    borderWidth:   1,
    borderColor:   '#ddd',
    borderRadius:  8,
    padding:       12,
    fontSize:      18,
    letterSpacing: 8,
    marginBottom:  10,
    backgroundColor: '#fafafa',
    textAlign:     'center',
  },
  pinErrorText: {
    color:        '#e53935',
    fontSize:     13,
    marginBottom: 8,
    textAlign:    'center',
  },
});
