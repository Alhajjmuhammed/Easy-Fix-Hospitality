import React, { useEffect, useRef, useState, useCallback } from 'react';
import { View, StyleSheet, StatusBar } from 'react-native';
import {
  Text, Button, Dialog, Portal, Snackbar, ActivityIndicator, Surface,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { apiAttendanceScan, apiAttendanceConfirm } from '../../api/attendance';

// ─── helpers ─────────────────────────────────────────────────────────────────
function fmtTime(str) {
  if (!str) return '—';
  // Handles both "HH:MM" shift times and ISO 8601 datetime strings from API
  const d = new Date(str);
  if (!isNaN(d.getTime())) {
    const h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, '0');
    const ampm = h >= 12 ? 'PM' : 'AM';
    const h12 = h % 12 === 0 ? 12 : h % 12;
    return `${h12}:${m} ${ampm}`;
  }
  // Fallback: plain "HH:MM" or "HH:MM:SS"
  const parts = str.split(':');
  const h = parseInt(parts[0], 10);
  const m = parts[1] || '00';
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m} ${ampm}`;
}

function actionLabel(action) {
  if (action === 'check_in')  return 'Check In';
  if (action === 'check_out') return 'Check Out';
  return action;
}

function actionColor(action) {
  return action === 'check_in' ? '#2E7D32' : '#1565C0';
}

// ─── Corner frame overlay for QR viewfinder ──────────────────────────────────
function ScanFrame() {
  const SIZE   = 240;
  const CORNER = 28;
  const THICK  = 4;
  const COLOR  = '#ffffff';

  const corner = (style) => (
    <View
      style={[
        {
          position: 'absolute',
          width: CORNER,
          height: CORNER,
          borderColor: COLOR,
          borderWidth: THICK,
        },
        style,
      ]}
    />
  );

  return (
    <View style={{ width: SIZE, height: SIZE, position: 'relative' }}>
      {corner({ top: 0, left: 0, borderRightWidth: 0, borderBottomWidth: 0, borderTopLeftRadius: 6 })}
      {corner({ top: 0, right: 0, borderLeftWidth: 0, borderBottomWidth: 0, borderTopRightRadius: 6 })}
      {corner({ bottom: 0, left: 0, borderRightWidth: 0, borderTopWidth: 0, borderBottomLeftRadius: 6 })}
      {corner({ bottom: 0, right: 0, borderLeftWidth: 0, borderTopWidth: 0, borderBottomRightRadius: 6 })}
    </View>
  );
}

// ─── Main screen ─────────────────────────────────────────────────────────────
export default function AttendanceScreen({ navigation }) {
  const mountedRef  = useRef(true);
  const scanningRef = useRef(false); // debounce: only one scan processed at a time

  const [permission, requestPermission] = useCameraPermissions();

  // Dialog state
  const [scanResult, setScanResult]   = useState(null);  // API response from /scan/
  const [scannedToken, setScannedToken] = useState(null);
  const [dialogVisible, setDialogVisible] = useState(false);
  const [alreadyDoneVisible, setAlreadyDoneVisible] = useState(false);

  // Async state
  const [confirming, setConfirming] = useState(false);
  const [snack, setSnack]           = useState('');
  const [snackColor, setSnackColor] = useState('#323232');

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  // ── QR scan handler ─────────────────────────────────────────────────────────
  const handleScan = useCallback(async ({ data: qrData }) => {
    if (scanningRef.current || !mountedRef.current) return;
    if (!qrData) return;
    scanningRef.current = true;

    try {
      const result = await apiAttendanceScan(qrData);
      if (!mountedRef.current) return;

      setScannedToken(qrData);
      setScanResult(result);

      if (result.action === 'already_done') {
        setAlreadyDoneVisible(true);
      } else {
        setDialogVisible(true);
      }
    } catch (err) {
      if (!mountedRef.current) return;
      const msg = err.response?.data?.error || err.response?.data?.detail || 'Invalid QR code';
      setSnack(msg);
      setSnackColor('#E53935');
      // Allow rescanning after error
      setTimeout(() => { scanningRef.current = false; }, 2500);
    }
  }, []);

  // ── Confirm attendance ───────────────────────────────────────────────────────
  const handleConfirm = async () => {
    if (!scannedToken || !scanResult) return;
    setConfirming(true);
    try {
      const res = await apiAttendanceConfirm(scannedToken, scanResult.action);
      if (!mountedRef.current) return;
      setDialogVisible(false);
      setSnack(res.message || `${actionLabel(scanResult.action)} recorded successfully`);
      setSnackColor('#2E7D32');
    } catch (err) {
      if (!mountedRef.current) return;
      setDialogVisible(false);
      setSnack(err.response?.data?.error || err.response?.data?.detail || 'Could not record attendance');
      setSnackColor('#E53935');
    } finally {
      if (mountedRef.current) setConfirming(false);
      // Reset for next scan
      setScanResult(null);
      setScannedToken(null);
      setTimeout(() => { scanningRef.current = false; }, 1500);
    }
  };

  const handleCancel = () => {
    setDialogVisible(false);
    setAlreadyDoneVisible(false);
    setScanResult(null);
    setScannedToken(null);
    setTimeout(() => { scanningRef.current = false; }, 500);
  };

  // ── Permission loading ───────────────────────────────────────────────────────
  if (!permission) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#2c3e50" />
      </View>
    );
  }

  // ── Permission denied ────────────────────────────────────────────────────────
  if (!permission.granted) {
    return (
      <View style={styles.permissionContainer}>
        <MaterialCommunityIcons name="camera-off" size={64} color="#9E9E9E" />
        <Text style={styles.permissionTitle}>Camera Access Required</Text>
        <Text style={styles.permissionBody}>
          The camera is needed to scan the restaurant QR code for attendance.
        </Text>
        <Button
          mode="contained"
          onPress={requestPermission}
          style={styles.permissionBtn}
          contentStyle={{ paddingVertical: 6 }}
        >
          Grant Camera Access
        </Button>
      </View>
    );
  }

  // ── Main camera view ─────────────────────────────────────────────────────────
  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#000" />

      {/* Camera */}
      <CameraView
        style={StyleSheet.absoluteFillObject}
        barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
        onBarcodeScanned={dialogVisible || alreadyDoneVisible ? undefined : handleScan}
      />

      {/* Dark overlay — top */}
      <View style={styles.overlayTop} />

      {/* Middle row: left dark | scan frame | right dark */}
      <View style={styles.overlayMiddle}>
        <View style={styles.overlaySide} />
        <ScanFrame />
        <View style={styles.overlaySide} />
      </View>

      {/* Dark overlay — bottom */}
      <View style={styles.overlayBottom}>
        <Text style={styles.instructionText}>
          Point your camera at the restaurant QR code
        </Text>

        <Surface style={styles.historyBtnSurface} elevation={3}>
          <Button
            mode="contained-tonal"
            icon="history"
            onPress={() => navigation.navigate('MyAttendance')}
            style={styles.historyBtn}
            labelStyle={{ fontFamily: 'Poppins_600SemiBold', fontSize: 14 }}
          >
            My Attendance History
          </Button>
        </Surface>
      </View>

      {/* ── Confirmation dialog ─────────────────────────────────────────── */}
      <Portal>
        <Dialog visible={dialogVisible} onDismiss={handleCancel} style={styles.dialog}>
          <Dialog.Title style={styles.dialogTitle}>
            <MaterialCommunityIcons
              name={scanResult?.action === 'check_in' ? 'login' : 'logout'}
              size={22}
              color={actionColor(scanResult?.action)}
            />
            {'  '}Confirm {actionLabel(scanResult?.action)}
          </Dialog.Title>

          <Dialog.Content>
            {scanResult ? (
              <View style={styles.dialogBody}>
                {/* Restaurant */}
                <View style={styles.infoRow}>
                  <MaterialCommunityIcons name="store-outline" size={18} color="#555" />
                  <Text style={styles.infoLabel}>Restaurant</Text>
                  <Text style={styles.infoValue}>{scanResult.restaurant_name || '—'}</Text>
                </View>

                {/* Action badge */}
                <View style={styles.infoRow}>
                  <MaterialCommunityIcons name="badge-account-outline" size={18} color="#555" />
                  <Text style={styles.infoLabel}>Action</Text>
                  <View
                    style={[
                      styles.actionBadge,
                      { backgroundColor: actionColor(scanResult.action) },
                    ]}
                  >
                    <Text style={styles.actionBadgeText}>{actionLabel(scanResult.action)}</Text>
                  </View>
                </View>

                {/* Current time */}
                <View style={styles.infoRow}>
                  <MaterialCommunityIcons name="clock-outline" size={18} color="#555" />
                  <Text style={styles.infoLabel}>Time</Text>
                  <Text style={styles.infoValue}>{scanResult.current_time || '—'}</Text>
                </View>

                {/* Shift */}
                {scanResult.shift ? (
                  <View style={[styles.shiftCard]}>
                    <Text style={styles.shiftTitle}>
                      <MaterialCommunityIcons name="timetable" size={14} color="#1565C0" />
                      {'  '}Shift: {scanResult.shift.name}
                    </Text>
                    <Text style={styles.shiftTime}>
                      {fmtTime(scanResult.shift.start_time)} – {fmtTime(scanResult.shift.end_time)}
                    </Text>
                  </View>
                ) : null}
              </View>
            ) : (
              <ActivityIndicator />
            )}
          </Dialog.Content>

          <Dialog.Actions>
            <Button onPress={handleCancel} disabled={confirming} textColor="#888">
              Cancel
            </Button>
            <Button
              mode="contained"
              onPress={handleConfirm}
              loading={confirming}
              disabled={confirming}
              buttonColor={actionColor(scanResult?.action)}
              labelStyle={{ fontFamily: 'Poppins_600SemiBold' }}
            >
              Confirm
            </Button>
          </Dialog.Actions>
        </Dialog>

        {/* ── Already done dialog ───────────────────────────────────────── */}
        <Dialog visible={alreadyDoneVisible} onDismiss={handleCancel} style={styles.dialog}>
          <Dialog.Title style={styles.dialogTitle}>Attendance Already Recorded</Dialog.Title>
          <Dialog.Content>
            <View style={styles.alreadyDoneContent}>
              <MaterialCommunityIcons name="check-circle" size={48} color="#2E7D32" />
              <Text style={styles.alreadyDoneText}>
                You have already completed attendance for today.
              </Text>
              {scanResult?.today_record ? (
                <View style={styles.todayRecord}>
                  {scanResult.today_record.check_in ? (
                    <Text style={styles.recordLine}>
                      Check-in: {fmtTime(scanResult.today_record.check_in)}
                    </Text>
                  ) : null}
                  {scanResult.today_record.check_out ? (
                    <Text style={styles.recordLine}>
                      Check-out: {fmtTime(scanResult.today_record.check_out)}
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </View>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={handleCancel}>OK</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      {/* ── Snackbar ─────────────────────────────────────────────────────── */}
      <Snackbar
        visible={!!snack}
        onDismiss={() => setSnack('')}
        duration={3000}
        style={{ backgroundColor: snackColor, marginBottom: 80 }}
      >
        {snack}
      </Snackbar>
    </View>
  );
}

// ─── Overlay measurements ─────────────────────────────────────────────────────
const FRAME_SIZE   = 240;
const OVERLAY_TOP  = 160;
const OVERLAY_BTM  = 180;

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  center:    { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#000' },

  // Camera overlay sections
  overlayTop: {
    height: OVERLAY_TOP,
    backgroundColor: 'rgba(0,0,0,0.60)',
    alignItems: 'center',
    justifyContent: 'flex-end',
    paddingBottom: 12,
  },
  overlayMiddle: {
    height: FRAME_SIZE,
    flexDirection: 'row',
  },
  overlaySide: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.60)',
  },
  overlayBottom: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.60)',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 24,
    paddingBottom: 32,
    paddingHorizontal: 24,
  },
  instructionText: {
    color: '#fff',
    fontSize: 15,
    fontFamily: 'Poppins_400Regular',
    textAlign: 'center',
    lineHeight: 22,
  },
  historyBtnSurface: {
    borderRadius: 12,
    overflow: 'hidden',
    width: '100%',
  },
  historyBtn: {
    borderRadius: 12,
  },

  // Permission UI
  permissionContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 32,
    backgroundColor: '#F5F5F5',
  },
  permissionTitle: {
    fontSize: 20,
    fontFamily: 'Poppins_700Bold',
    color: '#2c3e50',
    marginTop: 20,
    marginBottom: 10,
    textAlign: 'center',
  },
  permissionBody: {
    fontSize: 14,
    fontFamily: 'Poppins_400Regular',
    color: '#666',
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 28,
  },
  permissionBtn: {
    borderRadius: 10,
    minWidth: 220,
  },

  // Dialog
  dialog: {
    borderRadius: 16,
    marginHorizontal: 16,
  },
  dialogTitle: {
    fontFamily: 'Poppins_700Bold',
    fontSize: 17,
  },
  dialogBody: {
    gap: 10,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 4,
  },
  infoLabel: {
    fontFamily: 'Poppins_600SemiBold',
    fontSize: 13,
    color: '#555',
    width: 90,
  },
  infoValue: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 13,
    color: '#222',
    flex: 1,
  },
  actionBadge: {
    paddingHorizontal: 14,
    paddingVertical: 3,
    borderRadius: 20,
  },
  actionBadgeText: {
    color: '#fff',
    fontSize: 12,
    fontFamily: 'Poppins_700Bold',
  },
  shiftCard: {
    backgroundColor: '#E3F2FD',
    borderRadius: 8,
    padding: 10,
    marginTop: 4,
  },
  shiftTitle: {
    fontFamily: 'Poppins_600SemiBold',
    fontSize: 13,
    color: '#1565C0',
    marginBottom: 2,
  },
  shiftTime: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 13,
    color: '#1976D2',
  },

  // Already done
  alreadyDoneContent: {
    alignItems: 'center',
    gap: 12,
    paddingVertical: 8,
  },
  alreadyDoneText: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 14,
    color: '#444',
    textAlign: 'center',
    lineHeight: 22,
  },
  todayRecord: {
    backgroundColor: '#F1F8E9',
    borderRadius: 8,
    padding: 10,
    width: '100%',
    gap: 4,
  },
  recordLine: {
    fontFamily: 'Poppins_400Regular',
    fontSize: 13,
    color: '#2E7D32',
  },
});
