import React, { useState } from 'react';
import { View, FlatList, StyleSheet, Image } from 'react-native';
import {
  Text,
  Button,
  IconButton,
  Divider,
  Snackbar,
  useTheme,
  Surface,
  Dialog,
  Portal,
} from 'react-native-paper';
import { useCartStore } from '../../store/useCartStore';
import { useAuthStore } from '../../store/useAuthStore';
import { useCurrency } from '../../hooks/useCurrency';

export default function CartScreen({ navigation }) {
  const theme = useTheme();
  const { items, tableName, updateQuantity, removeItem, getSubtotal } = useCartStore();
  const { user } = useAuthStore();
  const { format } = useCurrency();

  const [snack, setSnack] = useState('');
  const [removeId, setRemoveId] = useState(null);

  const subtotal = getSubtotal();
  const taxRate = parseFloat(user?.tax_rate) || 0;   // stored as decimal fraction: 0.08 = 8%
  const taxAmount = subtotal * taxRate;
  const finalTotal = subtotal + taxAmount;

  if (!items.length) {
    return (
      <View style={styles.emptyContainer}>
        <Text variant="headlineSmall" style={styles.emptyText}>
          Your cart is empty
        </Text>
        <Button onPress={() => navigation.navigate('Menu')} mode="outlined" style={styles.backBtn}>
          Back to Menu
        </Button>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text variant="titleMedium" style={styles.tableLabel}>
        {tableName || 'No table selected'}
      </Text>

      <FlatList
        data={items}
        keyExtractor={(i) => String(i.product.id)}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => (
          <Surface style={styles.row} elevation={1}>
            {item.product.image_url ? (
              <Image source={{ uri: item.product.image_url }} style={styles.itemImage} />
            ) : (
              <View style={[styles.itemImage, styles.itemImagePlaceholder]} />
            )}
            <View style={styles.productMeta}>
              <Text variant="bodyMedium" style={styles.productName}>
                {item.product.name}
              </Text>
              {item.product.has_promotion ? (
                <Text variant="bodySmall" style={{ fontFamily: 'Poppins_400Regular' }}>
                  <Text style={styles.strikePrice}>
                    {format(item.product.original_price)}
                  </Text>
                  {'  '}
                  <Text style={{ color: '#2e7d32', fontFamily: 'Poppins_700Bold' }}>
                    {format(item.product.current_price)}
                  </Text>
                  {' x '}{item.quantity} = {' '}
                  <Text style={{ color: theme.colors.primary, fontFamily: 'Poppins_600SemiBold' }}>
                    {format(parseFloat(item.product.current_price) * item.quantity)}
                  </Text>
                </Text>
              ) : (
                <Text variant="bodySmall" style={{ color: theme.colors.primary, fontFamily: 'Poppins_400Regular' }}>
                  {format(item.product.current_price)} x {item.quantity}{' = '}
                  {format(parseFloat(item.product.current_price) * item.quantity)}
                </Text>
              )}
            </View>
            <View style={styles.qtyRow}>
              <IconButton
                icon="minus"
                size={18}
                onPress={() => updateQuantity(item.product.id, item.quantity - 1)}
              />
              <Text variant="bodyLarge" style={{ fontFamily: 'Poppins_600SemiBold' }}>{item.quantity}</Text>
              <IconButton
                icon="plus"
                size={18}
                onPress={() => updateQuantity(item.product.id, item.quantity + 1)}
              />
              <IconButton
                icon="delete"
                size={18}
                iconColor={theme.colors.error}
                onPress={() => setRemoveId(item.product.id)}
              />
            </View>
          </Surface>
        )}
        ItemSeparatorComponent={() => <Divider />}
      />

      <Surface style={styles.footer} elevation={4}>
        <View style={styles.totalRow}>
          <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_400Regular' }}>Subtotal</Text>
          <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_400Regular' }}>{format(subtotal)}</Text>
        </View>
        {taxRate > 0 && (
          <View style={styles.totalRow}>
            <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_400Regular' }}>Tax ({taxRate}%)</Text>
            <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_400Regular' }}>{format(taxAmount)}</Text>
          </View>
        )}
        <View style={[styles.totalRow, styles.grandTotalRow]}>
          <Text variant="titleMedium" style={{ fontFamily: 'Poppins_700Bold' }}>Total</Text>
          <Text variant="titleMedium" style={{ fontFamily: 'Poppins_700Bold', color: theme.colors.primary }}>
            {format(finalTotal)}
          </Text>
        </View>

        <View style={styles.btnRow}>
          <Button
            mode="outlined"
            onPress={() => navigation.navigate('Menu')}
            style={styles.continueBtn}
            icon="arrow-left"
          >
            Continue
          </Button>
          <Button
            mode="contained"
            onPress={() => navigation.navigate('PlaceOrder')}
            style={styles.placeBtn}
            contentStyle={styles.placeBtnContent}
            icon="check-circle"
          >
            Place Order
          </Button>
        </View>
      </Surface>

      <Portal>
        <Dialog visible={!!removeId} onDismiss={() => setRemoveId(null)}>
          <Dialog.Title>Remove Item</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium" style={{ fontFamily: 'Poppins_400Regular' }}>Remove this item from your cart?</Text>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setRemoveId(null)}>Cancel</Button>
            <Button
              onPress={() => {
                removeItem(removeId);
                setRemoveId(null);
              }}
            >
              Remove
            </Button>
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
  emptyContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  emptyText: { marginBottom: 16, opacity: 0.6, fontFamily: 'Poppins_400Regular' },
  backBtn: { marginTop: 8 },
  tableLabel: { padding: 16, fontFamily: 'Poppins_700Bold' },
  list: { paddingHorizontal: 12, paddingBottom: 8 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 10,
    borderRadius: 8,
    marginVertical: 4,
  },
  itemImage: { width: 64, height: 64, borderRadius: 8, marginRight: 10 },
  itemImagePlaceholder: { backgroundColor: '#f0f0f0' },
  productMeta: { flex: 1 },
  productName: { fontFamily: 'Poppins_600SemiBold', marginBottom: 2 },
  strikePrice: { textDecorationLine: 'line-through', opacity: 0.5, fontFamily: 'Poppins_400Regular' },
  qtyRow: { flexDirection: 'row', alignItems: 'center' },
  footer: {
    padding: 16,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
  },
  totalRowText: { fontFamily: 'Poppins_400Regular' },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  grandTotalRow: {
    borderTopWidth: 1,
    borderTopColor: '#e0e0e0',
    paddingTop: 8,
    marginBottom: 12,
  },
  btnRow: { flexDirection: 'row', gap: 10 },
  continueBtn: { flex: 1 },
  placeBtn: { flex: 2, borderRadius: 8 },
  placeBtnContent: { paddingVertical: 6 },
});
