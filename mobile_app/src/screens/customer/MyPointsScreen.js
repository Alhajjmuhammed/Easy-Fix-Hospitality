import React, { useCallback, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { Card, Text } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { apiMyPoints } from '../../api/loyalty';

export default function MyPointsScreen() {
  const [programs, setPrograms] = useState([]);
  const [code, setCode] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await apiMyPoints();
      setPrograms(d.programs || []);
      setCode(d.code || null);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <FlatList
      data={programs}
      keyExtractor={(p, i) => `${p.restaurant_name}-${i}`}
      contentContainerStyle={styles.list}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={() => { setLoading(true); load(); }} />}
      ListHeaderComponent={code && programs.length > 0 ? (
        <Card style={[styles.card, { backgroundColor: '#FFF0F6' }]}>
          <Card.Content style={{ alignItems: 'center' }}>
            <Text style={styles.small}>Your code to pay with points</Text>
            <Text style={styles.code} accessibilityLabel={`Your points code ${code.split('').join(' ')}`}>{code}</Text>
            <Text style={[styles.small, { textAlign: 'center' }]}>
              Tell it to the cashier only when you want to use your points. It changes after each use.
            </Text>
          </Card.Content>
        </Card>
      ) : null}
      ListEmptyComponent={!loading && (
        <View style={styles.empty}>
          <MaterialCommunityIcons name="gift-outline" size={56} color="#B0BEC5" />
          <Text style={styles.emptyText}>
            {error ? 'Could not load your points. Pull down to retry.'
              : 'No points yet. Restaurants with a loyalty programme give you points when you pay for an order.'}
          </Text>
        </View>
      )}
      renderItem={({ item }) => (
        <Card style={styles.card}>
          <Card.Content>
            <View style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.restaurant_name}</Text>
                <Text style={styles.small}>1 point per {item.spend_per_point} spent · use from {item.min_redeem_points} points</Text>
              </View>
              <View style={{ alignItems: 'flex-end' }}>
                <Text style={styles.points}>{item.points} pts</Text>
                <Text style={styles.small}>worth {item.worth}</Text>
              </View>
            </View>
            {item.history.map((h, i) => (
              <View key={i} style={styles.hist}>
                <Text style={[styles.small, { flex: 1 }]} numberOfLines={1}>{h.kind} · {h.note}</Text>
                <Text style={[styles.small, { color: h.points < 0 ? '#C62828' : '#2E7D32' }]}>{h.points > 0 ? '+' : ''}{h.points}</Text>
              </View>
            ))}
            <Text style={[styles.small, { marginTop: 8 }]}>To use your points, ask the cashier to pay with “Loyalty points”.</Text>
          </Card.Content>
        </Card>
      )}
    />
  );
}

const styles = StyleSheet.create({
  list: { padding: 12 },
  card: { marginBottom: 12, borderRadius: 12 },
  row: { flexDirection: 'row', gap: 8, marginBottom: 6 },
  name: { fontFamily: 'Poppins_700Bold', fontSize: 15 },
  points: { fontFamily: 'Poppins_700Bold', fontSize: 20, color: '#C2185B' },
  code: { fontFamily: 'Poppins_700Bold', fontSize: 34, letterSpacing: 8, color: '#2c3e50', marginVertical: 4 },
  small: { fontFamily: 'Poppins_400Regular', fontSize: 12, color: '#666' },
  hist: { flexDirection: 'row', borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#E0E0E0', paddingVertical: 4 },
  empty: { alignItems: 'center', marginTop: 48, paddingHorizontal: 24, gap: 12 },
  emptyText: { textAlign: 'center', color: '#90A4AE', fontFamily: 'Poppins_400Regular' },
});
