// ── Polyfills — must run before any other import ──────────────────────────
if (typeof global.DOMException === 'undefined') {
  global.DOMException = class DOMException extends Error {
    constructor(message, name) {
      super(message);
      this.name = name || 'DOMException';
    }
  };
}

if (typeof global.TextEncoder === 'undefined') {
  const { TextEncoder, TextDecoder } = require('text-encoding');
  global.TextEncoder = TextEncoder;
  global.TextDecoder = TextDecoder;
}
// ──────────────────────────────────────────────────────────────────────────

import { registerRootComponent } from 'expo';
import App from './App';

registerRootComponent(App);
