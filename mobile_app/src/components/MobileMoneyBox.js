import React, { useEffect, useRef, useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';
import { Button, Chip, Text, TextInput } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import NetInfo from '@react-native-community/netinfo';
import { apiMobileMoneyInfo, apiMobileMoneyStart, apiMobileMoneyStatus } from '../api/mobileMoney';
import { useT } from '../i18n';

/**
 * "Send payment request" to a phone (M-Pesa / Flutterwave PIN prompt) and follow it until paid.
 * Used in the cashier pay dialog (amount from the dialog) and on the customer's order screen.
 * Hidden when offline, when the restaurant has no mobile money, or with an older server.
 */
export default function MobileMoneyBox({ orderId, amount, onPaid, onMessage }) {
  const t = useT();
  const [info, setInfo] = useState(null);
  const [phone, setPhone] = useState('');
  const [network, setNetwork] = useState('');
  const [charge, setCharge] = useState(null);
  const [sending, setSending] = useState(false);
  const [following, setFollowing] = useState(false);
  const timer = useRef(null);
  const alive = useRef(true);
  const busy = useRef(false);        // blocks a second tap before the re-render disables the button

  useEffect(() => {
    alive.current = true;
    setInfo(null);
    setCharge(null);
    setFollowing(false);
    if (!orderId) return undefined;
    NetInfo.fetch().then((net) => {
      if (!net.isConnected) return;
      apiMobileMoneyInfo(orderId).then((d) => {
        if (!alive.current) return;
        setInfo(d);
        setPhone(d.customer_phone || '');
        setNetwork((d.networks || [])[0] || '');
      }).catch(() => {});
    });
    return () => { alive.current = false; clearTimeout(timer.current); };
  }, [orderId]);

  const poll =(id, startedAt = Date.now()) => {
    timer.current = setTimeout(async () => {
      if (Date.now() - startedAt > 25 * 60 * 1000) {      // stop following; the server keeps checking
        setFollowing(false);
        onMessage?.(t('Still not confirmed. It will be recorded automatically if the customer pays.'));
        return;
      }
      try {
        const c = await apiMobileMoneyStatus(id);
        if (!alive.current) return;
        setCharge((prev) => ({ ...prev, ...c }));
        // 'unknown' = no answer from M-Pesa yet; its callback can still settle it, so keep watching
        if (c.status === 'pending' || c.status === 'unknown') { poll(id, startedAt); return; }
        setFollowing(false);
        if (c.status === 'successful' && c.needs_refund) onMessage?.(t('Paid, but more than was due: {message}', { message: c.message }));
        if (c.status === 'successful') onPaid?.(c);
        else onMessage?.(`${c.status_display}${c.message ? `: ${c.message}` : ''}`);
      } catch (err) {
        const code = err?.response?.status;
        if (!alive.current) return;
        if (!(code >= 400 && code < 500)) poll(id, startedAt);   // 4xx: stop
        else setFollowing(false);
      }
    }, 4000);
  };

  const send = async () => {
    if (busy.current) return;
    busy.current = true;
    setSending(true);
    clearTimeout(timer.current);
    try {
      const c = await apiMobileMoneyStart(orderId, {
        phone: phone.trim(), amount: amount ?? info.balance_due, network,
      });
      setCharge(c);
      if (c.warning) onMessage?.(c.warning);
      if (c.redirect_url) Linking.openURL(c.redirect_url).catch(() => {});
      setFollowing(true);
      poll(c.id);
    } catch (err) {
      onMessage?.(err?.response?.data?.error || t('Could not send the payment request.'));
      // The request may have gone out anyway (slow reply): pick it up if the server has it open
      apiMobileMoneyInfo(orderId).then((d) => { if (alive.current) setInfo(d); }).catch(() => {});
    } finally {
      busy.current = false;
      setSending(false);
    }
  };

  // A request is still open (sent earlier, or its reply was lost): follow it instead of a new one
  useEffect(() => {
    const open = info && info.open_charge;
    if (!open || !alive.current) return;
    setCharge(open);
    setFollowing(true);
    clearTimeout(timer.current);
    poll(open.id);
  }, [info]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!info || !info.enabled) return null;

  const waiting = following && charge && (charge.status === 'pending' || charge.status === 'unknown');

  return (
    <View style={styles.box}>
      <View style={styles.row}>
        <MaterialCommunityIcons name="cellphone-arrow-down" size={18} color="#2E7D32" />
        <Text style={styles.title}>{t('Mobile money ({provider})', { provider: info.provider })}</Text>
      </View>
      <View style={[styles.row, { marginTop: 6 }]}>
        <TextInput dense mode="outlined" label={t('Phone number')} keyboardType="phone-pad" value={phone}
                   onChangeText={setPhone} style={{ flex: 1 }} disabled={waiting} />
      </View>
      {(info.networks || []).length > 0 && (
        <View style={[styles.row, { marginTop: 6, flexWrap: 'wrap' }]}>
          {info.networks.map((n) => (
            <Chip key={n} compact selected={network === n} onPress={() => setNetwork(n)} disabled={waiting}>{n}</Chip>
          ))}
        </View>
      )}
      {info.whole_amounts_only && <Text style={styles.hint}>{t('M-Pesa takes whole amounts only.')}</Text>}
      {waiting ? (
        <>
          <Text style={[styles.hint, { color: '#1565C0' }]}>
            {t('Request sent to {phone}. Waiting for the PIN…', { phone: charge.phone })}
          </Text>
          {!!charge.redirect_url && (
            <Button compact onPress={() => Linking.openURL(charge.redirect_url).catch(() => {})}>{t('Open approval page')}</Button>
          )}
        </>
      ) : charge && charge.status === 'successful' ? (
        <Text style={[styles.hint, { color: '#2E7D32' }]}>{charge.receipt ? t('Paid — receipt {receipt}.', { receipt: charge.receipt }) : t('Paid.')}</Text>
      ) : (
        <Button compact mode="contained" buttonColor="#2E7D32" style={{ marginTop: 6, alignSelf: 'flex-start' }}
                onPress={send} loading={sending} disabled={sending || phone.trim().length < 9}>
          {t('Send payment request')}
        </Button>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { borderWidth: 1, borderColor: '#C8E6C9', borderRadius: 8, padding: 8, marginBottom: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  title: { fontFamily: 'Poppins_600SemiBold', fontSize: 13 },
  hint: { fontFamily: 'Poppins_400Regular', fontSize: 12, color: '#777', marginTop: 4 },
});
