import React, { useEffect, useState, useCallback, useRef } from 'react';
import { ScrollView, View, StyleSheet, RefreshControl, FlatList, TouchableOpacity, Modal } from 'react-native';
import {
  Text,
  Card,
  Chip,
  ActivityIndicator,
  Snackbar,
  Divider,
  Surface,
  SegmentedButtons,
  Banner,
  Button,
  Checkbox,
} from 'react-native-paper';
import NetInfo from '@react-native-community/netinfo';
import client from '../../api/client';
import { getOfflinePendingOrders, getSyncMeta, setSyncMeta, getLocalReportStats } from '../../database/operations';
import { useCurrency } from '../../hooks/useCurrency';
import { MaterialCommunityIcons } from '@expo/vector-icons';

const PAYMENT_STATUS_COLOR = {
  unpaid:  '#C62828',
  partial: '#FF8F00',
  paid:    '#2E7D32',
};

const ORDER_STATUS_COLOR = {
  pending:   '#FF8F00',
  confirmed: '#2c3e50',
  preparing: '#6A1B9A',
  ready:     '#2E7D32',
  served:    '#2E7D32',
  cancelled: '#C62828',
};

const PERIODS = [
  { value: 'today',   label: 'Today' },
  { value: 'weekly',  label: 'This Week' },
  { value: 'monthly', label: 'This Month' },
];

