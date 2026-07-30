import React, { useEffect, useState, useCallback } from 'react';
import { View, FlatList, StyleSheet } from 'react-native';
import {
  Text, Card, Button, TextInput, Chip, ActivityIndicator,
  Snackbar, Divider, Banner,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import { apiPayments, apiReprintReceipt } from '../../api/payments';
import { useCurrency } from '../../hooks/useCurrency';
import { printReceipt } from '../../utils/printer';
import { useAuthStore } from '../../store/useAuthStore';

const METHOD_LABELS = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher' };

export default function CashierReceiptsScreen() {
  const { format } = useCurrency();
  const user = useAuthStore((s) => s.user);
  const [payments,      setPayments]      = useState([]);
  const [loading,       setLoading]       = useState(true);
  const [search,        setSearch]        = useState('');
  const [snack,         setSnack]         = useState('');
  const [reprinting,    setReprinting]    = useState(null);
  const [localPrinting, setLocalPrinting] = useState(null);
  const [isOffline,     setIsOffline]     = useState(false);

  const fetchPayments = useCallback(async () => {
    setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        setIsOffline(true);
        setPayments([]);
        return;
      }
      setIsOffline(false);
      const data = await apiPayments({ period: 'today' });
      setPayments(Array.isArray(data) ? data : []);
    } catch {
      setSnack('Could not load receipts');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchPayments(); }, [fetchPayments]);

  const handleReprint = async (paymentId) => {
    const net = await NetInfo.fetch();
    if (!net.isConnected) { setSnack('No internet — connect to reprint'); return; }
    setReprinting(paymentId);
    try {
      await apiReprintReceipt(paymentId);
      setSnack('Receipt sent to printer');
    } catch (err) {
      setSnack(err.response?.data?.error || 'Reprint failed');
    } finally {
      setReprinting(null);
    }
  };

  const handleLocalPrint = async (p) => {
    setLocalPrinting(p.id);
    try {
      // Build a minimal order object from the payment summary
      const orderObj = {
        order_number: p.order_number || p.order_id,
        table_number: p.table_number,
        created_at:   p.created_at,
        items:        p.items || [],
        subtotal:     p.subtotal || p.amount,
        total_amount: p.amount,
        total:        p.amount,
      };
      await printReceipt({
        orderId:        p.order_id,
        order:          orderObj,
        payment:        p,
        restaurantName: user?.restaurant_name || '',
        currencySymbol: user?.currency_symbol || '',
      });
    } catch (err) {
      setSnack('Print failed: ' + (err?.message || 'Unknown error'));
    } finally {
      setLocalPrinting(null);
    }
  };

  const filtered = payments.filter((p) => {
    if (!search.trim()) return true;
    const s = search.toLowerCase();
    return (
      String(p.id).includes(s) ||
      String(p.order_number || '').toLowerCase().includes(s) ||
      String(p.order_id || '').includes(s)
    );
  });

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
        Offline – receipts are not available without internet. Connect to view your receipts.
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
        keyExtractor={(p) => String(p.id)}
        contentContainerStyle={styles.list}
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
                  Receipt #{p.id}
                </Text>
                <Chip mode="flat" compact
                  style={{ backgroundColor: '#E8F5E9' }}
                  textStyle={{ color: '#2E7D32', fontSize: 11 }}>
                  {METHOD_LABELS[p.payment_method] || p.payment_method}
                </Chip>
              </View>
              <Text variant="bodySmall" style={styles.meta}>
                Order #{p.order_number || p.order_id} · Table {p.table_number}
              </Text>
              <Text variant="bodySmall" style={styles.meta}>
                {new Date(p.created_at).toLocaleString()}
              </Text>
              <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_700Bold', marginTop: 4 }}>
                {format(p.amount)}
              </Text>
            </Card.Content>
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
  container: { flex: 1, backgroundColor: '#F5F5F5' },
  center:    { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 32 },
  search:    { margin: 12 },
  list:      { padding: 12, paddingBottom: 32 },
  card:      { marginBottom: 8, borderRadius: 10 },
  row:       { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  meta:      { opacity: 0.65, marginBottom: 1 },
});
