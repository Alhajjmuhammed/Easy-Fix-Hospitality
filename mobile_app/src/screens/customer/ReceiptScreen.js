import React, { useEffect, useState } from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import {
  Text,
  Card,
  Divider,
  ActivityIndicator,
  Button,
  Banner,
  useTheme,
} from 'react-native-paper';
import { useNavigation } from '@react-navigation/native';
import NetInfo from '@react-native-community/netinfo';
import { apiOrderDetail } from '../../api/orders';
import { getOrderById } from '../../database/operations';
import { useAuthStore } from '../../store/useAuthStore';
import { printReceipt } from '../../utils/printer';

const PAYMENT_METHOD_LABELS = {
  cash:    'Cash',
  card:    'Card',
  digital: 'Digital',
  voucher: 'Voucher',
};

export default function ReceiptScreen({ route }) {
  const { orderId } = route.params;
  const theme = useTheme();
  const navigation = useNavigation();
  const user = useAuthStore((s) => s.user);

  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [printing, setPrinting] = useState(false);
  const [isOffline, setIsOffline] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const net = await NetInfo.fetch();
        if (!net.isConnected) {
          const cached = await getOrderById(orderId);
          if (cached) { setOrder(cached); setIsOffline(true); }
        } else {
          const data = await apiOrderDetail(orderId);
          setOrder(data);
        }
      } catch {
        try {
          const cached = await getOrderById(orderId);
          if (cached) { setOrder(cached); setIsOffline(true); }
        } catch {}
      } finally {
        setLoading(false);
      }
    })();
  }, [orderId]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (!order) {
    return (
      <View style={styles.center}>
        <Text style={{ fontFamily: 'Poppins_400Regular' }}>Receipt not available</Text>
        <Button onPress={() => navigation.goBack()} style={{ marginTop: 12 }}>
          Go Back
        </Button>
      </View>
    );
  }

  const P700 = 'Poppins_700Bold';
  const P600 = 'Poppins_600SemiBold';
  const P400 = 'Poppins_400Regular';

  const handleLocalPrint = async () => {
    setPrinting(true);
    try {
      await printReceipt({
        orderId:        order?.id,
        order,
        restaurantName: user?.restaurant_name || '',
        currencySymbol: user?.currency_symbol || '',
      });
    } catch (err) {
      // user cancelled or error — silently ignore cancel
    } finally {
      setPrinting(false);
    }
  };

  const fmt = (v) => {
    const n = parseFloat(v);
    return isNaN(n) ? '0.00' : n.toFixed(2);
  };

  const createdAt = order.created_at
    ? new Date(order.created_at).toLocaleString()
    : '';

  return (
    <ScrollView contentContainerStyle={styles.container}>

      {isOffline && (
        <Banner visible icon="wifi-off" actions={[]} style={{ backgroundColor: '#FFF8E1' }}>
          Offline – showing cached data. Connect to view live receipt details.
        </Banner>
      )}

      {/* ── Receipt header ── */}
      <View style={[styles.header, { backgroundColor: '#2c3e50' }]}>
        <Text variant="headlineSmall" style={[styles.headerTitle, { fontFamily: P700 }]}>
          Receipt
        </Text>
        <Text variant="bodyMedium" style={{ color: '#fff', fontFamily: P400 }}>
          {user?.restaurant_name || 'Restaurant'}
        </Text>
        <Text variant="bodySmall" style={{ color: '#ccc', fontFamily: P400, marginTop: 4 }}>
          Order #{order.order_number || order.id}
        </Text>
      </View>

      {/* ── Order Information ── */}
      <Card style={styles.card}>
        <Card.Content>
          <Text variant="labelLarge" style={styles.sectionLabel}>ORDER INFORMATION</Text>
          <View style={styles.infoRow}>
            <Text style={{ fontFamily: P600 }}>Order Number</Text>
            <Text style={{ fontFamily: P400 }}>#{order.order_number || order.id}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={{ fontFamily: P600 }}>
              {order.order_type === 'delivery' || order.order_type === 'pickup' ? 'Type' : 'Table'}
            </Text>
            <Text style={{ fontFamily: P400 }}>
              {order.order_type === 'delivery' ? 'Delivery' : order.order_type === 'pickup' ? 'Pickup' : `Table ${order.table_number}`}
            </Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={{ fontFamily: P600 }}>Date & Time</Text>
            <Text style={{ fontFamily: P400, flex: 1, textAlign: 'right' }}>{createdAt}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={{ fontFamily: P600 }}>Customer</Text>
            <Text style={{ fontFamily: P400 }}>{order.ordered_by_name || '—'}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={{ fontFamily: P600 }}>Status</Text>
            <Text style={{ fontFamily: P600, color: '#2E7D32' }}>
              {order.status ? order.status.charAt(0).toUpperCase() + order.status.slice(1) : '—'}
            </Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={{ fontFamily: P600 }}>Payment</Text>
            <Text style={{ fontFamily: P600, color: '#2E7D32' }}>Paid</Text>
          </View>
        </Card.Content>
      </Card>

      {/* ── Order Items ── */}
      <Card style={styles.card}>
        <Card.Content>
          <Text variant="labelLarge" style={styles.sectionLabel}>ORDER ITEMS</Text>
          {order.items?.map((item) => (
            <View key={item.id}>
              <View style={styles.itemRow}>
                <Text style={{ fontFamily: P600, flex: 1 }}>{item.product_name}</Text>
                <Text style={{ fontFamily: P400, color: '#666', marginHorizontal: 8 }}>
                  {item.quantity}×
                </Text>
                <Text style={{ fontFamily: P600 }}>{fmt(item.total_price)}</Text>
              </View>
              {item.special_notes ? (
                <Text variant="bodySmall" style={{ fontFamily: P400, color: '#9E9E9E', marginBottom: 4, paddingLeft: 4 }}>
                  Note: {item.special_notes}
                </Text>
              ) : null}
              <Divider style={{ marginVertical: 4, opacity: 0.3 }} />
            </View>
          ))}
        </Card.Content>
      </Card>

      {/* ── Order Summary ── */}
      <Card style={styles.card}>
        <Card.Content>
          <Text variant="labelLarge" style={styles.sectionLabel}>ORDER SUMMARY</Text>
          <View style={styles.infoRow}>
            <Text style={{ fontFamily: P400 }}>Subtotal</Text>
            <Text style={{ fontFamily: P400 }}>{fmt(order.subtotal)}</Text>
          </View>
          {order.tax_amount > 0 && (
            <View style={styles.infoRow}>
              <Text style={{ fontFamily: P400 }}>Tax</Text>
              <Text style={{ fontFamily: P400 }}>{fmt(order.tax_amount)}</Text>
            </View>
          )}
          {order.discount_amount > 0 && (
            <View style={styles.infoRow}>
              <Text style={{ fontFamily: P400, color: '#2E7D32' }}>Discount</Text>
              <Text style={{ fontFamily: P600, color: '#2E7D32' }}>-{fmt(order.discount_amount)}</Text>
            </View>
          )}
          <Divider style={{ marginVertical: 8 }} />
          <View style={styles.infoRow}>
            <Text style={{ fontFamily: P700, fontSize: 16 }}>Total Paid</Text>
            <Text style={{ fontFamily: P700, fontSize: 16, color: '#2E7D32' }}>
              {fmt(order.total)}
            </Text>
          </View>
        </Card.Content>
      </Card>

      {/* ── Payment Information ── */}
      {order.payments?.length > 0 && (
        <Card style={styles.card}>
          <Card.Content>
            <Text variant="labelLarge" style={styles.sectionLabel}>PAYMENT INFORMATION</Text>
            {order.payments.map((p, idx) => (
              <View key={p.id ?? idx}>
                <View style={[styles.paymentBlock, { backgroundColor: '#E3F2FD' }]}>
                  <View style={styles.infoRow}>
                    <Text style={{ fontFamily: P600 }}>Method</Text>
                    <Text style={{ fontFamily: P400 }}>
                      {PAYMENT_METHOD_LABELS[p.payment_method] || p.payment_method}
                    </Text>
                  </View>
                  <View style={styles.infoRow}>
                    <Text style={{ fontFamily: P600 }}>Amount</Text>
                    <Text style={{ fontFamily: P700 }}>{fmt(p.amount)}</Text>
                  </View>
                  {p.processed_by_name ? (
                    <View style={styles.infoRow}>
                      <Text style={{ fontFamily: P600 }}>Processed by</Text>
                      <Text style={{ fontFamily: P400 }}>{p.processed_by_name}</Text>
                    </View>
                  ) : null}
                  {p.reference_number ? (
                    <View style={styles.infoRow}>
                      <Text style={{ fontFamily: P600 }}>Reference</Text>
                      <Text style={{ fontFamily: P400 }}>{p.reference_number}</Text>
                    </View>
                  ) : null}
                  {p.notes ? (
                    <View style={styles.infoRow}>
                      <Text style={{ fontFamily: P600 }}>Notes</Text>
                      <Text style={{ fontFamily: P400, flex: 1, textAlign: 'right' }}>{p.notes}</Text>
                    </View>
                  ) : null}
                </View>
                {idx < order.payments.length - 1 && <Divider style={{ marginVertical: 8 }} />}
              </View>
            ))}
          </Card.Content>
        </Card>
      )}

      {/* ── Special Instructions ── */}
      {order.special_instructions ? (
        <Card style={styles.card}>
          <Card.Content>
            <Text variant="labelLarge" style={styles.sectionLabel}>SPECIAL INSTRUCTIONS</Text>
            <Text variant="bodyMedium" style={{ fontFamily: P400 }}>
              {order.special_instructions}
            </Text>
          </Card.Content>
        </Card>
      ) : null}

      {/* ── Thank you message ── */}
      <View style={[styles.thankYou, { backgroundColor: '#E8F5E9' }]}>
        <Text style={{ fontFamily: P700, color: '#2E7D32', fontSize: 15, textAlign: 'center' }}>
          ❤  Thank you for dining with us!
        </Text>
      </View>

      {/* ── Back button ── */}
      <Button
        mode="outlined"
        icon="printer-wireless"
        onPress={handleLocalPrint}
        loading={printing}
        disabled={printing}
        style={[styles.backBtn, { marginBottom: 8 }]}
        labelStyle={{ fontFamily: P600 }}
      >
        Print on This Device
      </Button>

      <Button
        mode="outlined"
        icon="arrow-left"
        onPress={() => navigation.goBack()}
        style={styles.backBtn}
        labelStyle={{ fontFamily: P600 }}
      >
        Back to My Orders
      </Button>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center:    { flex: 1, justifyContent: 'center', alignItems: 'center' },
  container: { paddingBottom: 32 },
  header: {
    padding: 24,
    alignItems: 'center',
  },
  headerTitle: { color: '#fff', marginBottom: 4 },
  card:        { margin: 12, marginBottom: 0, borderRadius: 12 },
  sectionLabel: {
    fontFamily: 'Poppins_600SemiBold',
    color: '#9E9E9E',
    fontSize: 11,
    letterSpacing: 1,
    marginBottom: 10,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  itemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  paymentBlock: {
    padding: 12,
    borderRadius: 8,
    marginBottom: 4,
  },
  thankYou: {
    margin: 16,
    padding: 16,
    borderRadius: 12,
  },
  backBtn: { marginHorizontal: 16, marginTop: 8, borderRadius: 8 },
});
