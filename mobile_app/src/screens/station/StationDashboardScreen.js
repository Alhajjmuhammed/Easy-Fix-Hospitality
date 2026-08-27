import React, { useEffect, useState, useCallback, useRef } from 'react';
import { View, FlatList, StyleSheet, RefreshControl } from 'react-native';
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
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import { apiOrders, apiUpdateOrderStatus, apiPrintStationTicket } from '../../api/orders';
import { getOrders, getOfflinePendingOrders, updateCachedOrderStatus } from '../../database/operations';
import { useCurrency } from '../../hooks/useCurrency';
import { useAuthStore } from '../../store/useAuthStore';
import { usePrinterStore } from '../../store/usePrinterStore';
import { printOrderTicket } from '../../utils/printer';
import RestaurantHeader from '../../components/RestaurantHeader';
import { STATUS_COLORS } from '../../constants/statusColors';

const STATION_ICONS = {
  kitchen: 'chef-hat',
  bar:     'glass-cocktail',
  buffet:  'silverware-fork-knife',
  service: 'room-service',
};

const STATION_LABELS = {
  kitchen: 'Kitchen',
  bar:     'Bar',
  buffet:  'Buffet',
  service: 'Service',
};

const ACTIVE_STATUSES = ['pending', 'confirmed', 'preparing', 'ready'];

function filterForStation(orders, stationName) {
  return orders
    .filter((o) =>
      (o.items || o.order_items || []).some(
        (i) => (i.station || 'kitchen') === stationName,
      ),
    )
    .map((o) => ({
      ...o,
      items: (o.items || o.order_items || []).filter(
        (i) => (i.station || 'kitchen') === stationName,
      ),
    }));
}

function StatusChip({ status }) {
  const color = STATUS_COLORS[status] || '#9E9E9E';
  return (
    <Chip
      style={[styles.statusChip, { backgroundColor: color }]}
      textStyle={styles.statusChipText}
    >
      {(status || '').replace(/_/g, ' ').toUpperCase()}
    </Chip>
  );
}

const OrderCard = React.memo(function OrderCard({ order, onMarkPreparing, onMarkReady, onPrint, updatingId, printingId }) {
  const { format } = useCurrency();
  const isUpdating = updatingId === order.id;
  const isPrinting = printingId === order.id;
  const status = order.status;
  const canPrepare = status === 'pending' || status === 'confirmed';
  const canReady   = status === 'preparing';

  const tableLabel = order.table_number
    ? `Table ${order.table_number}`
    : order.order_type === 'delivery'
    ? 'Delivery'
    : 'Takeaway';

  return (
    <Card style={styles.card} elevation={2}>
      <Card.Content>
        {/* Header row */}
        <View style={styles.cardHeader}>
          <View style={styles.cardHeaderLeft}>
            <Text variant="titleMedium" style={styles.orderNumber}>
              Order #{order.order_number || order.id}
            </Text>
            <Text variant="bodySmall" style={styles.tableLabel}>
              {tableLabel}
            </Text>
          </View>
          <StatusChip status={status} />
        </View>

        <Divider style={styles.divider} />

        {/* Station items */}
        {(order.items || []).map((item, idx) => (
          <View key={item.id || idx} style={styles.itemRow}>
            <Text variant="bodyMedium" style={styles.itemQty}>
              x{item.quantity}
            </Text>
            <Text variant="bodyMedium" style={styles.itemName} numberOfLines={2}>
              {item.product_name || item.name || 'Item'}
            </Text>
            {(item.special_notes || item.notes) ? (
              <Text variant="bodySmall" style={styles.itemNotes}>
                Note: {item.special_notes || item.notes}
              </Text>
            ) : null}
          </View>
        ))}
      </Card.Content>

      {/* Action buttons */}
      <Card.Actions style={styles.cardActions}>
        <Button
          mode="outlined"
          onPress={() => onPrint(order)}
          loading={isPrinting}
          disabled={isPrinting || isUpdating}
          icon="printer"
          style={styles.printBtn}
          compact
        >
          Print
        </Button>
        {canPrepare && (
          <Button
            mode="contained"
            onPress={() => onMarkPreparing(order.id)}
            loading={isUpdating}
            disabled={isUpdating || isPrinting}
            buttonColor={STATUS_COLORS.preparing}
            style={styles.actionBtn}
            compact
          >
            Preparing
          </Button>
        )}
        {canReady && (
          <Button
            mode="contained"
            onPress={() => onMarkReady(order.id)}
            loading={isUpdating}
            disabled={isUpdating || isPrinting}
            buttonColor={STATUS_COLORS.ready}
            style={styles.actionBtn}
            compact
          >
            Ready
          </Button>
        )}
      </Card.Actions>
    </Card>
  );
});

