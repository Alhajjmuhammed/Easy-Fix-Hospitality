import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Button, Text, TextInput } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import { apiLinkLoyaltyCustomer, apiOrderLoyalty } from '../api/loyalty';

/**
 * Inside the cashier's pay dialog: shows the customer's loyalty points, lets the cashier link a
 * walk-in customer by phone, and offers "Pay with points". Hidden when loyalty is off, the order
 * is offline-only, the device is offline, or the server is older.
 */
export default function LoyaltyPayBox({ order, balanceDue, format, onUsePoints, onCode, onMessage }) {
  const [info, setInfo] = useState(null);
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [linking, setLinking] = useState(false);

  useEffect(() => {
    setInfo(null);
    setPhone('');
    setCode('');
    if (!order?.id || order._is_offline_pending) return undefined;
    let alive = true;
    NetInfo.fetch().then((net) => {
      if (!net.isConnected) return;
      apiOrderLoyalty(order.id).then((d) => { if (alive) setInfo(d); }).catch(() => {});
    });
    return () => { alive = false; };
  }, [order?.id, order?._is_offline_pending]);

  if (!info || !info.enabled) return null;

  const link = async () => {
    setLinking(true);
    try {
      setInfo(await apiLinkLoyaltyCustomer(order.id, phone.trim()));
    } catch (err) {
      onMessage?.(err?.response?.data?.error || 'Could not find the customer.');
    } finally {
      setLinking(false);
    }
  };

  const c = info.customer;
  const usable = c ? Math.min(Number(balanceDue) || 0, Number(c.worth) || 0) : 0;
  const needed = Math.ceil(usable / (Number(info.point_value) || 1) - 1e-9);
  const canUse = c && c.points >= info.min_redeem_points && needed >= info.min_redeem_points && usable > 0;

  return (
    <View style={styles.box}>
      <View style={styles.row}>
        <MaterialCommunityIcons name="gift-outline" size={18} color="#C2185B" />
        <Text style={styles.title}>Loyalty points</Text>
      </View>
      {c ? (
        <>
          <Text style={styles.text}>{c.name}{c.phone ? ` (${c.phone})` : ''}: {c.points} points · worth {format(Number(c.worth))}</Text>
          {canUse ? (
            <>
              <View style={[styles.row, { marginTop: 6 }]}>
                <TextInput dense mode="outlined" label="Customer's code" keyboardType="number-pad" maxLength={6}
                           value={code} onChangeText={(v) => { setCode(v.replace(/\D/g, '')); onCode?.(v.replace(/\D/g, '')); }}
                           style={{ width: 140 }} />
                <Button compact mode="outlined" icon="gift" disabled={code.length !== 6}
                        onPress={() => onUsePoints(usable.toFixed(2), code)}>
                  Use {needed} points
                </Button>
              </View>
              <Text style={styles.hint}>The customer finds the code in their app under My Points.</Text>
            </>
          ) : (
            <Text style={styles.hint}>Points can be used from {info.min_redeem_points} points.</Text>
          )}
        </>
      ) : (
        <>
          <Text style={styles.hint}>Registered customer? Enter their phone number so they earn points.</Text>
          <View style={styles.row}>
            <TextInput dense mode="outlined" label="Customer phone" keyboardType="phone-pad" value={phone}
                       onChangeText={setPhone} style={{ flex: 1 }} />
            <Button compact onPress={link} loading={linking} disabled={linking || phone.trim().length < 6}>Link</Button>
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { borderWidth: 1, borderColor: '#F8BBD0', borderRadius: 8, padding: 8, marginBottom: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  title: { fontFamily: 'Poppins_600SemiBold', fontSize: 13 },
  text: { fontFamily: 'Poppins_400Regular', fontSize: 13, marginTop: 4 },
  hint: { fontFamily: 'Poppins_400Regular', fontSize: 12, color: '#777', marginTop: 4, marginBottom: 4 },
});
