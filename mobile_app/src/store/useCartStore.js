import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { restaurantSwitchPatch, migrateCart } from '../utils/cartRestaurant';

// The restaurant currently selected in the app (customers: QR / list; staff: their own).
// Required lazily: useAuthStore requires this store too.
const selectedRestaurantId = () => {
  try { return require('./useAuthStore').useAuthStore.getState().restaurantId ?? null; } catch (_) { return null; }
};

export const useCartStore = create(
  persist(
    (set, get) => ({
      items: [],      // [{ product, quantity }]
      tableId: null,
      tableName: '',
      restaurantId: null,
      existingOrderId: null,  // set when adding items to an existing order
      orderType: 'dine-in',   // 'dine-in' | 'delivery' | 'pickup'
      deliveryAddress: '',
      deliveryPhone: '',
      deliveryLat: null,
      deliveryLng: null,
      // Not cleared with the cart: remembers whether the selected restaurant was chosen
      // for dine-in, so RestaurantSelector only skips to the table list in that case.
      lastOrderMode: null,     // 'dine-in' | 'remote' | null (unknown)

      // restaurantId: the restaurant the cart's products belong to. Switching to another
      // restaurant empties the cart (see restaurantSwitchPatch).
      setTable: (tableId, tableName, restaurantId) => {
        const rid = restaurantId ?? selectedRestaurantId();
        set({
          ...(restaurantSwitchPatch(get(), rid) || {}),
          tableId, tableName, restaurantId: rid, existingOrderId: null, orderType: 'dine-in',
          deliveryAddress: '', deliveryPhone: '', deliveryLat: null, deliveryLng: null,
          lastOrderMode: 'dine-in',
        });
      },

      setRemoteOrder: (restaurantId, orderType, deliveryAddress = '', deliveryPhone = '', deliveryLat = null, deliveryLng = null) => {
        const rid = restaurantId ?? selectedRestaurantId();
        set({
          ...(restaurantSwitchPatch(get(), rid) || {}),
          restaurantId: rid, tableId: null, tableName: '', existingOrderId: null, orderType,
          deliveryAddress, deliveryPhone, deliveryLat, deliveryLng,
          lastOrderMode: 'remote',
        });
      },

      /** Empty the cart if it holds another restaurant's products. Returns true if it was emptied. */
      ensureRestaurant: (restaurantId) => {
        const patch = restaurantSwitchPatch(get(), restaurantId);
        if (!patch) return false;
        set(patch);
        return Array.isArray(patch.items);
      },

      /** How the customer last chose a restaurant: 'dine-in' (QR / table) or 'remote'. */
      setLastOrderMode: (mode) => set({ lastOrderMode: mode }),

      setExistingOrder: (orderId) =>
        set({ existingOrderId: orderId }),

      addItem: (product, quantity = 1) => {
        const qty = Math.max(1, Math.round(quantity));
        // First item of an empty cart: the cart now belongs to the selected restaurant
        if (!get().items.length && get().restaurantId == null) {
          const rid = selectedRestaurantId();
          if (rid != null) set({ restaurantId: rid });
        }
        const items = get().items;
        const existing = items.find((i) => i.product.id === product.id);
        if (existing) {
          set({
            items: items.map((i) =>
              i.product.id === product.id
                ? { ...i, quantity: i.quantity + qty }
                : i,
            ),
          });
        } else {
          set({ items: [...items, { product, quantity: qty }] });
        }
      },

      removeItem: (productId) =>
        set({ items: get().items.filter((i) => i.product.id !== productId) }),

      updateQuantity: (productId, quantity) => {
        if (quantity <= 0) {
          get().removeItem(productId);
          return;
        }
        set({
          items: get().items.map((i) =>
            i.product.id === productId ? { ...i, quantity } : i,
          ),
        });
      },

      updateItemPrice: (productId, newPrice) =>
        set({
          items: get().items.map((i) =>
            i.product.id === productId
              ? { ...i, product: { ...i.product, current_price: newPrice } }
              : i,
          ),
        }),

      clearCart: () => set({ items: [], tableId: null, tableName: '', restaurantId: null, existingOrderId: null, orderType: 'dine-in', deliveryAddress: '', deliveryPhone: '', deliveryLat: null, deliveryLng: null }),

      getSubtotal: () =>
        get().items.reduce((sum, i) => sum + parseFloat(i.product.current_price || 0) * i.quantity, 0),

      getItemCount: () =>
        get().items.reduce((sum, i) => sum + i.quantity, 0),
    }),
    {
      name: 'easy-fix-cart',
      storage: createJSONStorage(() => AsyncStorage),
      // v1: the cart's restaurantId is always set. Older carts are emptied (see migrateCart).
      version: 1,
      migrate: (persisted, version) => migrateCart(persisted, version),
      // Only persist data fields; computed functions are recreated automatically
      partialize: (state) => ({
        items:           state.items,
        tableId:         state.tableId,
        tableName:       state.tableName,
        restaurantId:    state.restaurantId,
        existingOrderId: state.existingOrderId,
        orderType:       state.orderType,
        deliveryAddress: state.deliveryAddress,
        deliveryPhone:   state.deliveryPhone,
        deliveryLat:     state.deliveryLat,
        deliveryLng:     state.deliveryLng,
        lastOrderMode:   state.lastOrderMode,
      }),
    }
  )
);
