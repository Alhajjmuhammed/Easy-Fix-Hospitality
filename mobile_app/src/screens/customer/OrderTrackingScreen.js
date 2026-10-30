import React, { useEffect, useState, useCallback, useRef } from 'react';
import { View, StyleSheet, ScrollView, Alert } from 'react-native';
import {
  Text,
  Card,
  Chip,
  ActivityIndicator,
  Button,
  Divider,
  Snackbar,
  Dialog,
  Portal,
  TextInput,
  Banner,
  useTheme,
} from 'react-native-paper';
import { useNavigation } from '@react-navigation/native';
import { useOrderWebSocket } from '../../hooks/useOrderWebSocket';
import { apiOrderDetail, apiCancelOrder } from '../../api/orders';
import { apiCreateBillRequest } from '../../api/billRequests';
import { saveOfflineBillRequest, getOrderById, cacheOrders } from '../../database/operations';
import NetInfo from '@react-native-community/netinfo';
import { useSyncStore } from '../../store/useSyncStore';
import { useCurrency } from '../../hooks/useCurrency';
import OrderRatingCard from '../../components/OrderRatingCard';
import MobileMoneyBox from '../../components/MobileMoneyBox';
import { useT } from '../../i18n';

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

const PAYMENT_INFO = {
  unpaid:  { color: '#E65100', bg: '#FFF3E0', label: 'Payment Pending',  icon: '⏳' },
  partial: { color: '#1565C0', bg: '#E3F2FD', label: 'Partial Payment',  icon: '💳' },
  paid:    { color: '#2E7D32', bg: '#E8F5E9', label: 'Paid',             icon: '✅' },
};

// Order progress steps — delivery orders use a different final step
const DINE_IN_STEPS = [
  { key: 'pending',    label: 'Order Placed',     desc: 'Your order has been received' },
  { key: 'confirmed',  label: 'Confirmed',         desc: 'Kitchen has confirmed your order' },
  { key: 'preparing',  label: 'Preparing',         desc: 'Your food is being prepared' },
  { key: 'ready',      label: 'Ready',             desc: 'Your order is ready to be served' },
  { key: 'served',     label: 'Served',            desc: 'Your order has been delivered' },
];

const DELIVERY_STEPS = [
  { key: 'pending',          label: 'Order Placed',     desc: 'Your order has been received' },
  { key: 'confirmed',        label: 'Confirmed',         desc: 'Kitchen has confirmed your order' },
  { key: 'preparing',        label: 'Preparing',         desc: 'Your food is being prepared' },
  { key: 'ready',            label: 'Ready',             desc: 'Order is ready for pickup by rider' },
  { key: 'out_for_delivery', label: 'On the Way',        desc: 'Rider is delivering your order' },
  { key: 'delivered',        label: 'Delivered',         desc: 'Your order has arrived!' },
];

const PICKUP_STEPS = [
  { key: 'pending',   label: 'Order Placed',      desc: 'Your order has been received' },
  { key: 'confirmed', label: 'Confirmed',          desc: 'Kitchen has confirmed your order' },
  { key: 'preparing', label: 'Preparing',          desc: 'Your food is being prepared' },
  { key: 'ready',     label: 'Ready',              desc: 'Your order is ready for collection' },
  { key: 'served',    label: 'Collected',          desc: 'Enjoy your meal!' },
];

const DINE_IN_ORDER   = ['pending','confirmed','preparing','ready','served'];
const PICKUP_ORDER    = ['pending','confirmed','preparing','ready','served'];
const DELIVERY_ORDER  = ['pending','confirmed','preparing','ready','out_for_delivery','delivered'];

const POLL_INTERVAL = 60_000; // 60-second safety-net; WebSocket delivers live updates faster

