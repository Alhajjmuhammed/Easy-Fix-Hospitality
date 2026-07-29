import React, { useEffect, useState, useCallback } from 'react';
import { View, FlatList, StyleSheet, RefreshControl, ScrollView } from 'react-native';
import {
  Text, Card, Button, TextInput, Dialog, Portal, Chip,
  ActivityIndicator, Snackbar, useTheme, SegmentedButtons, FAB, Divider, Menu,
  List, RadioButton, Banner,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { apiOrders, apiUpdateOrderStatus, apiCancelOrder, apiTransferTable, apiPrintBill } from '../../api/orders';
import NetInfo from '@react-native-community/netinfo';
import { getOrders, cacheOrders, getOfflinePendingOrders, saveOfflinePayment } from '../../database/operations';
import { useSyncStore } from '../../store/useSyncStore';
import { apiRidersList, apiAssignRider, apiAutoAssign } from '../../api/delivery';
import { apiProcessPayment, apiVoidPayment } from '../../api/payments';
import { apiTables } from '../../api/tables';
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
  pending:          '#FFA000',
  confirmed:        '#2c3e50',
  preparing:        '#6A1B9A',
  ready:            '#2E7D32',
  served:           '#00796B',
  out_for_delivery: '#1565C0',
  delivered:        '#2E7D32',
  cancelled:        '#B71C1C',
};

