import React, { useMemo } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { Chip, Text } from 'react-native-paper';
import { useT } from '../i18n';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Next `days` dates as { value: 'YYYY-MM-DD', label }. */
export function upcomingDates(days = 14) {
  const out = [];
  const today = new Date();
  for (let i = 0; i < days; i += 1) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i);
    const label = i === 0 ? 'Today' : i === 1 ? 'Tomorrow'
      : d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
    out.push({ value: isoDate(d), label });
  }
  return out;
}

/** 30-minute slots 'HH:MM'; for today only slots at least `minLeadMinutes` from now. */
export function timeSlots(dateValue, minLeadMinutes = 15) {
  const slots = [];
  const now = new Date();
  const isToday = dateValue === isoDate(now);
  const earliest = now.getHours() * 60 + now.getMinutes() + minLeadMinutes;
  for (let m = 6 * 60; m <= 23 * 60 + 30; m += 30) {
    if (isToday && m < earliest) continue;
    slots.push(`${pad(Math.floor(m / 60))}:${pad(m % 60)}`);
  }
  return slots;
}

/** Date chips + time chips. Controlled: date/time strings and setters. */
export default function DateTimeChips({ date, time, onDate, onTime, minLeadMinutes = 15 }) {
  const t = useT();
  const dates = useMemo(() => upcomingDates(14), []);
  const slots = useMemo(() => timeSlots(date, minLeadMinutes), [date, minLeadMinutes]);
  return (
    <View>
      <Text variant="titleSmall" style={styles.label}>{t('Date')}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {dates.map((d) => (
          <Chip key={d.value} selected={date === d.value} onPress={() => { onDate(d.value); onTime(''); }}
                style={styles.chip}>{t(d.label)}</Chip>
        ))}
      </ScrollView>
      <Text variant="titleSmall" style={styles.label}>{t('Time')}</Text>
      {slots.length === 0 ? (
        <Text style={styles.empty}>{t('No more times today — please choose another day.')}</Text>
      ) : (
        <View style={styles.wrap}>
          {slots.map((s) => (
            <Chip key={s} selected={time === s} onPress={() => onTime(s)} style={styles.chip} compact>{s}</Chip>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  label: { fontFamily: 'Poppins_600SemiBold', marginTop: 12, marginBottom: 6 },
  row: { gap: 6, paddingBottom: 4 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { marginBottom: 2 },
  empty: { color: '#888', fontFamily: 'Poppins_400Regular' },
});
