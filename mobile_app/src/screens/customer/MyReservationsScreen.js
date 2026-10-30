import React, { useCallback, useEffect, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { Button, Card, Chip, Dialog, Portal, Snackbar, Text } from 'react-native-paper';
import { useFocusEffect } from '@react-navigation/native';
import { apiCancelReservation, apiReservations } from '../../api/reservations';
import { useT } from '../../i18n';

const STATUS_COLORS = {
  pending: '#F9A825', confirmed: '#2E7D32', seated: '#1565C0', completed: '#757575',
  declined: '#C62828', cancelled: '#C62828', no_show: '#C62828',
};

export default function MyReservationsScreen({ route }) {
  const t = useT();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [snack, setSnack] = useState(route?.params?.message || '');
  const [confirmCancel, setConfirmCancel] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await apiReservations();
      setItems(data.reservations || []);
    } catch {
      setSnack(t('Could not load reservations. Pull down to retry.'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => { if (route?.params?.message) setSnack(route.params.message); }, [route?.params?.message]);

  const doCancel = async () => {
    const res = confirmCancel;
    setConfirmCancel(null);
    try {
      await apiCancelReservation(res.id);
      setSnack(t('Reservation cancelled.'));
      load();
    } catch (err) {
      setSnack(err?.response?.data?.error || t('Could not cancel. Please try again.'));
    }
  };

  return (
    <View style={{ flex: 1 }}>
      <FlatList
        data={items}
        keyExtractor={(r) => String(r.id)}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => { setLoading(true); load(); }} />}
        ListEmptyComponent={!loading && (
          <Text style={styles.empty}>{t("No reservations yet. Book a table from a restaurant's page.")}</Text>
        )}
        renderItem={({ item }) => (
          <Card style={styles.card}>
            <Card.Content>
              <View style={styles.row}>
                <Text variant="titleMedium" style={styles.name}>{item.restaurant_name}</Text>
                <Chip compact textStyle={{ color: '#fff', fontSize: 11 }}
                      style={{ backgroundColor: STATUS_COLORS[item.status] || '#757575' }}>
                  {item.status === 'pending' ? t('Waiting for confirmation') : item.status_display}
                </Chip>
              </View>
              <Text style={styles.meta}>
                {t('{date} at {time}', { date: item.date, time: item.time })} · {t('{n} people', { n: item.party_size })}
                {item.table_number ? ` · ${t('Table {n}', { n: item.table_number })}` : ''}
              </Text>
              {!!item.notes && <Text style={styles.meta}>“{item.notes}”</Text>}
              {item.can_cancel && (
                <Button mode="text" textColor="#C62828" onPress={() => setConfirmCancel(item)} style={{ alignSelf: 'flex-start' }}>
                  {t('Cancel booking')}
                </Button>
              )}
            </Card.Content>
          </Card>
        )}
      />
      <Portal>
        <Dialog visible={!!confirmCancel} onDismiss={() => setConfirmCancel(null)}>
          <Dialog.Title>{t('Cancel reservation?')}</Dialog.Title>
          <Dialog.Content>
            <Text>{confirmCancel ? `${confirmCancel.restaurant_name}, ${t('{date} at {time}', { date: confirmCancel.date, time: confirmCancel.time })}` : ''}</Text>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setConfirmCancel(null)}>{t('Keep')}</Button>
            <Button textColor="#C62828" onPress={doCancel}>{t('Cancel it')}</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={4000}>{snack}</Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 32 },
  card: { marginBottom: 12, borderRadius: 12 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  name: { fontFamily: 'Poppins_700Bold', flex: 1 },
  meta: { color: '#555', fontFamily: 'Poppins_400Regular', marginTop: 4 },
  empty: { textAlign: 'center', color: '#888', marginTop: 40, fontFamily: 'Poppins_400Regular' },
});
