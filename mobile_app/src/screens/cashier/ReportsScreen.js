import React, { useEffect, useState, useCallback, useRef } from 'react';
import { ScrollView, View, StyleSheet, RefreshControl, FlatList, TouchableOpacity, Modal } from 'react-native';
import {
  Text, Card, Chip, ActivityIndicator, Snackbar, Divider, Surface, SegmentedButtons, Banner,
  Button, Checkbox,
} from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import client from '../../api/client';
import { getOfflinePendingOrders, getSyncMeta, setSyncMeta, getLocalReportStats } from '../../database/operations';
import { useCurrency } from '../../hooks/useCurrency';

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

export default function CashierReportsScreen() {
  const { format }                      = useCurrency();
  const [loading,           setLoading]           = useState(true);
  const [refreshing,        setRefreshing]         = useState(false);
  const [data,              setData]               = useState(null);
  const [snack,             setSnack]             = useState('');
  const [period,            setPeriod]            = useState('today');
  const [isOffline,         setIsOffline]         = useState(false);
  const [offlineOrders,     setOfflineOrders]     = useState([]);
  const [cacheTimestamp,    setCacheTimestamp]    = useState(null);
  const [selectedPids,      setSelectedPids]      = useState([]);
  const [tempPids,          setTempPids]          = useState([]);
  const [showPicker,        setShowPicker]        = useState(false);
  // Ref so fetchReport can always read the latest pids without being a closure dep
  const selectedPidsRef = useRef([]);
  useEffect(() => { selectedPidsRef.current = selectedPids; }, [selectedPids]);

  const fetchReport = useCallback(async (silent = false, pids) => {
    // pids passed explicitly (Apply/Clear); fall back to ref for period-change re-fetches
    const effectivePids = pids !== undefined ? pids : selectedPidsRef.current;
    if (!silent) setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!net.isConnected) {
        // Load last-cached report so staff see real data offline
        const [cached, cachedTs, cachedPeriod, pending] = await Promise.all([
          getSyncMeta('cashier_report_cache'),
          getSyncMeta('cashier_report_cache_ts'),
          getSyncMeta('cashier_report_cache_period'),
          getOfflinePendingOrders(),
        ]);
        if (cached) {
          setData(JSON.parse(cached));
          setCacheTimestamp(cachedTs || null);
        } else {
          // No server cache: compute from local SQLite data so staff see something useful
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
        const res = await client.get('/reports/cashier/', { params });
        setData(res.data);
        setIsOffline(false);
        setCacheTimestamp(null);
        const pending = await getOfflinePendingOrders();
        setOfflineOrders(pending);
        // Cache for offline use
        await Promise.all([
          setSyncMeta('cashier_report_cache', JSON.stringify(res.data)),
          setSyncMeta('cashier_report_cache_ts', new Date().toISOString()),
          setSyncMeta('cashier_report_cache_period', period),
        ]);
      }
    } catch {
      // Network error — try cached data, then fall back to local computation
      try {
        const [cached, cachedTs, pending] = await Promise.all([
          getSyncMeta('cashier_report_cache'),
          getSyncMeta('cashier_report_cache_ts'),
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
    return <View style={styles.center}><ActivityIndicator size="large" /></View>;
  }

  const stats       = data?.stats                || {};
  const orders      = data?.orders               || [];
  const myMethods   = data?.my_payment_methods   || [];
  const topProducts = data?.top_products         || [];

  const pendingOrders  = offlineOrders.filter((o) => !o._is_sync_error);
  const errorOrders    = offlineOrders.filter((o) => o._is_sync_error);
  const offlineTotal   = pendingOrders.reduce((s, o) => s + (o.total_amount || 0), 0);

  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); fetchReport(true); }} />
      }
    >
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

      {/* Sync-failed orders — always visible, requires staff action */}
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
                <Text variant="bodySmall" style={styles.meta}>
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

      {/* Offline queued orders summary (shown whether online or offline) */}
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
                <Text variant="bodySmall" style={styles.meta}>
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

      {/* Report — shows cached/local data when offline, live data when online */}
      {data ? (
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

      {/* Restaurant-wide stats */}
      <Text variant="labelLarge" style={styles.sectionTitle}>Restaurant Overview</Text>
      <View style={styles.statsRow}>
        <StatCard label="Orders"  value={stats.total_orders}                color="#2c3e50" icon="clipboard-list-outline" />
        <StatCard label="Revenue" value={format(stats.total_revenue ?? 0)}  color="#2E7D32" icon="cash-multiple" />
        <StatCard label="Items"   value={stats.total_items}                 color="#6A1B9A" icon="food-outline" />
        <StatCard label="Avg"     value={format(stats.avg_order_value ?? 0)} color="#FF8F00" icon="chart-line" />
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

      {/* My Collections */}
      <Text variant="labelLarge" style={styles.sectionTitle}>My Collections</Text>
      <Card style={[styles.card, { borderLeftWidth: 4, borderLeftColor: '#1565C0' }]}>
        <Card.Content>
          <View style={styles.row}>
            <View style={styles.myCollectStat}>
              <MaterialCommunityIcons name="cash-register" size={28} color="#1565C0" />
              <Text style={styles.bigValue}>{format(stats.my_total_collected ?? 0)}</Text>
              <Text style={styles.bigLabel}>Total Collected</Text>
            </View>
            <View style={styles.myCollectStat}>
              <MaterialCommunityIcons name="receipt" size={28} color="#6A1B9A" />
              <Text style={[styles.bigValue, { color: '#6A1B9A' }]}>{stats.my_payment_count ?? 0}</Text>
              <Text style={styles.bigLabel}>Payments Processed</Text>
            </View>
          </View>

          {myMethods.length > 0 && (
            <>
              <Divider style={{ marginVertical: 10 }} />
              <Text variant="bodySmall" style={{ fontFamily: 'Poppins_600SemiBold', marginBottom: 6 }}>By Method</Text>
              {myMethods.map((m) => (
                <View key={m.method} style={styles.methodRow}>
                  <Text variant="bodySmall" style={{ textTransform: 'capitalize', fontFamily: 'Poppins_400Regular' }}>
                    {m.method}
                  </Text>
                  <Text variant="bodySmall" style={{ fontFamily: 'Poppins_700Bold' }}>
                    {format(m.total)} ({m.count})
                  </Text>
                </View>
              ))}
            </>
          )}
        </Card.Content>
      </Card>

      {/* Top products */}
      {topProducts.length > 0 && (
        <>
          <Text variant="labelLarge" style={styles.sectionTitle}>Top Products</Text>
          <Card style={styles.card}>
            <Card.Content>
              {topProducts.map((p, i) => (
                <View key={i} style={styles.methodRow}>
                  <Text variant="bodySmall" style={{ fontFamily: 'Poppins_400Regular', flex: 1 }} numberOfLines={1}>
                    {i + 1}. {p.name}
                  </Text>
                  <Chip compact mode="flat" style={{ backgroundColor: '#2c3e5015' }}>
                    {p.qty} sold
                  </Chip>
                </View>
              ))}
            </Card.Content>
          </Card>
        </>
      )}

      <Divider style={styles.divider} />

      {/* Orders list */}
      <Text variant="labelLarge" style={styles.sectionTitle}>All Orders ({orders.length})</Text>

      {orders.length === 0 ? (
        <Card style={styles.card}>
          <Card.Content style={styles.emptyContent}>
            <MaterialCommunityIcons name="clipboard-text-off-outline" size={40} color="#ccc" />
            <Text variant="bodyMedium" style={{ opacity: 0.5, marginTop: 8 }}>No orders for this period</Text>
          </Card.Content>
        </Card>
      ) : (
        orders.map((order) => {
          const statusColor = ORDER_STATUS_COLOR[order.status]           || '#888';
          const payColor    = PAYMENT_STATUS_COLOR[order.payment_status] || '#888';
          return (
            <Card key={order.id} style={styles.card}>
              <Card.Content>
                <View style={styles.row}>
                  <Text variant="titleSmall" style={{ fontFamily: 'Poppins_700Bold' }}>
                    #{order.order_number || order.id}
                  </Text>
                  <View style={styles.row}>
                    <Chip mode="flat" compact style={{ backgroundColor: statusColor + '22', marginRight: 4 }}
                      textStyle={{ color: statusColor, fontSize: 10 }}>
                      {order.status?.toUpperCase()}
                    </Chip>
                    <Chip mode="flat" compact style={{ backgroundColor: payColor + '22' }}
                      textStyle={{ color: payColor, fontSize: 10 }}>
                      {order.payment_status?.toUpperCase()}
                    </Chip>
                  </View>
                </View>
                <Text variant="bodySmall" style={styles.meta}>
                  Table {order.table_number} · {order.items_count} items · by {order.ordered_by}
                </Text>
                <Text variant="bodySmall" style={styles.meta}>
                  {new Date(order.created_at).toLocaleTimeString()}
                </Text>
                <Text variant="bodySmall" style={{ fontFamily: 'Poppins_700Bold', marginTop: 4 }}>
                  {format(order.total_amount)}
                </Text>
              </Card.Content>
            </Card>
          );
        })
      )}

        </>
      ) : null}

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>{snack}</Snackbar>
    </ScrollView>
  );
}

