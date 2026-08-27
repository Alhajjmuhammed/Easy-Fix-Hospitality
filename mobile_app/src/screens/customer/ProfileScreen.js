import React, { useState, useCallback, useRef, useEffect } from 'react';
import { View, StyleSheet, ScrollView, RefreshControl } from 'react-native';
import {
  Text,
  Card,
  Divider,
  Button,
  ActivityIndicator,
  Avatar,
  useTheme,
  Dialog,
  Portal,
} from 'react-native-paper';
import { useFocusEffect } from '@react-navigation/native';
import { useAuthStore } from '../../store/useAuthStore';
import { apiMe } from '../../api/auth';

const P700 = 'Poppins_700Bold';
const P600 = 'Poppins_600SemiBold';
const P400 = 'Poppins_400Regular';

function formatDate(isoString) {
  if (!isoString) return '—';
  try {
    return new Date(isoString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  } catch {
    return '—';
  }
}

function InfoRow({ label, value }) {
  return (
    <View style={styles.infoRow}>
      <Text variant="bodySmall" style={[styles.label, { fontFamily: P600 }]}>
        {label}
      </Text>
      <Text variant="bodyMedium" style={{ fontFamily: P400, flex: 1, textAlign: 'right' }}>
        {value || '—'}
      </Text>
    </View>
  );
}

export default function ProfileScreen() {
  const theme = useTheme();
  const { user: cachedUser, logout } = useAuthStore();
  const [user, setUser] = useState(cachedUser);
  const [refreshing, setRefreshing] = useState(false);
  const [logoutVisible, setLogoutVisible] = useState(false);
  const [fetchError, setFetchError] = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => { return () => { mountedRef.current = false; }; }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setFetchError(false);
    try {
      const fresh = await apiMe();
      if (!mountedRef.current) return;
      setUser(fresh.data);
    } catch {
      if (mountedRef.current && !user) setFetchError(true);
    } finally {
      if (mountedRef.current) setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh])
  );

  const handleLogout = async () => {
    setLogoutVisible(false);
    await logout();
  };

  if (!user) {
    if (fetchError) {
      return (
        <View style={styles.center}>
          <Text style={{ fontFamily: P400, color: '#757575', marginBottom: 16 }}>
            Could not load profile
          </Text>
          <Button mode="outlined" icon="refresh" onPress={refresh}>
            Retry
          </Button>
        </View>
      );
    }
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username;
  const initials = fullName
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);

  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} />
      }
    >
      {/* Avatar + Name */}
      <View style={styles.avatarSection}>
        <Avatar.Text
          size={80}
          label={initials}
          style={{ backgroundColor: theme.colors.primary }}
          labelStyle={{ fontFamily: P700, fontSize: 28 }}
        />
        <Text variant="headlineSmall" style={[styles.name, { fontFamily: P700 }]}>
          {fullName}
        </Text>
        <View style={[styles.roleBadge, { backgroundColor: theme.colors.primaryContainer }]}>
          <Text style={{ fontFamily: P600, fontSize: 12, color: theme.colors.onPrimaryContainer }}>
            Customer
          </Text>
        </View>
        {user.restaurant_name ? (
          <Text variant="bodySmall" style={[styles.restaurantName, { fontFamily: P400 }]}>
            🍽  {user.restaurant_name}
          </Text>
        ) : null}
      </View>

      {/* Account info */}
      <Card style={styles.card}>
        <Card.Title title="Account Details" titleStyle={{ fontFamily: P700 }} />
        <Card.Content>
          <InfoRow label="Username"    value={user.username} />
          <Divider style={styles.divider} />
          <InfoRow label="Email"       value={user.email} />
          <Divider style={styles.divider} />
          <InfoRow label="Phone"       value={user.phone_number} />
          <Divider style={styles.divider} />
          <InfoRow label="Address"     value={user.address} />
        </Card.Content>
      </Card>

      {/* Membership info */}
      <Card style={styles.card}>
        <Card.Title title="Membership" titleStyle={{ fontFamily: P700 }} />
        <Card.Content>
          <InfoRow label="Member Since" value={formatDate(user.date_joined)} />
          <Divider style={styles.divider} />
          <InfoRow label="Last Login"   value={formatDate(user.last_login)} />
        </Card.Content>
      </Card>

      {/* Logout */}
      <Button
        mode="outlined"
        icon="logout"
        textColor="#B71C1C"
        style={styles.logoutBtn}
        labelStyle={{ fontFamily: P600 }}
        onPress={() => setLogoutVisible(true)}
      >
        Log Out
      </Button>

      {/* Logout confirmation dialog */}
      <Portal>
        <Dialog visible={logoutVisible} onDismiss={() => setLogoutVisible(false)}>
          <Dialog.Title style={{ fontFamily: P700 }}>Log Out</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium" style={{ fontFamily: P400 }}>
              Are you sure you want to log out?
            </Text>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setLogoutVisible(false)} labelStyle={{ fontFamily: P600 }}>
              Cancel
            </Button>
            <Button
              textColor="#B71C1C"
              onPress={handleLogout}
              labelStyle={{ fontFamily: P600 }}
            >
              Log Out
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>

    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container:     { padding: 16, paddingBottom: 40 },
  center:        { flex: 1, justifyContent: 'center', alignItems: 'center' },
  avatarSection: { alignItems: 'center', marginBottom: 20, marginTop: 8 },
  name:          { marginTop: 12, marginBottom: 4 },
  roleBadge:     { paddingHorizontal: 12, paddingVertical: 4, borderRadius: 12, marginBottom: 6 },
  restaurantName:{ opacity: 0.7, marginTop: 2 },
  card:          { marginBottom: 12, borderRadius: 12 },
  infoRow:       { flexDirection: 'row', alignItems: 'center', paddingVertical: 10 },
  label:         { opacity: 0.6, width: 110 },
  divider:       { marginVertical: 0 },
  logoutBtn:     { marginTop: 8, borderColor: '#B71C1C' },
});
