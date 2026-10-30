import React, { useEffect, useState, useCallback, useRef } from 'react';
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
import { buildReceiptText, shareOnWhatsApp } from '../../utils/shareReceipt';
import { printReceipt }     from '../../utils/printer';
import { useAuthStore }     from '../../store/useAuthStore';
import { useT } from '../../i18n';
const METHOD_LABEL = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher' };

export default function ReceiptScreen({ route }) {
  const t = useT();
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

  const mountedRef = useRef(true);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

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
    const net = await NetInfo.fetch();
    if (!mountedRef.current) return;
    if (!net.isConnected) { setSnack('No internet — connect to reprint'); return; }
    setReprinting(true);
    try {
      await apiReprintReceipt(paymentId);
      if (mountedRef.current) setSnack('Receipt sent to printer');
    } catch (err) {
      if (mountedRef.current) setSnack(err.response?.data?.error || err.response?.data?.message || 'Reprint failed');
    } finally {
      if (mountedRef.current) setReprinting(false);
    }
  };

  const handleLocalPrint = async () => {
    if (!data) return;
    setPrinting(true);
    try {
      const staffName = data.payment?.processed_by_name
        || [user?.first_name, user?.last_name].filter(Boolean).join(' ')
        || user?.username || '';
      await printReceipt({
        orderId:        data.payment?.order_id ?? data.order?.id,
        order:          data.order,
        payment:        data.payment,
        restaurantName: user?.restaurant_name || '',
        currencySymbol: user?.currency_symbol || '',
        staffName,
      });
      if (mountedRef.current) setSnack('Receipt sent to printer');
    } catch (err) {
      if (mountedRef.current) setSnack(t('Print failed: {error}', { error: err?.message || t('Unknown error') }));
    } finally {
      if (mountedRef.current) setPrinting(false);
    }
  };

  if (loading && !isOffline) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }
  if (isOffline) {
    return (
      <View style={styles.center}>
        <Banner visible icon="wifi-off" actions={[]} style={{ backgroundColor: '#FFF8E1', width: '100%' }}>
          {t('Offline – connect to internet to view this receipt.')}
        </Banner>
      </View>
    );
  }
  if (!data) {
    return <View style={styles.center}><Text>{t('Receipt not found')}</Text></View>;
  }

  const { payment, order, change_amount, remaining_balance } = data;

  if (!payment || !order) {
    return (
      <View style={styles.center}>
        <Text style={{ fontFamily: 'Poppins_400Regular' }}>{t('Receipt data incomplete')}</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      {/* Header */}
      <Card style={styles.card}>
        <Card.Content>
          <Text variant="headlineMedium" style={styles.center}>{t('Receipt')}</Text>
          <Text variant="bodySmall" style={[styles.centerText, { color: theme.colors.onSurfaceVariant }]}>
            #{String(payment.id).padStart(6, '0')}
          </Text>
          <Text variant="bodySmall" style={[styles.centerText, { color: theme.colors.onSurfaceVariant, marginBottom: 8 }]}>
            {new Date(payment.created_at).toLocaleString()}
          </Text>
          <View style={styles.rowBetween}>
            <Text variant="bodyMedium">{t('Order Number')}</Text>
            <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_700Bold' }}>
              #{order.order_number}
            </Text>
          </View>
          <View style={styles.rowBetween}>
            <Text variant="bodyMedium">{t('Table')}</Text>
            <Text variant="bodyMedium">{order.table_number}</Text>
          </View>
          <View style={styles.rowBetween}>
            <Text variant="bodyMedium">{t('Payment Method')}</Text>
            <Chip compact style={{ height: 24 }}>
              {METHOD_LABEL[payment.payment_method] ? t(METHOD_LABEL[payment.payment_method]) : payment.payment_method}
            </Chip>
          </View>
          {payment.reference_number ? (
            <View style={styles.rowBetween}>
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{t('Reference')}</Text>
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                {payment.reference_number}
              </Text>
            </View>
          ) : null}
        </Card.Content>
      </Card>

      {/* Items */}
      <Card style={styles.card}>
        <Card.Title title={t('Items')} />
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
            <Text variant="bodyMedium">{t('Order Total')}</Text>
            <Text variant="bodyMedium">{format(order.total ?? order.total_amount)}</Text>
          </View>
          <Divider style={styles.divider} />
          <View style={styles.rowBetween}>
            <Text variant="titleMedium">{t('Amount Paid')}</Text>
            <Text variant="titleMedium" style={{ color: '#2E7D32', fontFamily: 'Poppins_700Bold' }}>
              {format(payment.amount)}
            </Text>
          </View>
          {change_amount > 0 && (
            <View style={styles.rowBetween}>
              <Text variant="bodyMedium">{t('Change')}</Text>
              <Text variant="bodyMedium">{format(change_amount)}</Text>
            </View>
          )}
          {remaining_balance > 0 && (
            <View style={styles.rowBetween}>
              <Text variant="bodyMedium" style={{ color: '#E65100', fontFamily: 'Poppins_700Bold' }}>
                {t('Remaining Balance')}
              </Text>
              <Text variant="bodyMedium" style={{ color: '#E65100', fontFamily: 'Poppins_700Bold' }}>
                {format(remaining_balance)}
              </Text>
            </View>
          )}
          {payment.processed_by_name ? (
            <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant, marginTop: 8 }}>
              {t('Processed by')}: {payment.processed_by_name}
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
        {t('Reprint (Send to Printer)')}
      </Button>

      <Button
        mode="outlined"
        icon="printer-wireless"
        onPress={handleLocalPrint}
        loading={printing}
        disabled={reprinting || printing}
        style={[styles.reprintBtn, { marginTop: 8 }]}
      >
        {t('Smart Print (Uses Settings)')}
      </Button>

      {data?.order && (
        <Button
          mode="outlined"
          icon="whatsapp"
          textColor="#25D366"
          onPress={() => shareOnWhatsApp(
            buildReceiptText(data.order, user?.restaurant_name, format), data.order.delivery_phone,
          ).catch(() => setSnack('WhatsApp is not available on this device'))}
          style={[styles.reprintBtn, { marginTop: 8 }]}
        >
          {t('Share on WhatsApp')}
        </Button>
      )}

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {t(snack)}
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
