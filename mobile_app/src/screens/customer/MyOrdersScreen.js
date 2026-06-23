import React, { useState, useCallback } from 'react';
import { FlatList, ScrollView, View, StyleSheet, RefreshControl } from 'react-native';
import {
  Text,
  Card,
  Chip,
  ActivityIndicator,
  Button,
  Dialog,
  Portal,
  TextInput,
  Snackbar,
  Banner,
  useTheme,
} from 'react-native-paper';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import NetInfo from '@react-native-community/netinfo';
import { apiOrders, apiCancelOrder } from '../../api/orders';
import { getOrders } from '../../database/operations';
import { useCartStore } from '../../store/useCartStore';

const STATUS_COLORS = {
  pending: '#FFA000',
  confirmed: '#2c3e50',
  preparing: '#6A1B9A',
  ready: '#2E7D32',
  served: '#00796B',
  cancelled: '#B71C1C',
};

const PAYMENT_COLORS = {
  unpaid:  { bg: '#FFF3E0', text: '#E65100', label: 'Payment Pending' },
  partial: { bg: '#E3F2FD', text: '#1565C0', label: 'Partial Payment' },
  paid:    { bg: '#E8F5E9', text: '#2E7D32', label: 'Paid' },
};

const FILTER_TABS = [
  { key: 'all',     label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'active',  label: 'Active' },
  { key: 'done',    label: 'Done' },
];

