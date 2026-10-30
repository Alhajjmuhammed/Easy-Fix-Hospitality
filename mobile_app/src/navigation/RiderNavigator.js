import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useT } from '../i18n';

import RiderDashboardScreen       from '../screens/delivery/RiderDashboardScreen';
import RiderActiveDeliveryScreen  from '../screens/delivery/RiderActiveDeliveryScreen';
import ProfileScreen              from '../screens/customer/ProfileScreen';
import AttendanceScreen           from '../screens/attendance/AttendanceScreen';
import MyAttendanceScreen         from '../screens/attendance/MyAttendanceScreen';

const Tab   = createBottomTabNavigator();
const Stack = createNativeStackNavigator();
const AttendanceStack = createNativeStackNavigator();

const riderHeader = {
  headerStyle: { backgroundColor: '#1565C0' },
  headerTintColor: '#fff',
  headerTitleStyle: { fontFamily: 'Poppins_700Bold' },
};

function RiderAttendanceStack() {
  const t = useT();
  return (
    <AttendanceStack.Navigator screenOptions={riderHeader}>
      <AttendanceStack.Screen name="AttendanceMain" component={AttendanceScreen} options={{ title: t('Attendance') }} />
      <AttendanceStack.Screen name="MyAttendance" component={MyAttendanceScreen} options={{ title: t('My Attendance') }} />
    </AttendanceStack.Navigator>
  );
}

function DeliveryStack() {
  const t = useT();
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: '#1565C0' },
        headerTintColor: '#fff',
        headerTitleStyle: { fontFamily: 'Poppins_700Bold' },
      }}
    >
      <Stack.Screen
        name="RiderDashboard"
        component={RiderDashboardScreen}
        options={{ title: t('My Deliveries') }}
      />
      <Stack.Screen
        name="RiderActiveDelivery"
        component={RiderActiveDeliveryScreen}
        options={{ title: t('Active Delivery') }}
      />
    </Stack.Navigator>
  );
}

export default function RiderNavigator() {
  const t = useT();
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor:   '#1565C0',
        tabBarInactiveTintColor: '#9E9E9E',
        tabBarLabelStyle: { fontFamily: 'Poppins_600SemiBold', fontSize: 11 },
        tabBarIcon: ({ color, size }) => {
          const icons = { Deliveries: 'motorbike', Attendance: 'badge-account-outline', Profile: 'account-circle' };
          return <MaterialCommunityIcons name={icons[route.name] || 'circle'} size={size} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Deliveries" component={DeliveryStack} options={{ title: t('Deliveries') }} />
      <Tab.Screen name="Attendance" component={RiderAttendanceStack} options={{ title: t('Attendance') }} />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{
          title: t('Profile'),
          headerShown: true,
          headerStyle: { backgroundColor: '#1565C0' },
          headerTintColor: '#fff',
          headerTitleStyle: { fontFamily: 'Poppins_700Bold' },
        }}
      />
    </Tab.Navigator>
  );
}
