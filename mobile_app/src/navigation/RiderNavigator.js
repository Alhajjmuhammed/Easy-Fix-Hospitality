import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import RiderDashboardScreen       from '../screens/delivery/RiderDashboardScreen';
import RiderActiveDeliveryScreen  from '../screens/delivery/RiderActiveDeliveryScreen';
import ProfileScreen              from '../screens/customer/ProfileScreen';

const Tab   = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

function DeliveryStack() {
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
        options={{ title: 'My Deliveries' }}
      />
      <Stack.Screen
        name="RiderActiveDelivery"
        component={RiderActiveDeliveryScreen}
        options={{ title: 'Active Delivery' }}
      />
    </Stack.Navigator>
  );
}

export default function RiderNavigator() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor:   '#1565C0',
        tabBarInactiveTintColor: '#9E9E9E',
        tabBarLabelStyle: { fontFamily: 'Poppins_600SemiBold', fontSize: 11 },
        tabBarIcon: ({ color, size }) => {
          const icons = { Deliveries: 'motorbike', Profile: 'account-circle' };
          return <MaterialCommunityIcons name={icons[route.name] || 'circle'} size={size} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Deliveries" component={DeliveryStack} options={{ title: 'Deliveries' }} />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{
          title: 'Profile',
          headerShown: true,
          headerStyle: { backgroundColor: '#1565C0' },
          headerTintColor: '#fff',
          headerTitleStyle: { fontFamily: 'Poppins_700Bold' },
        }}
      />
    </Tab.Navigator>
  );
}
