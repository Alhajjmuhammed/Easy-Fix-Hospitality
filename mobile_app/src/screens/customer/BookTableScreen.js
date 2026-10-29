import React, { useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { Button, IconButton, Snackbar, Text, TextInput } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useAuthStore } from '../../store/useAuthStore';
import { apiCreateReservation } from '../../api/reservations';
import DateTimeChips, { upcomingDates } from '../../components/DateTimeChips';

export default function BookTableScreen({ route, navigation }) {
  const { restaurant } = route.params;   // { id, name, reservations_auto_confirm, ... }
  const user = useAuthStore((s) => s.user);

  const [date, setDate] = useState(upcomingDates(1)[0].value);
  const [time, setTime] = useState('');
  const [people, setPeople] = useState(2);
  const [name, setName] = useState([user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || '');
  const [phone, setPhone] = useState(user?.phone_number || '');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [snack, setSnack] = useState('');

  const submit = async () => {
    if (!time) { setSnack('Please choose a time.'); return; }
    if (!name.trim() || !phone.trim()) { setSnack('Please enter your name and phone number.'); return; }
    setSaving(true);
    try {
      const { reservation } = await apiCreateReservation({
        restaurant_id: restaurant.id, date, time, party_size: people,
        name: name.trim(), phone: phone.trim(), notes: notes.trim(),
      });
      navigation.replace('MyReservations', {
        message: reservation.status === 'confirmed'
          ? 'Your table is confirmed.'
          : 'Booking request sent. You will be notified when the restaurant confirms.',
      });
    } catch (err) {
      setSnack(err?.response?.data?.error || 'Could not book. Please check your connection and try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <View style={styles.header}>
          <MaterialCommunityIcons name="calendar-check" size={40} color="#2e7d32" />
          <Text variant="headlineSmall" style={styles.title}>Book a Table</Text>
          <Text variant="bodyMedium" style={styles.subtitle}>{restaurant.name}</Text>
          {!restaurant.reservations_auto_confirm && (
            <Text variant="bodySmall" style={styles.subtitle}>The restaurant will confirm your booking.</Text>
          )}
        </View>

        <Text variant="titleSmall" style={styles.label}>Number of people</Text>
        <View style={styles.people}>
          <IconButton icon="minus" mode="outlined" onPress={() => setPeople((p) => Math.max(1, p - 1))} />
          <Text variant="headlineSmall" style={{ fontFamily: 'Poppins_700Bold', minWidth: 40, textAlign: 'center' }}>{people}</Text>
          <IconButton icon="plus" mode="outlined" onPress={() => setPeople((p) => Math.min(100, p + 1))} />
        </View>

        <DateTimeChips date={date} time={time} onDate={setDate} onTime={setTime} />

        <TextInput label="Name for the booking" value={name} onChangeText={setName} mode="outlined"
                   style={styles.input} maxLength={120} />
        <TextInput label="Phone" value={phone} onChangeText={setPhone} mode="outlined" keyboardType="phone-pad"
                   style={styles.input} maxLength={30} />
        <TextInput label="Requests (optional)" value={notes} onChangeText={setNotes} mode="outlined" multiline
                   numberOfLines={2} style={styles.input} maxLength={1000} placeholder="Birthday, high chair…" />

        <Button mode="contained" icon="check-circle" onPress={submit} loading={saving} disabled={saving}
                style={styles.submit} contentStyle={{ paddingVertical: 6 }}>
          Request booking
        </Button>
      </ScrollView>
      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={4000}>{snack}</Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20, paddingBottom: 40 },
  header: { alignItems: 'center', marginBottom: 12 },
  title: { fontFamily: 'Poppins_700Bold', color: '#2c3e50', marginTop: 8 },
  subtitle: { color: '#777', fontFamily: 'Poppins_400Regular', textAlign: 'center', marginTop: 2 },
  label: { fontFamily: 'Poppins_600SemiBold', marginTop: 12, marginBottom: 4 },
  people: { flexDirection: 'row', alignItems: 'center' },
  input: { marginTop: 12 },
  submit: { marginTop: 20, borderRadius: 10 },
});
