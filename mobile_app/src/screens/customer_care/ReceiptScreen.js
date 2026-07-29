import React, { useEffect, useState, useCallback } from 'react';
import { View, ScrollView, StyleSheet } from 'react-native';
import {
  Text,
  Card,
  Divider,
  ActivityIndicator,
  Button,
  Snackbar,
  Banner,
  Chip,
  useTheme,
} from 'react-native-paper';
import NetInfo from '@react-native-community/netinfo';
import { apiPaymentReceipt, apiReprintReceipt } from '../../api/payments';
import { useCurrency } from '../../hooks/useCurrency';
import { printReceipt }     from '../../utils/printer';
import { useAuthStore }     from '../../store/useAuthStore';
import { usePrinterStore }  from '../../store/usePrinterStore';

const METHOD_LABEL = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher' };

export default function ReceiptScreen({ route }) {
  const { paymentId } = route.params;
  const theme = useTheme();
  const { format } = useCurrency();
  const user = useAuthStore((s) => s.user);
  const [loading, setLoading] = useState(true);
  const [reprinting, setReprinting] = useState(false);
  const [printing, setPrinting] = useState(false);
  const [snack, setSnack] = useState('');
  const [data, setData] = useState(null);
  const [isOffline, setIsOffline] = useState(false);

  const fetchReceipt = useCallback(async () => {
    try {
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        setIsOffline(true);
        return;
      }
      const result = await apiPaymentReceipt(paymentId);
      setData(result);
    } catch {
      setSnack('Could not load receipt');
    } finally {
      setLoading(false);
    }
  }, [paymentId]);

  useEffect(() => { fetchReceipt(); }, [fetchReceipt]);

  const handleReprint = async () => {
    setReprinting(true);
    try {
      await apiReprintReceipt(paymentId);
      setSnack('Receipt sent to printer');
    } catch (err) {
      setSnack(err.response?.data?.error || err.response?.data?.message || 'Reprint failed');
    } finally {
      setReprinting(false);
    }
  };

  const handleLocalPrint = async () => {
    if (!data) return;
    setPrinting(true);
    try {
      await printReceipt({
        orderId:        data.payment?.order_id ?? data.order?.id,
        order:          data.order,
        payment:        data.payment,
        restaurantName: user?.restaurant_name || '',
        currencySymbol: user?.currency_symbol || '',
      });
    } catch (err) {
      setSnack('Print failed: ' + (err?.message || 'Unknown error'));
    } finally {
      setPrinting(false);
    }
  };

  if (loading && !isOffline) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }
  if (isOffline) {
    return (
      <View style={styles.center}>
        <Banner visible icon="wifi-off" actions={[]} style={{ backgroundColor: '#FFF8E1', width: '100%' }}>
          Offline – connect to internet to view this receipt.
        </Banner>
      </View>
    );
  }
  if (!data) {
    return <View style={styles.center}><Text>Receipt not found</Text></View>;
  }

  const { payment, order, change_amount, remaining_balance } = data;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      {/* Header */}
      <Card style={styles.card}>
        <Card.Content>
          <Text variant="headlineMedium" style={styles.center}>Receipt</Text>
          <Text variant="bodySmall" style={[styles.centerText, { color: theme.colors.onSurfaceVariant }]}>
            #{String(payment.id).padStart(6, '0')}
          </Text>
          <Text variant="bodySmall" style={[styles.centerText, { color: theme.colors.onSurfaceVariant, marginBottom: 8 }]}>
            {new Date(payment.created_at).toLocaleString()}
          </Text>
          <View style={styles.rowBetween}>
            <Text variant="bodyMedium">Order</Text>
            <Text variant="bodyMedium" style={{ fontWeight: 'bold' }}>
              #{order.order_number}
            </Text>
          </View>
          <View style={styles.rowBetween}>
            <Text variant="bodyMedium">Table</Text>
            <Text variant="bodyMedium">{order.table_number}</Text>
          </View>
          <View style={styles.rowBetween}>
            <Text variant="bodyMedium">Payment Method</Text>
            <Chip compact style={{ height: 24 }}>
              {METHOD_LABEL[payment.payment_method] || payment.payment_method}
            </Chip>
          </View>
          {payment.reference_number ? (
            <View style={styles.rowBetween}>
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>Ref</Text>
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                {payment.reference_number}
              </Text>
            </View>
          ) : null}
        </Card.Content>
      </Card>

      {/* Items */}
      <Card style={styles.card}>
        <Card.Title title="Items" />
        <Card.Content>
          {order.items?.map((item, idx) => (
            <View key={item.id}>
              {idx > 0 && <Divider style={styles.divider} />}
              <View style={styles.rowBetween}>
                <View style={{ flex: 1, marginRight: 8 }}>
                  <Text variant="bodyMedium">{item.product_name}</Text>
                  <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                    {item.quantity} × {format(item.unit_price)}
                  </Text>
                </View>
                <Text variant="bodyMedium">{format(item.total_price)}</Text>
              </View>
            </View>
          ))}
        </Card.Content>
      </Card>

      {/* Totals */}
      <Card style={styles.card}>
        <Card.Content>
          <View style={styles.rowBetween}>
            <Text variant="bodyMedium">Order Total</Text>
            <Text variant="bodyMedium">{format(order.total ?? order.total_amount)}</Text>
          </View>
          <Divider style={styles.divider} />
          <View style={styles.rowBetween}>
            <Text variant="titleMedium">Amount Paid</Text>
            <Text variant="titleMedium" style={{ color: '#2E7D32', fontWeight: 'bold' }}>
              {format(payment.amount)}
            </Text>
          </View>
          {change_amount > 0 && (
            <View style={styles.rowBetween}>
              <Text variant="bodyMedium">Change</Text>
              <Text variant="bodyMedium">{format(change_amount)}</Text>
            </View>
          )}
          {remaining_balance > 0 && (
            <View style={styles.rowBetween}>
              <Text variant="bodyMedium" style={{ color: '#E65100', fontWeight: 'bold' }}>
                Remaining Balance
              </Text>
              <Text variant="bodyMedium" style={{ color: '#E65100', fontWeight: 'bold' }}>
                {format(remaining_balance)}
              </Text>
            </View>
          )}
          {payment.processed_by_name ? (
            <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant, marginTop: 8 }}>
              Processed by: {payment.processed_by_name}
            </Text>
          ) : null}
        </Card.Content>
      </Card>

      {/* Reprint */}
      <Button
        mode="contained"
        icon="printer"
        onPress={handleReprint}
        loading={reprinting}
        disabled={reprinting || printing}
        style={styles.reprintBtn}
      >
        Reprint (Send to Printer)
      </Button>

      <Button
        mode="outlined"
        icon="printer-wireless"
        onPress={handleLocalPrint}
        loading={printing}
        disabled={reprinting || printing}
        style={[styles.reprintBtn, { marginTop: 8 }]}
      >
        Smart Print (Uses Settings)
      </Button>

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {snack}
      </Snackbar>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container:   { padding: 12, paddingBottom: 32 },
  center:      { flex: 1, justifyContent: 'center', alignItems: 'center' },
  centerText:  { textAlign: 'center' },
  card:        { marginBottom: 12 },
  divider:     { marginVertical: 6 },
  rowBetween:  { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 3 },
  reprintBtn:  { marginTop: 4 },
});
