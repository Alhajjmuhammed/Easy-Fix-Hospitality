import React, { useEffect } from 'react';
import { View, StyleSheet } from 'react-native';
import { Text, Button, Chip, useTheme } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useCurrency } from '../../hooks/useCurrency';

export default function OrderConfirmationScreen({ route, navigation }) {
  const theme = useTheme();
  const { format } = useCurrency();
  const { order } = route.params || {};

  // Auto-navigate back to TableSelection after 2 seconds (matches web's 2-second redirect)
  useEffect(() => {
    const timer = setTimeout(() => {
      navigation.reset({
        index: 0,
        routes: [{ name: 'TableSelection' }],
      });
    }, 2000);
    return () => clearTimeout(timer);
  }, [navigation]);

  const total = order?.total_amount
    ? format(order.total_amount)
    : format(0);

  return (
    <View style={styles.container}>
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
            <Text variant="titleSmall" style={[styles.value, { fontFamily: 'Poppins_600SemiBold' }]}>#{order.order_number}</Text>
          </View>
        )}
        {order?.table_number && (
          <View style={styles.detailRow}>
            <Text variant="bodyMedium" style={styles.label}>Table</Text>
            <Text variant="titleSmall" style={[styles.value, { fontFamily: 'Poppins_600SemiBold' }]}>Table {order.table_number}</Text>
          </View>
        )}
        <View style={styles.detailRow}>
          <Text variant="bodyMedium" style={styles.label}>Total</Text>
          <Text variant="titleSmall" style={[styles.value, { color: theme.colors.primary, fontFamily: 'Poppins_700Bold' }]}>
            {total}
          </Text>
        </View>
        <View style={styles.detailRow}>
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

      <Text variant="bodySmall" style={styles.redirectNote}>
        Returning to table selection in a moment...
      </Text>

      {/* Action buttons */}
      <Button
        mode="contained"
        onPress={() =>
          navigation.reset({
            index: 0,
            routes: [{ name: 'TableSelection' }],
          })
        }
        style={styles.btn}
        contentStyle={styles.btnContent}
        icon="silverware-fork-knife"
      >
        Order More
      </Button>

      <Button
        mode="outlined"
        onPress={() => {
          // OrderConfirmationScreen is nested inside OrderStackNavigator (the "Order" tab).
          // To switch to the MyOrders tab we must go up to the Tab navigator first.
          navigation.getParent()?.navigate('MyOrders');
        }}
        style={styles.btn}
        contentStyle={styles.btnContent}
        icon="receipt"
      >
        View My Orders
      </Button>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  icon: { marginBottom: 16 },
  heading: { fontFamily: 'Poppins_700Bold', textAlign: 'center', marginBottom: 8 },
  subtitle: { fontFamily: 'Poppins_400Regular', opacity: 0.7, textAlign: 'center', marginBottom: 24 },
  detailsCard: {
    width: '100%',
    borderRadius: 16,
    padding: 20,
    elevation: 2,
    marginBottom: 16,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#f0f0f0',
  },
  label: { opacity: 0.7, fontFamily: 'Poppins_400Regular' },
  value: { fontFamily: 'Poppins_600SemiBold' },
  redirectNote: { opacity: 0.5, marginBottom: 24, textAlign: 'center', fontFamily: 'Poppins_400Regular' },
  btn: { width: '100%', marginBottom: 12, borderRadius: 8 },
  btnContent: { paddingVertical: 6 },
});