export default function StationDashboardScreen() {
  const theme    = useTheme();
  const { user } = useAuthStore();
  const { localKotBot } = usePrinterStore();
  const stationName = (user?.role_name || 'kitchen').toLowerCase();
  const stationLabel = STATION_LABELS[stationName] || stationName;
  const stationIcon  = STATION_ICONS[stationName]  || 'chef-hat';

  const mountedRef = useRef(true);
  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  const [orders,      setOrders]      = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [refreshing,  setRefreshing]  = useState(false);
  const [isOffline,   setIsOffline]   = useState(false);
  const [updatingId,  setUpdatingId]  = useState(null);
  const [printingId,  setPrintingId]  = useState(null);
  const [snack,       setSnack]       = useState('');

  // ── Network monitoring ──────────────────────────────────────────────────────
  useEffect(() => {
    const unsub = NetInfo.addEventListener((state) => {
      const offline = !(state.isConnected && state.isInternetReachable);
      if (mountedRef.current) setIsOffline(offline);
      if (!offline) fetchOrders(true); // re-fetch on reconnect
    });
    return unsub;
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Fetch orders ────────────────────────────────────────────────────────────
  const fetchOrders = useCallback(async (silent = false) => {
    if (!silent && mountedRef.current) setLoading(true);

    try {
      const raw = await apiOrders({ status: 'pending,confirmed,preparing,ready' });
      if (mountedRef.current) {
        setOrders(filterForStation(raw || [], stationName));
        setIsOffline(false);
      }
    } catch (err) {
      // Fall back to SQLite cache when offline
      try {
        const [cached, pendingOffline] = await Promise.all([
          getOrders(ACTIVE_STATUSES),
          getOfflinePendingOrders(),
        ]);
        const pendingActive = (pendingOffline || []).filter(
          (o) => ACTIVE_STATUSES.includes(o.status || 'pending'),
        );
        const merged = [...(cached || []), ...pendingActive];
        if (mountedRef.current) {
          setOrders(filterForStation(merged, stationName));
          setIsOffline(true);
        }
      } catch {
        if (mountedRef.current) setIsOffline(true);
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [stationName]);

  // Initial load + auto-refresh every 20 s
  useEffect(() => {
    fetchOrders();
    const interval = setInterval(() => fetchOrders(true), 20000);
    return () => clearInterval(interval);
  }, [fetchOrders]);

  // ── Pull-to-refresh ─────────────────────────────────────────────────────────
  const onRefresh = useCallback(async () => {
    if (mountedRef.current) setRefreshing(true);
    await fetchOrders(true);
    if (mountedRef.current) setRefreshing(false);
  }, [fetchOrders]);

  // ── Status updates ──────────────────────────────────────────────────────────
  const updateStatus = useCallback(async (orderId, newStatus) => {
    if (mountedRef.current) setUpdatingId(orderId);

    const applyLocalUpdate = () => {
      if (!mountedRef.current) return;
      setOrders((prev) =>
        filterForStation(
          prev.map((o) => (o.id === orderId ? { ...o, status: newStatus } : o)),
          stationName,
        ).filter((o) => ACTIVE_STATUSES.includes(o.status)),
      );
    };

    try {
      // Offline-pending orders exist only locally — skip API entirely
      const isOfflineOrder = String(orderId).startsWith('offline_');
      if (isOfflineOrder) {
        applyLocalUpdate();
        if (mountedRef.current) setSnack(`Order marked as ${newStatus}`);
        return;
      }

      try {
        await apiUpdateOrderStatus(orderId, newStatus);
        if (mountedRef.current) {
          setSnack(`Order marked as ${newStatus}`);
          applyLocalUpdate();
        }
      } catch (err) {
        if (!mountedRef.current) return;
        const isNetworkError = !err.response;
        if (isNetworkError) {
          // Network failure — optimistic update + SQLite write; server wins on reconnect
          applyLocalUpdate();
          try { await updateCachedOrderStatus(orderId, newStatus); } catch { /* best-effort */ }
          setSnack('Saved locally — will sync when reconnected');
        } else {
          setSnack(err?.response?.data?.error || 'Failed to update status');
        }
      }
    } finally {
      if (mountedRef.current) setUpdatingId(null);
    }
  }, [stationName]);

  const handleMarkPreparing = useCallback((id) => updateStatus(id, 'preparing'), [updateStatus]);
  const handleMarkReady     = useCallback((id) => updateStatus(id, 'ready'),     [updateStatus]);

  // ── Print ticket ─────────────────────────────────────────────────────────
  const handlePrint = useCallback(async (order) => {
    if (mountedRef.current) setPrintingId(order.id);
    const isOfflineOrder = String(order.id).startsWith('offline_');
    const useLocal = localKotBot || isOffline || isOfflineOrder;
    try {
      if (useLocal) {
        // Local BT print: offline orders, offline mode, or localKotBot flag
        const restaurantName = user?.restaurant_name || '';
        const orderedBy = user?.username || '';
        await printOrderTicket(order, restaurantName, stationName, orderedBy);
        if (mountedRef.current) setSnack('Ticket sent to printer');
      } else {
        // Online: ask server to print via its configured printer
        await apiPrintStationTicket(order.id);
        if (mountedRef.current) setSnack('Ticket printed');
      }
    } catch (err) {
      if (mountedRef.current) {
        const base = err?.response?.data?.error || err?.message || 'Print failed';
        const hint = useLocal ? ' — check Bluetooth & printer connection' : '';
        setSnack(base + hint);
      }
    } finally {
      if (mountedRef.current) setPrintingId(null);
    }
  }, [localKotBot, isOffline, stationName, user]);

  const renderOrderCard = useCallback(
    ({ item }) => (
      <OrderCard
        order={item}
        onMarkPreparing={handleMarkPreparing}
        onMarkReady={handleMarkReady}
        onPrint={handlePrint}
        updatingId={updatingId}
        printingId={printingId}
      />
    ),
    [handleMarkPreparing, handleMarkReady, handlePrint, updatingId, printingId]
  );

  // ── Render ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <View style={[styles.centered, { backgroundColor: theme.colors.background }]}>
        <ActivityIndicator size="large" />
        <Text style={styles.loadingText}>Loading {stationLabel} orders…</Text>
      </View>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.background }]}>
      <RestaurantHeader />
      {/* Offline banner */}
      {isOffline && (
        <Banner
          visible
          icon={({ size }) => (
            <MaterialCommunityIcons name="wifi-off" size={size} color="#B71C1C" />
          )}
          style={styles.banner}
        >
          You are offline — showing cached orders.
        </Banner>
      )}

      {/* Station header */}
      <View style={styles.stationHeader}>
        <MaterialCommunityIcons
          name={stationIcon}
          size={24}
          color={theme.colors.primary}
          style={styles.stationIcon}
        />
        <Text variant="titleLarge" style={styles.stationTitle}>
          {stationLabel} Station
        </Text>
        <Text variant="bodySmall" style={styles.orderCount}>
          {orders.length} active {orders.length === 1 ? 'order' : 'orders'}
        </Text>
      </View>

      <Divider />

      {/* Order list */}
      <FlatList
        data={orders}
        keyExtractor={(item) => String(item.id)}
        renderItem={renderOrderCard}
        extraData={{ updatingId, printingId }}
        removeClippedSubviews
        maxToRenderPerBatch={10}
        windowSize={7}
        contentContainerStyle={
          orders.length === 0 ? styles.emptyContainer : styles.listContent
        }
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <MaterialCommunityIcons
              name={stationIcon}
              size={64}
              color={theme.colors.outlineVariant || '#BDBDBD'}
            />
            <Text variant="titleMedium" style={styles.emptyTitle}>
              No active orders
            </Text>
            <Text variant="bodyMedium" style={styles.emptySubtitle}>
              No pending items for {stationLabel} right now.
            </Text>
          </View>
        }
      />

      <Snackbar
        visible={!!snack}
        onDismiss={() => setSnack('')}
        duration={3000}
        style={styles.snackbar}
      >
        {snack}
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: {
    marginTop: 12,
    color: '#757575',
  },
  banner: {
    backgroundColor: '#FFEBEE',
  },
  stationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  stationIcon: {
    marginRight: 8,
  },
  stationTitle: {
    fontFamily: 'Poppins_700Bold',
    flex: 1,
  },
  orderCount: {
    color: '#757575',
  },
  listContent: {
    padding: 12,
    paddingBottom: 32,
  },
  emptyContainer: {
    flex: 1,
  },
  card: {
    marginBottom: 12,
    borderRadius: 10,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  cardHeaderLeft: {
    flex: 1,
    marginRight: 8,
  },
  orderNumber: {
    fontFamily: 'Poppins_700Bold',
  },
  tableLabel: {
    color: '#757575',
    marginTop: 2,
  },
  statusChip: {
    height: 28,
    justifyContent: 'center',
  },
  statusChipText: {
    color: '#FFFFFF',
    fontSize: 10,
    fontFamily: 'Poppins_700Bold',
  },
  divider: {
    marginVertical: 10,
  },
  itemRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingVertical: 3,
    flexWrap: 'wrap',
  },
  itemQty: {
    fontFamily: 'Poppins_700Bold',
    minWidth: 32,
    color: '#424242',
  },
  itemName: {
    flex: 1,
  },
  itemNotes: {
    width: '100%',
    marginLeft: 32,
    color: '#E65100',
    fontStyle: 'italic',
  },
  cardActions: {
    paddingHorizontal: 12,
    paddingBottom: 10,
    justifyContent: 'flex-end',
    flexWrap: 'wrap',
  },
  printBtn: {
    marginRight: 'auto',
  },
  actionBtn: {
    marginLeft: 8,
  },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 80,
    paddingHorizontal: 32,
  },
  emptyTitle: {
    marginTop: 16,
    fontFamily: 'Poppins_700Bold',
    textAlign: 'center',
  },
  emptySubtitle: {
    marginTop: 8,
    color: '#757575',
    textAlign: 'center',
  },
  snackbar: {
    marginBottom: 16,
  },
});