export default function CashierMyOrdersScreen({ navigation }) {
  const theme = useTheme();
  const { format } = useCurrency();

  const [orders,         setOrders]         = useState([]);
  const [loading,        setLoading]        = useState(true);
  const [refreshing,     setRefreshing]     = useState(false);
  const [period,         setPeriod]         = useState('today');
  const [updatingStatus, setUpdatingStatus] = useState(null);
  const [snack,          setSnack]          = useState('');

  // Pay dialog
  const [payDialog, setPayDialog] = useState(null);
  const [amount,    setAmount]    = useState('');
  const [method,    setMethod]    = useState('cash');
  const [reference, setReference] = useState('');
  const [paying,    setPaying]    = useState(false);

  // Void dialog
  const [voidDialog, setVoidDialog] = useState(null);
  const [voidReason, setVoidReason] = useState('');
  const [voiding,    setVoiding]    = useState(false);

  // Cancel dialog
  const [cancelDialog, setCancelDialog] = useState(null);
  const [cancelReason, setCancelReason] = useState('');
  const [cancelling,   setCancelling]   = useState(false);

  // Transfer dialog
  const [transferDialog,    setTransferDialog]    = useState(null);
  const [tables,             setTables]            = useState([]);
  const [targetTable,        setTargetTable]       = useState(null);
  const [transferring,       setTransferring]      = useState(false);
  const [tableMenuVisible,   setTableMenuVisible]  = useState(false);

  // Assign rider dialog
  const [assignDialog,    setAssignDialog]    = useState(null);
  const [riderOptions,    setRiderOptions]    = useState([]);
  const [selectedRider,   setSelectedRider]   = useState(null);
  const [assigning,       setAssigning]       = useState(false);
  const [autoAssigning,   setAutoAssigning]   = useState(false);

  // Per-card action menus
  const [menuOpenId, setMenuOpenId] = useState(null);
  const [isOffline, setIsOffline] = useState(false);

  const buildParams = useCallback(() => {
    const params = { my_orders: 'true' };
    if (period === 'today') params.period = 'today';
    else if (period === 'week') params.period = 'week';
    return params;
  }, [period]);

  const fetchOrders = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        const [offlinePending, cached] = await Promise.all([
          getOfflinePendingOrders(),
          getOrders(null),
        ]);
        setOrders([...offlinePending, ...cached]);
        setIsOffline(true);
        return;
      }
      const [offlinePending, data] = await Promise.all([
        getOfflinePendingOrders(),
        apiOrders(buildParams()),
      ]);
      const fetched = Array.isArray(data) ? data : data.results || [];
      setOrders([...offlinePending, ...fetched]);
      setIsOffline(false);
      try { await cacheOrders(fetched); } catch { /* best-effort */ }
    } catch {
      try {
        const [offlinePending, cached] = await Promise.all([
          getOfflinePendingOrders(),
          getOrders(null),
        ]);
        setOrders([...offlinePending, ...cached]);
      } catch {
        setOrders([]);
      }
      setIsOffline(true);
      setSnack('Could not load orders — showing cached data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [buildParams]);

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
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        await saveOfflinePayment({
          order_id:         payDialog.id,
          order_number:     payDialog.order_number,
          amount:           parsed,
          payment_method:   method,
          reference_number: reference.trim(),
          notes:            '',
        });
        await useSyncStore.getState().refreshPendingCount();
        setOrders((prev) =>
          prev.map((o) => {
            if (o.id !== payDialog.id) return o;
            const newPaid = (o.total_paid ?? 0) + parsed;
            const newDue  = Math.max(0, (o.balance_due ?? o.total ?? 0) - parsed);
            const newStatus = newDue <= 0 ? 'paid' : newPaid > 0 ? 'partial' : o.payment_status;
            return { ...o, total_paid: newPaid, balance_due: newDue, payment_status: newStatus };
          })
        );
        setPayDialog(null);
        setSnack('No internet – payment saved and will sync automatically');
        return;
      }
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
    if (!payment) { setSnack('No payment to void'); return; }
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
  const openCancel = (order) => { setCancelDialog(order); setCancelReason(''); };

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
    const net = await NetInfo.fetch();
    if (!net.isConnected) { setSnack('No internet — connect to print the bill'); return; }
    try {
      await apiPrintBill(order.id);
      setSnack('Bill sent to printer');
    } catch (err) {
      setSnack(err.response?.data?.error || 'Print failed');
    }
  };

  // ── Assign rider ────────────────────────────────────────────────────────────
  const openAssignRider = async (order) => {
    setAssignDialog(order);
    setSelectedRider(null);
    try {
      const riders = await apiRidersList(true, true);
      setRiderOptions(riders || []);
    } catch {
      setSnack('Could not load riders');
      setAssignDialog(null);
    }
  };

  const handleAutoAssign = async () => {
    if (!assignDialog) return;
    setAutoAssigning(true);
    try {
      const res = await apiAutoAssign(assignDialog.id);
      setAssignDialog(null);
      const label = res.is_cross_restaurant
        ? `Assigned to ${res.rider_name} (${res.rider_restaurant}) from global pool`
        : `Assigned to ${res.rider_name}`;
      setSnack(label);
      fetchOrders(true);
    } catch (err) {
      setSnack(err.response?.data?.error || 'Auto-assign failed');
    } finally {
      setAutoAssigning(false);
    }
  };

  const handleAssignRider = async () => {
    if (!assignDialog || !selectedRider) return;
    setAssigning(true);
    try {
      await apiAssignRider(assignDialog.id, selectedRider);
      setAssignDialog(null);
      setSnack('Rider assigned!');
      fetchOrders(true);
    } catch (err) {
      setSnack(err.response?.data?.error || 'Could not assign rider');
    } finally {
      setAssigning(false);
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
        Offline – showing cached orders. Connect to see your personal order history.
      </Banner>
      <SegmentedButtons
        value={period}
        onValueChange={setPeriod}
        buttons={[
          { value: 'today', label: 'Today' },
          { value: 'week',  label: 'This Week' },
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
            <MaterialCommunityIcons name="account-clock-outline" size={48} color="#ccc" />
            <Text variant="bodyLarge" style={{ opacity: 0.4, marginTop: 8 }}>No orders placed by you</Text>
          </View>
        )}
        renderItem={({ item: order }) => {
          const isDelivery    = order.order_type === 'delivery';
          const statusColor   = STATUS_COLORS[order.status] || theme.colors.primary;
          const nextStatus    = STATUS_NEXT[order.status];
          const showAssign    = isDelivery && order.status === 'ready';
          const effectiveNext = showAssign ? null : nextStatus;
          const isPaid        = order.payment_status === 'paid';
          const hasPay        = order.balance_due > 0 || (!isPaid && order.status !== 'cancelled');
          const hasPayment    = order.payments && order.payments.length > 0;
          const isMenuOpen    = menuOpenId === order.id;

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
                        <Button compact icon="dots-vertical" disabled={!!order._is_offline_pending} onPress={() => setMenuOpenId(isMenuOpen ? null : order.id)} />
                      }
                    >
                      <Menu.Item leadingIcon="eye" title="View Order" onPress={() => { setMenuOpenId(null); navigation.navigate('OrderDetail', { orderId: order.id }); }} />
                      <Divider />
                      <Menu.Item leadingIcon="printer" title="Print Bill" onPress={() => { setMenuOpenId(null); handlePrintBill(order); }} />
                      <Menu.Item leadingIcon="swap-horizontal" title="Transfer Table" onPress={() => { setMenuOpenId(null); openTransfer(order); }} disabled={isPaid || order.status === 'cancelled'} />
                      {hasPayment && (
                        <Menu.Item leadingIcon="cancel" title="Void Payment" onPress={() => { setMenuOpenId(null); openVoid(order); }} />
                      )}
                      <Divider />
                      <Menu.Item leadingIcon="close-circle-outline" title="Cancel Order" titleStyle={{ color: '#E53935' }} onPress={() => { setMenuOpenId(null); openCancel(order); }} disabled={order.status === 'cancelled' || isPaid} />
                    </Menu>
                  </View>
                </View>
                {order._is_sync_error && (
                  <>
                    <Chip icon="alert-circle" mode="flat" compact
                      style={{ backgroundColor: '#FFEBEE', alignSelf: 'flex-start', marginBottom: 4 }}
                      textStyle={{ fontSize: 10, color: '#C62828' }}>
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
                  <Chip icon="cloud-upload" mode="flat" compact
                    style={{ backgroundColor: '#FFF3E0', alignSelf: 'flex-start', marginBottom: 4 }}
                    textStyle={{ fontSize: 10, color: '#E65100' }}>
                    Queued – syncs when online
                  </Chip>
                )}
                <Text variant="bodySmall" style={styles.meta}>
                  {isDelivery ? '🚴 Delivery' : `Table ${order.table_number}`} · {order.items_count} item{order.items_count !== 1 ? 's' : ''} · Total: {format(order.total)}
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
                {order._is_sync_error ? (
                  <Text variant="bodySmall" style={{ color: '#C62828', opacity: 0.7, paddingHorizontal: 8 }}>
                    Re-take this order manually
                  </Text>
                ) : order._is_offline_pending ? (
                  <Text variant="bodySmall" style={{ color: '#E65100', opacity: 0.7, paddingHorizontal: 8 }}>
                    Actions available after sync
                  </Text>
                ) : (
                  <>
                    {effectiveNext && (
                      <Button mode="outlined" compact loading={updatingStatus === order.id}
                        disabled={updatingStatus === order.id} onPress={() => handleStatusAdvance(order)}>
                        → {effectiveNext}
                      </Button>
                    )}
                    {showAssign && (
                      <Button mode="outlined" compact icon="moped" onPress={() => openAssignRider(order)}>
                        Assign Rider
                      </Button>
                    )}
                    {hasPay && !isPaid && order.status !== 'cancelled' && (
                      <Button mode="contained" compact onPress={() => openPayment(order)}>Pay</Button>
                    )}
                  </>
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

        {/* ── Void Dialog ─────────────────────────────────────────────── */}
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

        {/* ── Cancel Dialog ───────────────────────────────────────────── */}
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

        {/* ── Transfer Dialog ─────────────────────────────────────────── */}
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
                <Menu.Item key={t.id} title={`Table ${t.table_number ?? t.tbl_no}`}
                  onPress={() => { setTargetTable(t); setTableMenuVisible(false); }} />
              ))}
            </Menu>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setTransferDialog(null)}>Cancel</Button>
            <Button mode="contained" loading={transferring} disabled={!targetTable || transferring} onPress={handleTransfer}>Transfer</Button>
          </Dialog.Actions>
        </Dialog>

        {/* ── Assign Rider Dialog ─────────────────────────────────────────── */}
        <Dialog visible={!!assignDialog} onDismiss={() => setAssignDialog(null)}>
          <Dialog.Title>Assign Delivery Rider</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={{ marginBottom: 10, opacity: 0.7 }}>
              Order #{assignDialog?.order_number || assignDialog?.id}
            </Text>

            <Button
              mode="contained"
              icon="auto-fix"
              loading={autoAssigning}
              disabled={autoAssigning || assigning}
              onPress={handleAutoAssign}
              style={{ marginBottom: 12, borderRadius: 8 }}
              buttonColor="#1565C0"
            >
              Auto-Assign Best Available
            </Button>

            <Text variant="labelSmall" style={{ textAlign: 'center', color: '#9E9E9E', marginBottom: 8 }}>
              — or choose manually —
            </Text>

            {riderOptions.length === 0 ? (
              <Text variant="bodyMedium" style={{ color: '#757575', marginVertical: 4 }}>
                No available riders right now.
              </Text>
            ) : (
              <ScrollView style={{ maxHeight: 220 }}>
                <RadioButton.Group
                  onValueChange={(v) => setSelectedRider(Number(v))}
                  value={selectedRider ? String(selectedRider) : ''}
                >
                  {riderOptions.map((r) => (
                    <List.Item
                      key={r.id}
                      title={r.name}
                      description={
                        r.is_local
                          ? `${r.vehicle_display} · ${r.phone || 'No phone'}`
                          : `${r.vehicle_display} · ${r.restaurant}`
                      }
                      left={() => <RadioButton value={String(r.id)} />}
                      right={() =>
                        !r.is_local ? (
                          <Text style={{ fontSize: 10, color: '#1565C0', alignSelf: 'center', marginRight: 4 }}>
                            🌐 Global
                          </Text>
                        ) : null
                      }
                      onPress={() => setSelectedRider(r.id)}
                      style={{ paddingLeft: 0 }}
                    />
                  ))}
                </RadioButton.Group>
              </ScrollView>
            )}
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setAssignDialog(null)}>Cancel</Button>
            <Button
              mode="outlined"
              loading={assigning}
              disabled={assigning || autoAssigning || !selectedRider}
              onPress={handleAssignRider}
            >
              Assign Selected
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>{snack}</Snackbar>
      <FAB icon="refresh" style={styles.fab} size="small" onPress={() => fetchOrders(true)} />
    </View>
  );
}

const styles = StyleSheet.create({
  container:  { flex: 1, backgroundColor: '#F5F5F5' },
  center:     { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 32 },
  filterBtns: { margin: 12 },
  list:       { padding: 12, paddingBottom: 80 },
  card:       { marginBottom: 10, borderRadius: 10 },
  row:        { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  meta:       { opacity: 0.65, marginBottom: 2 },
  fab:        { position: 'absolute', right: 16, bottom: 16, backgroundColor: '#2c3e50' },
});
