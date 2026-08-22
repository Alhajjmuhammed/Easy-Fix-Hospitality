import React, { useState, useEffect, useRef } from 'react';
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
import { saveOfflineOrder, cacheOrders } from '../../database/operations';
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
  const navTimer = useRef(null);
  useEffect(() => () => { if (navTimer.current) clearTimeout(navTimer.current); }, []);
  const mountedRef = useRef(true);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  const subtotal = getSubtotal();
  const taxRate = parseFloat(user?.tax_rate) || 0;
  const cartTotal = subtotal * (1 + taxRate);   // tax-inclusive, matches CartScreen and server
  const isAddingToExisting = !!existingOrderId;

  const handleConfirmOrder = async () => {
    // Station-aware ticket helper — prints one ticket per station (KOT/BOT/etc.),
    // fire-and-forget. Items with no station default to 'kitchen'.
    // alwaysFire=true bypasses the localKotBot guard (used for offline orders —
    // kitchen/bar always needs tickets regardless of the user's online preference)
    const fireTickets = (order, alwaysFire = false) => {
      if (!localKotBot && !alwaysFire) return;
      const rName = user?.restaurant_name || '';
      const userFullName = [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || '';
      const orderedBy = order.ordered_by_name || userFullName;
      const allItems = order.items || order.order_items || [];
      // Default null/empty station to 'kitchen' so items always appear on a ticket
      const stations = [...new Set(allItems.map(i => i.station || 'kitchen'))];
      // One ticket per station (KOT / BOT / Buffet / Service)
      stations.forEach(s => printOrderTicket(order, rName, s, orderedBy).catch(() => {}));
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
        delivery_lat: deliveryLat != null ? parseFloat(Number(deliveryLat).toFixed(7)) : null,
        delivery_lng: deliveryLng != null ? parseFloat(Number(deliveryLng).toFixed(7)) : null,
      };

      if (net.isConnected) {
        try {
          if (isAddingToExisting) {
            // Add items to existing order
            const result = await apiAddItemsToOrder(existingOrderId, {
              items: orderData.items,
              special_instructions: orderData.special_instructions,
            }, localKotBot);
            // Cache immediately so the updated order is available offline
            cacheOrders([result.order]).catch(() => {});
            // Print ticket for ONLY the newly added items (not the full order)
            const newItemsOrder = {
              ...result.order,
              items: items.map((i) => ({
                product_name: i.product.name,
                quantity: i.quantity,
                special_notes: i.special_notes || '',
                station: i.product.station || 'kitchen',
              })),
            };
            clearCart();
            fireTickets(newItemsOrder);
            navigation.replace('OrderConfirmation', { order: result.order });
          } else {
            const result = await apiPlaceOrder(orderData, localKotBot);
            // Cache immediately so the order is available offline
            cacheOrders([result.order]).catch(() => {});
            clearCart();
            fireTickets(result.order);
            navigation.replace('OrderConfirmation', { order: result.order });
          }
        } catch (err) {
          if (!mountedRef.current) return;
          if (err.response?.status === 409) {
            const { price_changes, unavailable_items } = err.response.data;
            if (unavailable_items?.length) {
              setSnack(
                `Some items are no longer available: ${unavailable_items.map(i => i.name || i).join(', ')}`
              );
            }
            if (price_changes?.length) {
              setConflictDialog(price_changes);
            } else if (!unavailable_items?.length) {
              setSnack(err.response.data?.detail || 'Order failed. Please try again.');
            }
          } else {
            const friendlyMsg = err.response?.data?.detail
              || err.response?.data?.error
              || err.response?.data?.message
              || (err.response ? 'Please check your order and try again.' : 'No internet connection. Please try again.');
            setSnack(friendlyMsg);
          }
        }
      } else {
        await saveOfflineOrder({
          ...orderData,
          user_id: user?.id,
          total_amount: cartTotal,
          tax_rate: taxRate,
          // Signal that the BT ticket was already fired locally so the sync
          // endpoint skips auto_print_new_items and avoids a duplicate print.
          local_print_fired: localKotBot,
          // Link to the existing server order so the sync endpoint appends items
          // instead of creating a duplicate standalone order.
          ...(isAddingToExisting ? { existing_order_id: existingOrderId } : {}),
        });
        await refreshPendingCount();

        // Print draft ticket from cart data (new items only) if localKotBot is enabled.
        // Station is included so tickets split by station (KOT/BOT) exactly
        // like online orders. fireTickets() is a no-op when localKotBot=false.
        const draftOrder = {
          order_number: isAddingToExisting ? 'ADD-ITEMS' : 'OFFLINE',
          table_number: tableName,
          created_at:   new Date().toISOString(),
          items:        items.map((i) => ({
            product_name:  i.product.name,
            quantity:      i.quantity,
            special_notes: i.special_notes || '',
            station:       i.product.station || 'kitchen',
          })),
          special_instructions: notes.trim(),
        };
        fireTickets(draftOrder, true); // always fire KOT/BOT when offline

        clearCart();
        if (isAddingToExisting) {
          setSnack('Items saved – will be added to order when online');
          navTimer.current = setTimeout(() => navigation.goBack(), 1500);
        } else {
          setSnack('Order saved – will sync when online');
          navTimer.current = setTimeout(() => {
            navigation.reset({ index: 0, routes: [{ name: 'TableSelection' }] });
          }, 1500);
        }
      }
    } catch (err) {
      if (mountedRef.current) setSnack(err.message || 'Something went wrong.');
    } finally {
      if (mountedRef.current) setLoading(false);
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

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
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
                {c.name}: {format(c.old_price)} → {format(c.new_price)}
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
