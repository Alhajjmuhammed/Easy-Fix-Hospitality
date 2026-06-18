import React, { useState } from 'react';
import { View, StyleSheet, TouchableOpacity, Image, Alert, Modal } from 'react-native';
import { Text, Menu as PaperMenu, Divider } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuthStore } from '../store/useAuthStore';

function stringToColor(str = '') {
  const PALETTE = ['#2c3e50', '#AD1457', '#6A1B9A', '#00838F', '#2E7D32', '#E65100', '#4527A0', '#37474F'];
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

function initials(name = '') {
  return name.split(' ').filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
}

export default function RestaurantHeader({ extraMenuItems = [], onBack = null }) {
  const { user, logout } = useAuthStore();
  const insets = useSafeAreaInsets();
  const [menuVisible, setMenuVisible] = useState(false);
  const [profileVisible, setProfileVisible] = useState(false);

  const restaurantName = user?.restaurant_name || 'Restaurant';
  const logoUrl = user?.restaurant_logo_url || null;
  const staffName =
    [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || 'Staff';
  const restaurantColor = stringToColor(restaurantName);
  const restaurantInitials = initials(restaurantName);
  const staffInitials = initials(staffName) || staffName.slice(0, 2).toUpperCase();
  const roleName = (user?.role_name || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

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

        {/* Left — logo + restaurant name + greeting */}
        <View style={styles.leftGroup}>
          {logoUrl ? (
            <Image source={{ uri: logoUrl }} style={styles.logoImage} resizeMode="cover" />
          ) : (
            <View style={[styles.logoCircle, { backgroundColor: restaurantColor }]}>
              <Text style={styles.logoText}>{restaurantInitials}</Text>
            </View>
          )}
          <View style={styles.nameBlock}>
            <Text style={styles.restaurantName} numberOfLines={1}>{restaurantName}</Text>
            <Text style={styles.greetingText} numberOfLines={1}>Welcome, {staffName.split(' ')[0]}</Text>
          </View>
        </View>

        {/* Right — staff initials + three-dots menu */}
        <View style={styles.rightGroup}>
          <View style={[styles.staffCircle, { backgroundColor: restaurantColor + '22', borderColor: restaurantColor + '55' }]}>
            <Text style={[styles.staffInitials, { color: restaurantColor }]}>{staffInitials}</Text>
          </View>
          <PaperMenu
            visible={menuVisible}
            onDismiss={() => setMenuVisible(false)}
            anchor={
              <TouchableOpacity onPress={() => setMenuVisible(true)} style={styles.dotsBtn} hitSlop={8}>
                <MaterialCommunityIcons name="dots-vertical" size={22} color="#666" />
              </TouchableOpacity>
            }
          >
            {extraMenuItems.map((item, i) => (
              <PaperMenu.Item
                key={i}
                leadingIcon={item.icon}
                title={item.label}
                onPress={() => { setMenuVisible(false); item.onPress(); }}
                titleStyle={item.color ? { color: item.color } : undefined}
              />
            ))}
            {extraMenuItems.length > 0 && <Divider />}
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

      {/* Profile Modal */}
      <Modal
        visible={profileVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setProfileVisible(false)}
      >
        <View style={styles.profileOverlay}>
          <TouchableOpacity
            style={StyleSheet.absoluteFill}
            activeOpacity={1}
            onPress={() => setProfileVisible(false)}
          />
          <View style={styles.profileCard}>
            <View style={[styles.profileAvatar, { backgroundColor: restaurantColor }]}>
              <Text style={styles.profileAvatarText}>{staffInitials}</Text>
            </View>
            <Text style={styles.profileFullName}>{staffName}</Text>
            <Text style={styles.profileRoleText}>{roleName}</Text>
            <View style={styles.profileSep} />
            <View style={styles.profileRow}>
              <MaterialCommunityIcons name="account-outline" size={16} color="#888" />
              <Text style={styles.profileRowText}>{user?.username}</Text>
            </View>
            {!!user?.email && (
              <View style={styles.profileRow}>
                <MaterialCommunityIcons name="email-outline" size={16} color="#888" />
                <Text style={styles.profileRowText}>{user.email}</Text>
              </View>
            )}
            <View style={styles.profileRow}>
              <MaterialCommunityIcons name="store-outline" size={16} color="#888" />
              <Text style={styles.profileRowText}>{restaurantName}</Text>
            </View>
            <TouchableOpacity
              style={[styles.profileCloseBtn, { backgroundColor: restaurantColor }]}
              onPress={() => setProfileVisible(false)}
            >
              <Text style={styles.profileCloseBtnText}>Close</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { backgroundColor: '#fff' },
  inner: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingBottom: 12,
    justifyContent: 'space-between',
  },
  backBtn: { marginRight: 8 },
  leftGroup: { flexDirection: 'row', alignItems: 'center', flex: 1, marginRight: 8 },
  logoImage: { width: 44, height: 44, borderRadius: 12, marginRight: 10, backgroundColor: '#f0f0f0' },
  logoCircle: { width: 44, height: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center', marginRight: 10 },
  logoText: { color: '#fff', fontFamily: 'Poppins_700Bold', fontSize: 16, lineHeight: 20 },
  nameBlock: { flex: 1 },
  restaurantName: { fontFamily: 'Poppins_700Bold', fontSize: 15, color: '#1A1A1A', lineHeight: 20 },
  greetingText: { fontFamily: 'Poppins_400Regular', fontSize: 11, color: '#888', lineHeight: 16 },
  rightGroup: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  staffCircle: { width: 36, height: 36, borderRadius: 18, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  staffInitials: { fontFamily: 'Poppins_600SemiBold', fontSize: 12, lineHeight: 16 },
  dotsBtn: { padding: 4 },
  divider: { height: 1, backgroundColor: '#F0F0F0' },
  // Profile modal
  profileOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'center', alignItems: 'center' },
  profileCard: { backgroundColor: '#fff', borderRadius: 20, padding: 28, width: '82%', alignItems: 'center', elevation: 8 },
  profileAvatar: { width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  profileAvatarText: { color: '#fff', fontFamily: 'Poppins_700Bold', fontSize: 26, lineHeight: 32 },
  profileFullName: { fontFamily: 'Poppins_700Bold', fontSize: 17, color: '#1A1A1A', textAlign: 'center' },
  profileRoleText: { fontFamily: 'Poppins_400Regular', fontSize: 12, color: '#888', marginTop: 2, marginBottom: 8, textAlign: 'center' },
  profileSep: { width: '100%', height: 1, backgroundColor: '#F0F0F0', marginVertical: 12 },
  profileRow: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'stretch', paddingVertical: 4 },
  profileRowText: { fontFamily: 'Poppins_400Regular', fontSize: 13, color: '#444', flex: 1 },
  profileCloseBtn: { marginTop: 20, paddingVertical: 10, paddingHorizontal: 40, borderRadius: 10 },
  profileCloseBtnText: { color: '#fff', fontFamily: 'Poppins_600SemiBold', fontSize: 14 },
});
