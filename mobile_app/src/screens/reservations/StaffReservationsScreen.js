import React, { useCallback, useState } from 'react';
import { FlatList, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import {
  Banner, Button, Card, Chip, Dialog, FAB, IconButton, Menu, Portal, Snackbar, Text, TextInput,
} from 'react-native-paper';
import { useFocusEffect } from '@react-navigation/native';
import {
  apiCreateReservation, apiReservations, apiReservationStatus, apiReservationTable,
} from '../../api/reservations';
import { apiTables } from '../../api/tables';
import DateTimeChips, { upcomingDates } from '../../components/DateTimeChips';
import { useT } from '../../i18n';

const LABELS = {
  confirmed: 'Confirm', declined: 'Decline', cancelled: 'Cancel', seated: 'Seated',
  completed: 'Completed', no_show: 'No-show',
};
const DANGER = ['declined', 'cancelled', 'no_show'];
const STATUS_COLORS = {
  pending: '#F9A825', confirmed: '#2E7D32', seated: '#1565C0', completed: '#757575',
  declined: '#C62828', cancelled: '#C62828', no_show: '#C62828',
};

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const shiftDay = (value, days) => {
  const [y, m, d] = value.split('-').map(Number);
  return isoDate(new Date(y, m - 1, d + days));
};

export default function StaffReservationsScreen() {
  const t = useT();
  const [day, setDay] = useState(isoDate(new Date()));
  const [filter, setFilter] = useState('active');
  const [data, setData] = useState({ reservations: [], pending_upcoming: [], can_manage: false });
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [snack, setSnack] = useState('');
  const [tableMenuFor, setTableMenuFor] = useState(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: '', phone: '', people: '2', date: upcomingDates(1)[0].value, time: '', notes: '', restaurantId: null });
  const restaurants = data.restaurants || [];
  const defaultRestaurantId = (restaurants.find((r) => r.default) || restaurants[0] || {}).id;

  const load = useCallback(async () => {
    try {
      const [res, tbl] = await Promise.all([apiReservations({ date: day, status: filter }), apiTables().catch(() => [])]);
      setData(res);
      setTables(tbl || []);
    } catch (err) {
      setSnack(err?.response?.status === 403
        ? "You don't have permission to view reservations."
        : 'Could not load reservations. Pull down to retry.');
    } finally {
      setLoading(false);
    }
  }, [day, filter]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const showWarnings = (warnings, fallback) => setSnack(warnings && warnings.length ? warnings.join(' ') : fallback);

  const changeStatus = async (res, status) => {
    try {
      await apiReservationStatus(res.id, status);
      setSnack(`${res.name}: ${LABELS[status] ? t(LABELS[status]) : status}`);
      load();
    } catch (err) {
      setSnack(err?.response?.data?.error || 'Could not update. Please try again.');
    }
  };

  const setTable = async (res, tableId) => {
    setTableMenuFor(null);
    try {
      const r = await apiReservationTable(res.id, tableId);
      showWarnings(r.warnings, tableId ? t('Table set for {name}', { name: res.name }) : t('Table cleared for {name}', { name: res.name }));
      load();
    } catch (err) {
      setSnack(err?.response?.data?.error || 'Could not set the table.');
    }
  };

  const addBooking = async () => {
    const people = Number(form.people);
    if (!form.name.trim() || !form.phone.trim() || !form.time) {
      setSnack('Name, phone and time are required.');
      return;
    }
    if (!Number.isInteger(people) || people < 1 || people > 100) {
      setSnack('Number of people must be between 1 and 100.');
      return;
    }
    try {
      const r = await apiCreateReservation({
        name: form.name.trim(), phone: form.phone.trim(), party_size: people,
        date: form.date, time: form.time, notes: form.notes.trim(),
        restaurant_id: form.restaurantId || defaultRestaurantId,
      });
      setAdding(false);
      setForm((f) => ({ ...f, name: '', phone: '', notes: '', time: '' }));
      if (form.date === day) load(); else setDay(form.date);   // same day: reload explicitly
      showWarnings(r.warnings, t('Booking added for {name}', { name: r.reservation.name }));
    } catch (err) {
      setSnack(err?.response?.data?.error || 'Could not add the booking.');
    }
  };

  // Older tables have no restaurant link; they belong to the owner's own (default) restaurant.
  const tablesFor = (res) => tables.filter((tb) => tb.restaurant_id === res.restaurant_id
    || (tb.restaurant_id == null && res.restaurant_id === defaultRestaurantId));

  return (
    <View style={{ flex: 1 }}>
      {data.pending_upcoming?.length > 0 && (
        <Banner visible icon="timer-sand" style={{ backgroundColor: '#FFF8E1' }}
                actions={[{ label: t('Show'), onPress: () => { setDay(data.pending_upcoming[0].date); setFilter('pending'); } }]}>
          {data.pending_upcoming.length > 1
            ? t('{n} bookings waiting for confirmation', { n: data.pending_upcoming.length })
            : t('{n} booking waiting for confirmation', { n: data.pending_upcoming.length })}
        </Banner>
      )}
      <View style={styles.toolbar}>
        <IconButton icon="chevron-left" onPress={() => setDay((d) => shiftDay(d, -1))} />
        <Button compact onPress={() => setDay(isoDate(new Date()))}>{day}</Button>
        <IconButton icon="chevron-right" onPress={() => setDay((d) => shiftDay(d, 1))} />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
          {[['active', 'Active'], ['pending', 'Pending'], ['all', 'All']].map(([k, label]) => (
            <Chip key={k} compact selected={filter === k} onPress={() => setFilter(k)}>{t(label)}</Chip>
          ))}
        </ScrollView>
      </View>

      <FlatList
        data={data.reservations}
        keyExtractor={(r) => String(r.id)}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => { setLoading(true); load(); }} />}
        ListEmptyComponent={!loading && <Text style={styles.empty}>{t('No bookings for this day.')}</Text>}
        renderItem={({ item }) => (
          <Card style={[styles.card, { borderLeftColor: STATUS_COLORS[item.status] || '#ccc' }]}>
            <Card.Content>
              <View style={styles.row}>
                <Text variant="titleMedium" style={styles.time}>{item.time}</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>{item.name} · {t('{n} people', { n: item.party_size })}</Text>
                  <Text style={styles.meta}>
                    {item.phone} · {item.table_number ? t('Table {n}', { n: item.table_number }) : t('No table')}
                  </Text>
                  {!!item.notes && <Text style={styles.meta}>“{item.notes}”</Text>}
                  {(item.warnings || []).map((w, i) => <Text key={i} style={styles.warning}>⚠ {w}</Text>)}
                </View>
                <Chip compact textStyle={{ color: '#fff', fontSize: 11 }}
                      style={{ backgroundColor: STATUS_COLORS[item.status] || '#757575' }}>{item.status_display}</Chip>
              </View>
              {data.can_manage && (
                <View style={styles.actions}>
                  {(item.next_statuses || []).map((s) => (
                    <Button key={s} compact mode={DANGER.includes(s) ? 'outlined' : 'contained'}
                            textColor={DANGER.includes(s) ? '#C62828' : undefined}
                            onPress={() => changeStatus(item, s)}>{LABELS[s] ? t(LABELS[s]) : s}</Button>
                  ))}
                  {['pending', 'confirmed', 'seated'].includes(item.status) && (
                    <Menu visible={tableMenuFor === item.id} onDismiss={() => setTableMenuFor(null)}
                          anchor={<Button compact icon="table-chair" onPress={() => setTableMenuFor(item.id)}>{t('Table')}</Button>}>
                      <Menu.Item title={t('No table')} onPress={() => setTable(item, null)} />
                      {tablesFor(item).map((tb) => (
                        <Menu.Item key={tb.id} title={`${tb.tbl_no} (${tb.capacity})`} onPress={() => setTable(item, tb.id)} />
                      ))}
                    </Menu>
                  )}
                </View>
              )}
            </Card.Content>
          </Card>
        )}
      />

      {data.can_manage && <FAB icon="plus" label={t('Add booking')} style={styles.fab} onPress={() => setAdding(true)} />}

      <Portal>
        <Dialog visible={adding} onDismiss={() => setAdding(false)} style={{ maxHeight: '90%' }}>
          <Dialog.Title>{t('Add booking')}</Dialog.Title>
          <Dialog.ScrollArea>
            <ScrollView keyboardShouldPersistTaps="handled">
              {restaurants.length > 1 && (
                <View style={styles.restaurantRow}>
                  {restaurants.map((r) => (
                    <Chip key={r.id} compact selected={(form.restaurantId || defaultRestaurantId) === r.id}
                          onPress={() => setForm((f) => ({ ...f, restaurantId: r.id }))}>{r.name}</Chip>
                  ))}
                </View>
              )}
              <TextInput label={t('Name')} value={form.name} onChangeText={(v) => setForm({ ...form, name: v })} mode="outlined" style={styles.input} />
              <TextInput label={t('Phone')} value={form.phone} keyboardType="phone-pad" onChangeText={(v) => setForm({ ...form, phone: v })} mode="outlined" style={styles.input} />
              <TextInput label={t('People')} value={form.people} keyboardType="number-pad" onChangeText={(v) => setForm({ ...form, people: v.replace(/\D/g, '') })} mode="outlined" style={styles.input} />
              <DateTimeChips date={form.date} time={form.time} minLeadMinutes={-24 * 60}
                             onDate={(v) => setForm((f) => ({ ...f, date: v }))} onTime={(v) => setForm((f) => ({ ...f, time: v }))} />
              <TextInput label={t('Notes')} value={form.notes} onChangeText={(v) => setForm({ ...form, notes: v })} mode="outlined" style={styles.input} />
            </ScrollView>
          </Dialog.ScrollArea>
          <Dialog.Actions>
            <Button onPress={() => setAdding(false)}>{t('Close')}</Button>
            <Button mode="contained" onPress={addBooking}>{t('Save')}</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={5000}>{t(snack)}</Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  toolbar: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 4 },
  list: { padding: 12, paddingBottom: 96 },
  card: { marginBottom: 10, borderRadius: 10, borderLeftWidth: 4 },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  time: { fontFamily: 'Poppins_700Bold', minWidth: 52 },
  name: { fontFamily: 'Poppins_600SemiBold' },
  meta: { color: '#555', fontFamily: 'Poppins_400Regular', fontSize: 12, marginTop: 2 },
  warning: { color: '#C62828', fontSize: 12, marginTop: 2 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 },
  empty: { textAlign: 'center', color: '#888', marginTop: 40, fontFamily: 'Poppins_400Regular' },
  fab: { position: 'absolute', right: 16, bottom: 16 },
  input: { marginTop: 8 },
  restaurantRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 },
});
