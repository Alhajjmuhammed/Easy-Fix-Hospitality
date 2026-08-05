import React, { useState, useEffect, useCallback } from 'react';
import { View, FlatList, StyleSheet, RefreshControl } from 'react-native';
import {
  Text, Card, Chip, Button, ActivityIndicator,
  Snackbar, Switch, Divider, Banner,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import NetInfo from '@react-native-community/netinfo';
import { useAuthStore } from '../../store/useAuthStore';
import {
  apiMyAssignments,
  apiToggleAvailability,
} from '../../api/delivery';

const STATUS_COLOR = {
  assigned:  '#1565C0',
  picked_up: '#6A1B9A',
  delivered: '#2E7D32',
  failed:    '#B71C1C',
};

const VEHICLE_ICON = {
  motorcycle: 'motorbike',
  bicycle:    'bicycle',
  car:        'car',
  foot:       'walk',
};

export default function RiderDashboardScreen() {
  const navigation = useNavigation();
  const { user } = useAuthStore();

  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading]         = useState(true);
  const [refreshing, setRefreshing]   = useState(false);
  const [available, setAvailable]     = useState(true);
  const [togglingAvail, setTogglingAvail] = useState(false);
  const [snack, setSnack]             = useState('');
  const [isOffline, setIsOffline]     = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        setIsOffline(true);
        setLoading(false);
        setRefreshing(false);
        return;
      }
      setIsOffline(false);
      const data = await apiMyAssignments();
      setAssignments(data.assignments || []);
      setAvailable(data.is_available ?? true);
    } catch {
      setSnack('Could not load assignments');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => load(true), 30_000);
    return () => clearInterval(t);
  }, [load]);

  const handleToggleAvail = async () => {
    const net = await NetInfo.fetch();
    if (!net.isConnected) { setSnack('No internet — connect to update availability'); return; }
    setTogglingAvail(true);
    try {
      const res = await apiToggleAvailability();
      setAvailable(res.is_available);
      setSnack(res.is_available ? 'You are now available' : 'You are now offline');
    } catch {
      setSnack('Could not update availability');
    } finally {
      setTogglingAvail(false);
    }
  };

  const active = assignments.filter(a => ['assigned', 'picked_up'].includes(a.status));
  const recent = assignments.filter(a => !['assigned', 'picked_up'].includes(a.status));

  const renderItem = ({ item }) => {
    const color = STATUS_COLOR[item.status] || '#757575';
    const isActive = ['assigned', 'picked_up'].includes(item.status);
    return (
      <Card style={styles.card} onPress={() => navigation.navigate('RiderActiveDelivery', { assignmentOrderId: item.order_id })}>
        <Card.Content>
          <View style={styles.row}>
            <Text variant="titleMedium" style={styles.bold}>Order #{item.order_number}</Text>
            <Chip
              compact
              style={{ backgroundColor: color + '22' }}
              textStyle={{ color, fontSize: 11, fontFamily: 'Poppins_600SemiBold' }}
            >
              {item.status_display}
            </Chip>
          </View>
          <View style={styles.row}>
            <MaterialCommunityIcons name="map-marker" size={15} color="#757575" />
            <Text variant="bodySmall" style={styles.addr} numberOfLines={2}>
              {item.delivery_address || 'No address'}
            </Text>
          </View>
          <Text variant="bodySmall" style={styles.meta}>
            {(item.items || []).map(i => `${i.qty}× ${i.name}`).join(' · ')}
          </Text>
          <Text variant="bodySmall" style={styles.meta}>Customer: {item.customer_name}</Text>
          {isActive && (
            <Button
              mode="contained"
              style={styles.btn}
              labelStyle={{ fontFamily: 'Poppins_600SemiBold', fontSize: 13 }}
              onPress={() => navigation.navigate('RiderActiveDelivery', { assignmentOrderId: item.order_id })}
              icon="map-marker-radius"
            >
              Open Map
            </Button>
          )}
        </Card.Content>
      </Card>
    );
  };

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }

  return (
    <View style={styles.screen}>
      <Banner
        visible={isOffline}
        icon="wifi-off"
        actions={[]}
        style={{ backgroundColor: '#FFF8E1' }}
      >
        Offline – assignments not available. Connect to internet to view deliveries.
      </Banner>

      {/* Availability toggle header */}
      <View style={styles.availBar}>
        <View style={styles.availLeft}>
          <MaterialCommunityIcons
            name={VEHICLE_ICON[user?.vehicle_type] || 'motorbike'}
            size={22}
            color={available ? '#2E7D32' : '#757575'}
          />
          <Text variant="bodyMedium" style={[styles.availText, { color: available ? '#2E7D32' : '#757575' }]}>
            {available ? 'Available for delivery' : 'Offline / Not available'}
          </Text>
        </View>
        <Switch
          value={available}
          onValueChange={handleToggleAvail}
          disabled={togglingAvail}
          color="#2E7D32"
        />
      </View>

      <FlatList
        data={[...active, ...(recent.length > 0 ? [{ _divider: true }] : []), ...recent]}
        keyExtractor={(item, i) => item._divider ? 'div' : String(item.order_id)}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        renderItem={({ item }) => {
          if (item._divider) {
            return (
              <View style={styles.sectionHeader}>
                <Text variant="labelLarge" style={styles.sectionLabel}>Recent</Text>
                <Divider />
              </View>
            );
          }
          return renderItem({ item });
        }}
        ListHeaderComponent={
          active.length > 0 ? (
            <View style={styles.sectionHeader}>
              <Text variant="labelLarge" style={styles.sectionLabel}>Active</Text>
            </View>
          ) : null
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <MaterialCommunityIcons name="package-variant" size={48} color="#BDBDBD" />
            <Text variant="bodyMedium" style={{ color: '#9E9E9E', marginTop: 8, fontFamily: 'Poppins_400Regular' }}>
              No deliveries assigned yet
            </Text>
          </View>
        }
        contentContainerStyle={{ padding: 12, paddingBottom: 40 }}
      />

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>{snack}</Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  screen:       { flex: 1, backgroundColor: '#F5F5F5' },
  center:       { flex: 1, justifyContent: 'center', alignItems: 'center' },
  availBar:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
                  backgroundColor: '#fff', paddingHorizontal: 16, paddingVertical: 10,
                  borderBottomWidth: 1, borderBottomColor: '#E0E0E0' },
  availLeft:    { flexDirection: 'row', alignItems: 'center', gap: 8 },
  availText:    { fontFamily: 'Poppins_600SemiBold', fontSize: 13 },
  card:         { marginBottom: 10, borderRadius: 12 },
  row:          { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  bold:         { fontFamily: 'Poppins_700Bold' },
  addr:         { flex: 1, fontFamily: 'Poppins_400Regular', color: '#424242', marginLeft: 4 },
  meta:         { fontFamily: 'Poppins_400Regular', color: '#757575', fontSize: 12, marginTop: 2 },
  btn:          { marginTop: 10, borderRadius: 8 },
  sectionHeader:{ paddingHorizontal: 4, paddingVertical: 6 },
  sectionLabel: { fontFamily: 'Poppins_700Bold', color: '#2c3e50', marginBottom: 4 },
  empty:        { alignItems: 'center', paddingTop: 60 },
});
