import React, { useEffect, useState, useCallback } from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import {
  Text,
  Card,
  Chip,
  Divider,
  ActivityIndicator,
  Button,
  IconButton,
  Dialog,
  Portal,
  TextInput,
  Snackbar,
  Banner,
  useTheme,
  Menu,
} from 'react-native-paper';
import NetInfo from '@react-native-community/netinfo';
import { apiOrderDetail, apiCancelOrder, apiCancelOrderItem, apiTransferTable } from '../../api/orders';
import { apiTables } from '../../api/tables';
import { getOrderById } from '../../database/operations';
import { useCurrency } from '../../hooks/useCurrency';
import { useAuthStore } from '../../store/useAuthStore';
import { printReceipt } from '../../utils/printer';

const STATUS_COLORS = {
  pending:   '#FFA000',
  confirmed: '#2c3e50',
  preparing: '#6A1B9A',
  ready:     '#2E7D32',
  served:    '#00796B',
  cancelled: '#B71C1C',
};

const PAYMENT_COLORS = {
  unpaid:          '#E65100',
  partial:         '#F9A825',
  paid:            '#2E7D32',
  fully_refunded:  '#616161',
};

export default function OrderDetailScreen({ route, navigation }) {
  const { orderId } = route.params;
  const theme = useTheme();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [isOffline, setIsOffline] = useState(false);
  const [cancelDialog, setCancelDialog] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const [snack, setSnack] = useState('');
  const [cancelItemDialog, setCancelItemDialog] = useState(false);
  const [cancelItemTarget, setCancelItemTarget] = useState(null); // {id, product_name}
  const [cancelItemReason, setCancelItemReason] = useState('');
  const [cancellingItem, setCancellingItem] = useState(false);

  // 3-dots action menu
  const [menuOpen, setMenuOpen]                     = useState(false);
  // Transfer dialog
  const [transferDialog, setTransferDialog]         = useState(false);
  const [tables, setTables]                         = useState([]);
  const [targetTable, setTargetTable]               = useState(null);
  const [tableMenuVisible, setTableMenuVisible]     = useState(false);
  const [transferring, setTransferring]             = useState(false);

  const { format } = useCurrency();
  const { user } = useAuthStore();

  const fetchOrder = useCallback(async () => {
    try {
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        const cached = await getOrderById(orderId);
        if (cached) {
          setOrder(cached);
          setIsOffline(true);
        } else {
          setError('Order not available offline.');
        }
        return;
      }
      const data = await apiOrderDetail(orderId);
      setOrder(data);
      setIsOffline(false);
    } catch {
      // Network error — try SQLite cache before giving up
      try {
        const cached = await getOrderById(orderId);
        if (cached) {
          setOrder(cached);
          setIsOffline(true);
        } else {
          setError('Could not load order.');
        }
      } catch {
        setError('Could not load order.');
      }
    } finally {
      setLoading(false);
    }
  }, [orderId]);

  useEffect(() => { fetchOrder(); }, [fetchOrder]);

  const openCancelItem = (item) => {
    setCancelItemTarget(item);
    setCancelItemReason('');
    setCancelItemDialog(true);
  };

  const handleCancelItem = async () => {
    if (!cancelItemTarget) return;
    const net = await NetInfo.fetch();
    if (!net.isConnected) { setSnack('No internet — connect to remove item'); setCancelItemDialog(false); return; }
    setCancellingItem(true);
    try {
      const res = await apiCancelOrderItem(cancelItemTarget.id, cancelItemReason);
      setCancelItemDialog(false);
      setSnack(res.message || `"${cancelItemTarget.product_name}" removed`);
      fetchOrder();
    } catch (err) {
      setSnack(err.response?.data?.error || 'Could not cancel item');
    } finally {
      setCancellingItem(false);
    }
  };

  const handleCancel = async () => {
    const net = await NetInfo.fetch();
    if (!net.isConnected) { setSnack('No internet — connect to cancel order'); setCancelDialog(false); return; }
    setCancelling(true);
    try {
      await apiCancelOrder(orderId, cancelReason || 'Cancelled by customer care');
      setCancelDialog(false);
      setSnack('Order cancelled');
      fetchOrder();
    } catch (err) {
      setSnack(err.response?.data?.error || 'Could not cancel order');
    } finally {
      setCancelling(false);
    }
  };

  // ── Print bill ─────────────────────────────────────────────────────────────
  const handlePrintBill = async () => {
    const staffName = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || '';
    try {
      const ok = await printReceipt({
        orderId: isOffline ? undefined : orderId,
        order,
        restaurantName: user?.restaurant_name || 'Restaurant',
        currencySymbol: '',
        staffName,
      });
      if (ok) setSnack('Bill sent to printer');
    } catch (err) {
      setSnack('Print failed: ' + (err.message || 'unknown error'));
    }
  };

  // ── Transfer table ─────────────────────────────────────────────────────────
  const openTransfer = async () => {
    setTransferDialog(true);
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
    if (!targetTable) return;
    const net = await NetInfo.fetch();
    if (!net.isConnected) { setSnack('No internet — connect to transfer table'); setTransferDialog(false); return; }
    setTransferring(true);
    try {
      await apiTransferTable(orderId, targetTable.id);
      setTransferDialog(false);
      setSnack('Table transferred');
      fetchOrder();
    } catch (err) {
      setSnack(err.response?.data?.detail || 'Transfer failed');
    } finally {
      setTransferring(false);
    }
  };

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }
  if (error || !order) {
    return <View style={styles.center}><Text>{error || 'Order not found'}</Text></View>;
  }

  const statusColor  = STATUS_COLORS[order.status]          || theme.colors.primary;
  const payColor     = PAYMENT_COLORS[order.payment_status] || theme.colors.primary;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      {/* Offline banner */}
      <Banner
        visible={isOffline}
        icon="wifi-off"
        actions={[]}
        style={{ backgroundColor: '#FFF8E1', marginHorizontal: -12, marginTop: -12, marginBottom: 12 }}
      >
        Offline – showing cached data. Cancel and Transfer require internet. Print works via Bluetooth.
      </Banner>

      {/* Header */}
      <Card style={styles.card}>
        <Card.Content>
          <View style={styles.headerRow}>
            <Text variant="headlineMedium">#{order.order_number || order.id}</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Text variant="bodySmall" style={styles.date}>
                {new Date(order.created_at).toLocaleString()}
              </Text>
              <Menu
                visible={menuOpen}
                onDismiss={() => setMenuOpen(false)}
                anchor={
                  <Button compact icon="dots-vertical" onPress={() => setMenuOpen(true)} />
                }
              >
                <Menu.Item leadingIcon="printer" title="Print Bill" onPress={() => { setMenuOpen(false); handlePrintBill(); }} />
                <Menu.Item leadingIcon="swap-horizontal" title="Transfer Table" onPress={() => { setMenuOpen(false); openTransfer(); }} disabled={order.payment_status === 'paid' || order.status === 'cancelled'} />
                <Divider />
                <Menu.Item leadingIcon="close-circle-outline" title="Cancel Order" titleStyle={{ color: '#E53935' }} onPress={() => { setMenuOpen(false); setCancelDialog(true); }} disabled={order.status === 'cancelled' || order.payment_status === 'paid'} />
              </Menu>
            </View>
          </View>
          <Text variant="bodyMedium" style={styles.tableLabel}>
            Table: {order.table_number}
          </Text>
          {order.ordered_by_name ? (
            <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
              By: {order.ordered_by_name}
            </Text>
          ) : null}
          <View style={styles.chipRow}>
            <Chip
              mode="flat"
              style={[styles.chip, { backgroundColor: statusColor + '22' }]}
              textStyle={{ color: statusColor, fontFamily: 'Poppins_700Bold', fontSize: 11 }}
            >
              {order.status.replace('_', ' ').toUpperCase()}
            </Chip>
            <Chip
              mode="flat"
              style={[styles.chip, { backgroundColor: payColor + '22' }]}
              textStyle={{ color: payColor, fontFamily: 'Poppins_700Bold', fontSize: 11 }}
            >
              {order.payment_status.replace('_', ' ').toUpperCase()}
            </Chip>
          </View>
        </Card.Content>
      </Card>

      {/* Items */}
      <Card style={styles.card}>
        <Card.Title title="Items" />
        <Card.Content>
          {order.items?.map((item, idx) => {
            const canCancelItem =
              !isOffline &&
              !['cancelled', 'served'].includes(order.status) &&
              order.payment_status !== 'paid' &&
              (order.items?.length ?? 0) > 1;
            return (
              <View key={item.id}>
                {idx > 0 && <Divider style={styles.divider} />}
                <View style={styles.itemRow}>
                  <View style={styles.itemName}>
                    <Text variant="bodyMedium">{item.product_name}</Text>
                    <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                      {item.quantity} × {format(item.unit_price)}
                    </Text>
                  </View>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Text variant="bodyMedium" style={styles.itemTotal}>
                      {format(item.total_price)}
                    </Text>
                    {canCancelItem && (
                      <IconButton
                        icon="close-circle-outline"
                        size={18}
                        iconColor="#C62828"
                        style={{ margin: 0, marginLeft: 4 }}
                        onPress={() => openCancelItem(item)}
                      />
                    )}
                  </View>
                </View>
              </View>
            );
          })}
        </Card.Content>
      </Card>

      {/* Totals */}
      <Card style={styles.card}>
        <Card.Content>
          <View style={styles.summaryRow}>
            <Text variant="bodyMedium">Subtotal</Text>
            <Text variant="bodyMedium">{format(order.subtotal ?? order.total_amount)}</Text>
          </View>
          {order.tax_amount > 0 && (
            <View style={styles.summaryRow}>
              <Text variant="bodyMedium">Tax</Text>
              <Text variant="bodyMedium">{format(order.tax_amount)}</Text>
            </View>
          )}
          <Divider style={styles.divider} />
          <View style={styles.summaryRow}>
            <Text variant="titleMedium">Total</Text>
            <Text variant="titleMedium">{format(order.total ?? order.total_amount)}</Text>
          </View>
          {order.total_paid > 0 && (
            <View style={styles.summaryRow}>
              <Text variant="bodyMedium" style={{ color: '#2E7D32' }}>Paid</Text>
              <Text variant="bodyMedium" style={{ color: '#2E7D32' }}>
                {format(order.total_paid)}
              </Text>
            </View>
          )}
          {order.balance_due > 0 && (
            <View style={styles.summaryRow}>
              <Text variant="bodyMedium" style={{ color: '#E65100', fontFamily: 'Poppins_700Bold' }}>
                Balance Due
              </Text>
              <Text variant="bodyMedium" style={{ color: '#E65100', fontFamily: 'Poppins_700Bold' }}>
                {format(order.balance_due)}
              </Text>
            </View>
          )}
        </Card.Content>
      </Card>

      {/* Special instructions */}
      {!!order.special_instructions && (
        <Card style={styles.card}>
          <Card.Title title="Notes" />
          <Card.Content>
            <Text variant="bodyMedium">{order.special_instructions}</Text>
          </Card.Content>
        </Card>
      )}

      {/* Payments / Receipt */}
      {order.payments?.length > 0 && (
        <Card style={styles.card}>
          <Card.Title title="Payments" />
          <Card.Content>
            {order.payments.map((p, idx) => (
              <View key={p.id}>
                {idx > 0 && <Divider style={styles.divider} />}
                <View style={styles.summaryRow}>
                  <Text variant="bodyMedium">
                    #{String(p.id).padStart(4, '0')} · {p.payment_method}
                  </Text>
                  <Button
                    compact
                    mode="outlined"
                    icon="receipt"
                    onPress={() => navigation.navigate('Receipt', { paymentId: p.id })}
                  >
                    View
                  </Button>
                </View>
                <Text variant="bodySmall" style={{ color: '#2E7D32' }}>
                  {format(p.amount)}
                </Text>
              </View>
            ))}
          </Card.Content>
        </Card>
      )}

      {/* Action buttons */}
      {order.status === 'pending' && !isOffline && (
        <Button
          mode="contained"
          icon="cancel"
          buttonColor="#C62828"
          onPress={() => setCancelDialog(true)}
          style={{ marginBottom: 8 }}
        >
          Cancel Order
        </Button>
      )}

      {/* Cancel item dialog */}
      <Portal>
        <Dialog visible={cancelItemDialog} onDismiss={() => setCancelItemDialog(false)}>
          <Dialog.Title>Remove Item</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium" style={{ marginBottom: 12 }}>
              Remove "{cancelItemTarget?.product_name}" from this order?
            </Text>
            <TextInput
              label="Reason (optional)"
              value={cancelItemReason}
              onChangeText={setCancelItemReason}
              mode="outlined"
              multiline
            />
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setCancelItemDialog(false)}>Back</Button>
            <Button
              mode="contained"
              buttonColor="#C62828"
              loading={cancellingItem}
              disabled={cancellingItem}
              onPress={handleCancelItem}
            >
              Remove
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      {/* Cancel order dialog */}
      <Portal>
        <Dialog visible={cancelDialog} onDismiss={() => setCancelDialog(false)}>
          <Dialog.Title>Cancel Order</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium" style={{ marginBottom: 12 }}>
              Are you sure you want to cancel order #{order.order_number}?
            </Text>
            <TextInput
              label="Reason (optional)"
              value={cancelReason}
              onChangeText={setCancelReason}
              mode="outlined"
              multiline
            />
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setCancelDialog(false)}>Back</Button>
            <Button
              mode="contained"
              buttonColor="#C62828"
              loading={cancelling}
              disabled={cancelling}
              onPress={handleCancel}
            >
              Cancel Order
            </Button>
          </Dialog.Actions>
        </Dialog>

        {/* Transfer Table Dialog */}
        <Dialog visible={transferDialog} onDismiss={() => setTransferDialog(false)}>
          <Dialog.Title>Transfer Table</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={{ marginBottom: 12, opacity: 0.7 }}>
              Move order #{order.order_number || order.id} from Table {order.table_number}
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
              {tables.map((t) => (
                <Menu.Item key={t.id} title={`Table ${t.table_number}`}
                  onPress={() => { setTargetTable(t); setTableMenuVisible(false); }} />
              ))}
              {tables.length === 0 && <Menu.Item title="No available tables" disabled />}
            </Menu>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setTransferDialog(false)}>Cancel</Button>
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

const styles = StyleSheet.create({
  container:  { padding: 12, paddingBottom: 32 },
  center:     { flex: 1, justifyContent: 'center', alignItems: 'center' },
  card:       { marginBottom: 12 },
  headerRow:  { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  date:       { color: '#888' },
  tableLabel: { marginBottom: 6 },
  chipRow:    { flexDirection: 'row', gap: 8, marginTop: 8 },
  chip:       { height: 28 },
  divider:    { marginVertical: 6 },
  itemRow:    { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', paddingVertical: 4 },
  itemName:   { flex: 1, marginRight: 8 },
  itemTotal:  { minWidth: 60, textAlign: 'right' },
  summaryRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3 },
});