function getRelativeTime(isoString, t) {
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    if (isNaN(diffMs) || diffMs < 0) return '';
    const diffSecs = Math.floor(diffMs / 1000);
    if (diffSecs < 60) return t(diffSecs !== 1 ? '{n} seconds' : '{n} second', { n: diffSecs });
    const diffMins = Math.floor(diffSecs / 60);
    if (diffMins < 60) return t(diffMins !== 1 ? '{n} minutes' : '{n} minute', { n: diffMins });
    const diffHrs = Math.floor(diffMins / 60);
    return t(diffHrs !== 1 ? '{n} hours' : '{n} hour', { n: diffHrs });
  } catch {
    return '';
  }
}

export default function OrderTrackingScreen({ route }) {
  const { orderId } = route.params;
  const t = useT();
  const theme = useTheme();
  const navigation = useNavigation();
  const { refreshPendingCount } = useSyncStore();
  const { format: formatCurrency } = useCurrency();

  const mountedRef = useRef(true);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [billRequesting, setBillRequesting] = useState(false);
  const [snack, setSnack] = useState('');
  const [isOffline, setIsOffline] = useState(false);

  // Cancel dialog state
  const [cancelVisible, setCancelVisible] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [cancelling, setCancelling] = useState(false);

  const fetchOrder = useCallback(async () => {
    try {
      const net = await NetInfo.fetch();
      if (!mountedRef.current) return;
      if (net.isConnected) {
        const data = await apiOrderDetail(orderId);
        if (!mountedRef.current) return;
        setOrder(data);
        setIsOffline(false);
        try { await cacheOrders([data]); } catch { /* best-effort */ }
      } else {
        setIsOffline(true);
        const cached = await getOrderById(orderId);
        if (!mountedRef.current) return;
        if (cached) setOrder(cached);
      }
    } catch {
      // Network error — try cache
      try {
        const cached = await getOrderById(orderId);
        if (!mountedRef.current) return;
        if (cached) {
          setOrder(cached);
          setIsOffline(true);
        }
      } catch {
        // SQLite error — leave existing order state as-is
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [orderId]);

  // WebSocket: receive live status updates; fall back to 60-second polling
  useOrderWebSocket(
    orderId,
    useCallback(() => { fetchOrder(); }, [fetchOrder]),
  );

  useEffect(() => {
    fetchOrder();
    const interval = setInterval(fetchOrder, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchOrder]);

  const handleBillRequest = async () => {
    if (!order) return;
    setBillRequesting(true);
    try {
      const net = await NetInfo.fetch();
      if (!mountedRef.current) return;
      if (net.isConnected) {
        await apiCreateBillRequest(order.table_info);
        if (!mountedRef.current) return;
        setOrder((prev) => prev ? { ...prev, pending_bill_requested: true } : prev);
        setSnack(t('Bill requested – staff have been notified'));
      } else {
        await saveOfflineBillRequest(order.table_info);
        await refreshPendingCount();
        if (!mountedRef.current) return;
        setOrder(prev => prev ? { ...prev, pending_bill_requested: true } : prev);
        setSnack(t('Bill request saved – will sync when online'));
      }
    } catch (err) {
      if (mountedRef.current) setSnack(err.response?.data?.detail || t('Could not request bill'));
    } finally {
      if (mountedRef.current) setBillRequesting(false);
    }
  };

  const handleCancelConfirm = async () => {
    const net = await NetInfo.fetch();
    if (!mountedRef.current) return;
    if (!net.isConnected) { setSnack(t('No internet — connect to cancel the order')); setCancelVisible(false); return; }
    setCancelling(true);
    try {
      const reason = cancelReason.trim() || 'Changed mind / No longer needed';
      await apiCancelOrder(orderId, reason);
      if (!mountedRef.current) return;
      setCancelVisible(false);
      setCancelReason('');
      setSnack(t('Order cancelled'));
      fetchOrder(); // refresh
    } catch (err) {
      if (mountedRef.current) setSnack(err.response?.data?.error || t('Could not cancel order'));
    } finally {
      if (mountedRef.current) setCancelling(false);
    }
  };

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
        <Text style={{ fontFamily: 'Poppins_400Regular' }}>
          {isOffline ? t('You are offline – order not in local cache') : t('Order not found')}
        </Text>
      </View>
    );
  }

  const statusColor = STATUS_COLORS[order.status] || theme.colors.primary;
  const payInfo = PAYMENT_INFO[order.payment_status] || PAYMENT_INFO.unpaid;
  const P700 = 'Poppins_700Bold';
  const P600 = 'Poppins_600SemiBold';
  const P400 = 'Poppins_400Regular';

  // Delivery vs dine-in progress
  const isDelivery     = order.order_type === 'delivery';
  const isPickup       = order.order_type === 'pickup';
  const PROGRESS_STEPS = isDelivery ? DELIVERY_STEPS : isPickup ? PICKUP_STEPS : DINE_IN_STEPS;
  const STEP_ORDER     = isDelivery ? DELIVERY_ORDER  : isPickup ? PICKUP_ORDER  : DINE_IN_ORDER;

  // Progress tracking
  const currentStepIdx = STEP_ORDER.indexOf(order.status);
  const isCancelled = order.status === 'cancelled';
  const isOutForDelivery = order.status === 'out_for_delivery';
  const isDelivered      = order.status === 'delivered';
  const fmt = formatCurrency;

  return (
    <ScrollView contentContainerStyle={styles.container}>

      {/* ── Offline banner ── */}
      {isOffline && (
        <Banner visible icon="wifi-off" actions={[]} style={{ backgroundColor: '#FFF8E1', marginBottom: 8 }}>
          {t('You are offline – showing last synced data. Live updates paused.')}
        </Banner>
      )}

      {/* ── Status header card ── */}
      <Card style={styles.statusCard}>
        <Card.Content style={styles.statusContent}>
          <Text variant="headlineMedium" style={[styles.orderNum, { fontFamily: P700 }]}>
            {t('Order #{number}', { number: order.order_number || order.id })}
          </Text>
          <View style={styles.badgeRow}>
            <Chip
              mode="flat"
              style={[styles.statusChip, { backgroundColor: statusColor + '22' }]}
              textStyle={{ color: statusColor, fontFamily: P600 }}
            >
              {order.status?.toUpperCase() ?? ''}
            </Chip>
            <View style={[styles.payBadge, { backgroundColor: payInfo.bg }]}>
              <Text style={{ color: payInfo.color, fontSize: 12, fontFamily: P600 }}>
                {payInfo.icon}  {t(payInfo.label)}
              </Text>
            </View>
          </View>
          {order.confirmed_by_name ? (
            <Text variant="bodySmall" style={{ fontFamily: P400, color: '#9E9E9E', marginTop: 6 }}>
              {t('Confirmed by:')} {order.confirmed_by_name}
            </Text>
          ) : null}
        </Card.Content>
      </Card>

      {/* ── Cancellation notice ── */}
      {isCancelled && (
        <Card style={[styles.card, { backgroundColor: '#FFEBEE' }]}>
          <Card.Content>
            <Text variant="titleSmall" style={{ fontFamily: P700, color: '#B71C1C', marginBottom: 4 }}>
              ✗  {t('Order Cancelled')}
            </Text>
            {order.reason_if_cancelled ? (
              <Text variant="bodySmall" style={{ fontFamily: P400, color: '#B71C1C' }}>
                {t('Reason:')} {order.reason_if_cancelled}
              </Text>
            ) : null}
          </Card.Content>
        </Card>
      )}

      {/* ── Progress timeline (not for cancelled orders) ── */}
      {!isCancelled && (
        <Card style={styles.card}>
          <Card.Title title={t('Order Progress')} titleStyle={{ fontFamily: P700 }} />
          <Card.Content>
            {PROGRESS_STEPS.map((step, idx) => {
              const isCompleted = currentStepIdx > idx;
              const isActive    = currentStepIdx === idx;
              const isPending   = currentStepIdx < idx;
              const dotColor = isCompleted ? '#2E7D32' : isActive ? '#2c3e50' : '#BDBDBD';
              return (
                <View key={step.key} style={styles.stepRow}>
                  <View style={[styles.stepDot, { backgroundColor: dotColor }]}>
                    <Text style={{ color: '#fff', fontSize: 10, fontFamily: P700 }}>
                      {isCompleted ? '✓' : idx + 1}
                    </Text>
                  </View>
                  <View style={styles.stepContent}>
                    <Text variant="bodyMedium" style={{
                      fontFamily: isActive || isCompleted ? P700 : P400,
                      color: isPending ? '#9E9E9E' : '#212121',
                    }}>
                      {t(step.label)}
                    </Text>
                    <Text variant="bodySmall" style={{ fontFamily: P400, color: '#9E9E9E' }}>
                      {t(step.desc)}
                    </Text>
                    {isActive && (
                      <Text variant="labelSmall" style={{ fontFamily: P600, color: '#2c3e50', marginTop: 2 }}>
                        ● {t('Current Status')}
                      </Text>
                    )}
                  </View>
                </View>
              );
            })}

            {/* Completion messages */}
            {order.status === 'served' && order.payment_status !== 'paid' && (
              <View style={[styles.infoBanner, { backgroundColor: '#E3F2FD' }]}>
                <Text style={{ fontFamily: P400, color: '#1565C0', fontSize: 13 }}>
                  ℹ  {t('Order complete! Please proceed to payment to finalize your order.')}
                </Text>
              </View>
            )}
            {order.status === 'served' && order.payment_status === 'paid' && (
              <View style={[styles.infoBanner, { backgroundColor: '#E8F5E9' }]}>
                <Text style={{ fontFamily: P700, color: '#2E7D32', fontSize: 13 }}>
                  ✅  {t('All done! Thank you for dining with us. Enjoy your meal!')}
                </Text>
              </View>
            )}
          </Card.Content>
        </Card>
      )}

      {/* ── Order items ── */}
      <Card style={styles.card}>
        <Card.Title title={t('Items')} titleStyle={{ fontFamily: P700 }} />
        <Card.Content>
          {order.items?.map((item) => (
            <View key={item.id} style={styles.itemRow}>
              <View style={{ flex: 1 }}>
                <Text variant="bodyMedium" style={{ fontFamily: P400 }}>{item.product_name}</Text>
                {item.special_notes ? (
                  <Text variant="bodySmall" style={{ fontFamily: P400, color: '#9E9E9E' }}>
                    {t('Note:')} {item.special_notes}
                  </Text>
                ) : null}
              </View>
              <Text variant="bodyMedium" style={{ fontFamily: P400, marginLeft: 8 }}>
                {item.quantity} × {formatCurrency(item.unit_price)}
              </Text>
            </View>
          ))}
          <Divider style={styles.divider} />
          <View style={styles.itemRow}>
            <Text variant="bodySmall" style={{ fontFamily: P400 }}>{t('Subtotal')}</Text>
            <Text variant="bodySmall" style={{ fontFamily: P400 }}>{fmt(order.subtotal)}</Text>
          </View>
          {order.tax_amount > 0 && (
            <View style={styles.itemRow}>
              <Text variant="bodySmall" style={{ fontFamily: P400 }}>{t('Tax')}</Text>
              <Text variant="bodySmall" style={{ fontFamily: P400 }}>{fmt(order.tax_amount)}</Text>
            </View>
          )}
          {order.delivery_fee > 0 && (
            <View style={styles.itemRow}>
              <Text variant="bodySmall" style={{ fontFamily: P400 }}>{t('Delivery fee')}</Text>
              <Text variant="bodySmall" style={{ fontFamily: P400 }}>{fmt(order.delivery_fee)}</Text>
            </View>
          )}
          <View style={styles.itemRow}>
            <Text variant="titleSmall" style={{ fontFamily: P700 }}>{t('Total')}</Text>
            <Text variant="titleSmall" style={{ fontFamily: P700 }}>{fmt(order.total)}</Text>
          </View>
          {order.total_paid > 0 && order.payment_status !== 'paid' && (
            <View style={styles.itemRow}>
              <Text variant="bodySmall" style={{ fontFamily: P600 }}>{t('Paid')}</Text>
              <Text variant="bodySmall" style={{ fontFamily: P600 }}>{fmt(order.total_paid)}</Text>
            </View>
          )}
          {order.balance_due > 0 && (
            <View style={[styles.itemRow, styles.balanceRow]}>
              <Text variant="bodyMedium" style={{ color: theme.colors.error, fontFamily: P600 }}>
                {t('Balance Due')}
              </Text>
              <Text variant="bodyMedium" style={{ color: theme.colors.error, fontFamily: P700 }}>
                {fmt(order.balance_due)}
              </Text>
            </View>
          )}
        </Card.Content>
      </Card>

      {/* ── Special Instructions ── */}
      {(() => {
        const cleaned = (order.special_instructions || '')
          .replace(/\[offline:[^\]]*\]/g, '')
          .replace(/\[offline-append:[^\]]*\]/g, '')
          .trim();
        return cleaned ? (
          <Card style={styles.card}>
            <Card.Content>
              <Text variant="labelLarge" style={{ fontFamily: P600, color: '#9E9E9E', marginBottom: 4 }}>
                {t('SPECIAL INSTRUCTIONS')}
              </Text>
              <Text variant="bodyMedium" style={{ fontFamily: P400 }}>
                {cleaned}
              </Text>
            </Card.Content>
          </Card>
        ) : null;
      })()}

      {/* ── Action buttons ── */}

      {/* Track Delivery – live map button for delivery orders */}
      {isDelivery && (isOutForDelivery || isDelivered) && (
        <Button
          mode="contained"
          buttonColor="#1565C0"
          onPress={() => navigation.navigate('DeliveryTracking', { orderId: order.id })}
          style={styles.actionBtn}
          icon="map-marker-radius"
          labelStyle={{ fontFamily: P600 }}
        >
          {isDelivered ? t('View Delivery Map') : t('Track Live on Map')}
        </Button>
      )}

      {/* Bill request – dine-in only, when served and not yet paid */}
      {order.table_info && order.status === 'served' && order.payment_status !== 'paid' && (
        order.pending_bill_requested ? (
          <View style={[styles.infoBanner, { backgroundColor: '#E3F2FD', marginTop: 8 }]}>
            <Text style={{ fontFamily: P700, color: '#1565C0', fontSize: 13, marginBottom: 2 }}>
              🕐  {t('Bill Request Sent!')}
            </Text>
            <Text style={{ fontFamily: P400, color: '#1565C0', fontSize: 12 }}>
              {order.pending_bill_requested_at
                ? t('Requested {time} ago. Staff will bring your bill shortly.', { time: getRelativeTime(order.pending_bill_requested_at, t) })
                : t('Staff have been notified and will bring your bill shortly.')}
            </Text>
          </View>
        ) : (
          <Button
            mode="contained"
            onPress={handleBillRequest}
            loading={billRequesting}
            disabled={billRequesting}
            style={styles.actionBtn}
            icon="receipt"
            labelStyle={{ fontFamily: P600 }}
          >
            {t('Request Bill')}
          </Button>
        )
      )}

      {/* Pay from the phone (only when the restaurant takes mobile money online) */}
      {!isOffline && !isCancelled && order.payment_status !== 'paid' && (
        <MobileMoneyBox orderId={order.id} onMessage={setSnack}
          onPaid={() => { setSnack(t('Payment received — thank you!')); fetchOrder(); }} />
      )}

      {/* Rate the order – once served / delivered (customer only; hidden otherwise) */}
      {!isOffline && (
        <OrderRatingCard orderId={order.id} status={order.status} orderType={order.order_type} onMessage={setSnack} />
      )}

      {/* View Receipt – when paid */}
      {order.payment_status === 'paid' && (
        <Button
          mode="contained"
          buttonColor="#2E7D32"
          onPress={() => navigation.navigate('Receipt', { orderId: order.id })}
          style={styles.actionBtn}
          icon="file-document-outline"
          labelStyle={{ fontFamily: P600 }}
        >
          {t('View Receipt')}
        </Button>
      )}

      {/* Cancel Order – only pending; disabled offline */}
      {order.status === 'pending' && (
        <Button
          mode="outlined"
          textColor={isOffline ? '#9E9E9E' : '#B71C1C'}
          style={[styles.actionBtn, styles.cancelBtn]}
          icon="close-circle-outline"
          disabled={isOffline}
          onPress={() => { setCancelReason(''); setCancelVisible(true); }}
          labelStyle={{ fontFamily: P600 }}
        >
          {isOffline ? t('Cancel Order (connect first)') : t('Cancel Order')}
        </Button>
      )}

      {/* Cannot cancel message */}
      {['confirmed', 'preparing', 'ready'].includes(order.status) && (
        <View style={[styles.infoBanner, { backgroundColor: '#FFF3E0', marginTop: 8 }]}>
          <Text style={{ fontFamily: P400, color: '#E65100', fontSize: 12 }}>
            ℹ  {t('Order cannot be cancelled – it has been confirmed by the kitchen.')}
          </Text>
        </View>
      )}

      {/* ── Cancel Order Dialog ── */}
      <Portal>
        <Dialog visible={cancelVisible} onDismiss={() => setCancelVisible(false)}>
          <Dialog.Title style={{ fontFamily: P700 }}>{t('Cancel Order')}</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium" style={{ fontFamily: P400, marginBottom: 12 }}>
              {t('Are you sure you want to cancel Order #{number}?', { number: order.order_number || order.id })}
              {' '}{t('This action cannot be undone.')}
            </Text>
            <TextInput
              label={t('Reason (optional)')}
              value={cancelReason}
              onChangeText={setCancelReason}
              mode="outlined"
              placeholder={t('Changed mind / No longer needed')}
              style={{ fontFamily: P400 }}
            />
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setCancelVisible(false)} labelStyle={{ fontFamily: P600 }}>
              {t('Keep Order')}
            </Button>
            <Button
              textColor="#B71C1C"
              loading={cancelling}
              disabled={cancelling}
              onPress={handleCancelConfirm}
              labelStyle={{ fontFamily: P600 }}
            >
              {t('Cancel Order')}
            </Button>
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
  container:    { padding: 16, paddingBottom: 32 },
  center:       { flex: 1, justifyContent: 'center', alignItems: 'center' },
  statusCard:   { marginBottom: 12, borderRadius: 12 },
  statusContent: { alignItems: 'center', paddingVertical: 12 },
  orderNum:     { marginBottom: 10 },
  badgeRow:     { flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'center' },
  statusChip:   { paddingHorizontal: 8 },
  payBadge:     { paddingHorizontal: 12, paddingVertical: 5, borderRadius: 16 },
  card:         { marginBottom: 12, borderRadius: 12 },
  stepRow:      { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 14 },
  stepDot:      {
    width: 28, height: 28, borderRadius: 14,
    justifyContent: 'center', alignItems: 'center',
    marginRight: 12, marginTop: 2,
  },
  stepContent:  { flex: 1 },
  infoBanner:   { padding: 12, borderRadius: 8, marginTop: 8 },
  itemRow:      { flexDirection: 'row', justifyContent: 'space-between', marginVertical: 3 },
  divider:      { marginVertical: 8 },
  balanceRow:   { marginTop: 4 },
  actionBtn:    { borderRadius: 8, marginTop: 8 },
  cancelBtn:    { borderColor: '#B71C1C' },
});
