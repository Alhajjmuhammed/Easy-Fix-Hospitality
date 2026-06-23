import React, { useEffect, useState, useCallback } from 'react';
import { View, FlatList, StyleSheet, RefreshControl, Alert } from 'react-native';
import {
  Text, Card, Button, TextInput, Dialog, Portal, Chip,
  ActivityIndicator, Snackbar, Banner, useTheme, SegmentedButtons, FAB, Divider, Menu,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import { apiOrders, apiUpdateOrderStatus, apiCancelOrder, apiTransferTable, apiPrintBill } from '../../api/orders';
import { apiProcessPayment, apiVoidPayment } from '../../api/payments';
import { apiTables } from '../../api/tables';
import { getOrders, cacheOrders } from '../../database/operations';
import { useCurrency } from '../../hooks/useCurrency';

const PAYMENT_METHODS = [
  { value: 'cash',    label: 'Cash' },
  { value: 'card',    label: 'Card' },
  { value: 'digital', label: 'Digital' },
  { value: 'voucher', label: 'Voucher' },
];

const STATUS_NEXT = {
  pending:   'confirmed',
  confirmed: 'preparing',
  preparing: 'ready',
  ready:     'served',
};

const STATUS_COLORS = {
  pending:   '#FFA000',
  confirmed: '#2c3e50',
  preparing: '#6A1B9A',
  ready:     '#2E7D32',
  served:    '#00796B',
  cancelled: '#B71C1C',
};

export default function CashierDashboardScreen({ navigation }) {
  const theme = useTheme();
  const { format } = useCurrency();

  const [orders,          setOrders]          = useState([]);
  const [loading,         setLoading]         = useState(true);
  const [refreshing,      setRefreshing]      = useState(false);
  const [filter,          setFilter]          = useState('active');
  const [updatingStatus,  setUpdatingStatus]  = useState(null);
  const [snack,           setSnack]           = useState('');
  const [isOffline,       setIsOffline]       = useState(false);

  // Pay dialog
  const [payDialog,  setPayDialog]  = useState(null);
  const [amount,     setAmount]     = useState('');
  const [method,     setMethod]     = useState('cash');
  const [reference,  setReference]  = useState('');
  const [paying,     setPaying]     = useState(false);

  // Void dialog
  const [voidDialog,    setVoidDialog]    = useState(null);
  const [voidReason,    setVoidReason]    = useState('');
  const [voiding,       setVoiding]       = useState(false);

  // Cancel dialog
  const [cancelDialog,  setCancelDialog]  = useState(null);
  const [cancelReason,  setCancelReason]  = useState('');
  const [cancelling,    setCancelling]    = useState(false);

  // Transfer dialog
  const [transferDialog, setTransferDialog] = useState(null);
  const [tables,          setTables]         = useState([]);
  const [targetTable,     setTargetTable]    = useState(null);
  const [transferring,    setTransferring]   = useState(false);
  const [tableMenuVisible, setTableMenuVisible] = useState(false);

  // Per-card action menus
  const [menuOpenId, setMenuOpenId] = useState(null);

  const fetchOrders = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (net.isConnected) {
        const params = filter === 'active'
          ? { status: 'pending,confirmed,preparing,ready' }
          : {};
        const data = await apiOrders(params);
        const fetched = Array.isArray(data) ? data : data.results || [];
        setOrders(fetched);
        setIsOffline(false);
        try { await cacheOrders(fetched); } catch { /* best-effort */ }
      } else {
        const activeStatuses = ['pending', 'confirmed', 'preparing', 'ready', 'served'];
        const cached = await getOrders(filter === 'active' ? activeStatuses : null);
        setOrders(cached);
        setIsOffline(true);
      }
    } catch {
      // Network error — fall back to cache
      try {
        const cached = await getOrders(['pending', 'confirmed', 'preparing', 'ready', 'served']);
        setOrders(cached);
      } catch {
        setOrders([]);
      }
      setIsOffline(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchOrders();
    const interval = setInterval(() => fetchOrders(true), 20_000);
    return () => clearInterval(interval);
  }, [fetchOrders]);

  // ── Status advance ─────────────────────────────────────────────────────────
  const handleStatusAdvance = async (order) => {
    const next = STATUS_NEXT[order.status];
    if (!next) return;
    setUpdatingStatus(order.id);
    try {
      await apiUpdateOrderStatus(order.id, next);
      fetchOrders(true);
    } catch {
      setSnack('Could not update status');
    } finally {
      setUpdatingStatus(null);
    }
  };

  // ── Payment ────────────────────────────────────────────────────────────────
  const openPayment = (order) => {
    setPayDialog(order);
    setAmount(String(order.balance_due > 0 ? order.balance_due : order.total ?? ''));
    setMethod('cash');
    setReference('');
  };

  const handlePayment = async () => {
    if (!payDialog || !amount) return;
    const parsed = parseFloat(amount);
    if (isNaN(parsed) || parsed <= 0) { setSnack('Enter a valid amount'); return; }
    setPaying(true);
    try {
      await apiProcessPayment({ order_id: payDialog.id, amount: parsed, payment_method: method, reference_number: reference.trim() });
      setPayDialog(null);
      setSnack('Payment recorded');
      fetchOrders(true);
    } catch (err) {
      setSnack(err.response?.data?.detail || err.response?.data?.error || 'Payment failed');
    } finally {
      setPaying(false);
    }
  };

  // ── Void ───────────────────────────────────────────────────────────────────
  const openVoid = (order) => {
    const payment = order.payments?.[0];
    if (!payment) { setSnack('No payment found to void'); return; }
    setVoidDialog({ order, paymentId: payment.id });
    setVoidReason('');
  };

  const handleVoid = async () => {
    if (!voidDialog) return;
    setVoiding(true);
    try {
      await apiVoidPayment(voidDialog.paymentId, voidReason.trim());
      setVoidDialog(null);
      setSnack('Payment voided');
      fetchOrders(true);
    } catch (err) {
      setSnack(err.response?.data?.detail || 'Void failed');
    } finally {
      setVoiding(false);
    }
  };

  // ── Cancel order ───────────────────────────────────────────────────────────
  const openCancel = (order) => {
    setCancelDialog(order);
    setCancelReason('');
  };

  const handleCancel = async () => {
    if (!cancelDialog) return;
    setCancelling(true);
    try {
      await apiCancelOrder(cancelDialog.id, cancelReason.trim());
      setCancelDialog(null);
      setSnack('Order cancelled');
      fetchOrders(true);
    } catch (err) {
      setSnack(err.response?.data?.detail || 'Cancel failed');
    } finally {
      setCancelling(false);
    }
  };

  // ── Transfer table ─────────────────────────────────────────────────────────
  const openTransfer = async (order) => {
    setTransferDialog(order);
    setTargetTable(null);
    setTableMenuVisible(false);
    try {
      const t = await apiTables();
      setTables((t || []).filter((tb) => tb.is_available === true));
    } catch {
      setTables([]);
    }
  };

  const handleTransfer = async () => {
    if (!transferDialog || !targetTable) return;
    setTransferring(true);
    try {
      await apiTransferTable(transferDialog.id, targetTable.id);
      setTransferDialog(null);
      setSnack('Table transferred');
      fetchOrders(true);
    } catch (err) {
      setSnack(err.response?.data?.detail || 'Transfer failed');
    } finally {
      setTransferring(false);
    }
  };

  // ── Print bill ─────────────────────────────────────────────────────────────
  const handlePrintBill = async (order) => {
    try {
      await apiPrintBill(order.id);
      setSnack('Bill sent to printer');
    } catch (err) {
      setSnack(err.response?.data?.error || 'Print failed');
    }
  };

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }

  return (
    <View style={styles.container}>
      <Banner
        visible={isOffline}
        icon="wifi-off"
        actions={[]}
        style={{ backgroundColor: '#FFF8E1' }}
      >
        You are offline – showing cached orders. Changes require connection.
      </Banner>
      <SegmentedButtons
        value={filter}
        onValueChange={setFilter}
        buttons={[
          { value: 'active', label: 'Active' },
          { value: 'all',    label: 'All Today' },
        ]}
        style={styles.filterBtns}
      />

      <FlatList
        data={orders}
        keyExtractor={(o) => String(o.id)}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); fetchOrders(true); }} />
        }
        ListEmptyComponent={() => (
          <View style={styles.center}>
            <MaterialCommunityIcons name="clipboard-text-off-outline" size={48} color="#ccc" />
            <Text variant="bodyLarge" style={{ opacity: 0.4, marginTop: 8 }}>No orders</Text>
          </View>
        )}
        renderItem={({ item: order }) => {
          const statusColor = STATUS_COLORS[order.status] || theme.colors.primary;
          const nextStatus  = STATUS_NEXT[order.status];
          const isPaid      = order.payment_status === 'paid';
          const hasPay      = order.balance_due > 0 || (!isPaid && order.status !== 'cancelled');
          const hasPayment  = order.payments && order.payments.length > 0;
          const isMenuOpen  = menuOpenId === order.id;

          return (
            <Card style={styles.card}>
              <Card.Content>
                <View style={styles.row}>
                  <Text variant="titleMedium" style={{ fontFamily: 'Poppins_700Bold' }}>
                    #{order.order_number || order.id}
                  </Text>
                  <View style={styles.row}>
                    <Chip mode="flat" style={{ backgroundColor: statusColor + '22' }} textStyle={{ color: statusColor, fontSize: 11 }}>
                      {order.status?.toUpperCase()}
                    </Chip>
                    <Menu
                      visible={isMenuOpen}
                      onDismiss={() => setMenuOpenId(null)}
                      anchor={
                        <Button compact icon="dots-vertical" onPress={() => setMenuOpenId(isMenuOpen ? null : order.id)} />
                      }
                    >
                      <Menu.Item leadingIcon="eye" title="View Order" onPress={() => { setMenuOpenId(null); navigation.navigate('OrderDetail', { orderId: order.id }); }} />
                      <Divider />
                      <Menu.Item leadingIcon="printer" title="Print Bill"    onPress={() => { setMenuOpenId(null); handlePrintBill(order); }} />
                      <Menu.Item leadingIcon="swap-horizontal" title="Transfer Table" onPress={() => { setMenuOpenId(null); openTransfer(order); }} disabled={isPaid || order.status === 'cancelled'} />
                      {hasPayment && (
                        <Menu.Item leadingIcon="cancel" title="Void Payment" onPress={() => { setMenuOpenId(null); openVoid(order); }} />
                      )}
                      <Divider />
                      <Menu.Item leadingIcon="close-circle-outline" title="Cancel Order" titleStyle={{ color: '#E53935' }} onPress={() => { setMenuOpenId(null); openCancel(order); }} disabled={order.status === 'cancelled' || isPaid} />
                    </Menu>
                  </View>
                </View>
                <Text variant="bodySmall" style={styles.meta}>
                  Table {order.table_number} · {order.items_count} item{order.items_count !== 1 ? 's' : ''} · Total: {format(order.total)}
                </Text>
                {order.balance_due > 0 && (
                  <Text variant="bodySmall" style={{ color: theme.colors.error, fontFamily: 'Poppins_600SemiBold' }}>
                    Due: {format(order.balance_due)}
                  </Text>
                )}
                {isPaid && (
                  <Text variant="bodySmall" style={{ color: '#2E7D32', fontFamily: 'Poppins_600SemiBold' }}>✓ Fully Paid</Text>
                )}
              </Card.Content>
              <Card.Actions>
                {nextStatus && (
                  <Button mode="outlined" compact loading={updatingStatus === order.id}
                    disabled={updatingStatus === order.id} onPress={() => handleStatusAdvance(order)}>
                    → {nextStatus}
                  </Button>
                )}
                {hasPay && !isPaid && order.status !== 'cancelled' && (
                  <Button mode="contained" compact onPress={() => openPayment(order)}>
                    Pay
                  </Button>
                )}
              </Card.Actions>
            </Card>
          );
        }}
      />

      {/* ── Pay Dialog ─────────────────────────────────────────────────── */}
      <Portal>
        <Dialog visible={!!payDialog} onDismiss={() => setPayDialog(null)}>
          <Dialog.Title>Process Payment</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={{ marginBottom: 8, opacity: 0.7 }}>
              Order #{payDialog?.order_number || payDialog?.id} · Table {payDialog?.table_number}
            </Text>
            <Text variant="bodyMedium" style={{ marginBottom: 12, fontFamily: 'Poppins_700Bold' }}>
              Balance Due: {format(payDialog?.balance_due ?? payDialog?.total ?? 0)}
            </Text>
            <TextInput label="Amount" value={amount} onChangeText={setAmount}
              keyboardType="decimal-pad" mode="outlined" style={{ marginBottom: 12 }} />
            <Text variant="labelMedium" style={{ marginBottom: 6 }}>Payment Method</Text>
            <SegmentedButtons value={method} onValueChange={setMethod}
              buttons={PAYMENT_METHODS} style={{ marginBottom: 12 }} />
            {method !== 'cash' && (
              <TextInput label="Reference / Approval Code" value={reference}
                onChangeText={setReference} mode="outlined" />
            )}
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setPayDialog(null)}>Cancel</Button>
            <Button mode="contained" loading={paying} disabled={paying} onPress={handlePayment}>Confirm</Button>
          </Dialog.Actions>
        </Dialog>

        {/* ── Void Dialog ────────────────────────────────────────────────── */}
        <Dialog visible={!!voidDialog} onDismiss={() => setVoidDialog(null)}>
          <Dialog.Title>Void Payment</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={{ marginBottom: 12, opacity: 0.7 }}>
              Order #{voidDialog?.order?.order_number || voidDialog?.order?.id}
            </Text>
            <TextInput label="Void Reason (optional)" value={voidReason}
              onChangeText={setVoidReason} mode="outlined" multiline numberOfLines={2} />
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setVoidDialog(null)}>Cancel</Button>
            <Button mode="contained" buttonColor="#E53935" loading={voiding} disabled={voiding} onPress={handleVoid}>Void</Button>
          </Dialog.Actions>
        </Dialog>

        {/* ── Cancel Dialog ──────────────────────────────────────────────── */}
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

        {/* ── Transfer Table Dialog ──────────────────────────────────────── */}
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
                  {targetTable ? `Table ${targetTable.table_number}` : 'Select available table'}
                </Button>
              }
            >
              {tables.length === 0 && <Menu.Item title="No available tables" disabled />}
              {tables.map((t) => (
                <Menu.Item key={t.id} title={`Table ${t.table_number} — ${t.name || ''}`}
                  onPress={() => { setTargetTable(t); setTableMenuVisible(false); }} />
              ))}
            </Menu>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setTransferDialog(null)}>Cancel</Button>
            <Button mode="contained" loading={transferring} disabled={!targetTable || transferring} onPress={handleTransfer}>Transfer</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>{snack}</Snackbar>

      <FAB icon="refresh" style={styles.fab} size="small" onPress={() => fetchOrders(true)} />
    </View>
  );
}

const styles = StyleSheet.create({
  container:   { flex: 1, backgroundColor: '#F5F5F5' },
  center:      { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 32 },
  filterBtns:  { margin: 12 },
  list:        { padding: 12, paddingBottom: 80 },
  card:        { marginBottom: 10, borderRadius: 10 },
  row:         { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  meta:        { opacity: 0.65, marginBottom: 2 },
  fab:         { position: 'absolute', right: 16, bottom: 16, backgroundColor: '#2c3e50' },
});