export default function MyOrdersScreen() {
  const theme = useTheme();
  const navigation = useNavigation();
  const { setTable, clearCart, addItem } = useCartStore();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [reorderingId, setReorderingId] = useState(null);
  const [isOffline, setIsOffline] = useState(false);

  // Cancel dialog state
  const [cancelTarget, setCancelTarget] = useState(null);
  const [cancelReason, setCancelReason] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const [snack, setSnack] = useState('');
  const [activeFilter, setActiveFilter] = useState('all');

  const fetchOrders = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (net.isConnected) {
        const data = await apiOrders();
        setOrders(Array.isArray(data) ? data : data.results || []);
        setIsOffline(false);
      } else {
        const cached = await getOrders();
        setOrders(cached);
        setIsOffline(true);
      }
    } catch {
      // Network error — fall back to cache
      try {
        const cached = await getOrders();
        setOrders(cached);
      } catch {
        setOrders([]);
      }
      setIsOffline(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Refresh every time the tab is focused (catches new orders placed in the Order tab)
  useFocusEffect(
    useCallback(() => {
      fetchOrders();
    }, [fetchOrders])
  );

  const handleCancel = useCallback((order) => {
    setCancelReason('');
    setCancelTarget(order);
  }, []);

  const handleOrderAgain = useCallback((order) => {
    if (!order.items?.length) {
      setSnack('No items found in this order');
      return;
    }
    setReorderingId(order.id);
    clearCart();
    setTable(order.table_info, `Table ${order.table_number}`, null);
    order.items.forEach((item) => {
      addItem(
        {
          id: item.product_id,
          name: item.product_name,
          current_price: parseFloat(item.unit_price),
        },
        item.quantity,
      );
    });
    setReorderingId(null);
    setSnack('Items added to cart!');
    // Navigate to Cart in the Order tab
    navigation.navigate('Order', { screen: 'Cart' });
  }, [clearCart, setTable, addItem, navigation]);

  const handleCancelConfirm = async () => {
    if (!cancelTarget) return;
    setCancelling(true);
    try {
      const reason = cancelReason.trim() || 'Changed mind / No longer needed';
      await apiCancelOrder(cancelTarget.id, reason);
      setCancelTarget(null);
      setCancelReason('');
      setSnack('Order cancelled');
      fetchOrders(true);
    } catch (err) {
      setSnack(err.response?.data?.error || 'Could not cancel order');
    } finally {
      setCancelling(false);
    }
  };

  const filteredOrders = orders.filter((o) => {
    if (activeFilter === 'all') return true;
    if (activeFilter === 'pending') return o.status === 'pending';
    if (activeFilter === 'active') return ['confirmed', 'preparing', 'ready', 'served'].includes(o.status);
    if (activeFilter === 'done') return o.status === 'cancelled' || (o.status === 'served' && o.payment_status === 'paid');
    return true;
  });

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <>
      {/* ── Offline banner ── */}
      <Banner
        visible={isOffline}
        icon="wifi-off"
        actions={[]}
        style={styles.offlineBanner}
      >
        You are offline – showing your last synced orders.
      </Banner>

      {/* ── Filter tabs ── */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.filterBar}
      >
        {FILTER_TABS.map((tab) => (
          <Chip
            key={tab.key}
            selected={activeFilter === tab.key}
            onPress={() => setActiveFilter(tab.key)}
            style={[styles.filterChip, activeFilter === tab.key && styles.filterChipActive]}
            textStyle={[
              styles.filterChipText,
              activeFilter === tab.key && styles.filterChipTextActive,
            ]}
          >
            {tab.label}
          </Chip>
        ))}
      </ScrollView>

      <FlatList
        data={filteredOrders}
        keyExtractor={(o) => String(o.id)}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              fetchOrders(true);
            }}
          />
        }
        ListEmptyComponent={() => (
          <View style={styles.center}>
            <Text variant="bodyLarge" style={{ opacity: 0.5, fontFamily: 'Poppins_400Regular' }}>
              {activeFilter === 'all' ? 'No orders yet' : `No ${activeFilter} orders`}
            </Text>
          </View>
        )}
        renderItem={({ item: order }) => {
          const color = STATUS_COLORS[order.status] || theme.colors.primary;
          const pay = PAYMENT_COLORS[order.payment_status] || PAYMENT_COLORS.unpaid;
          return (
            <Card
              style={styles.card}
              onPress={() =>
                navigation.navigate('OrderTracking', { orderId: order.id })
              }
            >
              <Card.Content>
                {/* Header row: order# + status */}
                <View style={styles.row}>
                  <Text variant="titleMedium" style={{ fontFamily: 'Poppins_700Bold' }}>
                    Order #{order.order_number || order.id}
                  </Text>
                  <Chip
                    mode="flat"
                    style={[styles.chip, { backgroundColor: color + '22' }]}
                    textStyle={{ color, fontSize: 11, fontFamily: 'Poppins_600SemiBold' }}
                  >
                    {order.status.toUpperCase()}
                  </Chip>
                </View>

                {/* Payment status badge */}
                <View style={[styles.payBadge, { backgroundColor: pay.bg }]}>
                  <Text style={{ color: pay.text, fontSize: 11, fontFamily: 'Poppins_600SemiBold' }}>
                    {pay.label}
                  </Text>
                </View>

                <Text variant="bodySmall" style={styles.meta}>
                  Table {order.table_number} · {order.items_count} item{order.items_count !== 1 ? 's' : ''} · Total: {order.total}
                </Text>
                {order.created_at ? (
                  <Text variant="bodySmall" style={styles.date}>
                    {new Date(order.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </Text>
                ) : null}
                {order.special_instructions ? (
                  <Text variant="bodySmall" style={styles.specialInstructions} numberOfLines={1}>
                    📝 {order.special_instructions}
                  </Text>
                ) : null}
              </Card.Content>

              {/* Action buttons */}
              <Card.Actions style={styles.actions}>
                <Button
                  compact
                  mode="outlined"
                  icon="eye"
                  onPress={() => navigation.navigate('OrderTracking', { orderId: order.id })}
                  labelStyle={{ fontFamily: 'Poppins_600SemiBold', fontSize: 12 }}
                >
                  Track
                </Button>

                {order.payment_status === 'paid' && (
                  <Button
                    compact
                    mode="outlined"
                    icon="receipt"
                    textColor="#2E7D32"
                    style={styles.receiptBtn}
                    onPress={() => navigation.navigate('Receipt', { orderId: order.id })}
                    labelStyle={{ fontFamily: 'Poppins_600SemiBold', fontSize: 12 }}
                  >
                    Receipt
                  </Button>
                )}

                {['served', 'cancelled'].includes(order.status) && (
                  <Button
                    compact
                    mode="outlined"
                    icon="repeat"
                    textColor="#6A1B9A"
                    style={styles.reorderBtn}
                    loading={reorderingId === order.id}
                    disabled={reorderingId === order.id}
                    onPress={() => handleOrderAgain(order)}
                    labelStyle={{ fontFamily: 'Poppins_600SemiBold', fontSize: 12 }}
                  >
                    Order Again
                  </Button>
                )}

                {order.status === 'pending' && (
                  <Button
                    compact
                    mode="outlined"
                    icon="close-circle-outline"
                    textColor="#B71C1C"
                    style={styles.cancelBtn}
                    loading={cancelTarget?.id === order.id && cancelling}
                    disabled={cancelTarget?.id === order.id && cancelling}
                    onPress={() => handleCancel(order)}
                    labelStyle={{ fontFamily: 'Poppins_600SemiBold', fontSize: 12 }}
                  >
                    Cancel
                  </Button>
                )}
              </Card.Actions>
            </Card>
          );
        }}
      />

      {/* Cancel Order Dialog */}
      <Portal>
        <Dialog visible={!!cancelTarget} onDismiss={() => setCancelTarget(null)}>
          <Dialog.Title style={{ fontFamily: 'Poppins_700Bold' }}>Cancel Order</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_400Regular', marginBottom: 12 }}>
              Cancel Order #{cancelTarget?.order_number || cancelTarget?.id}?{`\n`}This action cannot be undone.
            </Text>
            <TextInput
              label="Reason (optional)"
              value={cancelReason}
              onChangeText={setCancelReason}
              mode="outlined"
              placeholder="Changed mind / No longer needed"
              style={{ fontFamily: 'Poppins_400Regular' }}
            />
          </Dialog.Content>
          <Dialog.Actions>
            <Button
              onPress={() => setCancelTarget(null)}
              labelStyle={{ fontFamily: 'Poppins_600SemiBold' }}
            >
              Keep Order
            </Button>
            <Button
              textColor="#B71C1C"
              loading={cancelling}
              disabled={cancelling}
              onPress={handleCancelConfirm}
              labelStyle={{ fontFamily: 'Poppins_600SemiBold' }}
            >
              Cancel Order
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {snack}
      </Snackbar>
    </>
  );
}

