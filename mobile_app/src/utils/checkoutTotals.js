/**
 * Checkout totals — must match the server (Restaurant.delivery_fee_for + Order.compute_total):
 *   fee   = delivery fee, or 0 when food subtotal reaches the free-delivery minimum
 *   tax   = (food + fee if the restaurant taxes the fee) × tax rate
 *   total = food + fee + tax
 * `profile` is the logged-in user's profile (tax/delivery settings of the selected restaurant).
 */
export function checkoutTotals(foodSubtotal, profile, orderType) {
  const food = Number(foodSubtotal) || 0;
  const rate = Math.min(1, Math.max(0, parseFloat(profile?.tax_rate) || 0));
  let fee = 0;
  if (orderType === 'delivery') {
    fee = Math.max(0, parseFloat(profile?.delivery_fee) || 0);
    const freeMin = profile?.free_delivery_minimum;
    if (freeMin !== null && freeMin !== undefined && food >= Number(freeMin)) fee = 0;
  }
  const taxable = food + (profile?.delivery_fee_taxable && fee > 0 ? fee : 0);
  const tax = taxable * rate;
  return { food, fee, tax, total: food + fee + tax, rate, isDelivery: orderType === 'delivery' };
}
