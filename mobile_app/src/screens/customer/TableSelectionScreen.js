import React, { useEffect, useState, useCallback } from 'react';
import { FlatList, StyleSheet, View } from 'react-native';
import {
  Text,
  Card,
  Chip,
  ActivityIndicator,
  FAB,
  useTheme,
  Snackbar,
  Dialog,
  Button,
  Portal,
  Divider,
  List,
} from 'react-native-paper';
import NetInfo from '@react-native-community/netinfo';
import { apiTables } from '../../api/tables';
import { getTables, saveTables } from '../../database/operations';
import { useCartStore } from '../../store/useCartStore';
import { apiActiveOrdersForTable } from '../../api/orders';
import { useAuthStore } from '../../store/useAuthStore';

export default function TableSelectionScreen({ navigation }) {
  const theme = useTheme();
  const { setTable, clearCart, setExistingOrder } = useCartStore();
  const { setRestaurant, user } = useAuthStore();
  const isStaff = user?.role_name && user.role_name !== 'customer';
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [snack, setSnack] = useState('');
  const [occupiedTable, setOccupiedTable] = useState(null);
  const [showOccupiedDialog, setShowOccupiedDialog] = useState(false);
  const [activeOrders, setActiveOrders] = useState([]);
  const [showOrderPicker, setShowOrderPicker] = useState(false);
  const [loadingOrders, setLoadingOrders] = useState(false);

  const loadTables = useCallback(async () => {
    setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (net.isConnected) {
        const data = await apiTables();
        await saveTables(data);
        setTables(data);
      } else {
        const local = await getTables();
        setTables(local);
        setSnack('Offline – showing cached tables');
      }
    } catch {
      const local = await getTables();
      setTables(local);
      setSnack('Could not refresh – showing cached data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTables();
  }, [loadTables]);

  const goToMenu = (table) => {
    setTable(table.id, `Table ${table.table_number}`, null);
    navigation.navigate('Menu', { tableId: table.id, tableName: `Table ${table.table_number}` });
  };

  const handleSelect = (table) => {
    if (!table.is_available) {
      setOccupiedTable(table);
      setShowOccupiedDialog(true);
      return;
    }
    goToMenu(table);
  };

  const handleNewOrder = () => {
    setShowOccupiedDialog(false);
    clearCart();
    goToMenu(occupiedTable);
  };

  const handleAddToExisting = async () => {
    setShowOccupiedDialog(false);
    setLoadingOrders(true);
    try {
      const orders = await apiActiveOrdersForTable(occupiedTable.id);
      if (!orders || orders.length === 0) {
        // No orders belong to this user at this table — same as web: show error, stay on table screen.
        setSnack(`You have no active orders at Table ${occupiedTable.table_number}. Choose "New Order" to start one.`);
        return;
      }
      // Always show picker — even for a single order (matches web behaviour).
      setActiveOrders(orders);
      setShowOrderPicker(true);
    } catch {
      setSnack('Could not fetch orders. Please try again.');
    } finally {
      setLoadingOrders(false);
    }
  };

  const handlePickOrder = (order) => {
    setShowOrderPicker(false);
    // Clear stale cart items before entering add-to-existing flow
    const tableName = `Table ${occupiedTable.table_number}`;
    clearCart();
    setTable(occupiedTable.id, tableName, null);
    setExistingOrder(order.id);
    navigation.navigate('Menu', { tableId: occupiedTable.id, tableName });
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {/* Change restaurant banner — only shown for customers who scanned a QR code.
          CC/cashier staff have a fixed restaurant from user.get_owner() on the backend. */}
      {!isStaff && (
        <Button
          icon="swap-horizontal"
          mode="text"
          compact
          onPress={async () => {
            await setRestaurant(null);
            navigation.replace('RestaurantSelector');
          }}
          style={styles.changeRestaurantBtn}
          labelStyle={styles.changeRestaurantLabel}
        >
          Change Restaurant
        </Button>
      )}

      <FlatList
        data={tables}
        keyExtractor={(item) => String(item.id)}
        numColumns={2}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => {
          const available = item.is_available;
          const cardBg  = available ? '#E8F5E9' : '#FFEBEE';
          const accent  = available ? '#2E7D32' : '#C62828';
          const chipBg  = available ? '#C8E6C9' : '#FFCDD2';
          return (
          <Card
            style={[styles.card, { backgroundColor: cardBg, borderColor: accent }]}
            onPress={() => handleSelect(item)}
          >
            <Card.Content style={styles.cardContent}>
              <Text variant="titleLarge" style={[styles.tableNum, { color: accent }]}>
                {item.table_number}
              </Text>
              <Chip
                mode="flat"
                style={[styles.chip, { backgroundColor: chipBg }]}
                textStyle={{ fontSize: 11, color: accent, fontFamily: 'Poppins_600SemiBold' }}
              >
                {available ? 'Available' : 'Occupied'}
              </Chip>
              {item.capacity ? (
                <Text variant="bodySmall" style={styles.capacity}>
                  Seats {item.capacity}
                </Text>
              ) : null}
            </Card.Content>
          </Card>
          );
        }}
      />

      <FAB icon="refresh" style={styles.fab} onPress={loadTables} />

      {/* Occupied table action dialog */}
      <Portal>
        <Dialog visible={showOccupiedDialog} onDismiss={() => setShowOccupiedDialog(false)}>
          <Dialog.Title>Table Occupied</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_400Regular' }}>
              Table {occupiedTable?.table_number} is currently occupied. What would you like to do?
            </Text>
          </Dialog.Content>
          <Dialog.Actions style={styles.dialogActions}>
            <Button onPress={() => setShowOccupiedDialog(false)}>Cancel</Button>
            <Button loading={loadingOrders} onPress={handleAddToExisting}>Add to Existing</Button>
            <Button mode="contained" onPress={handleNewOrder}>New Order</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      {/* Order picker dialog — always shown when adding to existing (matches web) */}
      <Portal>
        <Dialog visible={showOrderPicker} onDismiss={() => setShowOrderPicker(false)}>
          <Dialog.Title>Your Orders at Table {occupiedTable?.table_number}</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodySmall" style={{ marginBottom: 8, opacity: 0.7, fontFamily: 'Poppins_400Regular' }}>
              Select the order you want to add items to:
            </Text>
            {activeOrders.map((order, idx) => (
              <View key={order.id}>
                {idx > 0 && <Divider style={{ marginVertical: 6 }} />}
                <List.Item
                  title={`Order #${order.order_number || order.id}`}
                  titleStyle={{ fontFamily: 'Poppins_600SemiBold' }}
                  description={() => (
                    <View style={{ marginTop: 4 }}>
                      <Text style={{ fontSize: 12, color: '#555', fontFamily: 'Poppins_400Regular' }}>
                        {(order.items || []).map((i) => `${i.product_name} ×${i.quantity}`).join(', ') || 'No items'}
                      </Text>
                      <Text style={{ fontSize: 12, color: '#888', marginTop: 2, fontFamily: 'Poppins_400Regular' }}>
                        Total: {Number(order.total_amount ?? 0).toFixed(2)} · {order.status} · {order.payment_status}
                      </Text>
                    </View>
                  )}
                  left={(props) => <List.Icon {...props} icon="clipboard-list" />}
                  right={(props) => (
                    <Button {...props} compact mode="contained" onPress={() => handlePickOrder(order)}>
                      Select
                    </Button>
                  )}
                />
              </View>
            ))}
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setShowOrderPicker(false)}>Cancel</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

      <Snackbar
        visible={!!snack}
        onDismiss={() => setSnack('')}
        duration={4500}
      >
        {snack}
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  changeRestaurantBtn:   { alignSelf: 'flex-end', marginRight: 8, marginTop: 4 },
  changeRestaurantLabel: { fontSize: 12, color: '#2c3e50', fontFamily: 'Poppins_600SemiBold' },
  list: { padding: 12 },
  card: {
    flex: 1,
    margin: 6,
    borderRadius: 12,
    borderWidth: 1,
  },
  cardContent: { alignItems: 'center', paddingVertical: 10 },
  tableNum: { fontFamily: 'Poppins_700Bold', marginBottom: 6 },
  chip: { marginBottom: 4 },
  capacity: { marginTop: 4, opacity: 0.7, fontFamily: 'Poppins_400Regular' },
  fab: { position: 'absolute', right: 16, bottom: 16 },
  dialogActions: { flexWrap: 'wrap', justifyContent: 'flex-end' },
});
