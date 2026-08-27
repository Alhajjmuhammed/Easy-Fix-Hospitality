import React, { useEffect, useState, useCallback, useRef } from 'react';
import { ScrollView, View, StyleSheet, RefreshControl, Image } from 'react-native';
import {
  Text,
  Card,
  Button,
  Chip,
  ActivityIndicator,
  Snackbar,
  Banner,
  Divider,
  useTheme,
  Surface,
  Menu,
  Portal,
  Dialog,
  TextInput,
} from 'react-native-paper';
import NetInfo from '@react-native-community/netinfo';
import { apiOrders, apiCancelOrder, apiTransferTable } from '../../api/orders';
import { apiTables } from '../../api/tables';
import { apiBillRequests, apiCompleteBillRequest } from '../../api/billRequests';
import { getOrders, cacheOrders, getOfflinePendingOrders, deleteOfflineOrder } from '../../database/operations';
import { useSyncStore } from '../../store/useSyncStore';
import { useCurrency } from '../../hooks/useCurrency';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useAuthStore } from '../../store/useAuthStore';
import { printReceipt } from '../../utils/printer';
import { STATUS_COLORS } from '../../constants/statusColors';

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

function RestaurantBanner() {
  const { user } = useAuthStore();
  const restaurantName = user?.restaurant_name || 'Restaurant';
  const logoUrl = user?.restaurant_logo_url || null;
  const staffFirstName = user?.first_name || user?.username || 'there';
  const color = stringToColor(restaurantName);
  const initials = nameInitials(restaurantName);
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });

  return (
    <View style={[bannerStyles.wrapper, { backgroundColor: color }]}>
      {/* Decorative circles */}
      <View style={[bannerStyles.circle1, { backgroundColor: 'rgba(255,255,255,0.08)' }]} />
      <View style={[bannerStyles.circle2, { backgroundColor: 'rgba(255,255,255,0.06)' }]} />

      {/* Logo */}
      {logoUrl ? (
        <Image source={{ uri: logoUrl }} style={bannerStyles.logoImage} resizeMode="cover" />
      ) : (
        <View style={bannerStyles.logoCircle}>
          <Text style={bannerStyles.logoInitials}>{initials}</Text>
        </View>
      )}

      {/* Text */}
      <Text style={bannerStyles.restaurantName} numberOfLines={1}>{restaurantName}</Text>
      <Text style={bannerStyles.greeting}>{getGreeting()}, {staffFirstName}!</Text>
      <Text style={bannerStyles.date}>{today}</Text>
    </View>
  );
}

const bannerStyles = StyleSheet.create({
  wrapper: {
    marginHorizontal: -16,
    marginTop: -16,
    marginBottom: 20,
    paddingTop: 32,
    paddingBottom: 36,
    alignItems: 'center',
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
    overflow: 'hidden',
  },
  circle1: {
    position: 'absolute', width: 180, height: 180, borderRadius: 90,
    top: -60, right: -40,
  },
  circle2: {
    position: 'absolute', width: 120, height: 120, borderRadius: 60,
    bottom: -30, left: -20,
  },
  logoImage: {
    width: 80, height: 80, borderRadius: 20,
    borderWidth: 3, borderColor: 'rgba(255,255,255,0.5)',
    marginBottom: 12,
  },
  logoCircle: {
    width: 80, height: 80, borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    borderWidth: 3, borderColor: 'rgba(255,255,255,0.5)',
    alignItems: 'center', justifyContent: 'center',
    marginBottom: 12,
  },
  logoInitials: {
    color: '#fff', fontFamily: 'Poppins_700Bold', fontSize: 30, lineHeight: 36,
  },
  restaurantName: {
    color: '#fff', fontFamily: 'Poppins_700Bold', fontSize: 22, lineHeight: 28, textAlign: 'center',
    paddingHorizontal: 24,
  },
  greeting: {
    color: 'rgba(255,255,255,0.85)', fontFamily: 'Poppins_400Regular',
    fontSize: 13, marginTop: 4, textAlign: 'center',
  },
  date: {
    color: 'rgba(255,255,255,0.65)', fontFamily: 'Poppins_400Regular',
    fontSize: 11, marginTop: 2, textAlign: 'center',
  },
});