export default function CCReportsScreen() {
  const [loading,        setLoading]        = useState(true);
  const [refreshing,     setRefreshing]     = useState(false);
  const [data,           setData]           = useState(null);
  const [snack,          setSnack]          = useState('');
  const [period,         setPeriod]         = useState('today');
  const [isOffline,      setIsOffline]      = useState(false);
  const [offlineOrders,  setOfflineOrders]  = useState([]);
  const [cacheTimestamp, setCacheTimestamp] = useState(null);
  const [selectedPids,   setSelectedPids]   = useState([]);
  const [tempPids,       setTempPids]       = useState([]);
  const [showPicker,     setShowPicker]     = useState(false);
  const { format } = useCurrency();
  // Ref so fetchReport can always read the latest pids without being a closure dep
  const selectedPidsRef = useRef([]);
  useEffect(() => { selectedPidsRef.current = selectedPids; }, [selectedPids]);

  const fetchReport = useCallback(async (silent = false, pids) => {
    // pids passed explicitly (Apply/Clear); fall back to ref for initial/refresh fetches
    const effectivePids = pids !== undefined ? pids : selectedPidsRef.current;
    if (!silent) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        const [cached, cachedTs, pending] = await Promise.all([
          getSyncMeta('cc_report_cache'),
          getSyncMeta('cc_report_cache_ts'),
          getOfflinePendingOrders(),
        ]);
        if (cached) {
          setData(JSON.parse(cached));
          setCacheTimestamp(cachedTs || null);
        } else {
          const localStats = await getLocalReportStats();
          setData(localStats);
          setCacheTimestamp(null);
          setSnack('Offline – showing locally computed data');
        }
        setOfflineOrders(pending);
        setIsOffline(true);
      } else {
        const params = { period };
        if (effectivePids.length > 0) params.product_ids = effectivePids.join(',');
        const res = await client.get('/reports/cc/', { params });
        setData(res.data);
        setIsOffline(false);
        setCacheTimestamp(null);
        const pending = await getOfflinePendingOrders();
        setOfflineOrders(pending);
        await Promise.all([
          setSyncMeta('cc_report_cache', JSON.stringify(res.data)),
          setSyncMeta('cc_report_cache_ts', new Date().toISOString()),
        ]);
      }
    } catch {
      try {
        const [cached, cachedTs, pending] = await Promise.all([
          getSyncMeta('cc_report_cache'),
          getSyncMeta('cc_report_cache_ts'),
          getOfflinePendingOrders(),
        ]);
        if (cached) {
          setData(JSON.parse(cached));
          setCacheTimestamp(cachedTs || null);
          setSnack('Using cached data – could not reach server');
        } else {
          const localStats = await getLocalReportStats();
          setData(localStats);
          setCacheTimestamp(null);
          setSnack('Offline – showing locally computed data');
        }
        setOfflineOrders(pending);
      } catch {
        setOfflineOrders([]);
        setData(null);
        setSnack('Could not load report');
      }
      setIsOffline(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [period]); // selectedPids intentionally omitted — accessed via ref to avoid double-fetch

  useEffect(() => { fetchReport(); }, [fetchReport]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const stats  = data?.stats  || {};
  const orders = data?.orders || [];
  const pendingOrders = offlineOrders.filter((o) => !o._is_sync_error);
  const errorOrders   = offlineOrders.filter((o) => o._is_sync_error);
  const offlineTotal  = pendingOrders.reduce((s, o) => s + (o.total_amount || 0), 0);

  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); fetchReport(true); }} />
      }
    >
      {/* Product picker modal */}
      <Modal visible={showPicker} transparent animationType="slide" onRequestClose={() => setShowPicker(false)}>
        <View style={styles.pickerOverlay}>
          <View style={styles.pickerSheet}>
            <View style={styles.pickerHeader}>
              <Text variant="titleMedium" style={{ fontFamily: 'Poppins_700Bold' }}>Filter by Product</Text>
              <TouchableOpacity onPress={() => setShowPicker(false)}>
                <MaterialCommunityIcons name="close" size={22} color="#666" />
              </TouchableOpacity>
            </View>
            <FlatList
              data={data?.products || []}
              keyExtractor={(item) => String(item.id)}
              style={{ maxHeight: 360 }}
              ListEmptyComponent={() => (
                <Text style={{ textAlign: 'center', opacity: 0.5, padding: 20 }}>No products available</Text>
              )}
              renderItem={({ item }) => {
                const checked = tempPids.includes(item.id);
                return (
                  <TouchableOpacity
                    style={styles.pickerRow}
                    onPress={() => setTempPids((prev) =>
                      checked ? prev.filter((id) => id !== item.id) : [...prev, item.id]
                    )}
                  >
                    <Checkbox status={checked ? 'checked' : 'unchecked'} />
                    <View style={{ flex: 1 }}>
                      <Text variant="bodySmall" style={{ fontFamily: 'Poppins_600SemiBold' }} numberOfLines={1}>{item.name}</Text>
                      <Text variant="bodySmall" style={{ opacity: 0.55, fontSize: 11 }}>{item['main_category__name']}</Text>
                    </View>
                  </TouchableOpacity>
                );
              }}
            />
            <Divider />
            <View style={styles.pickerActions}>
              <Button mode="outlined" onPress={() => setTempPids([])} style={{ flex: 1 }}>Clear</Button>
              <Button mode="contained" onPress={() => {
                setSelectedPids(tempPids);
                setShowPicker(false);
                fetchReport(false, tempPids);
              }} style={{ flex: 1 }}>Apply</Button>
            </View>
          </View>
        </View>
      </Modal>

      {/* Offline banner */}
      <Banner
        visible={isOffline || offlineOrders.length > 0}
        icon={isOffline ? 'wifi-off' : 'cloud-upload'}
        actions={[]}
        style={{ backgroundColor: isOffline ? '#FFF8E1' : '#E8F5E9', marginHorizontal: -16, marginTop: -16, marginBottom: 12 }}
      >
        {isOffline
          ? cacheTimestamp
            ? `Offline – cached report from ${new Date(cacheTimestamp).toLocaleTimeString()}. Pull to refresh when connected.`
            : `Offline – showing data from local device. Connect for the full server report.`
          : `${pendingOrders.length} queued for sync · ${errorOrders.length} failed – check below.`}
      </Banner>

      {/* Sync-failed orders */}
      {errorOrders.length > 0 && (
        <>
          <Text variant="labelLarge" style={[styles.sectionTitle, { color: '#C62828' }]}>
            Failed to Sync – Re-take Manually
          </Text>
          {errorOrders.map((o) => (
            <Card key={o.offline_id} style={[styles.card, { borderLeftWidth: 4, borderLeftColor: '#C62828' }]}>
              <Card.Content>
                <View style={styles.row}>
                  <Chip icon="alert-circle" mode="flat" compact
                    style={{ backgroundColor: '#FFEBEE' }} textStyle={{ fontSize: 10, color: '#C62828' }}>
                    SYNC FAILED
                  </Chip>
                  <Text variant="bodySmall" style={{ fontFamily: 'Poppins_700Bold' }}>
                    {format(o.total_amount || 0)}
                  </Text>
                </View>
                <Text variant="bodySmall" style={{ opacity: 0.65 }}>
                  {o.order_type === 'delivery' ? '🚴 Delivery' : `Table ${o.table_number}`}
                  {' · '}{o.items_count} item{o.items_count !== 1 ? 's' : ''}
                  {' · '}{new Date(o.created_at).toLocaleTimeString()}
                </Text>
                {!!o.error_message && (
                  <Text variant="bodySmall" style={{ color: '#C62828', fontSize: 10, marginTop: 2 }}>
                    {o.error_message}
                  </Text>
                )}
              </Card.Content>
            </Card>
          ))}
          <Divider style={styles.divider} />
        </>
      )}

      {/* Offline queued orders */}
      {pendingOrders.length > 0 && (
        <>
          <Text variant="labelLarge" style={[styles.sectionTitle, { color: '#E65100' }]}>
            Queued Orders (Pending Sync)
          </Text>
          <Card style={[styles.card, { borderLeftWidth: 4, borderLeftColor: '#E65100' }]}>
            <Card.Content>
              <View style={styles.row}>
                <View style={{ alignItems: 'center', flex: 1 }}>
                  <Text style={{ fontFamily: 'Poppins_700Bold', fontSize: 22, color: '#E65100' }}>
                    {pendingOrders.length}
                  </Text>
                  <Text style={styles.statLabel}>Queued Orders</Text>
                </View>
                <View style={{ alignItems: 'center', flex: 1 }}>
                  <Text style={{ fontFamily: 'Poppins_700Bold', fontSize: 22, color: '#E65100' }}>
                    {format(offlineTotal)}
                  </Text>
                  <Text style={styles.statLabel}>Queued Total</Text>
                </View>
              </View>
            </Card.Content>
          </Card>
          {pendingOrders.map((o) => (
            <Card key={o.offline_id} style={[styles.card, { borderLeftWidth: 3, borderLeftColor: '#FFA726' }]}>
              <Card.Content>
                <View style={styles.row}>
                  <Chip icon="cloud-upload" mode="flat" compact
                    style={{ backgroundColor: '#FFF3E0' }} textStyle={{ fontSize: 10, color: '#E65100' }}>
                    PENDING SYNC
                  </Chip>
                  <Text variant="bodySmall" style={{ fontFamily: 'Poppins_700Bold' }}>
                    {format(o.total_amount || 0)}
                  </Text>
                </View>
                <Text variant="bodySmall" style={{ opacity: 0.65 }}>
                  {o.order_type === 'delivery' ? '🚴 Delivery' : `Table ${o.table_number}`}
                  {' · '}{o.items_count} item{o.items_count !== 1 ? 's' : ''}
                  {' · '}{new Date(o.created_at).toLocaleTimeString()}
                </Text>
              </Card.Content>
            </Card>
          ))}
          {!isOffline && <Divider style={styles.divider} />}
        </>
      )}

      {/* Report */}
      {isOffline && !data ? (
        <Card style={styles.card}>
          <Card.Content style={styles.emptyContent}>
            <MaterialCommunityIcons name="wifi-off" size={40} color="#ccc" />
            <Text variant="bodyMedium" style={{ opacity: 0.5, marginTop: 8, textAlign: 'center' }}>
              Connect to internet to load the report
            </Text>
          </Card.Content>
        </Card>
      ) : data ? (
        <>
          {/* Period selector */}
          <SegmentedButtons
            value={period}
            onValueChange={setPeriod}
            buttons={PERIODS}
            style={styles.periods}
          />

          {/* Product filter chip */}
          <TouchableOpacity
            onPress={() => { setTempPids(selectedPids); setShowPicker(true); }}
            style={styles.filterChipRow}
          >
            <Chip
              icon="food-outline"
              mode={selectedPids.length > 0 ? 'flat' : 'outlined'}
              style={selectedPids.length > 0 ? { backgroundColor: '#1565C022' } : {}}
              textStyle={selectedPids.length > 0 ? { color: '#1565C0' } : {}}
            >
              {selectedPids.length === 0
                ? 'All Products'
                : `${selectedPids.length} Product${selectedPids.length > 1 ? 's' : ''} Selected`}
            </Chip>
            {selectedPids.length > 0 && (
              <TouchableOpacity onPress={() => { setSelectedPids([]); fetchReport(false, []); }} style={{ marginLeft: 6 }}>
                <MaterialCommunityIcons name="close-circle" size={18} color="#C62828" />
              </TouchableOpacity>
            )}
          </TouchableOpacity>

          {/* Stats cards */}
          <View style={styles.statsRow}>
            <StatCard label="Orders"    value={stats.total_orders}               color="#2c3e50" icon="clipboard-list-outline" />
            <StatCard label="Revenue"   value={format(stats.total_revenue ?? 0)} color="#2E7D32" icon="cash-multiple" />
            <StatCard label="Items"     value={stats.total_items}                color="#6A1B9A" icon="food-outline" />
            <StatCard label="Avg Order" value={format(stats.avg_order_value ?? 0)} color="#FF8F00" icon="chart-line" />
          </View>

          {/* Payment breakdown */}
          <Card style={styles.card}>
            <Card.Content>
              <Text variant="titleSmall" style={styles.cardTitle}>Payment Breakdown</Text>
              <View style={styles.breakdownRow}>
                <BreakdownChip label="Paid"    value={stats.paid_orders}    color="#2E7D32" />
                <BreakdownChip label="Partial" value={stats.partial_orders} color="#FF8F00" />
                <BreakdownChip label="Unpaid"  value={stats.unpaid_orders}  color="#C62828" />
              </View>
            </Card.Content>
          </Card>

          <Divider style={styles.divider} />

          {/* Orders list */}
          <Text variant="titleSmall" style={styles.sectionTitle}>
            Orders ({orders.length})
          </Text>

          {orders.length === 0 ? (
            <Card style={styles.card}>
              <Card.Content style={styles.emptyContent}>
                <Text variant="bodyMedium" style={{ opacity: 0.5 }}>No orders for this period</Text>
              </Card.Content>
            </Card>
          ) : (
            orders.map((order) => (
              <Card key={order.id} style={styles.orderCard}>
                <Card.Content>
                  <View style={styles.row}>
                    <Text variant="titleSmall" style={{ fontFamily: 'Poppins_700Bold' }}>
                      #{order.order_number}
                    </Text>
                    <Chip
                      mode="flat"
                      compact
                      style={{ backgroundColor: (PAYMENT_STATUS_COLOR[order.payment_status] || '#666') + '22' }}
                      textStyle={{ fontSize: 10, color: PAYMENT_STATUS_COLOR[order.payment_status] || '#666', fontFamily: 'Poppins_700Bold' }}
                    >
                      {order.payment_status?.toUpperCase() || 'UNPAID'}
                    </Chip>
                  </View>

                  <View style={styles.row}>
                    <Text variant="bodySmall" style={{ opacity: 0.65 }}>
                      Table {order.table_number} · {order.items_count} item{order.items_count !== 1 ? 's' : ''}
                    </Text>
                    <Chip
                      mode="flat"
                      compact
                      style={{ backgroundColor: (ORDER_STATUS_COLOR[order.status] || '#666') + '22' }}
                      textStyle={{ fontSize: 10, color: ORDER_STATUS_COLOR[order.status] || '#666' }}
                    >
                      {order.status?.toUpperCase()}
                    </Chip>
                  </View>

                  <View style={[styles.row, { marginTop: 6 }]}>
                    <Text variant="bodySmall" style={{ opacity: 0.6 }}>
                      {new Date(order.created_at).toLocaleString()}
                    </Text>
                    <Text variant="bodySmall" style={{ fontFamily: 'Poppins_700Bold' }}>
                      {format(order.total_amount)}
                    </Text>
                  </View>
                </Card.Content>
              </Card>
            ))
          )}
        </>
      ) : null}

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {snack}
      </Snackbar>
    </ScrollView>
  );
}

