import React, { useCallback, useState } from 'react';
import { useFocusEffect } from '@react-navigation/native';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import { Button, Card, Text, TextInput } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { apiOrderRating, apiRateOrder } from '../api/feedback';

const FINISHED = ['served', 'delivered'];

function Stars({ value, onChange, size = 34, label }) {
  return (
    <View style={styles.starRow} accessibilityRole="radiogroup" accessibilityLabel={label}>
      {[1, 2, 3, 4, 5].map((n) => (
        <TouchableOpacity key={n} disabled={!onChange} onPress={() => onChange && onChange(n)}
                          accessibilityRole="radio" accessibilityState={{ checked: value === n }}
                          accessibilityLabel={`${n} star${n > 1 ? 's' : ''}`} hitSlop={6}>
          <MaterialCommunityIcons name={n <= value ? 'star' : 'star-outline'} size={size} color="#F5A623" />
        </TouchableOpacity>
      ))}
    </View>
  );
}

/** "How was your order?" for the customer once it is served/delivered; shows their rating and any reply after. */
export default function OrderRatingCard({ orderId, status, orderType, onMessage }) {
  const [info, setInfo] = useState(null);
  const [food, setFood] = useState(0);
  const [delivery, setDelivery] = useState(0);
  const [comment, setComment] = useState('');
  const [sending, setSending] = useState(false);

  // On focus too, so a reply opened from a notification shows even if this screen was already open
  useFocusEffect(useCallback(() => {
    if (!FINISHED.includes(status)) return undefined;
    let alive = true;
    apiOrderRating(orderId)
      .then((d) => { if (alive) setInfo(d); })
      .catch(() => { /* older server or not the customer's order: no card */ });
    return () => { alive = false; };
  }, [orderId, status]));

  if (!info || (!info.can_rate && !info.rating)) return null;

  const submit = async () => {
    if (!food) { onMessage?.('Please choose 1 to 5 stars for the food.'); return; }
    setSending(true);
    try {
      const body = { food_stars: food, comment: comment.trim() };
      if (orderType === 'delivery' && delivery) body.delivery_stars = delivery;
      const r = await apiRateOrder(orderId, body);
      setInfo({ can_rate: false, rating: r.rating });
      onMessage?.('Thank you for your feedback!');
    } catch (err) {
      onMessage?.(err?.response?.data?.error || 'Could not send your rating. Please try again.');
    } finally {
      setSending(false);
    }
  };

  if (info.rating) {
    const r = info.rating;
    return (
      <Card style={styles.card}>
        <Card.Content>
          <Text style={styles.title}>Your rating</Text>
          <Stars value={r.food_stars} size={22} label="Food rating" />
          {r.delivery_stars ? (
            <View style={styles.inline}><Text style={styles.small}>Delivery </Text><Stars value={r.delivery_stars} size={18} label="Delivery rating" /></View>
          ) : null}
          {!!r.comment && <Text style={styles.comment}>“{r.comment}”</Text>}
          {!!r.reply && (
            <View style={styles.reply}>
              <Text style={styles.replyTitle}>Reply from the restaurant</Text>
              <Text style={styles.small}>{r.reply}</Text>
            </View>
          )}
        </Card.Content>
      </Card>
    );
  }

  return (
    <Card style={styles.card}>
      <Card.Content>
        <Text style={styles.title}>How was your order?</Text>
        <Text style={styles.small}>Food</Text>
        <Stars value={food} onChange={setFood} label="Rate the food" />
        {orderType === 'delivery' && (
          <>
            <Text style={[styles.small, { marginTop: 8 }]}>Delivery (optional)</Text>
            <Stars value={delivery} onChange={setDelivery} size={28} label="Rate the delivery" />
          </>
        )}
        <TextInput mode="outlined" label="Comment (optional)" value={comment} onChangeText={setComment}
                   multiline maxLength={1000} style={{ marginTop: 10 }} />
        <Button mode="contained" onPress={submit} loading={sending} disabled={sending}
                buttonColor="#F5A623" style={{ marginTop: 10 }}>
          Send rating
        </Button>
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { marginBottom: 12, borderRadius: 12 },
  title: { fontFamily: 'Poppins_700Bold', fontSize: 15, marginBottom: 6 },
  small: { fontFamily: 'Poppins_400Regular', fontSize: 13, color: '#555' },
  starRow: { flexDirection: 'row', gap: 4, marginVertical: 4 },
  inline: { flexDirection: 'row', alignItems: 'center' },
  comment: { fontFamily: 'Poppins_400Regular', fontSize: 13, marginTop: 6 },
  reply: { backgroundColor: '#EEF5FF', borderRadius: 8, padding: 8, marginTop: 8 },
  replyTitle: { fontFamily: 'Poppins_600SemiBold', fontSize: 12, marginBottom: 2 },
});
