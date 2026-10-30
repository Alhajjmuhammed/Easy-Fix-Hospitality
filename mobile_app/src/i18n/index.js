/**
 * Translations. The English text is the key: t('My Orders') → 'Oda Zangu' in Kiswahili.
 * A text without a translation simply shows in English, so a missing entry never breaks a screen.
 * Placeholders: t('Order #{number}', { number: 12 }).
 *
 * Swahili texts live in ./sw/*.js (one file per area) so they are easy to review.
 */
import { useCallback } from 'react';
import { useLanguageStore } from '../store/useLanguageStore';
import common from './sw/common';
import customerOrdering from './sw/customer_ordering';
import customerAccount from './sw/customer_account';
import customerShared from './sw/customer_shared';
import staff from './sw/staff';

const SW = { ...common, ...customerShared, ...customerOrdering, ...customerAccount, ...staff };

function fill(text, params) {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (m, k) => (params[k] !== undefined && params[k] !== null ? String(params[k]) : m));
}

export function translate(language, text, params) {
  if (language === 'sw' && typeof text === 'string' && SW[text]) return fill(SW[text], params);
  return fill(text, params);
}

/** In components: const t = useT(); … t('My Orders') */
export function useT() {
  const language = useLanguageStore((s) => s.language);
  return useCallback((text, params) => translate(language, text, params), [language]);
}

/** Outside components (e.g. notification handlers). */
export function t(text, params) {
  return translate(useLanguageStore.getState().language, text, params);
}
