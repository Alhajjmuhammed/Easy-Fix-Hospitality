import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import RestaurantSelectorScreen from '../screens/customer/RestaurantSelectorScreen';
import TableSelectionScreen     from '../screens/customer/TableSelectionScreen';
import OrderTypeScreen          from '../screens/customer/OrderTypeScreen';
import DeliveryInfoScreen       from '../screens/customer/DeliveryInfoScreen';
import MenuScreen               from '../screens/customer/MenuScreen';
import CartScreen               from '../screens/customer/CartScreen';
import PlaceOrderScreen         from '../screens/customer/PlaceOrderScreen';
import OrderTrackingScreen      from '../screens/customer/OrderTrackingScreen';
import OrderConfirmationScreen  from '../screens/customer/OrderConfirmationScreen';
import MyOrdersScreen           from '../screens/customer/MyOrdersScreen';
import ReceiptScreen            from '../screens/customer/ReceiptScreen';
import ProfileScreen            from '../screens/customer/ProfileScreen';
import CustomerHeader           from '../components/CustomerHeader';

const Tab            = createBottomTabNavigator();
const OrderStack     = createNativeStackNavigator();
const MyOrdersStack  = createNativeStackNavigator();

function OrderStackNavigator() {
  return (
    <OrderStack.Navigator
      screenOptions={({ navigation }) => ({
        headerShown: true,
        header: () => (
          <CustomerHeader
            onBack={navigation.canGoBack() ? () => navigation.goBack() : null}
          />
        ),
      })}
    >
      <OrderStack.Screen
        name="RestaurantSelector"
        component={RestaurantSelectorScreen}
        options={{ headerShown: false }}
      />
      <OrderStack.Screen name="TableSelection" component={TableSelectionScreen} />
      <OrderStack.Screen name="OrderType"     component={OrderTypeScreen} />
      <OrderStack.Screen name="DeliveryInfo"  component={DeliveryInfoScreen} />
      <OrderStack.Screen name="Menu"           component={MenuScreen} />
      <OrderStack.Screen name="Cart"           component={CartScreen} />
      <OrderStack.Screen name="PlaceOrder"     component={PlaceOrderScreen} />
      <OrderStack.Screen
        name="OrderConfirmation"
        component={OrderConfirmationScreen}
        options={{ headerShown: false }}
      />
      <OrderStack.Screen name="OrderTracking"  component={OrderTrackingScreen} />
      <OrderStack.Screen name="Receipt"        component={ReceiptScreen} />
    </OrderStack.Navigator>
  );
}

function MyOrdersStackNavigator() {
  return (
    <MyOrdersStack.Navigator
      screenOptions={({ navigation }) => ({
        headerShown: true,
        header: () => (
          <CustomerHeader
            onBack={navigation.canGoBack() ? () => navigation.goBack() : null}
          />
        ),
      })}
    >
      <MyOrdersStack.Screen name="MyOrdersList"   component={MyOrdersScreen} />
      <MyOrdersStack.Screen name="OrderTracking"  component={OrderTrackingScreen} />
      <MyOrdersStack.Screen name="Receipt"        component={ReceiptScreen} />
    </MyOrdersStack.Navigator>
  );
}

export default function CustomerNavigator() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: true,
        header: () => <CustomerHeader />,
        tabBarActiveTintColor:   '#2c3e50',
        tabBarInactiveTintColor: '#9E9E9E',
        tabBarLabelStyle: { fontFamily: 'Poppins_600SemiBold', fontSize: 11 },
        tabBarIcon: ({ color, size }) => {
          const icons = {
            Order:    'silverware-fork-knife',
            MyOrders: 'receipt',
            Profile:  'account-circle',
          };
          return (
            <MaterialCommunityIcons
              name={icons[route.name] || 'circle'}
              size={size}
              color={color}
            />
          );
        },
      })}
    >
      <Tab.Screen
        name="Order"
        component={OrderStackNavigator}
        options={{ title: 'Order', headerShown: false }}
      />
      <Tab.Screen
        name="MyOrders"
        component={MyOrdersStackNavigator}
        options={{ title: 'My Orders', headerShown: false }}
      />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{ title: 'Profile' }}
      />
    </Tab.Navigator>
  );
}
