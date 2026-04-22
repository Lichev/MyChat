/**
 * crypto_init.js — Serial initialisation of libsodium then Olm.
 *
 * Order matters: libsodium must be fully ready before Olm because the
 * keystore (which Olm uses immediately after account creation) needs
 * libsodium's HKDF (pickle-key derivation).
 *
 * Exposes one global Promise: window.PM_CRYPTO_READY
 * Idempotent: safe to import/load multiple times.
 *
 * CSP: no inline JS. This file is a static asset loaded by <script src>.
 * The 'wasm-unsafe-eval' CSP directive is required for both runtimes.
 */

'use strict';

(function () {
  // Already initialised — expose the same promise.
  if (window.PM_CRYPTO_READY) return;

  window.PM_CRYPTO_READY = (async function initCrypto() {
    // ── 1. libsodium ──────────────────────────────────────────────────
    // sodium.js ships as a UMD bundle that attaches `sodium` to window
    // after its WASM is ready. We wait for the `onload` promise it exposes.
    if (!window.sodium) {
      throw new Error('PM: libsodium not loaded. Ensure sodium.js <script> precedes crypto_init.js.');
    }
    await window.sodium.ready;

    // ── 2. Olm ────────────────────────────────────────────────────────
    // Olm.js attaches `Olm` to window. We call Olm.init() with a
    // locateFile callback so it finds the WASM blob in the vendor path.
    if (!window.Olm) {
      throw new Error('PM: Olm not loaded. Ensure olm.js <script> precedes crypto_init.js.');
    }
    await window.Olm.init({
      locateFile: function (filename) {
        // Stable vendored path — must match the template <script src>.
        return '/static/vendor/olm/3.2.15/' + filename;
      },
    });

    return { sodium: window.sodium, Olm: window.Olm };
  })();
})();