function StatCard({ label, value, color, icon }) {
  return (
    <Surface style={[styles.statCard, { backgroundColor: color + '12' }]} elevation={0}>
      <View style={[styles.statIconWrap, { backgroundColor: color + '25' }]}>
        <MaterialCommunityIcons name={icon} size={18} color={color} />
      </View>
      <Text style={[styles.statValue, { color }]} numberOfLines={1}>{value ?? 0}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </Surface>
  );
}

function BreakdownChip({ label, value, color }) {
  return (
    <View style={[styles.breakdownItem, { backgroundColor: color + '15', borderColor: color + '40', borderWidth: 1 }]}>
      <Text style={[styles.breakdownValue, { color }]}>{value ?? 0}</Text>
      <Text style={styles.breakdownLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container:      { padding: 16, paddingBottom: 32 },
  center:         { flex: 1, justifyContent: 'center', alignItems: 'center' },
  periods:        { marginBottom: 16 },
  sectionTitle:   { fontFamily: 'Poppins_700Bold', fontSize: 13, marginBottom: 8, marginTop: 4, color: '#2c3e50' },
  statsRow:       { flexDirection: 'row', gap: 8, marginBottom: 16 },
  statCard:       { flex: 1, alignItems: 'center', paddingVertical: 12, paddingHorizontal: 4, borderRadius: 10 },
  statIconWrap:   { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 6 },
  statValue:      { fontFamily: 'Poppins_700Bold', fontSize: 16, lineHeight: 22 },
  statLabel:      { fontFamily: 'Poppins_400Regular', fontSize: 10, opacity: 0.7, textAlign: 'center' },
  card:           { marginBottom: 10, borderRadius: 10 },
  cardTitle:      { fontFamily: 'Poppins_700Bold', marginBottom: 10 },
  emptyContent:   { alignItems: 'center', paddingVertical: 24 },
  row:            { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  meta:           { opacity: 0.65, marginBottom: 1 },
  divider:        { marginVertical: 16 },
  breakdownRow:   { flexDirection: 'row', gap: 8 },
  breakdownItem:  { flex: 1, alignItems: 'center', paddingVertical: 10, borderRadius: 8 },
  breakdownValue: { fontFamily: 'Poppins_700Bold', fontSize: 18 },
  breakdownLabel: { fontFamily: 'Poppins_400Regular', fontSize: 11, opacity: 0.8 },
  myCollectStat:  { flex: 1, alignItems: 'center', paddingVertical: 8 },
  bigValue:       { fontFamily: 'Poppins_700Bold', fontSize: 20, color: '#1565C0', marginTop: 4 },
  bigLabel:       { fontFamily: 'Poppins_400Regular', fontSize: 11, opacity: 0.7, textAlign: 'center' },
  methodRow:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  filterChipRow:  { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  pickerOverlay:  { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'flex-end' },
  pickerSheet:    { backgroundColor: '#fff', borderTopLeftRadius: 18, borderTopRightRadius: 18, paddingBottom: 24 },
  pickerHeader:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 16 },
  pickerRow:      { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, paddingHorizontal: 16, gap: 10 },
  pickerActions:  { flexDirection: 'row', gap: 10, padding: 16 },
});
