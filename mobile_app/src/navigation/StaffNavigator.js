import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useAuthStore } from '../store/useAuthStore';
import StationDashboardScreen from '../screens/station/StationDashboardScreen';

import CCDashboardScreen         from '../screens/customer_care/DashboardScreen';
import CCPaymentsScreen          from '../screens/customer_care/PaymentsScreen';
import CCOrderDetailScreen       from '../screens/customer_care/OrderDetailScreen';
import CCReportsScreen           from '../screens/customer_care/ReportsScreen';
import CCReceiptScreen           from '../screens/customer_care/ReceiptScreen';
import CCReceiptManagementScreen from '../screens/customer_care/ReceiptManagementScreen';
import TableSelectionScreen      from '../screens/customer/TableSelectionScreen';
import MenuScreen                from '../screens/customer/MenuScreen';
import CartScreen                from '../screens/customer/CartScreen';
import PlaceOrderScreen          from '../screens/customer/PlaceOrderScreen';
import OrderConfirmationScreen   from '../screens/customer/OrderConfirmationScreen';
import CashierDashboardScreen    from '../screens/cashier/DashboardScreen';
import CashierReceiptsScreen     from '../screens/cashier/ReceiptsScreen';
import CashierReportsScreen      from '../screens/cashier/ReportsScreen';
import CashierMyOrdersScreen     from '../screens/cashier/MyOrdersScreen';
import CashierWasteScreen        from '../screens/cashier/WasteScreen';
import RestaurantHeader          from '../components/RestaurantHeader';
import PrinterSettingsScreen     from '../screens/settings/PrinterSettingsScreen';
import AttendanceScreen          from '../screens/attendance/AttendanceScreen';
import MyAttendanceScreen        from '../screens/attendance/MyAttendanceScreen';

const Tab = createBottomTabNavigator();
const CCOrderStack          = createNativeStackNavigator();
const CCPaymentStack        = createNativeStackNavigator();
const CashierMyOrdersStack  = createNativeStackNavigator();
const CashierDashboardStack = createNativeStackNavigator();
const StationStack          = createNativeStackNavigator();
const StationTab            = createBottomTabNavigator();
const AttendanceStack       = createNativeStackNavigator();

const STATION_ROLES = ['kitchen', 'bar', 'buffet', 'service'];

function CashierDashboardStackNavigator() {
  return (
    <CashierDashboardStack.Navigator
      screenOptions={({ navigation }) => ({
        headerShown: true,
        header: () => (
          <RestaurantHeader
            onBack={navigation.canGoBack() ? () => navigation.goBack() : null}
          />
        ),
      })}
    >
      <CashierDashboardStack.Screen name="DashboardMain" component={CashierDashboardScreen} />
      <CashierDashboardStack.Screen name="OrderDetail"   component={CCOrderDetailScreen} />
      <CashierDashboardStack.Screen name="Receipt"       component={CCReceiptScreen} />
    </CashierDashboardStack.Navigator>
  );
}

function CashierMyOrdersStackNavigator() {
  return (
    <CashierMyOrdersStack.Navigator
      screenOptions={({ navigation }) => ({
        headerShown: true,
        header: () => (
          <RestaurantHeader
            onBack={navigation.canGoBack() ? () => navigation.goBack() : null}
          />
        ),
      })}
    >
      <CashierMyOrdersStack.Screen name="MyOrdersList" component={CashierMyOrdersScreen} />
      <CashierMyOrdersStack.Screen name="OrderDetail"  component={CCOrderDetailScreen} />
      <CashierMyOrdersStack.Screen name="Receipt"      component={CCReceiptScreen} />
    </CashierMyOrdersStack.Navigator>
  );
}

function CCOrderStackNavigator() {
  return (
    <CCOrderStack.Navigator
      screenOptions={({ navigation }) => ({
        headerShown: true,
        header: () => (
          <RestaurantHeader
            onBack={navigation.canGoBack() ? () => navigation.goBack() : null}
          />
        ),
      })}
    >
      <CCOrderStack.Screen
        name="TableSelection"
        component={TableSelectionScreen}
      />
      <CCOrderStack.Screen
        name="Menu"
        component={MenuScreen}
      />
      <CCOrderStack.Screen
        name="Cart"
        component={CartScreen}
      />
      <CCOrderStack.Screen
        name="PlaceOrder"
        component={PlaceOrderScreen}
      />
      <CCOrderStack.Screen
        name="OrderConfirmation"
        component={OrderConfirmationScreen}
        options={{ headerShown: false }}
      />
    </CCOrderStack.Navigator>
  );
}

function CCPaymentStackNavigator() {
  return (
    <CCPaymentStack.Navigator
      screenOptions={({ navigation }) => ({
        headerShown: true,
        header: () => (
          <RestaurantHeader
            onBack={navigation.canGoBack() ? () => navigation.goBack() : null}
          />
        ),
      })}
    >
      <CCPaymentStack.Screen
        name="PaymentsList"
        component={CCPaymentsScreen}
        options={({ navigation }) => ({
          header: () => (
            <RestaurantHeader
              extraMenuItems={[
                {
                  icon: 'receipt-text-check',
                  label: 'Receipt Management',
                  onPress: () => navigation.navigate('ReceiptManagement'),
                },
              ]}
            />
          ),
        })}
      />
      <CCPaymentStack.Screen name="OrderDetail"   component={CCOrderDetailScreen} />
      <CCPaymentStack.Screen name="Receipt"        component={CCReceiptScreen} />
      <CCPaymentStack.Screen name="ReceiptManagement" component={CCReceiptManagementScreen} />
    </CCPaymentStack.Navigator>
  );
}

