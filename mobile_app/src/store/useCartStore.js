import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';

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

      setTable: (tableId, tableName, restaurantId) =>
        set({ tableId, tableName, restaurantId, existingOrderId: null, orderType: 'dine-in', deliveryAddress: '', deliveryPhone: '' }),

      setRemoteOrder: (restaurantId, orderType, deliveryAddress = '', deliveryPhone = '') =>
        set({ restaurantId, tableId: null, tableName: '', existingOrderId: null, orderType, deliveryAddress, deliveryPhone }),

      setExistingOrder: (orderId) =>
        set({ existingOrderId: orderId }),

      addItem: (product, quantity = 1) => {
        const items = get().items;
        const existing = items.find((i) => i.product.id === product.id);
        if (existing) {
          set({
            items: items.map((i) =>
              i.product.id === product.id
                ? { ...i, quantity: i.quantity + quantity }
                : i,
            ),
          });
        } else {
          set({ items: [...items, { product, quantity }] });
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

      clearCart: () => set({ items: [], tableId: null, tableName: '', restaurantId: null, existingOrderId: null, orderType: 'dine-in', deliveryAddress: '', deliveryPhone: '' }),

      getSubtotal: () =>
        get().items.reduce((sum, i) => sum + i.product.current_price * i.quantity, 0),

      getItemCount: () =>
        get().items.reduce((sum, i) => sum + i.quantity, 0),
    }),
    {
      name: 'easy-fix-cart',
      storage: createJSONStorage(() => AsyncStorage),
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
      }),
    }
  )
);
