import React, { useState } from 'react';
import { View, StyleSheet, TouchableOpacity, Alert, Modal } from 'react-native';
import { Text, Menu as PaperMenu, Divider } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuthStore } from '../store/useAuthStore';

const PRIMARY = '#2c3e50';

function initials(name = '') {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('');
}

export default function CustomerHeader({ onBack = null }) {
  const { user, logout } = useAuthStore();
  const insets = useSafeAreaInsets();
  const [menuVisible,    setMenuVisible]    = useState(false);
  const [profileVisible, setProfileVisible] = useState(false);

  const fullName =
    [user?.first_name, user?.last_name].filter(Boolean).join(' ') ||
    user?.username ||
    'Guest';
  const userInitials    = initials(fullName) || fullName.slice(0, 2).toUpperCase();
  const firstName       = fullName.split(' ')[0];

  const handleLogout = () => {
    setMenuVisible(false);
    Alert.alert('Logout', 'Are you sure you want to logout?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Logout', style: 'destructive', onPress: logout },
    ]);
  };

  const handleProfile = () => {
    setMenuVisible(false);
    setProfileVisible(true);
  };

  return (
    <View style={[styles.wrapper, { paddingTop: insets.top + 8 }]}>
      <View style={styles.inner}>

        {/* Optional back arrow */}
        {onBack && (
          <TouchableOpacity onPress={onBack} style={styles.backBtn} hitSlop={8}>
            <MaterialCommunityIcons name="arrow-left" size={24} color="#333" />
          </TouchableOpacity>
        )}

        {/* Left — brand icon + greeting */}
        <View style={styles.leftGroup}>
          <View style={styles.brandIcon}>
            <MaterialCommunityIcons name="silverware-fork-knife" size={22} color="#fff" />
          </View>
          <View style={styles.nameBlock}>
            <Text style={styles.brandName} numberOfLines={1}>Easy Fix</Text>
            <Text style={styles.greetingText} numberOfLines={1}>Hello, {firstName} 👋</Text>
          </View>
        </View>

        {/* Right — user initials + three-dots */}
        <View style={styles.rightGroup}>
          <View style={styles.avatarCircle}>
            <Text style={styles.avatarText}>{userInitials}</Text>
          </View>
          <PaperMenu
            visible={menuVisible}
            onDismiss={() => setMenuVisible(false)}
            anchor={
              <TouchableOpacity
                onPress={() => setMenuVisible(true)}
                style={styles.dotsBtn}
                hitSlop={8}
              >
                <MaterialCommunityIcons name="dots-vertical" size={22} color="#666" />
              </TouchableOpacity>
            }
          >
            <PaperMenu.Item
              leadingIcon="account-circle-outline"
              title="Profile"
              onPress={handleProfile}
            />
            <Divider />
            <PaperMenu.Item
              leadingIcon="logout"
              title="Logout"
              onPress={handleLogout}
              titleStyle={{ color: '#E53935' }}
            />
          </PaperMenu>
        </View>
      </View>

      <View style={styles.divider} />

      {/* ── Profile Modal ─────────────────────────────────────────────── */}
      <Modal
        visible={profileVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setProfileVisible(false)}
      >
        <View style={styles.overlay}>
          <TouchableOpacity
            style={StyleSheet.absoluteFill}
            activeOpacity={1}
            onPress={() => setProfileVisible(false)}
          />
          <View style={styles.card}>
            <View style={styles.cardAvatar}>
              <Text style={styles.cardAvatarText}>{userInitials}</Text>
            </View>
            <Text style={styles.cardName}>{fullName}</Text>
            <Text style={styles.cardRole}>Customer</Text>
            <View style={styles.sep} />
            <View style={styles.row}>
              <MaterialCommunityIcons name="account-outline" size={16} color="#888" />
              <Text style={styles.rowText}>{user?.username}</Text>
            </View>
            {!!user?.email && (
              <View style={styles.row}>
                <MaterialCommunityIcons name="email-outline" size={16} color="#888" />
                <Text style={styles.rowText}>{user.email}</Text>
              </View>
            )}
            {!!user?.phone_number && (
              <View style={styles.row}>
                <MaterialCommunityIcons name="phone-outline" size={16} color="#888" />
                <Text style={styles.rowText}>{user.phone_number}</Text>
              </View>
            )}
            {!!user?.address && (
              <View style={styles.row}>
                <MaterialCommunityIcons name="map-marker-outline" size={16} color="#888" />
                <Text style={styles.rowText}>{user.address}</Text>
              </View>
            )}
            {!!user?.date_joined && (
              <View style={styles.row}>
                <MaterialCommunityIcons name="calendar-outline" size={16} color="#888" />
                <Text style={styles.rowText}>
                  Member since {new Date(user.date_joined).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
                </Text>
              </View>
            )}
            {!!user?.last_login && (
              <View style={styles.row}>
                <MaterialCommunityIcons name="clock-outline" size={16} color="#888" />
                <Text style={styles.rowText}>
                  Last login {new Date(user.last_login).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
                </Text>
              </View>
            )}
            <TouchableOpacity
              style={styles.closeBtn}
              onPress={() => setProfileVisible(false)}
            >
              <Text style={styles.closeBtnText}>Close</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper:       { backgroundColor: '#fff' },
  inner:         {
    flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16,
    paddingBottom: 12, justifyContent: 'space-between',
  },
  backBtn:       { marginRight: 8 },
  leftGroup:     { flexDirection: 'row', alignItems: 'center', flex: 1, marginRight: 8 },
  brandIcon:     {
    width: 40, height: 40, borderRadius: 12, backgroundColor: PRIMARY,
    alignItems: 'center', justifyContent: 'center', marginRight: 10,
  },
  nameBlock:     { flex: 1 },
  brandName:     { fontFamily: 'Poppins_700Bold', fontSize: 15, color: PRIMARY, lineHeight: 20 },
  greetingText:  { fontFamily: 'Poppins_400Regular', fontSize: 11, color: '#888', lineHeight: 16 },
  rightGroup:    { flexDirection: 'row', alignItems: 'center', gap: 4 },
  avatarCircle:  {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: PRIMARY + '22', borderWidth: 1, borderColor: PRIMARY + '55',
    alignItems: 'center', justifyContent: 'center',
  },
  avatarText:    { fontFamily: 'Poppins_600SemiBold', fontSize: 12, color: PRIMARY, lineHeight: 16 },
  dotsBtn:       { padding: 4 },
  divider:       { height: 1, backgroundColor: '#F0F0F0' },
  // Profile modal
  overlay:       { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'center', alignItems: 'center' },
  card:          { backgroundColor: '#fff', borderRadius: 20, padding: 28, width: '82%', alignItems: 'center', elevation: 8 },
  cardAvatar:    {
    width: 72, height: 72, borderRadius: 36, backgroundColor: PRIMARY,
    alignItems: 'center', justifyContent: 'center', marginBottom: 12,
  },
  cardAvatarText: { color: '#fff', fontFamily: 'Poppins_700Bold', fontSize: 26, lineHeight: 32 },
  cardName:      { fontFamily: 'Poppins_700Bold', fontSize: 17, color: '#1A1A1A', textAlign: 'center' },
  cardRole:      { fontFamily: 'Poppins_400Regular', fontSize: 12, color: '#888', marginTop: 2, marginBottom: 8 },
  sep:           { width: '100%', height: 1, backgroundColor: '#F0F0F0', marginVertical: 12 },
  row:           { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'stretch', paddingVertical: 4 },
  rowText:       { fontFamily: 'Poppins_400Regular', fontSize: 13, color: '#444', flex: 1 },
  closeBtn:      { marginTop: 20, paddingVertical: 10, paddingHorizontal: 40, borderRadius: 10, backgroundColor: PRIMARY },
  closeBtnText:  { color: '#fff', fontFamily: 'Poppins_600SemiBold', fontSize: 14 },
});
