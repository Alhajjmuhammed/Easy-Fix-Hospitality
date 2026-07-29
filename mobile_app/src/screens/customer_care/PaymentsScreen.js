import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import {
  Text,
  Card,
  Button,
  IconButton,
  TextInput,
  Dialog,
  Portal,
  Chip,
  Menu,
  ActivityIndicator,
  Snackbar,
  useTheme,
  SegmentedButtons,
  Divider,
  TouchableRipple,
  Banner,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import { apiOrders, apiPrintBill, apiTransferTable } from '../../api/orders';
import { apiProcessPayment } from '../../api/payments';
import { apiTables } from '../../api/tables';
import { useCurrency } from '../../hooks/useCurrency';
import { saveOfflinePayment, getOrders } from '../../database/operations';
import { useSyncStore } from '../../store/useSyncStore';

const PAYMENT_METHODS = [
  { value: 'cash',    label: 'Cash' },
  { value: 'card',    label: 'Card' },
  { value: 'digital', label: 'Digital' },
];

const STATUS_FILTER_OPTIONS = [
  { value: '',        label: 'All' },
  { value: 'unpaid',  label: 'Unpaid' },
  { value: 'partial', label: 'Partial' },
  { value: 'paid',    label: 'Paid' },
];

const PAYMENT_STATUS_COLOR = {
  unpaid:  '#C62828',
  partial: '#FF8F00',
  paid:    '#2E7D32',
};

const ORDER_STATUS_COLOR = {
  pending:   '#FF8F00',
  confirmed: '#2c3e50',
  preparing: '#6A1B9A',
  ready:     '#2E7D32',
  served:    '#2E7D32',
  cancelled: '#C62828',
};

export default function CCPaymentsScreen({ navigation }) {
  const theme = useTheme();
  const { format } = useCurrency();
  const [orders, setOrders]         = useState([]);
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [tableFilter, setTableFilter]   = useState('');   // '' = all
  const [tableMenuOpen, setTableMenuOpen] = useState(false);
  const [allTables, setAllTables]         = useState([]);

  // Payment dialog
  const [payDialog, setPayDialog] = useState(null);
  const [amount, setAmount]       = useState('');
  const [method, setMethod]       = useState('cash');
  const [reference, setReference] = useState('');
  const [notes, setNotes]         = useState('');
  const [paying, setPaying]       = useState(false);

  // Transfer dialog
  const [transferDialog, setTransferDialog] = useState(null); // order
  const [tables, setTables]                 = useState([]);
  const [selectedTableId, setSelectedTableId] = useState('');
  const [transferring, setTransferring]     = useState(false);

  // Per-card action menu
  const [menuOpenId, setMenuOpenId] = useState(null);

  const [snack, setSnack] = useState('');
  const [isOffline, setIsOffline] = useState(false);

  const fetchOrders = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        const cached = await getOrders(null);
        const filtered = statusFilter
          ? cached.filter((o) => o.payment_status === statusFilter)
          : cached;
        setOrders(filtered);
        setIsOffline(true);
        return;
      }
      const params = { period: 'today' };
      if (statusFilter) params.payment_status = statusFilter;
      const data = await apiOrders(params);
      setOrders(Array.isArray(data) ? data : []);
      setIsOffline(false);
    } catch {
      setSnack('Could not load orders');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [statusFilter]);

  // Re-fetch every time this tab comes into focus (covers switching tabs after placing an order)
  useFocusEffect(
    useCallback(() => {
      fetchOrders();
    }, [fetchOrders])
  );

  // Load table list once for the dropdown filter
  useEffect(() => {
    apiTables().then((data) => setAllTables(Array.isArray(data) ? data : [])).catch(() => {});
  }, []);

  // â”€â”€ Payment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const openPayment = (order) => {
    setPayDialog(order);
    setAmount(String(order.balance_due > 0 ? order.balance_due.toFixed(2) : order.total?.toFixed(2) ?? ''));
    setMethod('cash');
    setReference('');
    setNotes('');
  };

  const handlePayment = async () => {
    if (!payDialog || !amount) return;
    const parsedAmount = parseFloat(amount);
    if (isNaN(parsedAmount) || parsedAmount <= 0) { setSnack('Enter a valid amount'); return; }
    setPaying(true);
    try {
      const netState = await NetInfo.fetch();
      if (!netState.isConnected) {
        // Save offline — will sync automatically when internet restores
        await saveOfflinePayment({
          order_id:         payDialog.id,
          order_number:     payDialog.order_number,
          amount:           parsedAmount,
          payment_method:   method,
          reference_number: reference.trim(),
          notes:            notes.trim(),
        });
        await useSyncStore.getState().refreshPendingCount();
        // Update local state so the Pay button reflects this offline payment
        // and staff cannot accidentally pay the same order twice offline
        setOrders((prev) =>
          prev.map((o) => {
            if (o.id !== payDialog.id) return o;
            const newPaid   = (o.total_paid   ?? 0) + parsedAmount;
            const newDue    = Math.max(0, (o.balance_due ?? o.total ?? 0) - parsedAmount);
            const newStatus = newDue <= 0 ? 'paid' : newPaid > 0 ? 'partial' : o.payment_status;
            return { ...o, total_paid: newPaid, balance_due: newDue, payment_status: newStatus };
          })
        );
        setPayDialog(null);
        setSnack('No internet — payment saved offline and will sync automatically');
        return;
      }
      await apiProcessPayment({
        order_id:         payDialog.id,
        amount:           parsedAmount,
        payment_method:   method,
        reference_number: reference.trim(),
        notes:            notes.trim(),
      });
      setPayDialog(null);
      setSnack('Payment recorded successfully');
      fetchOrders(true);
    } catch (err) {
      setSnack(
        err.response?.data?.error ||
        err.response?.data?.detail ||
        err.response?.data?.amount?.[0] ||
        'Payment failed'
      );
    } finally {
      setPaying(false);
    }
  };

  // â”€â”€ Print Bill â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const handlePrintBill = async (order) => {
    const netState = await NetInfo.fetch();
    if (!netState.isConnected) {
      setSnack('No internet — connect to Wi-Fi or mobile data to print the bill');
      return;
    }
    try {
      const res = await apiPrintBill(order.id);
      setSnack(res.message || 'Bill sent to printer');
    } catch (err) {
      setSnack(
        err.response?.data?.error ||
        err.response?.data?.message ||
        'Bill print failed'
      );
    }
  };

  // â”€â”€ Transfer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const openTransfer = async (order) => {
    setTransferDialog(order);
    setSelectedTableId('');
    try {
      const data = await apiTables();
      setTables(Array.isArray(data) ? data : []);
    } catch {
      setSnack('Could not load tables');
    }
  };

  const handleTransfer = async () => {
    if (!selectedTableId) { setSnack('Please select a destination table'); return; }
    setTransferring(true);
    try {
      const res = await apiTransferTable(transferDialog.id, parseInt(selectedTableId));
      setTransferDialog(null);
      setSnack(res.message || 'Order transferred');
      fetchOrders(true);
    } catch (err) {
      setSnack(err.response?.data?.error || 'Transfer failed');
    } finally {
      setTransferring(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const filteredOrders = tableFilter
    ? orders.filter((o) => String(o.table_number) === String(tableFilter))
    : orders;

  return (
    <View style={styles.container}>
      <Banner
        visible={isOffline}
        icon="wifi-off"
        actions={[]}
        style={{ backgroundColor: '#FFF8E1', marginHorizontal: -16, marginTop: -16, marginBottom: 8 }}
      >
        Offline – showing cached orders. Payments saved offline will sync when connected.
      </Banner>
      {/* Filters */}
      <View style={styles.filterBox}>
        <Menu
          visible={tableMenuOpen}
          onDismiss={() => setTableMenuOpen(false)}
          contentStyle={styles.menuContent}
          anchor={
            <TouchableRipple
              onPress={() => setTableMenuOpen(true)}
              borderless
              style={styles.dropdownBtn}
            >
              <View style={styles.dropdownInner}>
                <MaterialCommunityIcons
                  name="table-chair"
                  size={18}
                  color={tableFilter ? '#2c3e50' : '#666'}
                  style={{ marginRight: 8 }}
                />
                <Text
                  variant="bodyMedium"
                  style={[styles.dropdownLabel, tableFilter && { color: '#2c3e50', fontFamily: 'Poppins_600SemiBold' }]}
                >
                  {tableFilter ? `Table ${tableFilter}` : 'All Tables'}
                </Text>
                <View style={{ flex: 1 }} />
                {tableFilter ? (
                  <TouchableOpacity
                    hitSlop={8}
                    onPress={() => setTableFilter('')}
                  >
                    <MaterialCommunityIcons name="close-circle" size={18} color="#2c3e50" />
                  </TouchableOpacity>
                ) : (
                  <MaterialCommunityIcons name="chevron-down" size={20} color="#666" />
                )}
              </View>
            </TouchableRipple>
          }
        >
          <Menu.Item
            title="All Tables"
            leadingIcon={!tableFilter ? 'check' : 'table-furniture'}
            onPress={() => { setTableFilter(''); setTableMenuOpen(false); }}
            titleStyle={!tableFilter ? { color: '#2c3e50', fontFamily: 'Poppins_700Bold' } : undefined}
          />
          <Divider />
          {allTables.map((t) => {
            const active = String(tableFilter) === String(t.table_number);
            return (
              <Menu.Item
                key={t.id}
                title={`Table ${t.table_number}`}
                leadingIcon={active ? 'check' : (t.is_available ? 'circle-outline' : 'circle')}
                onPress={() => { setTableFilter(String(t.table_number)); setTableMenuOpen(false); }}
                titleStyle={[
                  active && { color: '#2c3e50', fontFamily: 'Poppins_700Bold' },
                  !t.is_available && !active && { color: '#FF8F00' },
                ]}
              />
            );
          })}
        </Menu>
        <View style={styles.statusChips}>
          {STATUS_FILTER_OPTIONS.map((opt) => (
            <Chip
              key={opt.value}
              mode={statusFilter === opt.value ? 'flat' : 'outlined'}
              selected={statusFilter === opt.value}
              onPress={() => setStatusFilter(opt.value)}
              compact
              style={styles.filterChip}
            >
              {opt.label}
            </Chip>
          ))}
        </View>
        <Text variant="bodySmall" style={styles.countLabel}>
          {filteredOrders.length} order{filteredOrders.length !== 1 ? 's' : ''}
        </Text>
      </View>

      <Divider />

      <FlatList
        data={filteredOrders}
        keyExtractor={(o) => String(o.id)}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); fetchOrders(true); }}
          />
        }
        ListEmptyComponent={() => (
          <View style={styles.empty}>
            <Text variant="bodyLarge" style={{ opacity: 0.5 }}>No orders found</Text>
          </View>
        )}
        renderItem={({ item: order }) => {
          const isCancelled = order.status === 'cancelled';
          const isPaid = order.payment_status === 'paid';
          const borderColor = isCancelled ? '#9E9E9E' : (PAYMENT_STATUS_COLOR[order.payment_status] || '#ccc');
          const isMenuOpen = menuOpenId === order.id;
          return (
          <Card style={[styles.card, { borderLeftColor: borderColor, opacity: isCancelled ? 0.7 : 1 }]}>
            <Card.Content>
              {/* Order # + payment badge + 3-dots menu */}
              <View style={styles.row}>
                <Text variant="titleSmall" style={{ fontFamily: 'Poppins_700Bold', textDecorationLine: isCancelled ? 'line-through' : 'none', color: isCancelled ? '#9E9E9E' : undefined }}>
                  {order.order_number}
                </Text>
                <View style={styles.badgeRow}>
                  <Chip
                    mode="flat" compact
                    style={{ backgroundColor: (PAYMENT_STATUS_COLOR[order.payment_status] || '#666') + '22' }}
                    textStyle={{ fontSize: 10, color: PAYMENT_STATUS_COLOR[order.payment_status] || '#666', fontFamily: 'Poppins_700Bold' }}
                  >
                    {order.payment_status?.toUpperCase() || 'UNPAID'}
                  </Chip>
                  <Chip
                    mode="flat" compact
                    style={{ backgroundColor: (ORDER_STATUS_COLOR[order.status] || '#666') + '22', marginLeft: 4 }}
                    textStyle={{ fontSize: 10, color: ORDER_STATUS_COLOR[order.status] || '#666' }}
                  >
                    {order.status?.toUpperCase()}
                  </Chip>
                  <Menu
                    visible={isMenuOpen}
                    onDismiss={() => setMenuOpenId(null)}
                    anchor={
                      <Button compact icon="dots-vertical" onPress={() => setMenuOpenId(isMenuOpen ? null : order.id)} />
                    }
                  >
                    {!isCancelled && !isPaid && (
                      <Menu.Item leadingIcon="cash" title="Pay" onPress={() => { setMenuOpenId(null); openPayment(order); }} />
                    )}
                    <Menu.Item leadingIcon="printer" title="Print Bill" onPress={() => { setMenuOpenId(null); handlePrintBill(order); }} />
                    {!isCancelled && !isPaid && (
                      <Menu.Item leadingIcon="swap-horizontal" title="Transfer Table" onPress={() => { setMenuOpenId(null); openTransfer(order); }} />
                    )}
                  </Menu>
                </View>
              </View>

              {/* Table Â· items */}
              <Text variant="bodySmall" style={styles.meta}>
                Table {order.table_number} Â· {order.items_count} item{order.items_count !== 1 ? 's' : ''}
                {order.created_at ? `  Â·  ${new Date(order.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
              </Text>

              {/* Amounts */}
              <View style={styles.amountRow}>
                <Text variant="bodySmall">Total: <Text style={{ fontFamily: 'Poppins_700Bold' }}>{format(order.total)}</Text></Text>
                <Text variant="bodySmall">Paid: <Text style={{ color: '#2E7D32', fontFamily: 'Poppins_700Bold' }}>{format(order.total_paid ?? 0)}</Text></Text>
                <Text variant="bodySmall">Due: <Text style={{ color: '#C62828', fontFamily: 'Poppins_700Bold' }}>{format(order.balance_due ?? order.total ?? 0)}</Text></Text>
              </View>
            </Card.Content>

            {/* View button — only visible action; Pay/Print/Transfer are in the 3-dots menu */}
            <Card.Actions style={styles.actions}>
              <Button
                compact
                mode="outlined"
                icon="eye"
                onPress={() => navigation.navigate('OrderDetail', { orderId: order.id })}
              >
                View
              </Button>
            </Card.Actions>
          </Card>
          );
        }}
      />

      <Portal>
        {/* â”€â”€ Payment Dialog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <Dialog visible={!!payDialog} onDismiss={() => !paying && setPayDialog(null)}>
          <Dialog.Title>Process Payment</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={styles.dialogMeta}>
              {payDialog?.order_number} Â· Table {payDialog?.table_number}
            </Text>
            <Text variant="bodySmall" style={[styles.dialogMeta, { marginBottom: 12 }]}>
              Balance due:{' '}
              <Text style={{ fontFamily: 'Poppins_700Bold', color: '#C62828' }}>
                {format(payDialog?.balance_due)}
              </Text>
            </Text>
            <TextInput label="Amount" value={amount} onChangeText={setAmount}
              keyboardType="decimal-pad" mode="outlined" style={styles.dialogInput} />
            <Text variant="labelMedium" style={styles.methodLabel}>Payment method</Text>
            <SegmentedButtons value={method} onValueChange={setMethod}
              buttons={PAYMENT_METHODS} style={styles.segmented} />
            {method !== 'cash' && (
              <TextInput label="Reference / Approval code" value={reference}
                onChangeText={setReference} mode="outlined" style={styles.dialogInput} />
            )}
            <TextInput label="Notes (optional)" value={notes} onChangeText={setNotes}
              mode="outlined" multiline numberOfLines={2} style={styles.dialogInput} />
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setPayDialog(null)} disabled={paying}>Cancel</Button>
            <Button mode="contained" onPress={handlePayment} loading={paying} disabled={paying}>
              Confirm Payment
            </Button>
          </Dialog.Actions>
        </Dialog>

        {/* â”€â”€ Transfer Dialog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <Dialog visible={!!transferDialog} onDismiss={() => !transferring && setTransferDialog(null)}>
          <Dialog.Title>Transfer to Another Table</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={[styles.dialogMeta, { marginBottom: 12 }]}>
              Moving {transferDialog?.order_number} from Table {transferDialog?.table_number}
            </Text>
            {tables.length === 0 ? (
              <ActivityIndicator />
            ) : (
              <>
                <Text variant="labelMedium" style={styles.methodLabel}>Select destination table:</Text>
                <View style={styles.tableGrid}>
                  {tables
                    .filter((t) => String(t.id) !== String(transferDialog?.table_info))
                    .map((t) => (
                      <Chip
                        key={t.id}
                        mode={selectedTableId === String(t.id) ? 'flat' : 'outlined'}
                        selected={selectedTableId === String(t.id)}
                        onPress={() => setSelectedTableId(String(t.id))}
                        style={[
                          styles.tableChip,
                          !t.is_available && { borderColor: '#FF8F00' },
                        ]}
                        textStyle={!t.is_available ? { color: '#FF8F00' } : undefined}
                      >
                        {t.table_number || `Table ${t.table_number}`}
                        {!t.is_available ? ' â—' : ''}
                      </Chip>
                    ))}
                </View>
                {selectedTableId && !tables.find((t) => String(t.id) === selectedTableId)?.is_available && (
                  <Text variant="bodySmall" style={{ color: '#FF8F00', marginTop: 8 }}>
                    âš  This table is occupied. Order will still be transferred.
                  </Text>
                )}
              </>
            )}
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setTransferDialog(null)} disabled={transferring}>Cancel</Button>
            <Button mode="contained" onPress={handleTransfer} loading={transferring}
              disabled={transferring || !selectedTableId} buttonColor="#FF8F00">
              Transfer
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {snack}
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container:    { flex: 1, backgroundColor: '#f5f5f5' },
  center:       { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  empty:        { flex: 1, alignItems: 'center', paddingTop: 60 },
  filterBox:    { padding: 12, backgroundColor: '#fff' },
  dropdownBtn:  {
    borderWidth: 1.5,
    borderColor: '#E0E0E0',
    borderRadius: 10,
    backgroundColor: '#FAFAFA',
    marginBottom: 10,
    overflow: 'hidden',
  },
  dropdownInner: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  dropdownLabel:  { fontSize: 14, color: '#444' },
  menuContent:    { borderRadius: 12, marginTop: -4 },
  segmented:    { marginBottom: 8 },
  statusChips:  { flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginBottom: 6 },
  filterChip:   { marginRight: 4 },
  countLabel:   { opacity: 0.6, marginTop: 2 },
  list:         { padding: 12, paddingBottom: 40 },
  card:         { marginBottom: 10, borderRadius: 10, borderLeftWidth: 4 },
  row:          { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  badgeRow:     { flexDirection: 'row', alignItems: 'center' },
  amountRow:    { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6, flexWrap: 'wrap' },
  meta:         { opacity: 0.65, marginBottom: 4 },
  actions:      { flexDirection: 'row', paddingHorizontal: 4, paddingBottom: 4, gap: 0 },
  iconBtn:      { margin: 2 },
  dialogMeta:   { opacity: 0.7, marginBottom: 4 },
  dialogInput:  { marginBottom: 10 },
  methodLabel:  { marginBottom: 6, opacity: 0.7 },
  tableGrid:    { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  tableChip:    { marginBottom: 4 },
});

