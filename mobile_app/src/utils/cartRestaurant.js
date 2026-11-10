// Which restaurant a cart belongs to. Kept free of React Native imports so the rule
// can be tested in plain Node.

/** Same restaurant id? Ids may arrive as numbers or strings; null only matches null. */
export function sameRestaurant(a, b) {
  const x = a === undefined || a === '' ? null : a;
  const y = b === undefined || b === '' ? null : b;
  if (x === null || y === null) return x === null && y === null;
  return String(x) === String(y);
}

/**
 * State changes needed before the cart is used for restaurant `restaurantId`.
 * Products (and an "add to existing order" target) belong to one restaurant: when the
 * restaurant changes they are dropped, otherwise they would be sent to the wrong
 * restaurant and fail with "Product not found". A cart whose restaurant is unknown
 * (null, e.g. saved by an older app version) is treated as a different restaurant.
 * Returns null when nothing has to change.
 */
export function restaurantSwitchPatch(cart, restaurantId) {
  const target = restaurantId === undefined || restaurantId === '' ? null : restaurantId;
  const current = cart?.restaurantId ?? null;
  const hasContent = !!(cart?.items?.length || cart?.existingOrderId);
  if (sameRestaurant(current, target)) return null;
  if (!hasContent) return { restaurantId: target };
  return { restaurantId: target, items: [], existingOrderId: null, tableId: null, tableName: '' };
}

/**
 * Persisted carts from app versions before 1.2.0 (persist version 0) have no reliable
 * restaurant id (dine-in carts always stored null): drop their items.
 */
export function migrateCart(persisted, version) {
  if (!persisted || typeof persisted !== 'object') return persisted;
  if (version < 1 && persisted.restaurantId == null
      && (persisted.items?.length || persisted.existingOrderId)) {
    return { ...persisted, items: [], existingOrderId: null, tableId: null, tableName: '' };
  }
  return persisted;
}