function StatCard({ label, value, color, icon }) {
  return (
    <Surface style={[styles.statCard, { backgroundColor: color + '12' }]} elevation={0}>
      <View style={[styles.statIconWrap, { backgroundColor: color + '25' }]}>
        <MaterialCommunityIcons name={icon} size={18} color={color} />
      </View>
      <Text style={[styles.statValue, { color }]}>{value ?? 0}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </Surface>
  );
}

function BreakdownChip({ label, value, color }) {
  return (
    <View style={styles.breakdownItem}>
      <Text variant="titleMedium" style={[styles.breakdownValue, { color }]}>{value ?? 0}</Text>
      <Text variant="bodySmall" style={{ opacity: 0.65 }}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container:      { padding: 16, paddingBottom: 40 },
  center:         { flex: 1, justifyContent: 'center', alignItems: 'center' },
  statsRow:       { flexDirection: 'row', gap: 8, marginBottom: 12 },
  statCard:       { flex: 1, alignItems: 'center', paddingVertical: 14, paddingHorizontal: 6, borderRadius: 10 },
  statIconWrap:   { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 6 },
  statValue:      { fontFamily: 'Poppins_700Bold', fontSize: 16, lineHeight: 22 },
  statLabel:      { fontFamily: 'Poppins_500Medium', opacity: 0.65, fontSize: 10, marginTop: 2, textAlign: 'center' },
  card:           { borderRadius: 10, marginBottom: 12 },
  orderCard:      { borderRadius: 10, marginBottom: 8 },
  cardTitle:      { fontFamily: 'Poppins_700Bold', marginBottom: 10 },
  breakdownRow:   { flexDirection: 'row', justifyContent: 'space-around' },
  breakdownItem:  { alignItems: 'center' },
  breakdownValue: { fontFamily: 'Poppins_700Bold' },
  divider:        { marginBottom: 12 },
  sectionTitle:   { fontFamily: 'Poppins_700Bold', marginBottom: 8 },
  emptyContent:   { alignItems: 'center', paddingVertical: 24 },
  row:            { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  periods:        { marginBottom: 12 },
  filterChipRow:  { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  pickerOverlay:  { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'flex-end' },
  pickerSheet:    { backgroundColor: '#fff', borderTopLeftRadius: 18, borderTopRightRadius: 18, paddingBottom: 24 },
  pickerHeader:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 16 },
  pickerRow:      { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, paddingHorizontal: 16, gap: 10 },
  pickerActions:  { flexDirection: 'row', gap: 10, padding: 16 },
});
