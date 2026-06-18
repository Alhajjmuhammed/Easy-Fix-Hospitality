import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Vibration,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

const PAD = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
  [null, '0', 'del'],
];

export default function LockScreen({ onUnlock }) {
  const [pin, setPin] = useState('');
  const [error, setError] = useState(false);
  const [checking, setChecking] = useState(false);

  const handleDigit = async (digit) => {
    if (checking) return;
    const newPin = pin + digit;
    setPin(newPin);
    setError(false);

    if (newPin.length === 4) {
      setChecking(true);
      const ok = await onUnlock(newPin);
      if (!ok) {
        setError(true);
        Vibration.vibrate(400);
        setTimeout(() => {
          setPin('');
          setError(false);
          setChecking(false);
        }, 800);
      }
      // If ok, parent will unmount this screen — no need to reset
    }
  };

  const handleDelete = () => {
    if (checking) return;
    setPin((p) => p.slice(0, -1));
    setError(false);
  };

  return (
    <SafeAreaView style={styles.container}>
      <Ionicons name="lock-closed" size={52} color="#2c3e50" style={styles.lockIcon} />
      <Text style={styles.title}>Screen Locked</Text>
      <Text style={styles.subtitle}>Enter your 4-digit PIN</Text>

      {/* PIN dots */}
      <View style={styles.dotsRow}>
        {Array(4).fill(null).map((_, i) => (
          <View
            key={i}
            style={[
              styles.dot,
              pin.length > i && (error ? styles.dotError : styles.dotFilled),
            ]}
          />
        ))}
      </View>

      {error && <Text style={styles.errorText}>Wrong PIN — try again</Text>}

      {/* Number pad */}
      {PAD.map((row, ri) => (
        <View key={ri} style={styles.padRow}>
          {row.map((key, ki) => {
            if (!key) return <View key={ki} style={styles.keyPlaceholder} />;
            if (key === 'del') {
              return (
                <TouchableOpacity
                  key={ki}
                  style={styles.key}
                  onPress={handleDelete}
                  activeOpacity={0.6}
                >
                  <Ionicons name="backspace-outline" size={26} color="#2c3e50" />
                </TouchableOpacity>
              );
            }
            return (
              <TouchableOpacity
                key={ki}
                style={styles.key}
                onPress={() => handleDigit(key)}
                activeOpacity={0.6}
              >
                <Text style={styles.keyText}>{key}</Text>
              </TouchableOpacity>
            );
          })}
        </View>
      ))}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f0f2f5',
    alignItems: 'center',
    justifyContent: 'center',
  },
  lockIcon: { marginBottom: 16 },
  title: {
    fontSize: 24,
    fontWeight: '700',
    color: '#2c3e50',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 14,
    color: '#666',
    marginBottom: 36,
  },
  dotsRow: {
    flexDirection: 'row',
    marginBottom: 12,
  },
  dot: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
    borderColor: '#2c3e50',
    backgroundColor: '#f0f2f5',
    marginHorizontal: 10,
  },
  dotFilled: { backgroundColor: '#2c3e50' },
  dotError:  { borderColor: '#e74c3c', backgroundColor: '#e74c3c' },
  errorText: {
    color: '#e74c3c',
    fontSize: 13,
    marginBottom: 8,
    fontWeight: '500',
  },
  padRow: {
    flexDirection: 'row',
    marginVertical: 8,
  },
  key: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 14,
    elevation: 3,
    shadowColor: '#000',
    shadowOpacity: 0.1,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
  },
  keyPlaceholder: {
    width: 76,
    height: 76,
    marginHorizontal: 14,
  },
  keyText: {
    fontSize: 28,
    fontWeight: '600',
    color: '#2c3e50',
  },
});
