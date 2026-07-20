import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useAuthStore } from '../store/useAuthStore';
import LoginScreen from '../screens/auth/LoginScreen';
import RegisterScreen from '../screens/auth/RegisterScreen';
import CustomerNavigator from './CustomerNavigator';
import StaffNavigator from './StaffNavigator';
import RiderNavigator from './RiderNavigator';

const Stack = createNativeStackNavigator();

export default function AppNavigator() {
  const { token, user } = useAuthStore();

  const roleName = user?.role_name;
  const isCustomer      = !token || !user || roleName === 'customer';
  const isDeliveryRider = token && user && roleName === 'delivery_rider';

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {!token ? (
          <>
            <Stack.Screen name="Login" component={LoginScreen} />
            <Stack.Screen name="Register" component={RegisterScreen} />
          </>
        ) : isDeliveryRider ? (
          <Stack.Screen name="Rider" component={RiderNavigator} />
        ) : isCustomer ? (
          <Stack.Screen name="Customer" component={CustomerNavigator} />
        ) : (
          <Stack.Screen name="Staff" component={StaffNavigator} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
