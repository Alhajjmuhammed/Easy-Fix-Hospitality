import React, { useEffect, useState } from 'react';
import { View, StyleSheet } from 'react-native';
import { Surface, Text, IconButton, Button } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSyncStore } from '../store/useSyncStore';
import { useCurrency } from '../hooks/useCurrency';
import { useT } from '../i18n';
import { countOtherAccountsUnsent } from '../database/operations';

/** One line per thing that differs from what staff saw offline. */
export function describeSyncWarning(w, t, format) {
  const number = w.order_number || '?';
  const money = (v) => (v == null || v === '' ? '' : format(parseFloat(v)));
  switch (w.kind) {
    case 'order': {
      const lines = [];
      if (w.dropped > 0) {
        lines.push(t('Order {number}: {count} item(s) were unavailable and removed at sync.', { number, count: w.dropped }));
      }
      if (w.server_total != null) {
        lines.push(t('Order {number}: the total changed at sync from {old} to {total}. Check with the customer.', {
          number, old: money(w.local_total), total: money(w.server_total),
        }));
      } else if (w.price_changes > 0) {
        lines.push(t('Order {number}: {count} item price(s) changed at sync.', { number, count: w.price_changes }));
      }
      if (!lines.length) lines.push(t('Order {number} changed at sync. Check it before taking payment.', { number }));
      return lines.join('\n');
    }
    case 'payment':
      return t('Order {number}: offline payment of {amount} was recorded as {recorded} because the order total changed. {difference} difference — settle with the customer.', {
        number, amount: money(w.requested), recorded: money(w.recorded), difference: money(w.difference),
      });
    case 'payment_not_recorded':
      return t('Order {number}: offline payment of {amount} could not be recorded because the order was already fully paid. Settle or refund with the customer.', {
        number, amount: money(w.requested),
      });
    case 'status':
      return t('Order {number}: the status change to "{status}" made offline was refused: {error}', {
        number, status: t(w.new_status), error: w.error,
      });
    case 'batch':
      return t('The server refused {count} queued item(s): {error}. They stay on this phone and are shown as sync errors. Contact support if this continues.', {
        count: w.count, error: w.error,
      });
    default:
      return w.error || '';
  }
}

/** Owners/managers: unsent rows on this phone that belong to other accounts (or another
 *  restaurant). Only their own user can send them, by logging in on this phone. */
export function OtherAccountsUnsentNote() {
  const t = useT();
  const pendingCount = useSyncStore((s) => s.pendingCount);
  const lastSyncTime = useSyncStore((s) => s.lastSyncTime);
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    countOtherAccountsUnsent().then((n) => { if (alive) setCount(n); }).catch(() => {});
    return () => { alive = false; };
  }, [pendingCount, lastSyncTime]);
  if (!count) return null;
  return (
    <View style={styles.otherRow}>
      <MaterialCommunityIcons name="account-clock-outline" size={14} color="#6D4C41" />
      <Text variant="bodySmall" style={styles.otherText}>
        {t('{count} unsent items from other accounts on this phone. Only those users can send them, by logging in on this phone.', { count })}
      </Text>
    </View>
  );
}

/** Dismissible list of sync notices for the cashier / station (shown after a sync). */
export default function SyncWarningsBanner() {
  const t = useT();
  const { format } = useCurrency();
  const warnings = useSyncStore((s) => s.syncWarnings);
  const dismiss = useSyncStore((s) => s.dismissSyncWarning);
  const clearAll = useSyncStore((s) => s.clearSyncWarnings);
  if (!warnings || !warnings.length) return null;

  return (
    <Surface style={styles.box} elevation={1}>
      <View style={styles.header}>
        <MaterialCommunityIcons name="alert-circle-outline" size={18} color="#E65100" />
        <Text variant="titleSmall" style={styles.title}>{t('Sync notices')}</Text>
        {warnings.length > 1 && (
          <Button compact onPress={clearAll}>{t('Dismiss all')}</Button>
        )}
      </View>
      {warnings.map((w) => (
        <View key={w.key} style={styles.row}>
          <Text variant="bodySmall" style={styles.text}>{describeSyncWarning(w, t, format)}</Text>
          <IconButton icon="close" size={16} onPress={() => dismiss(w.key)} accessibilityLabel={t('Dismiss')} />
        </View>
      ))}
    </Surface>
  );
}

const styles = StyleSheet.create({
  box: { marginHorizontal: 12, marginTop: 8, padding: 10, borderRadius: 8, backgroundColor: '#FFF3E0' },
  header: { flexDirection: 'row', alignItems: 'center' },
  title: { flex: 1, marginLeft: 6, color: '#E65100' },
  row: { flexDirection: 'row', alignItems: 'center' },
  text: { flex: 1, color: '#4E342E' },
  otherRow: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 4, backgroundColor: '#EFEBE9' },
  otherText: { flex: 1, marginLeft: 6, color: '#4E342E' },
});
