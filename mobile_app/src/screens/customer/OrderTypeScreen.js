import React, { useState } from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import { Text, Card, Button, Snackbar, useTheme } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useCartStore } from '../../store/useCartStore';
import { useAuthStore } from '../../store/useAuthStore';

const ORDER_TYPES = [
  {
    type: 'delivery',
    icon: 'moped',
    title: 'Delivery',
    subtitle: 'Order now and get it delivered to your door',
    color: '#E65100',
    bg: '#FFF3E0',
  },
  {
    type: 'pickup',
    icon: 'store-clock',
    title: 'Pickup',
    subtitle: 'Order ahead and pick up at the restaurant',
    color: '#1565C0',
    bg: '#E3F2FD',
  },
];

export default function OrderTypeScreen({ route, navigation }) {
  const { restaurant } = route.params;   // { id, name, address, ... }
  const { setRemoteOrder } = useCartStore();
  const { setRestaurant } = useAuthStore();
  const [snack, setSnack] = useState('');

  const handleSelect = async (type) => {
    try {
      await setRestaurant(restaurant.id);
    } catch {
      setSnack('Could not save restaurant. Please try again.');
      return;
    }
    if (type === 'delivery') {
      navigation.navigate('DeliveryInfo', { restaurant, orderType: type });
    } else {
      // Pickup — go straight to menu
      setRemoteOrder(restaurant.id, type, '', '');
      navigation.navigate('Menu');
    }
  };

  return (
    <View style={{ flex: 1 }}>
    <ScrollView contentContainerStyle={styles.container}>
      <View style={styles.header}>
        <MaterialCommunityIcons name="silverware-fork-knife" size={40} color="#2c3e50" />
        <Text variant="headlineSmall" style={styles.title}>{restaurant.name}</Text>
        <Text variant="bodyMedium" style={styles.subtitle}>{restaurant.address}</Text>
      </View>

      <Text variant="titleMedium" style={styles.sectionLabel}>How would you like to receive your order?</Text>

      {ORDER_TYPES.map((opt) => (
        <Card
          key={opt.type}
          style={[styles.card, { borderLeftColor: opt.color }]}
          onPress={() => handleSelect(opt.type)}
        >
          <Card.Content style={styles.cardContent}>
            <View style={[styles.iconWrap, { backgroundColor: opt.bg }]}>
              <MaterialCommunityIcons name={opt.icon} size={32} color={opt.color} />
            </View>
            <View style={styles.textWrap}>
              <Text variant="titleMedium" style={[styles.optTitle, { color: opt.color }]}>
                {opt.title}
              </Text>
              <Text variant="bodySmall" style={styles.optSub}>{opt.subtitle}</Text>
            </View>
            <MaterialCommunityIcons name="chevron-right" size={24} color="#ccc" />
          </Card.Content>
        </Card>
      ))}

      <Button
        mode="outlined"
        icon="arrow-left"
        onPress={() => navigation.goBack()}
        style={styles.backBtn}
      >
        Back
      </Button>
    </ScrollView>
    <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
      {snack}
    </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20, paddingBottom: 40 },
  header: { alignItems: 'center', marginBottom: 28 },
  title: { fontFamily: 'Poppins_700Bold', color: '#2c3e50', marginTop: 10, textAlign: 'center' },
  subtitle: { color: '#888', fontFamily: 'Poppins_400Regular', textAlign: 'center', marginTop: 4 },
  sectionLabel: { fontFamily: 'Poppins_600SemiBold', color: '#2c3e50', marginBottom: 14 },
  card: {
    marginBottom: 14,
    borderRadius: 14,
    borderLeftWidth: 4,
    elevation: 2,
  },
  cardContent: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    gap: 14,
  },
  iconWrap: {
    width: 56,
    height: 56,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  textWrap: { flex: 1 },
  optTitle: { fontFamily: 'Poppins_700Bold' },
  optSub: { fontFamily: 'Poppins_400Regular', color: '#666', marginTop: 2 },
  backBtn: { marginTop: 10, borderColor: '#ccc' },
});