export default function CCDashboardScreen({ navigation }) {
  const theme = useTheme();
  const { format } = useCurrency();
  const { pendingCount, lastSyncTime } = useSyncStore();
  const { user } = useAuthStore();

  const mountedRef = useRef(true);
  const _syncRefreshTimer = useRef(null);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  const [loading, setLoading]           = useState(true);
  const [refreshing, setRefreshing]     = useState(false);
  const [billRequests, setBillRequests] = useState([]);
  const [recentOrders, setRecentOrders] = useState([]);
  const [stats, setStats]               = useState({ total: 0, pending: 0, completed: 0, cancelled: 0 });
  const [completing, setCompleting]     = useState(null);
  const [snack, setSnack]               = useState('');
  const [isOffline, setIsOffline]       = useState(false);
  const [printBillId, setPrintBillId]   = useState(null);

  // Per-card action menus
  const [menuOpenId, setMenuOpenId]       = useState(null);
  // Cancel dialog
  const [cancelDialog, setCancelDialog]   = useState(null);
  const [cancelReason, setCancelReason]   = useState('');
  const [cancelling, setCancelling]       = useState(false);
  // Transfer dialog
  const [transferDialog, setTransferDialog]     = useState(null);
  const [tables, setTables]                     = useState([]);
  const [targetTable, setTargetTable]           = useState(null);
  const [tableMenuVisible, setTableMenuVisible] = useState(false);
  const [transferring, setTransferring]         = useState(false);

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent && mountedRef.current) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!mountedRef.current) return;
      const offlinePending = await getOfflinePendingOrders();
      if (!mountedRef.current) return;

      if (net.isConnected) {
        const [ordersData, billData] = await Promise.all([
          apiOrders({ period: 'today' }),
          apiBillRequests(),
        ]);
        if (!mountedRef.current) return;
        const orders = Array.isArray(ordersData) ? ordersData : [];
        const allOrders = [...offlinePending, ...orders];
        setBillRequests(billData.bill_requests || []);
        setRecentOrders(allOrders.slice(0, 10));
        setStats({
          total:     allOrders.length,
          pending:   allOrders.filter((o) => ['pending', 'confirmed'].includes(o.status)).length,
          completed: allOrders.filter((o) => o.status === 'served' || o.status === 'delivered').length,
          cancelled: allOrders.filter((o) => o.status === 'cancelled').length,
        });
        setIsOffline(false);
        try { await cacheOrders(orders); } catch { /* best-effort */ }
      } else {
        const cached = await getOrders();
        if (!mountedRef.current) return;
        const allOrders = [...offlinePending, ...cached];
        setRecentOrders(allOrders.slice(0, 10));
        setBillRequests([]);
        setStats({
          total:     allOrders.length,
          pending:   allOrders.filter((o) => ['pending', 'confirmed'].includes(o.status)).length,
          completed: allOrders.filter((o) => o.status === 'served' || o.status === 'delivered').length,
          cancelled: allOrders.filter((o) => o.status === 'cancelled').length,
        });
        setIsOffline(true);
      }
    } catch {
      try {
        const offlinePending = await getOfflinePendingOrders();
        const cached = await getOrders();
        if (!mountedRef.current) return;
        const allOrders = [...offlinePending, ...cached];
        setRecentOrders(allOrders.slice(0, 10));
        setBillRequests([]);
        setStats({
          total:     allOrders.length,
          pending:   allOrders.filter((o) => ['pending', 'confirmed'].includes(o.status)).length,
          completed: allOrders.filter((o) => o.status === 'served' || o.status === 'delivered').length,
          cancelled: allOrders.filter((o) => o.status === 'cancelled').length,
        });
      } catch {
        if (mountedRef.current) { setRecentOrders([]); setBillRequests([]); }
      }
      if (mountedRef.current) setIsOffline(true);
    } finally {
      if (mountedRef.current) { setLoading(false); setRefreshing(false); }
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(() => fetchAll(true), 30_000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  useEffect(() => {
    clearTimeout(_syncRefreshTimer.current);
    _syncRefreshTimer.current = setTimeout(() => fetchAll(true), 300);
    return () => clearTimeout(_syncRefreshTimer.current);
  }, [pendingCount, lastSyncTime, fetchAll]);

  const handleComplete = async (id) => {
    const net = await NetInfo.fetch();
    if (!mountedRef.current) return;
    if (!net.isConnected) { setSnack('No internet — connect to complete a bill request'); return; }
    setCompleting(id);
    try {
      await apiCompleteBillRequest(id);
      if (!mountedRef.current) return;
      setBillRequests((prev) => prev.filter((r) => r.id !== id));
      setSnack('Bill request marked as complete');
    } catch (err) {
      if (mountedRef.current) setSnack(err.response?.data?.detail || 'Could not complete request');
    } finally {
      if (mountedRef.current) setCompleting(null);
    }
  };

  // ── Print bill ──────────────────────────────────────────────────────────────
  const handlePrintBill = async (order) => {
    if (mountedRef.current) setPrintBillId(order.id);
    const staffName = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || '';
    try {
      const ok = await printReceipt({
        orderId: order._is_offline_pending ? undefined : order.id,
        order,
        restaurantName: user?.restaurant_name || 'Restaurant',
        currencySymbol: user?.currency_symbol || '',
        staffName,
      });
      if (ok && mountedRef.current) setSnack('Bill sent to printer');
    } catch (err) {
      if (mountedRef.current) setSnack('Print failed: ' + (err.message || 'unknown error'));
    } finally {
      if (mountedRef.current) setPrintBillId(null);
    }
  };

  const handleDismissError = useCallback(async (offlineId) => {
    try {
      await deleteOfflineOrder(offlineId);
      if (mountedRef.current) fetchAll(true);
    } catch {
      if (mountedRef.current) setSnack('Could not dismiss order');
    }
  }, [fetchAll]);

  // ── Cancel order ────────────────────────────────────────────────────────────
  const openCancel = (order) => { setCancelDialog(order); setCancelReason(''); };

  const handleCancel = async () => {
    if (!cancelDialog) return;
    const net = await NetInfo.fetch();
    if (!mountedRef.current) return;
    if (!net.isConnected) { setSnack('No internet — connect to cancel an order'); setCancelDialog(null); return; }
    setCancelling(true);
    try {
      await apiCancelOrder(cancelDialog.id, cancelReason.trim());
      if (!mountedRef.current) return;
      setCancelDialog(null);
      setSnack('Order cancelled');
      fetchAll(true);
    } catch (err) {
      if (mountedRef.current) setSnack(err.response?.data?.detail || 'Cancel failed');
    } finally {
      if (mountedRef.current) setCancelling(false);
    }
  };

  // ── Transfer table ───────────────────────────────────────────────────────────
  const openTransfer = async (order) => {
    setTransferDialog(order);
    setTargetTable(null);
    setTableMenuVisible(false);
    const currentTblNum = String(order.table_number ?? '');
    try {
      const t = await apiTables();
      if (!mountedRef.current) return;
      setTables((t || []).filter((tb) =>
        tb.is_available === true &&
        String(tb.table_number ?? tb.tbl_no) !== currentTblNum,
      ));
    } catch {
      setTables([]);
    }
  };

  const handleTransfer = async () => {
    if (!transferDialog || !targetTable) return;
    const net = await NetInfo.fetch();
    if (!mountedRef.current) return;
    if (!net.isConnected) { setSnack('No internet — connect to transfer table'); setTransferDialog(null); return; }
    setTransferring(true);
    try {
      await apiTransferTable(transferDialog.id, targetTable.id);
      if (!mountedRef.current) return;
      setTransferDialog(null);
      setSnack('Table transferred');
      fetchAll(true);
    } catch (err) {
      if (mountedRef.current) setSnack(err.response?.data?.detail || 'Transfer failed');
    } finally {
      if (mountedRef.current) setTransferring(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); fetchAll(true); }} />
      }
    >
      {/* Offline / pending-sync banner */}
      <Banner
        visible={isOffline || pendingCount > 0}
        icon={isOffline ? 'wifi-off' : 'cloud-upload'}
        actions={[]}
        style={{ backgroundColor: isOffline ? '#FFF8E1' : '#E8F5E9', marginHorizontal: -16, marginTop: -16, marginBottom: 8 }}
      >
        {isOffline
          ? `Offline – showing cached orders.${pendingCount > 0 ? ` ${pendingCount} queued for sync.` : ' Connect to sync latest data.'}`
          : `${pendingCount} order(s) queued – will sync automatically when internet is available.`}
      </Banner>

      {/* Restaurant Banner */}
      <RestaurantBanner />

      {/* Stats Cards */}
      <Text variant="titleMedium" style={styles.sectionTitle}>Today's Summary</Text>
      <View style={styles.statsRow}>
        <StatCard label="Total"     value={stats.total}     color="#2c3e50" icon="clipboard-list-outline" />
        <StatCard label="Pending"   value={stats.pending}   color="#FF8F00" icon="clock-outline" />
        <StatCard label="Done"      value={stats.completed} color="#2E7D32" icon="check-circle-outline" />
        <StatCard label="Cancelled" value={stats.cancelled} color="#C62828" icon="close-circle-outline" />
      </View>

      {/* Pending Bill Requests */}
      <View style={styles.sectionHeader}>
        <Text variant="titleMedium" style={styles.sectionTitle}>Bill Requests</Text>
        <Chip icon="bell" mode="outlined" compact>
          {billRequests.length} pending
        </Chip>
      </View>

      {billRequests.length === 0 ? (
        <Card style={styles.emptyCard}>
          <Card.Content style={styles.emptyContent}>
            <Text variant="bodyMedium" style={{ opacity: 0.5 }}>No pending bill requests</Text>
          </Card.Content>
        </Card>
      ) : (
        billRequests.map((req) => (
          <Card key={req.id} style={styles.card}>
            <Card.Content>
              <View style={styles.row}>
                <Text variant="titleMedium" style={{ fontFamily: 'Poppins_700Bold' }}>
                  Table {req.table_number}
                </Text>
                <Chip
                  mode="flat"
                  compact
                  style={{ backgroundColor: '#FFF9C4' }}
                  textStyle={{ fontSize: 11 }}
                >
                  PENDING
                </Chip>
              </View>
              <Text variant="bodySmall" style={styles.meta}>
                Requested at {new Date(req.created_at).toLocaleTimeString()}
              </Text>
              {req.requested_by_name ? (
                <Text variant="bodySmall" style={styles.meta}>By: {req.requested_by_name}</Text>
              ) : null}
            </Card.Content>
            <Card.Actions>
              <Button mode="outlined" onPress={() => navigation.navigate('Payments')}>
                Process Payment
              </Button>
              <Button
                mode="contained"
                loading={completing === req.id}
                disabled={completing === req.id}
                onPress={() => handleComplete(req.id)}
              >
                Complete
              </Button>
            </Card.Actions>
          </Card>
        ))
      )}

      <Divider style={styles.divider} />

      {/* Recent Orders */}
      <View style={styles.sectionHeader}>
        <Text variant="titleMedium" style={styles.sectionTitle}>My Recent Orders</Text>
        <Button compact mode="text" onPress={() => navigation.navigate('Payments')}>
          View All
        </Button>
      </View>

      {recentOrders.length === 0 ? (
        <Card style={styles.emptyCard}>
          <Card.Content style={styles.emptyContent}>
            <Text variant="bodyMedium" style={{ opacity: 0.5 }}>No orders today</Text>
          </Card.Content>
        </Card>
      ) : (
        recentOrders.map((order) => {
          const orderId    = order._is_offline_pending ? `offline_${order.offline_id}` : order.id;
          const isMenuOpen = menuOpenId === orderId;
          const isPaid = order.payment_status === 'paid';
          return (
            <Card key={orderId} style={styles.card}>
              <Card.Content>
                <View style={styles.row}>
                  <Text variant="titleSmall" style={{ fontFamily: 'Poppins_700Bold' }}>
                    #{order.order_number}
                  </Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Chip
                      mode="flat"
                      compact
                      style={{ backgroundColor: STATUS_COLORS[order.status] + '22' }}
                      textStyle={{ fontSize: 11, color: STATUS_COLORS[order.status] }}
                    >
                      {order.status?.toUpperCase()}
                    </Chip>
                    <Menu
                      visible={isMenuOpen}
                      onDismiss={() => setMenuOpenId(null)}
                      anchor={
                        <Button compact icon="dots-vertical" onPress={() => setMenuOpenId(isMenuOpen ? null : orderId)} />
                      }
                    >
                      <Menu.Item leadingIcon="printer" title="Print Bill" disabled={printBillId === order.id} onPress={() => { setMenuOpenId(null); handlePrintBill(order); }} />
                      <Menu.Item leadingIcon="swap-horizontal" title="Transfer Table" onPress={() => { setMenuOpenId(null); openTransfer(order); }} disabled={isPaid || order.status === 'cancelled'} />
                      <Divider />
                      <Menu.Item leadingIcon="close-circle-outline" title="Cancel Order" titleStyle={{ color: '#E53935' }} onPress={() => { setMenuOpenId(null); openCancel(order); }} disabled={order.status === 'cancelled' || isPaid} />
                    </Menu>
                  </View>
                </View>
                {order._is_sync_error && (
                  <>
                    <Chip
                      icon="alert-circle"
                      mode="flat"
                      compact
                      style={{ backgroundColor: '#FFEBEE', alignSelf: 'flex-start', marginBottom: 4 }}
                      textStyle={{ fontSize: 10, color: '#C62828' }}
                    >
                      Sync Failed – re-take manually
                    </Chip>
                    {!!order.error_message && (
                      <Text variant="bodySmall" style={{ color: '#C62828', fontSize: 10, opacity: 0.8, marginBottom: 4 }}>
                        {order.error_message}
                      </Text>
                    )}
                  </>
                )}
                {order._is_offline_pending && !order._is_sync_error && (
                  <Chip
                    icon="cloud-upload"
                    mode="flat"
                    compact
                    style={{ backgroundColor: '#FFF3E0', alignSelf: 'flex-start', marginBottom: 4 }}
                    textStyle={{ fontSize: 10, color: '#E65100' }}
                  >
                    Queued – syncs when online
                  </Chip>
                )}
                <Text variant="bodySmall" style={styles.meta}>
                  {order.order_type === 'delivery' ? '🚴 Delivery' : `Table ${order.table_number ?? '?'}`} · {order.items_count} item{order.items_count !== 1 ? 's' : ''}
                </Text>
                <View style={styles.row}>
                  <Text variant="bodySmall">Total: {format(order.total)}</Text>
                  <Text
                    variant="bodySmall"
                    style={{ color: isPaid ? '#2E7D32' : '#C62828', fontFamily: 'Poppins_700Bold' }}
                  >
                    {order.payment_status?.toUpperCase() || 'UNPAID'}
                  </Text>
                </View>
              </Card.Content>
              {order._is_offline_pending && !order._is_sync_error && (
                <Card.Actions>
                  <Button compact mode="outlined" icon="printer" disabled={printBillId === order.id} loading={printBillId === order.id} onPress={() => handlePrintBill(order)}>Print</Button>
                  <Button compact mode="text" onPress={() => navigation.navigate('Payments')}>Pay / Manage</Button>
                </Card.Actions>
              )}
              {order._is_sync_error && (
                <Card.Actions>
                  <Button
                    mode="outlined"
                    compact
                    textColor="#C62828"
                    onPress={() => handleDismissError(order.offline_id)}
                  >
                    Dismiss
                  </Button>
                </Card.Actions>
              )}
            </Card>
          );
        })
      )}

      <Portal>
        {/* Cancel Order Dialog */}
        <Dialog visible={!!cancelDialog} onDismiss={() => setCancelDialog(null)}>
          <Dialog.Title>Cancel Order</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={{ marginBottom: 12, opacity: 0.7 }}>
              Order #{cancelDialog?.order_number || cancelDialog?.id} · Table {cancelDialog?.table_number}
            </Text>
            <TextInput label="Reason (optional)" value={cancelReason}
              onChangeText={setCancelReason} mode="outlined" multiline numberOfLines={2} />
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setCancelDialog(null)}>Back</Button>
            <Button mode="contained" buttonColor="#E53935" loading={cancelling} disabled={cancelling} onPress={handleCancel}>Cancel Order</Button>
          </Dialog.Actions>
        </Dialog>

        {/* Transfer Table Dialog */}
        <Dialog visible={!!transferDialog} onDismiss={() => setTransferDialog(null)}>
          <Dialog.Title>Transfer Table</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={{ marginBottom: 12, opacity: 0.7 }}>
              Move order #{transferDialog?.order_number || transferDialog?.id} from Table {transferDialog?.table_number}
            </Text>
            <Menu
              visible={tableMenuVisible}
              onDismiss={() => setTableMenuVisible(false)}
              anchor={
                <Button mode="outlined" onPress={() => setTableMenuVisible(true)}
                  icon="table-chair" style={{ marginBottom: 4 }}>
                  {targetTable ? `Table ${targetTable.table_number ?? targetTable.tbl_no}` : 'Select available table'}
                </Button>
              }
            >
              {tables.map((t) => (
                <Menu.Item key={t.id} title={`Table ${t.table_number ?? t.tbl_no}`}
                  onPress={() => { setTargetTable(t); setTableMenuVisible(false); }} />
              ))}
              {tables.length === 0 && <Menu.Item title="No available tables" disabled />}
            </Menu>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setTransferDialog(null)}>Cancel</Button>
            <Button mode="contained" loading={transferring} disabled={transferring || !targetTable} onPress={handleTransfer}>Transfer</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {snack}
      </Snackbar>
    </ScrollView>
  );
}

