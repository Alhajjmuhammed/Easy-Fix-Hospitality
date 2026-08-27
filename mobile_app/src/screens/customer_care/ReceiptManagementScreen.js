import React, { useEffect, useState, useCallback, useRef } from 'react';
import { FlatList, View, StyleSheet } from 'react-native';
import {
  Text,
  Card,
  TextInput,
  Button,
  ActivityIndicator,
  Snackbar,
  Divider,
  Chip,
  Banner,
  useTheme,
} from 'react-native-paper';
import NetInfo from '@react-native-community/netinfo';
import { apiPayments } from '../../api/payments';
import { useCurrency } from '../../hooks/useCurrency';

const METHOD_LABEL = { cash: 'Cash', card: 'Card', digital: 'Digital', voucher: 'Voucher' };

export default function ReceiptManagementScreen({ navigation }) {
  const theme = useTheme();
  const { format } = useCurrency();
  const [payments, setPayments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [snack, setSnack] = useState('');
  const [isOffline, setIsOffline] = useState(false);

  // Refs hold the latest filter values so fetchPayments has a stable identity
  // and does NOT fire on every keystroke.
  const searchRef   = useRef('');
  const dateFromRef = useRef('');
  const dateToRef   = useRef('');

  const mountedRef = useRef(true);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  const fetchPayments = useCallback(async () => {
    setLoading(true);
    try {
      const net = await NetInfo.fetch();
      if (!mountedRef.current) return;
      if (!net.isConnected) {
        setIsOffline(true);
        setPayments([]);
        return;
      }
      setIsOffline(false);
      const params = {};
      if (searchRef.current.trim())   params.search    = searchRef.current.trim();
      if (dateFromRef.current.trim()) params.date_from = dateFromRef.current.trim();
      if (dateToRef.current.trim())   params.date_to   = dateToRef.current.trim();
      const data = await apiPayments(params);
      if (!mountedRef.current) return;
      setPayments(Array.isArray(data) ? data : (data?.results || []));
    } catch {
      if (mountedRef.current) setSnack('Could not load receipts');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []); // stable — reads refs at call time

  // Run once on mount only
  useEffect(() => { fetchPayments(); }, [fetchPayments]);

  const renderItem = useCallback(({ item }) => (
    <Card
      style={styles.card}
      onPress={() => navigation.navigate('Receipt', { paymentId: item.id })}
    >
      <Card.Content>
        <View style={styles.rowBetween}>
          <Text variant="titleSmall">#{item.order_number}</Text>
          <Text variant="titleSmall" style={{ color: '#2E7D32', fontFamily: 'Poppins_700Bold' }}>
            {format(item.amount)}
          </Text>
        </View>
        <View style={styles.rowBetween}>
          <Chip compact style={{ height: 22 }}>
            {METHOD_LABEL[item.payment_method] || item.payment_method}
          </Chip>
          <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
            {item.created_at ? new Date(item.created_at).toLocaleString() : '—'}
          </Text>
        </View>
        {item.processed_by_name ? (
          <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant, marginTop: 2 }}>
            By: {item.processed_by_name}
          </Text>
        ) : null}
      </Card.Content>
    </Card>
  ), [format, navigation, theme]);

  return (
    <View style={styles.container}>
      <Banner
        visible={isOffline}
        icon="wifi-off"
        actions={[]}
        style={{ backgroundColor: '#FFF8E1' }}
      >
        Offline – receipts are not available without internet. Connect to search receipts.
      </Banner>
      {/* Filters */}
      <View style={styles.filterRow}>
        <TextInput
          label="Search order #"
          value={search}
          onChangeText={(v) => { setSearch(v); searchRef.current = v; }}
          mode="outlined"
          dense
          style={styles.searchInput}
          right={<TextInput.Icon icon="magnify" />}
        />
        <Button mode="contained" compact onPress={fetchPayments} style={styles.searchBtn}>
          Go
        </Button>
      </View>
      <View style={styles.filterRow}>
        <TextInput
          label="From (YYYY-MM-DD)"
          value={dateFrom}
          onChangeText={(v) => { setDateFrom(v); dateFromRef.current = v; }}
          mode="outlined"
          dense
          style={styles.dateInput}
        />
        <TextInput
          label="To (YYYY-MM-DD)"
          value={dateTo}
          onChangeText={(v) => { setDateTo(v); dateToRef.current = v; }}
          mode="outlined"
          dense
          style={styles.dateInput}
        />
      </View>

      <Divider style={{ marginBottom: 8 }} />

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" /></View>
      ) : (
        <FlatList
          data={payments}
          keyExtractor={(item) => String(item.id)}
          renderItem={renderItem}
          ListEmptyComponent={
            <Text style={{ textAlign: 'center', marginTop: 32, color: theme.colors.onSurfaceVariant }}>
              No receipts found
            </Text>
          }
          contentContainerStyle={{ paddingBottom: 32 }}
        />
      )}

      <Snackbar visible={!!snack} onDismiss={() => setSnack('')} duration={3000}>
        {snack}
      </Snackbar>
    </View>
  );
}

const styles = StyleSheet.create({
  container:  { flex: 1, padding: 12 },
  center:     { flex: 1, justifyContent: 'center', alignItems: 'center' },
  filterRow:  { flexDirection: 'row', gap: 8, marginBottom: 8, alignItems: 'center' },
  searchInput:{ flex: 1 },
  searchBtn:  { marginTop: 4 },
  dateInput:  { flex: 1 },
  card:       { marginBottom: 8 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 2 },
});
