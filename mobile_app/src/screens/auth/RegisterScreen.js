import React, { useState } from 'react';
import {
  View,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  TouchableOpacity,
} from 'react-native';
import {
  Text,
  TextInput,
  Button,
  HelperText,
  Surface,
  useTheme,
} from 'react-native-paper';
import { useNavigation } from '@react-navigation/native';
import { useAuthStore } from '../../store/useAuthStore';

export default function RegisterScreen() {
  const theme = useTheme();
  const navigation = useNavigation();
  const { register, isLoading, error } = useAuthStore();

  const [form, setForm] = useState({
    first_name: '',
    last_name: '',
    username: '',
    email: '',
    phone_number: '',
    password: '',
    confirm_password: '',
  });
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [confirmVisible, setConfirmVisible] = useState(false);

  const set = (field) => (value) => setForm((f) => ({ ...f, [field]: value }));

  const isValid =
    form.first_name.trim() &&
    form.last_name.trim() &&
    form.username.trim() &&
    form.email.trim() &&
    form.password.trim() &&
    form.confirm_password.trim();

  const handleRegister = () => {
    if (!isValid) return;
    register({
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      username: form.username.trim(),
      email: form.email.trim().toLowerCase(),
      phone_number: form.phone_number.trim(),
      password: form.password,
      confirm_password: form.confirm_password,
    });
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={styles.container}
        keyboardShouldPersistTaps="handled"
      >
        <Surface style={styles.card} elevation={3}>
          <Text variant="headlineMedium" style={styles.title}>
            Create Account
          </Text>

          <View style={styles.row}>
            <TextInput
              label="First Name"
              value={form.first_name}
              onChangeText={set('first_name')}
              style={[styles.input, styles.halfInput]}
              mode="outlined"
            />
            <TextInput
              label="Last Name"
              value={form.last_name}
              onChangeText={set('last_name')}
              style={[styles.input, styles.halfInput]}
              mode="outlined"
            />
          </View>

          <TextInput
            label="Username"
            value={form.username}
            onChangeText={set('username')}
            autoCapitalize="none"
            autoCorrect={false}
            style={styles.input}
            mode="outlined"
            left={<TextInput.Icon icon="account" />}
          />

          <TextInput
            label="Email"
            value={form.email}
            onChangeText={set('email')}
            autoCapitalize="none"
            keyboardType="email-address"
            style={styles.input}
            mode="outlined"
            left={<TextInput.Icon icon="email" />}
          />

          <TextInput
            label="Phone Number (optional)"
            value={form.phone_number}
            onChangeText={set('phone_number')}
            keyboardType="phone-pad"
            style={styles.input}
            mode="outlined"
            left={<TextInput.Icon icon="phone" />}
          />

          <TextInput
            label="Password"
            value={form.password}
            onChangeText={set('password')}
            secureTextEntry={!passwordVisible}
            style={styles.input}
            mode="outlined"
            left={<TextInput.Icon icon="lock" />}
            right={
              <TextInput.Icon
                icon={passwordVisible ? 'eye-off' : 'eye'}
                onPress={() => setPasswordVisible((v) => !v)}
              />
            }
          />

          <TextInput
            label="Confirm Password"
            value={form.confirm_password}
            onChangeText={set('confirm_password')}
            secureTextEntry={!confirmVisible}
            style={styles.input}
            mode="outlined"
            left={<TextInput.Icon icon="lock-check" />}
            right={
              <TextInput.Icon
                icon={confirmVisible ? 'eye-off' : 'eye'}
                onPress={() => setConfirmVisible((v) => !v)}
              />
            }
          />

          {error ? (
            <HelperText type="error" visible>
              {error}
            </HelperText>
          ) : null}

          <Button
            mode="contained"
            onPress={handleRegister}
            loading={isLoading}
            disabled={isLoading || !isValid}
            style={styles.button}
            contentStyle={styles.buttonContent}
          >
            Register
          </Button>

          <TouchableOpacity
            onPress={() => navigation.navigate('Login')}
            style={styles.loginLink}
          >
            <Text style={{ color: theme.colors.primary }}>
              Already have an account? Sign In
            </Text>
          </TouchableOpacity>
        </Surface>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  container: {
    flexGrow: 1,
    justifyContent: 'center',
    padding: 24,
  },
  card: {
    padding: 24,
    borderRadius: 12,
  },
  title: {
    textAlign: 'center',
    marginBottom: 24,
    fontFamily: 'Poppins_700Bold',
  },
  row: {
    flexDirection: 'row',
    gap: 8,
  },
  input: {
    marginBottom: 12,
  },
  halfInput: {
    flex: 1,
  },
  button: {
    marginTop: 8,
    borderRadius: 8,
  },
  buttonContent: {
    paddingVertical: 6,
  },
  loginLink: {
    marginTop: 16,
    alignItems: 'center',
  },
});
