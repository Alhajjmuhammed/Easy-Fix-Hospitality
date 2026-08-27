import React, { useState, useEffect, useRef } from 'react';
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
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [lockedOutUntil, setLockedOutUntil] = useState(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const timerRef = useRef(null);
  const wrongPinTimeoutRef = useRef(null);

  useEffect(() => {
    return () => clearTimeout(wrongPinTimeoutRef.current);
  }, []);

  useEffect(() => {
    if (!lockedOutUntil) return;
    const tick = () => {
      const remaining = Math.ceil((lockedOutUntil - Date.now()) / 1000);
      if (remaining <= 0) {
        setLockedOutUntil(null);
        setSecondsLeft(0);
        setError('');
        clearInterval(timerRef.current);
      } else {
        setSecondsLeft(remaining);
      }
    };
    tick();
    timerRef.current = setInterval(tick, 1000);
    return () => clearInterval(timerRef.current);
  }, [lockedOutUntil]);

  const isLockedOut = lockedOutUntil && Date.now() < lockedOutUntil;

  const handleDigit = async (digit) => {
    if (checking || isLockedOut) return;
    const newPin = pin + digit;
    setPin(newPin);
    setError('');

    if (newPin.length === 4) {
      setChecking(true);
      try {
        const result = await onUnlock(newPin);
        if (!result.success) {
          Vibration.vibrate(400);
          if (result.lockedOutUntil) {
            setLockedOutUntil(result.lockedOutUntil);
            setError('Too many attempts — locked out');
          } else {
            setError(`Wrong PIN — ${result.attemptsLeft} attempt${result.attemptsLeft !== 1 ? 's' : ''} left`);
          }
          wrongPinTimeoutRef.current = setTimeout(() => {
            setPin('');
            setChecking(false);
          }, 800);
        }
        // If success, parent unmounts this screen — no need to reset checking
      } catch (_) {
        // SecureStore / Keystore hardware error — reset so the keypad stays usable
        setError('Could not verify PIN. Try again.');
        setPin('');
        setChecking(false);
      }
    }
  };

  const handleDelete = () => {
    if (checking || isLockedOut) return;
    setPin((p) => p.slice(0, -1));
    setError('');
  };

  return (
    <SafeAreaView style={styles.container}>
      <Ionicons name="lock-closed" size={52} color="#2c3e50" style={styles.lockIcon} />
      <Text style={styles.title}>Screen Locked</Text>
      <Text style={styles.subtitle}>{isLockedOut ? `Try again in ${secondsLeft}s` : 'Enter your 4-digit PIN'}</Text>

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

      {!!error && <Text style={styles.errorText}>{error}</Text>}

      {/* Number pad */}
      {PAD.map((row, ri) => (
        <View key={ri} style={styles.padRow}>
          {row.map((key, ki) => {
            if (!key) return <View key={ki} style={styles.keyPlaceholder} />;
            if (key === 'del') {
              return (
                <TouchableOpacity
                  key={ki}
                  style={[styles.key, (isLockedOut || checking) && styles.keyDisabled]}
                  onPress={handleDelete}
                  activeOpacity={0.6}
                  disabled={!!isLockedOut || checking}
                >
                  <Ionicons name="backspace-outline" size={26} color={isLockedOut ? '#bbb' : '#2c3e50'} />
                </TouchableOpacity>
              );
            }
            return (
              <TouchableOpacity
                key={ki}
                style={[styles.key, (isLockedOut || checking) && styles.keyDisabled]}
                onPress={() => handleDigit(key)}
                activeOpacity={0.6}
                disabled={!!isLockedOut || checking}
              >
                <Text style={[styles.keyText, isLockedOut && styles.keyTextDisabled]}>{key}</Text>
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
  keyDisabled: { backgroundColor: '#e8e8e8', elevation: 0 },
  keyTextDisabled: { color: '#bbb' },
});
