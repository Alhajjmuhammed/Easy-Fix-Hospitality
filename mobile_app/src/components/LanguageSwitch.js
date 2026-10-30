import React from 'react';
import { StyleSheet, View } from 'react-native';
import { SegmentedButtons, Text } from 'react-native-paper';
import { LANGUAGES, useLanguageStore } from '../store/useLanguageStore';
import { useT } from '../i18n';

/** English / Kiswahili switch. Saved on the phone, and on the account (for notifications and SMS). */
export default function LanguageSwitch({ style }) {
  const t = useT();
  const language = useLanguageStore((s) => s.language);
  const setLanguage = useLanguageStore((s) => s.setLanguage);

  // Saved on the phone at once; saved on the account now, or after login / when back online.
  const change = (code) => setLanguage(code);

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