function AttendanceStackNavigator() {
  return (
    <AttendanceStack.Navigator
      screenOptions={({ navigation }) => ({
        headerShown: true,
        header: () => (
          <RestaurantHeader
            onBack={navigation.canGoBack() ? () => navigation.goBack() : null}
          />
        ),
      })}
    >
      <AttendanceStack.Screen name="AttendanceMain" component={AttendanceScreen} />
      <AttendanceStack.Screen name="MyAttendance"   component={MyAttendanceScreen} />
    </AttendanceStack.Navigator>
  );
}

const ICONS = {
  Dashboard:  'view-dashboard',
  Order:      'food-fork-drink',
  Payments:   'cash-register',
  Reports:    'chart-bar',
  Receipts:   'receipt-text',
  MyOrders:   'account-clock',
  Waste:      'trash-can-outline',
  Settings:   'cog-outline',
  Attendance: 'badge-account-outline',
};

const tabScreenOptions = ({ navigation }) => ({
  headerShown: true,
  header: () => (
    <RestaurantHeader
      onBack={navigation.canGoBack() ? () => navigation.goBack() : null}
    />
  ),
});

export default function StaffNavigator() {
  const { user } = useAuthStore();
  const isCashier  = user?.role_name === 'cashier';
  const isStation  = STATION_ROLES.includes(user?.role_name);
  const isManager  = ['manager', 'branch_owner', 'main_owner', 'owner'].includes(user?.role_name);

  // Station staff (kitchen / bar / buffet / service) get Dashboard + Printer Settings
  if (isStation) {
    return (
      <StationTab.Navigator
        screenOptions={({ route }) => ({
          headerShown: false,
          tabBarActiveTintColor: '#2c3e50',
          tabBarInactiveTintColor: '#9E9E9E',
          tabBarIcon: ({ color, size }) => {
            const icons = { Dashboard: 'view-dashboard', Settings: 'cog-outline' };
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
        <StationTab.Screen
          name="Dashboard"
          component={StationDashboardScreen}
          options={{ title: 'Orders', headerShown: false }}
        />
        <StationTab.Screen
          name="Settings"
          component={PrinterSettingsScreen}
          options={{ title: 'Printer', headerShown: false }}
        />
      </StationTab.Navigator>
    );
  }

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: '#2c3e50',
        tabBarInactiveTintColor: '#9E9E9E',
        tabBarIcon: ({ color, size }) => (
          <MaterialCommunityIcons
            name={ICONS[route.name] || 'circle'}
            size={size}
            color={color}
          />
        ),
      })}
    >
      {isCashier || isManager ? (
        <>
          <Tab.Screen
            name="Order"
            component={CCOrderStackNavigator}
            options={{ title: 'Menu', headerShown: false }}
          />
          <Tab.Screen
            name="Dashboard"
            component={CashierDashboardStackNavigator}
            options={{ title: 'Dashboard', headerShown: false }}
          />
          <Tab.Screen
            name="Receipts"
            component={CashierReceiptsScreen}
            options={{ headerShown: true, header: () => <RestaurantHeader /> }}
          />
          <Tab.Screen
            name="MyOrders"
            component={CashierMyOrdersStackNavigator}
            options={{ title: 'My Orders', headerShown: false }}
          />
          <Tab.Screen
            name="Reports"
            component={CashierReportsScreen}
            options={{ headerShown: true, header: () => <RestaurantHeader /> }}
          />
          <Tab.Screen
            name="Waste"
            component={CashierWasteScreen}
            options={{ title: 'Record Waste', headerShown: true, header: () => <RestaurantHeader /> }}
          />
          <Tab.Screen
            name="Settings"
            component={PrinterSettingsScreen}
            options={{ title: 'Printer', headerShown: false }}
          />
          <Tab.Screen
            name="Attendance"
            component={AttendanceStackNavigator}
            options={{ title: 'Attendance', headerShown: false }}
          />
        </>
      ) : (
        <>
          <Tab.Screen
            name="Dashboard"
            component={CCDashboardScreen}
            options={{
              headerShown: true,
              header: () => <RestaurantHeader />,
            }}
          />
          <Tab.Screen
            name="Order"
            component={CCOrderStackNavigator}
            options={{ title: 'Menu' }}
          />
          <Tab.Screen
            name="Payments"
            component={CCPaymentStackNavigator}
            options={{ title: 'Payments', headerShown: false }}
          />
          <Tab.Screen
            name="Reports"
            component={CCReportsScreen}
            options={{
              headerShown: true,
              header: () => <RestaurantHeader />,
            }}
          />
          <Tab.Screen
            name="Settings"
            component={PrinterSettingsScreen}
            options={{ title: 'Printer', headerShown: false }}
          />
          <Tab.Screen
            name="Attendance"
            component={AttendanceStackNavigator}
            options={{ title: 'Attendance', headerShown: false }}
          />
        </>
      )}
    </Tab.Navigator>
  );
}

