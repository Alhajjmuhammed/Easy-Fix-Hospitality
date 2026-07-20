import React from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import { Text, Button, Chip, useTheme } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useCurrency } from '../../hooks/useCurrency';
import { useAuthStore } from '../../store/useAuthStore';
import { useCartStore } from '../../store/useCartStore';

export default function OrderConfirmationScreen({ route, navigation }) {
  const theme = useTheme();
  const { format } = useCurrency();
  const { setRestaurant } = useAuthStore();
  const { clearCart } = useCartStore();
  const { order } = route.params || {};

  const isRemote = order?.order_type === 'delivery' || order?.order_type === 'pickup';

  const total = order?.total_amount ? format(order.total_amount) : format(0);

  const handleTrackOrder = () => {
    const orderId = order?.id;
    if (orderId) {
      navigation.replace('OrderTracking', { orderId });
    } else {
      navigation.getParent()?.navigate('MyOrders');
    }
  };

  const handleOrderAgain = async () => {
    // For remote orders: clear the saved restaurant so RestaurantSelector
    // doesn't skip straight to TableSelection, then go pick a restaurant again.
    if (isRemote) {
      try { await setRestaurant(null); } catch { /* ignore */ }
      clearCart();
      navigation.reset({ index: 0, routes: [{ name: 'RestaurantSelector' }] });
    } else {
      // Dine-in: go back to table selection to pick a table
      clearCart();
      navigation.reset({ index: 0, routes: [{ name: 'TableSelection' }] });
    }
  };

  const handleViewOrders = () => {
    navigation.getParent()?.navigate('MyOrders');
  };

  return (
    <ScrollView contentContainerStyle={styles.container}>
      {/* Success icon */}
      <MaterialCommunityIcons
        name="check-circle"
        size={96}
        color="#2e7d32"
        style={styles.icon}
      />

      <Text variant="headlineMedium" style={styles.heading}>
        Order Confirmed!
      </Text>

      <Text variant="bodyMedium" style={styles.subtitle}>
        Your order has been placed successfully
      </Text>

      {/* Order details card */}
      <View style={[styles.detailsCard, { backgroundColor: theme.colors.surface }]}>
        {order?.order_number && (
          <View style={styles.detailRow}>
            <Text variant="bodyMedium" style={styles.label}>Order Number</Text>
            <Text variant="titleSmall" style={[styles.value, { fontFamily: 'Poppins_600SemiBold' }]}>
              #{order.order_number}
            </Text>
          </View>
        )}

        {order?.order_type === 'delivery' && order?.delivery_address ? (
          <View style={styles.detailRow}>
            <Text variant="bodyMedium" style={styles.label}>Delivery to</Text>
            <Text
              variant="titleSmall"
              style={[styles.value, { fontFamily: 'Poppins_600SemiBold', flex: 1, textAlign: 'right' }]}
              numberOfLines={2}
            >
              {order.delivery_address}
            </Text>
          </View>
        ) : order?.order_type === 'pickup' ? (
          <View style={styles.detailRow}>
            <Text variant="bodyMedium" style={styles.label}>Order Type</Text>
            <Text variant="titleSmall" style={[styles.value, { fontFamily: 'Poppins_600SemiBold' }]}>Pickup</Text>
          </View>
        ) : order?.table_number && order.table_number !== 'N/A' ? (
          <View style={styles.detailRow}>
            <Text variant="bodyMedium" style={styles.label}>Table</Text>
            <Text variant="titleSmall" style={[styles.value, { fontFamily: 'Poppins_600SemiBold' }]}>
              Table {order.table_number}
            </Text>
          </View>
        ) : null}

        <View style={styles.detailRow}>
          <Text variant="bodyMedium" style={styles.label}>Total</Text>
          <Text variant="titleSmall" style={[styles.value, { color: theme.colors.primary, fontFamily: 'Poppins_700Bold' }]}>
            {total}
          </Text>
        </View>

        <View style={[styles.detailRow, { borderBottomWidth: 0 }]}>
          <Text variant="bodyMedium" style={styles.label}>Status</Text>
          <Chip
            compact
            mode="flat"
            style={{ backgroundColor: '#FFF3CD' }}
            textStyle={{ color: '#856404', fontSize: 12 }}
          >
            Pending
          </Chip>
        </View>
      </View>

      {/* Action buttons */}
      {isRemote && (
        <Button
          mode="contained"
          onPress={handleTrackOrder}
          style={styles.btn}
          contentStyle={styles.btnContent}
          icon="map-marker-path"
          buttonColor="#2e7d32"
        >
          Track Order
        </Button>
      )}

      <Button
        mode="contained"
        onPress={handleViewOrders}
        style={styles.btn}
        contentStyle={styles.btnContent}
        icon="receipt"
      >
        View My Orders
      </Button>

      <Button
        mode="outlined"
        onPress={handleOrderAgain}
        style={styles.btn}
        contentStyle={styles.btnContent}
        icon="silverware-fork-knife"
      >
        {isRemote ? 'Order Again' : 'New Order'}
      </Button>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
    paddingBottom: 40,
  },
  icon:     { marginBottom: 16 },
  heading:  { fontFamily: 'Poppins_700Bold', textAlign: 'center', marginBottom: 8 },
  subtitle: { fontFamily: 'Poppins_400Regular', opacity: 0.7, textAlign: 'center', marginBottom: 24 },
  detailsCard: {
    width: '100%',
    borderRadius: 16,
    padding: 20,
    elevation: 2,
    marginBottom: 24,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#f0f0f0',
  },
  label: { opacity: 0.7, fontFamily: 'Poppins_400Regular' },
  value: { fontFamily: 'Poppins_600SemiBold' },
  btn:   { width: '100%', marginBottom: 12, borderRadius: 8 },
  btnContent: { paddingVertical: 6 },
});
