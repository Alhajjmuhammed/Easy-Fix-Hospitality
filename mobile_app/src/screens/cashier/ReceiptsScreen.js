import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { View, FlatList, StyleSheet, RefreshControl } from 'react-native';
import {
  Text, Card, Button, TextInput, Chip, ActivityIndicator,
  Snackbar, Divider, Banner, useTheme,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import { apiPayments, apiReprintReceipt, apiPaymentReceipt } from '../../api/payments';
import { useCurrency } from '../../hooks/useCurrency';
import { printReceipt } from '../../utils/printer';
import { useAuthStore } from '../../store/useAuthStore';
import { getAllOfflinePayments, getOrderById } from '../../database/operations';

const METHOD_LABELS = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher' };

export default function CashierReceiptsScreen() {
  const theme = useTheme();
  const { format } = useCurrency();
  const user = useAuthStore((s) => s.user);
  const mountedRef = useRef(true);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  const [payments,      setPayments]      = useState([]);
  const [loading,       setLoading]       = useState(true);
  const [search,        setSearch]        = useState('');
  const [snack,         setSnack]         = useState('');
  const [reprinting,      setReprinting]      = useState(null);
  const [localPrinting,   setLocalPrinting]   = useState(null);
  const [offlinePrinting, setOfflinePrinting] = useState(null);
  const [isOffline,     setIsOffline]     = useState(false);
  const [refreshing,    setRefreshing]    = useState(false);

  const fetchPayments = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!mountedRef.current) return;
      if (!net.isConnected) {
        setIsOffline(true);
        // Show locally queued payments so staff can see what's pending sync
        const offline = await getAllOfflinePayments();
        if (!mountedRef.current) return;
        setPayments(offline.map((p) => ({ ...p, _offline: true })));
        return;
      }
      setIsOffline(false);
      const today = new Date().toISOString().slice(0, 10);
      const data = await apiPayments({ date_from: today, date_to: today });
      if (!mountedRef.current) return;
      setPayments(Array.isArray(data) ? data : []);
    } catch {
      if (mountedRef.current) setSnack('Could not load receipts');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { fetchPayments(); }, [fetchPayments]);

  const handleReprint = async (paymentId) => {
    const net = await NetInfo.fetch();
    if (!mountedRef.current) return;
    if (!net.isConnected) { setSnack('No internet — connect to reprint'); return; }
    setReprinting(paymentId);
    try {
      await apiReprintReceipt(paymentId);
      if (!mountedRef.current) return;
      setSnack('Receipt sent to printer');
    } catch (err) {
      if (mountedRef.current) setSnack(err.response?.data?.error || 'Reprint failed');
    } finally {
      if (mountedRef.current) setReprinting(null);
    }
  };

  const handleLocalPrint = async (p) => {
    setLocalPrinting(p.id);
    try {
      const net = await NetInfo.fetch();
      if (!mountedRef.current) return;
      if (!net.isConnected) { setSnack('No internet — connect to print here'); return; }
      const receiptData = await apiPaymentReceipt(p.id);
      if (!mountedRef.current) return;
      const staffName = receiptData.payment?.processed_by_name
        || [user?.first_name, user?.last_name].filter(Boolean).join(' ')
        || user?.username || '';
      await printReceipt({
        orderId:        receiptData.order?.id,
        order:          receiptData.order,
        payment:        receiptData.payment,
        restaurantName: user?.restaurant_name || '',
        currencySymbol: user?.currency_symbol || '',
        staffName,
      });
      if (!mountedRef.current) return;
      setSnack('Receipt sent to printer');
    } catch (err) {
      if (mountedRef.current) setSnack('Print failed: ' + (err?.message || 'Unknown error'));
    } finally {
      if (mountedRef.current) setLocalPrinting(null);
    }
  };

  const handleOfflinePrint = async (p) => {
    setOfflinePrinting(p.offline_id);
    try {
      let order = p.order_id ? await getOrderById(p.order_id) : null;
      if (!mountedRef.current) return;
      if (!order) {
        order = {
          id: p.order_id || null,
          order_number: p.order_number || '',
          table_number: p.table_number || null,
          items: [],
        };
      }
      const payment = {
        id: null,
        amount: p.amount,
        payment_method: p.payment_method,
        reference_number: p.reference_number || '',
        created_at: p.created_at,
      };
      const staffName = [user?.first_name, user?.last_name].filter(Boolean).join(' ')
        || user?.username || '';
      await printReceipt({
        order,
        payment,
        restaurantName: user?.restaurant_name || '',
        currencySymbol: user?.currency_symbol || '',
        staffName,
      });
      if (!mountedRef.current) return;
      setSnack('Receipt sent to printer');
    } catch (err) {
      if (mountedRef.current) setSnack('Print failed: ' + (err?.message || 'Unknown error'));
    } finally {
      if (mountedRef.current) setOfflinePrinting(null);
    }
  };

  const filtered = useMemo(
    () => payments.filter((p) => {
      if (!search.trim()) return true;
      const s = search.toLowerCase();
      return (
        String(p.id || p.offline_id || '').toLowerCase().includes(s) ||
        String(p.order_number || '').toLowerCase().includes(s) ||
        String(p.order_id || '').includes(s)
      );
    }),
    [payments, search]
  );

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.background }]}>
      <Banner
        visible={isOffline}
        icon="wifi-off"
        actions={[]}
        style={{ backgroundColor: '#FFF8E1' }}
      >
        Offline – showing locally queued payments. Connect to view full receipt history.
      </Banner>
      <TextInput
        placeholder="Search by receipt # or order #..."
        value={search}
        onChangeText={setSearch}
        mode="outlined"
        left={<TextInput.Icon icon="magnify" />}
        right={search ? <TextInput.Icon icon="close" onPress={() => setSearch('')} /> : null}
        style={styles.search}
        dense
      />

      <FlatList
        data={filtered}
        keyExtractor={(p) => p._offline ? `off-${p.offline_id}` : String(p.id)}
        removeClippedSubviews
        maxToRenderPerBatch={10}
        windowSize={7}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); fetchPayments(true).finally(() => { if (mountedRef.current) setRefreshing(false); }); }}
          />
        }
        ListEmptyComponent={() => (
          <View style={styles.center}>
            <MaterialCommunityIcons name="receipt-text-outline" size={48} color="#ccc" />
            <Text variant="bodyLarge" style={{ opacity: 0.4, marginTop: 8 }}>No receipts found</Text>
          </View>
        )}
        ItemSeparatorComponent={() => <Divider />}
        renderItem={({ item: p }) => (
          <Card style={styles.card}>
            <Card.Content>
              <View style={styles.row}>
                <Text variant="titleSmall" style={{ fontFamily: 'Poppins_700Bold' }}>
                  {p._offline ? `Offline #${p.offline_id?.slice(-6)}` : `Receipt #${p.id}`}
                </Text>
                <View style={{ flexDirection: 'row', gap: 4 }}>
                  {p._offline && (
                    <Chip mode="flat" compact
                      style={{ backgroundColor: p.sync_status === 'error' ? '#FFEBEE' : '#FFF8E1' }}
                      textStyle={{ color: p.sync_status === 'error' ? '#C62828' : '#E65100', fontSize: 11 }}>
                      {p.sync_status === 'synced' ? 'Synced' : p.sync_status === 'error' ? 'Error' : 'Pending'}
                    </Chip>
                  )}
                  <Chip mode="flat" compact
                    style={{ backgroundColor: '#E8F5E9' }}
                    textStyle={{ color: '#2E7D32', fontSize: 11 }}>
                    {METHOD_LABELS[p.payment_method] || p.payment_method}
                  </Chip>
                </View>
              </View>
              <Text variant="bodySmall" style={styles.meta}>
                Order #{p.order_number || p.order_id}{p.table_number != null ? ` · Table ${p.table_number}` : ''}
              </Text>
              <Text variant="bodySmall" style={styles.meta}>
                {new Date(p.created_at).toLocaleString()}
              </Text>
              <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_700Bold', marginTop: 4 }}>
                {format(p.amount)}
              </Text>
            </Card.Content>
            {p._offline ? (
              <Card.Actions>
                <Button
                  mode="text"
                  compact
                  icon="printer-wireless"
                  loading={offlinePrinting === p.offline_id}
                  disabled={offlinePrinting === p.offline_id}
                  onPress={() => handleOfflinePrint(p)}
                >
                  Print Local
                </Button>
              </Card.Actions>
            ) : (
              <Card.Actions>
                <Button
                  mode="outlined"
                  compact
                  icon="printer"
                  loading={reprinting === p.id}
                  disabled={reprinting === p.id || localPrinting === p.id}
                  onPress={() => handleReprint(p.id)}
                >
                  Reprint
                </Button>
                <Button
                  mode="text"
                  compact
                  icon="printer-wireless"
                  loading={localPrinting === p.id}
                  disabled={reprinting === p.id || localPrinting === p.id}
                  onPress={() => handleLocalPrint(p)}
                >
                  Print Here
                </Button>
              </Card.Actions>
            )}
          </Card>
        )}
      />

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {snack}
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  center:    { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 32 },
  search:    { margin: 12 },
  list:      { padding: 12, paddingBottom: 32 },
  card:      { marginBottom: 8, borderRadius: 10 },
  row:       { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  meta:      { opacity: 0.65, marginBottom: 1 },
});
