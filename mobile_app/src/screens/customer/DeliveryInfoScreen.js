import React, { useState } from 'react';
import { View, StyleSheet, ScrollView, KeyboardAvoidingView, Platform } from 'react-native';
import {
  Text, TextInput, Button, Surface, useTheme, Snackbar,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useCartStore } from '../../store/useCartStore';

export default function DeliveryInfoScreen({ route, navigation }) {
  const { restaurant, orderType } = route.params;
  const { setRemoteOrder } = useCartStore();

  const [address, setAddress]   = useState('');
  const [phone,   setPhone]     = useState('');
  const [snack,   setSnack]     = useState('');

  const handleContinue = () => {
    if (!address.trim()) {
      setSnack('Please enter your delivery address.');
      return;
    }
    if (!phone.trim()) {
      setSnack('Please enter your phone number so the rider can contact you.');
      return;
    }
    setRemoteOrder(restaurant.id, orderType, address.trim(), phone.trim());
    navigation.navigate('Menu');
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.container}>
        {/* Header */}
        <Surface style={styles.header} elevation={0}>
          <MaterialCommunityIcons name="moped" size={40} color="#E65100" />
          <Text variant="headlineSmall" style={styles.title}>Delivery Details</Text>
          <Text variant="bodyMedium" style={styles.subtitle}>Ordering from {restaurant.name}</Text>
        </Surface>

        <Text variant="bodyMedium" style={styles.hint}>
          Our delivery rider will use these details to deliver your order.
        </Text>

        {/* Address */}
        <TextInput
          label="Delivery Address *"
          value={address}
          onChangeText={setAddress}
          mode="outlined"
          multiline
          numberOfLines={3}
          placeholder="Street, building, floor, landmark…"
          style={styles.input}
          left={<TextInput.Icon icon="map-marker" />}
        />

        {/* Phone */}
        <TextInput
          label="Phone Number *"
          value={phone}
          onChangeText={setPhone}
          mode="outlined"
          keyboardType="phone-pad"
          placeholder="+1 555 000 0000"
          style={styles.input}
          left={<TextInput.Icon icon="phone" />}
        />

        <Button
          mode="contained"
          icon="silverware-fork-knife"
          onPress={handleContinue}
          style={styles.continueBtn}
          contentStyle={styles.continueBtnContent}
          labelStyle={{ fontFamily: 'Poppins_700Bold', fontSize: 15 }}
        >
          Browse Menu
        </Button>

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
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20, paddingBottom: 40 },
  header: {
    alignItems: 'center',
    backgroundColor: '#FFF3E0',
    padding: 24,
    borderRadius: 16,
    marginBottom: 20,
  },
  title: { fontFamily: 'Poppins_700Bold', color: '#E65100', marginTop: 10, textAlign: 'center' },
  subtitle: { color: '#888', fontFamily: 'Poppins_400Regular', textAlign: 'center', marginTop: 4 },
  hint: {
    fontFamily: 'Poppins_400Regular',
    color: '#555',
    marginBottom: 20,
    lineHeight: 22,
  },
  input: { marginBottom: 16, fontFamily: 'Poppins_400Regular' },
  continueBtn: {
    marginTop: 8,
    borderRadius: 10,
    backgroundColor: '#E65100',
  },
  continueBtnContent: { paddingVertical: 6 },
  backBtn: { marginTop: 10, borderColor: '#ccc' },
});
