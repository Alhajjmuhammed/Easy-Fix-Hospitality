import React from 'react';
import { StyleSheet, View } from 'react-native';
import { SegmentedButtons, Text } from 'react-native-paper';
import client from '../api/client';
import { useAuthStore } from '../store/useAuthStore';
import { LANGUAGES, useLanguageStore } from '../store/useLanguageStore';
import { useT } from '../i18n';

/** English / Kiswahili switch. Saved on the phone, and on the account (for notifications and SMS). */
export default function LanguageSwitch({ style }) {
  const t = useT();
  const language = useLanguageStore((s) => s.language);
  const setLanguage = useLanguageStore((s) => s.setLanguage);
  const token = useAuthStore((s) => s.token);

  const change = (code) => {
    setLanguage(code);
    if (token) client.post('/api/v1/auth/language/', { language: code }).catch(() => { /* older server: phone only */ });
  };

  return (
    <View style={[styles.wrap, style]}>
      <Text style={styles.label}>{t('Language')}</Text>
      <SegmentedButtons
        value={language}
        onValueChange={change}
        buttons={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
        density="small"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginVertical: 8 },
  label: { fontFamily: 'Poppins_600SemiBold', fontSize: 13, marginBottom: 6 },
});
