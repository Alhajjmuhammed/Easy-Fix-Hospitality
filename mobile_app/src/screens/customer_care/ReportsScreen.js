import React, { useEffect, useState, useCallback } from 'react';
import { ScrollView, View, StyleSheet, RefreshControl } from 'react-native';
import {
  Text,
  Card,
  Chip,
  ActivityIndicator,
  Snackbar,
  Divider,
  Surface,
} from 'react-native-paper';
import client from '../../api/client';
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

export default function CCReportsScreen() {
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing]  = useState(false);
  const [data, setData]              = useState(null);
  const [snack, setSnack]            = useState('');
  const { format } = useCurrency();

  const fetchReport = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await client.get('/reports/cc/', { params: { period: 'today' } });
      setData(res.data);
    } catch {
      setSnack('Could not load report');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const stats  = data?.stats  || {};
  const orders = data?.orders || [];

  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); fetchReport(true); }} />
      }
    >
      {/* Stats cards */}
      <View style={styles.statsRow}>
        <StatCard label="Orders"    value={stats.total_orders}             color="#2c3e50" icon="clipboard-list-outline" />
        <StatCard label="Revenue"   value={format(stats.total_revenue ?? 0)} color="#2E7D32" icon="cash-multiple" />
        <StatCard label="Items"     value={stats.total_items}             color="#6A1B9A" icon="food-outline" />
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
  statCard:       {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 6,
    borderRadius: 10,
  },
  statIconWrap:   {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 6,
  },
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
});
