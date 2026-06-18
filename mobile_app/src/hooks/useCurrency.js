import { useAuthStore } from '../store/useAuthStore';

// Mirrors accounts/models.py CURRENCY_SYMBOLS
const CURRENCY_SYMBOLS = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  KES: 'KSh',
  TZS: 'TSh',
  UGX: 'USh',
  RWF: 'RF',
  ZAR: 'R',
  NGN: '₦',
  GHS: 'GH₵',
  INR: '₹',
  AED: 'AED',
  SAR: 'SAR',
  CNY: '¥',
  JPY: '¥',
};

// Currencies that show no decimal places
const NO_DECIMAL = ['KES', 'TZS', 'UGX', 'RWF', 'JPY'];

/**
 * Returns { symbol, format(amount) }
 * format(12.5) → "KSh 12" or "$12.50" depending on the restaurant's currency.
 */
export function useCurrency() {
  const user = useAuthStore((s) => s.user);

  // Prefer symbol sent directly from server; fall back to client-side map
  const code   = user?.currency_code   || 'USD';
  const symbol = user?.currency_symbol || CURRENCY_SYMBOLS[code] || code;

  const decimals = NO_DECIMAL.includes(code) ? 0 : 2;

  const format = (amount) => {
    const n = Number(amount);
    if (isNaN(n)) return `${symbol}0`;
    return `${symbol}${n.toFixed(decimals)}`;
  };

  return { symbol, code, format };
}