function StatCard({ label, value, color, icon }) {
  return (
    <Surface style={[styles.statCard, { backgroundColor: color + '12' }]} elevation={0}>
      <View style={[styles.statIconWrap, { backgroundColor: color + '25' }]}>
        <MaterialCommunityIcons name={icon} size={20} color={color} />
      </View>
      <Text style={[styles.statValue, { color }]}>{value ?? 0}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </Surface>
  );
}

const styles = StyleSheet.create({
  container:     { padding: 16, paddingBottom: 32 },
  center:        { flex: 1, justifyContent: 'center', alignItems: 'center' },
  sectionTitle:  { fontFamily: 'Poppins_700Bold', marginBottom: 8 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  statsRow:      { flexDirection: 'row', gap: 8, marginBottom: 20 },
  statCard:      {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 6,
    borderRadius: 10,
  },
  statIconWrap:  {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
  statValue:     { fontFamily: 'Poppins_700Bold', fontSize: 22, lineHeight: 28 },
  statLabel:     { fontFamily: 'Poppins_500Medium', fontSize: 10, opacity: 0.7, marginTop: 2, textAlign: 'center' },
  divider:       { marginVertical: 16 },
  card:          { marginBottom: 10, borderRadius: 10 },
  emptyCard:     { borderRadius: 10, marginBottom: 8 },
  emptyContent:  { alignItems: 'center', paddingVertical: 24 },
  row:           { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  meta:          { opacity: 0.65, marginBottom: 2 },
});

