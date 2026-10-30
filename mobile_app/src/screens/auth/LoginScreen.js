import React, { useState, useRef } from 'react';
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
import { useT } from '../../i18n';
import LanguageSwitch from '../../components/LanguageSwitch';

export default function LoginScreen() {
  const t = useT();
  const theme = useTheme();
  const navigation = useNavigation();
  const { login, isLoading, error, clearError } = useAuthStore();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [passwordVisible, setPasswordVisible] = useState(false);
  const passwordRef = useRef();

  const handleChange = (setter) => (v) => { if (error) clearError(); setter(v); };

  const handleLogin = () => {
    if (!username.trim() || !password.trim()) return;
    login(username.trim(), password);
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
            {t('Welcome Back')}
          </Text>

          <TextInput
            label={t('Username')}
            value={username}
            onChangeText={handleChange(setUsername)}
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="next"
            onSubmitEditing={() => passwordRef.current?.focus()}
            textContentType="username"
            style={styles.input}
            mode="outlined"
            left={<TextInput.Icon icon="account" />}
          />

          <TextInput
            ref={passwordRef}
            label={t('Password')}
            value={password}
            onChangeText={handleChange(setPassword)}
            secureTextEntry={!passwordVisible}
            returnKeyType="done"
            onSubmitEditing={handleLogin}
            textContentType="password"
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

          {error ? (
            <HelperText type="error" visible>
              {t(error)}
            </HelperText>
          ) : null}

          <Button
            mode="contained"
            onPress={handleLogin}
            loading={isLoading}
            disabled={isLoading || !username.trim() || !password.trim()}
            style={styles.button}
            contentStyle={styles.buttonContent}
          >
            {t('Sign In')}
          </Button>

          <TouchableOpacity
            onPress={() => navigation.navigate('Register')}
            style={styles.registerLink}
          >
            <Text style={{ color: theme.colors.primary }}>
              {t('New customer? Create an account')}
            </Text>
          </TouchableOpacity>

          <LanguageSwitch style={{ marginTop: 16 }} />
        </Surface>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  container: {
    flex: 1,
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
  input: {
    marginBottom: 12,
  },
  button: {
    marginTop: 8,
    borderRadius: 8,
  },
  buttonContent: {
    paddingVertical: 6,
  },
  registerLink: {
    marginTop: 16,
    alignItems: 'center',
  },
});
