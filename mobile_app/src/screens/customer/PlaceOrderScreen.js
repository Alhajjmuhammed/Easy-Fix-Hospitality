import React, { useState } from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import {
  Text,
  Button,
  TextInput,
  Snackbar,
  useTheme,
  Surface,
  Divider,
  Dialog,
  Portal,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import { useCartStore } from '../../store/useCartStore';
import { useAuthStore } from '../../store/useAuthStore';
import { useSyncStore } from '../../store/useSyncStore';
import { apiPlaceOrder, apiAddItemsToOrder } from '../../api/orders';
import { usePrinterStore } from '../../store/usePrinterStore';
import { printOrderTicket } from '../../utils/printer';
import { saveOfflineOrder } from '../../database/operations';
import { useCurrency } from '../../hooks/useCurrency';

export default function PlaceOrderScreen({ navigation }) {
  const theme = useTheme();
  const { items, tableId, tableName, clearCart, getSubtotal, existingOrderId, orderType, deliveryAddress, deliveryPhone, deliveryLat, deliveryLng } = useCartStore();
  const { user, restaurantId } = useAuthStore();
  const { refreshPendingCount } = useSyncStore();
  const localKotBot = usePrinterStore((s) => s.localKotBot);
  const { format } = useCurrency();

  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [snack, setSnack] = useState('');
  const [conflictDialog, setConflictDialog] = useState(null);

  const cartTotal = getSubtotal();
  const isAddingToExisting = !!existingOrderId;

  const handleConfirmOrder = async () => {
    // Station-aware ticket helper — prints one ticket per station (KOT/BOT/etc.),
    // fire-and-forget. Falls back to one combined ticket if no station data.
    const fireTickets = (order) => {
      if (!localKotBot) return;
      const rName = user?.restaurant_name || '';
      const allItems = order.items || order.order_items || [];
      const stations = [...new Set(allItems.map(i => i.station).filter(Boolean))];
      if (stations.length === 0) {
        // No station info (old cached menu) → single combined ticket
        printOrderTicket(order, rName, null).catch(() => {});
      } else {
        // One ticket per station
        stations.forEach(s => printOrderTicket(order, rName, s).catch(() => {}));
      }
    };

    if (!items.length) return;
    setLoading(true);
    try {
      const net = await NetInfo.fetch();
      const isRemote = orderType === 'delivery' || orderType === 'pickup';
      const orderData = {
        ...(isRemote ? {} : { table_id: tableId }),
        items: items.map((i) => ({
          product_id: i.product.id,
          quantity: i.quantity,
          price: parseFloat(i.product.current_price),
        })),
        special_instructions: notes.trim(),
        restaurant_id: restaurantId,
        order_type: orderType || 'dine-in',
        delivery_address: deliveryAddress || '',
        delivery_phone: deliveryPhone || '',
        delivery_lat: deliveryLat != null ? parseFloat(deliveryLat.toFixed(7)) : null,
        delivery_lng: deliveryLng != null ? parseFloat(deliveryLng.toFixed(7)) : null,
      };

      if (net.isConnected) {
        try {
          if (isAddingToExisting) {
            // Add items to existing order
            const result = await apiAddItemsToOrder(existingOrderId, {
              items: orderData.items,
              special_instructions: orderData.special_instructions,
            }, localKotBot);
            clearCart();
            fireTickets(result.order);
            navigation.replace('OrderConfirmation', { order: result.order });
          } else {
            const result = await apiPlaceOrder(orderData, localKotBot);
            clearCart();
            fireTickets(result.order);
            navigation.replace('OrderConfirmation', { order: result.order });
          }
        } catch (err) {
          if (err.response?.status === 409) {
            const { price_changes, unavailable_items } = err.response.data;
            if (price_changes?.length) {
              setConflictDialog(price_changes);
            } else if (unavailable_items?.length) {
              setSnack(
                `Some items are no longer available: ${unavailable_items.map(i => i.name || i).join(', ')}`
              );
            } else {
              setSnack(err.response.data?.detail || 'Order failed. Please try again.');
            }
          } else {
            const data = err.response?.data;
            let errMsg = data?.error || data?.detail;
            if (!errMsg && data && typeof data === 'object') {
              // DRF serializer validation error: { field: ['msg'] }
              const firstKey = Object.keys(data)[0];
              const val = data[firstKey];
              errMsg = `${firstKey}: ${Array.isArray(val) ? val[0] : val}`;
            }
            setSnack(errMsg || err.message || 'Something went wrong.');
          }
        }
      } else {
        await saveOfflineOrder({ ...orderData, user_id: user?.id, total_amount: cartTotal });
        await refreshPendingCount();

        // Print draft ticket from cart data if localKotBot is enabled.
        // Station is included so tickets split by station (KOT/BOT) exactly
        // like online orders. fireTickets() is a no-op when localKotBot=false.
        const draftOrder = {
          order_number: 'OFFLINE',
          table_number: tableName,
          created_at:   new Date().toISOString(),
          items:        items.map((i) => ({
            product_name:  i.product.name,
            quantity:      i.quantity,
            special_notes: i.special_notes || '',
            station:       i.product.station || null,
          })),
          special_instructions: notes.trim(),
        };
        fireTickets(draftOrder);

        clearCart();
        setSnack('Order saved – will sync when online');
        const isRemoteOffline = orderType === 'delivery' || orderType === 'pickup';
        setTimeout(async () => {
          if (isRemoteOffline) {
            const { setRestaurant } = useAuthStore.getState();
            try { await setRestaurant(null); } catch { /* ignore */ }
            navigation.reset({ index: 0, routes: [{ name: 'RestaurantSelector' }] });
          } else {
            navigation.reset({ index: 0, routes: [{ name: 'TableSelection' }] });
          }
        }, 1500);
      }
    } catch (err) {
      setSnack(err.message || 'Something went wrong.');
    } finally {
      setLoading(false);
    }
  };

  const acceptPriceChanges = () => {
    // User accepts updated prices → update cart store prices, then retry
    const changes = conflictDialog;
    setConflictDialog(null);
    // Update prices in cart
    const { updateItemPrice } = useCartStore.getState();
    if (updateItemPrice) {
      changes.forEach(({ product_id, new_price }) => updateItemPrice(product_id, new_price));
    }
    setSnack('Prices updated – tap Confirm Order again to proceed.');
  };

  return (
    <View style={styles.container}>
      {/* Table reminder chip */}
      <Surface style={styles.infoBanner} elevation={0}>
        <MaterialCommunityIcons name="information" size={16} color="#2c3e50" style={{ marginRight: 6 }} />
        <Text variant="bodySmall" style={styles.infoBannerText}>
          {isAddingToExisting
            ? `${tableName || 'Unknown table'} • Adding items to existing order`
            : orderType === 'delivery'
              ? `Delivery to: ${deliveryAddress || 'your address'}`
              : orderType === 'pickup'
                ? 'Pickup order • Please review before confirming'
                : `${tableName || 'Unknown table'} • Please review your order before confirming`}
        </Text>
      </Surface>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Special instructions — matches web's textarea */}
        <Text variant="titleSmall" style={styles.sectionTitle}>
          Special Instructions (optional)
        </Text>
        <TextInput
          label="e.g. no onions, extra spicy…"
          value={notes}
          onChangeText={setNotes}
          mode="outlined"
          multiline
          numberOfLines={3}
          style={styles.notesInput}
        />

        {/* Order summary — read-only, matches web's order summary table */}
        <Text variant="titleSmall" style={styles.sectionTitle}>
          Order Summary
        </Text>
        <Surface style={styles.summaryCard} elevation={1}>
          {items.map((item, idx) => (
            <View key={item.product.id}>
              <View style={styles.summaryRow}>
                <Text variant="bodyMedium" style={[styles.summaryName, { fontFamily: 'Poppins_600SemiBold' }]}>
                  {item.product.name}
                </Text>
                <Text variant="bodyMedium">
                  {item.quantity} × {format(item.product.current_price)}
                </Text>
                <Text variant="bodyMedium" style={{ color: theme.colors.primary, minWidth: 64, textAlign: 'right' }}>
                  {format(parseFloat(item.product.current_price) * item.quantity)}
                </Text>
              </View>
              {idx < items.length - 1 && <Divider />}
            </View>
          ))}
          <Divider style={{ marginVertical: 8 }} />
          <View style={[styles.summaryRow, styles.totalRow]}>
            <Text variant="titleMedium" style={{ fontFamily: 'Poppins_700Bold', flex: 1 }}>
              Total
            </Text>
            <Text
              variant="titleMedium"
              style={{ fontFamily: 'Poppins_700Bold', color: theme.colors.primary }}
            >
              {format(cartTotal)}
            </Text>
          </View>
        </Surface>
      </ScrollView>

      {/* Bottom action buttons — matches web's "Back to Cart" + "Confirm Order" */}
      <Surface style={styles.footer} elevation={4}>
        <View style={styles.btnRow}>
          <Button
            mode="outlined"
            onPress={() => navigation.goBack()}
            style={styles.backBtn}
            icon="arrow-left"
            disabled={loading}
          >
            Back to Cart
          </Button>
          <Button
            mode="contained"
            onPress={handleConfirmOrder}
            loading={loading}
            disabled={loading}
            style={styles.confirmBtn}
            contentStyle={styles.confirmBtnContent}
            icon="check-circle"
          >
            {isAddingToExisting ? 'Add to Order' : 'Confirm Order'}
          </Button>
        </View>
      </Surface>

      {/* Price change conflict dialog */}
      <Portal>
        <Dialog visible={!!conflictDialog} onDismiss={() => setConflictDialog(null)}>
          <Dialog.Title>Prices Have Changed</Dialog.Title>
          <Dialog.Content>
            {conflictDialog?.map((c) => (
              <Text key={c.product_id} variant="bodyMedium" style={{ fontFamily: 'Poppins_400Regular' }}>
                {c.name}: {c.old_price} → {c.new_price}
              </Text>
            ))}
            <Text variant="bodySmall" style={{ marginTop: 8, fontFamily: 'Poppins_400Regular' }}>
              Accept updated prices to continue.
            </Text>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setConflictDialog(null)}>Cancel</Button>
            <Button onPress={acceptPriceChanges}>Accept</Button>
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
  container: { flex: 1 },
  infoBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#e3f2fd',
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  infoBannerText: { flex: 1, color: '#2c3e50', fontFamily: 'Poppins_400Regular' },
  scroll: { padding: 16, paddingBottom: 8 },
  sectionTitle: { fontFamily: 'Poppins_700Bold', marginBottom: 8, marginTop: 8 },
  notesInput: { marginBottom: 16 },
  summaryCard: { borderRadius: 8, overflow: 'hidden', marginBottom: 16 },
  summaryRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 10,
    gap: 8,
  },
  summaryName: { flex: 1 },
  totalRow: { paddingHorizontal: 10, paddingBottom: 10 },
  footer: {
    padding: 16,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
  },
  btnRow: { flexDirection: 'row', gap: 10 },
  backBtn: { flex: 1 },
  confirmBtn: { flex: 2, borderRadius: 8 },
  confirmBtnContent: { paddingVertical: 6 },
});