const styles = StyleSheet.create({
  offlineBanner: { backgroundColor: '#FFF8E1' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  filterBar: { paddingHorizontal: 12, paddingVertical: 8, gap: 8 },
  filterChip: { backgroundColor: '#F5F5F5', borderRadius: 20 },
  filterChipActive: { backgroundColor: '#2c3e50' },
  filterChipText: { fontFamily: 'Poppins_400Regular', fontSize: 13, color: '#555' },
  filterChipTextActive: { color: '#fff', fontFamily: 'Poppins_600SemiBold' },
  list: { padding: 12 },
  card: { marginBottom: 10, borderRadius: 12 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  chip: { paddingHorizontal: 4 },
  payBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
    marginBottom: 6,
  },
  meta: { opacity: 0.65, fontFamily: 'Poppins_400Regular' },
  date: { opacity: 0.5, fontFamily: 'Poppins_400Regular', marginTop: 3 },
  specialInstructions: {
    fontFamily: 'Poppins_400Regular',
    color: '#1565C0',
    marginTop: 4,
    backgroundColor: '#E3F2FD',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  actions: { paddingHorizontal: 8, paddingBottom: 8, gap: 6 },
  receiptBtn:  { borderColor: '#2E7D32' },
  reorderBtn:  { borderColor: '#6A1B9A' },
  cancelBtn:   { borderColor: '#B71C1C' },
});
