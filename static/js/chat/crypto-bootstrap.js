/**
 * crypto-bootstrap.js — Hub-level lazy crypto bootstrap.
 *
 * Runs once per browser on hub page load. Generates an Olm identity + SPK +
 * initial OTPK pool and publishes them to the server via HTTP, so peers can
 * establish sessions with this user before they ever open /pm/chat/.
 *
 * Idempotent via IndexedDB flag (PM_KEYSTORE.getBootstrapFlag /
 * setBootstrapFlag, added in keystore.js v5).
 *
 * CSP-safe: no inline code, no innerHTML. Reads URL + CSRF + self user id
 * from json_script data islands added to hub.html.
 *
 * Failure modes: if Olm / libsodium fail to load, or the HTTP POST fails,
 * the bootstrap logs a warning and returns silently. Hub must remain usable.
 *
 * Load order: this file is deferred, so it runs after DOMContentLoaded and
 * after all other deferred scripts (vendor + private_chat modules) have
 * executed and registered their globals.
 */

'use strict';

(function () {
  /**
   * Parse a json_script data island by element id. Returns null on any
   * failure rather than throwing — bootstrap must never crash the page.
   */
  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  // Module-scope in-flight promise: prevents concurrent duplicate runs when
  // runIfNeeded() is called from multiple call sites before bootstrap completes.
  var _inFlight = null;

  async function runBootstrap() {
    var registerUrl = readJson('hub-ctx-register-identity-url');
    var csrf        = readJson('hub-ctx-csrf');
    var selfUid     = readJson('hub-ctx-self-uid');

    if (!registerUrl || !csrf || selfUid === null || selfUid === undefined) {
      console.warn('[PM_BOOTSTRAP] missing context islands — skipping bootstrap');
      return;
    }

    // PM_CRYPTO_READY is set by crypto_init.js (also deferred). Because all
    // deferred scripts run in document order, crypto_init.js precedes us, so
    // the promise is guaranteed to be defined here. Guard defensively anyway.
    if (!window.PM_CRYPTO_READY) {
      console.warn('[PM_BOOTSTRAP] PM_CRYPTO_READY not defined — skipping');
      return;
    }
    try {
      await window.PM_CRYPTO_READY;
    } catch (e) {
      console.warn('[PM_BOOTSTRAP] crypto init failed — skipping', e);
      return;
    }

    // Initialise keystore — generates or loads the master key, derives
    // pickle_key, opens IndexedDB. Safe to call even if already init'd
    // (init() re-uses the existing _db if the same userId).
    try {
      await window.PM_KEYSTORE.init(selfUid);
    } catch (e) {
      console.warn('[PM_BOOTSTRAP] keystore init failed — skipping', e);
      return;
    }

    // Check the idempotency flag. On any read error we fail-open: the server
    // endpoint is idempotent so a redundant POST is always safe.
    var alreadyBootstrapped = false;
    try {
      alreadyBootstrapped = await window.PM_KEYSTORE.getBootstrapFlag();
    } catch (e) {
      console.warn('[PM_BOOTSTRAP] could not read bootstrap flag — proceeding anyway', e);
    }
    if (alreadyBootstrapped) {
      return;
    }

    // Load or create the Olm account from IndexedDB.
    var accountResult;
    try {
      accountResult = await window.PM_OLM_SESSION.loadOrCreateAccount();
    } catch (e) {
      console.warn('[PM_BOOTSTRAP] Olm account load/create failed — skipping', e);
      return;
    }

    // POST identity + SPK + OTPK pool to the server.
    try {
      await window.PM_OLM_SESSION.publishInitialKeysHttp(
        registerUrl, csrf, accountResult.account
      );
    } catch (e) {
      // Do NOT set the flag — next hub visit will retry.
      console.warn('[PM_BOOTSTRAP] publish failed — will retry on next hub visit', e);
      try { accountResult.account.free(); } catch (_) {}
      return;
    }

    // Persist completion flag so subsequent hub loads are instant no-ops.
    try {
      await window.PM_KEYSTORE.setBootstrapFlag();
    } catch (e) {
      // Flag write failure is non-fatal: next visit will POST again, which
      // the server handles silently as a duplicate.
      console.warn('[PM_BOOTSTRAP] could not persist bootstrap flag', e);
    }

    // Release C++ Olm memory before leaving scope.
    try { accountResult.account.free(); } catch (_) {}

    console.info('[PM_BOOTSTRAP] keys published successfully');
  }

  /**
   * runIfNeeded — idempotent, concurrency-safe entry point.
   *
   * If bootstrap has already completed (IndexedDB flag set) this is a
   * synchronous no-op via the flag check inside runBootstrap.
   * If a run is already in flight, the same promise is returned so
   * multiple concurrent callers all wait on the single execution.
   * Resets _inFlight after completion so a future genuine retry can re-run.
   */
  function runIfNeeded() {
    if (_inFlight) return _inFlight;
    _inFlight = runBootstrap().finally(function () { _inFlight = null; });
    return _inFlight;
  }

  // Expose so hub-dashboard.js (and any future call site) can retrigger.
  window.PM_CRYPTO_BOOTSTRAP = { runIfNeeded: runIfNeeded };

  /**
   * Schedule runBootstrap to run after the hub's own JS has had a chance to
   * render the page. requestIdleCallback ensures we don't contend with the
   * dashboard paint; the 3000ms timeout is a hard backstop so we still run
   * even in busy tabs. Falls back to setTimeout(500) in browsers without rIC
   * (Safari < 16.4, some older Chromiums).
   */
  function schedule() {
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(runIfNeeded, { timeout: 3000 });
    } else {
      setTimeout(runIfNeeded, 500);
    }
  }

  // DOMContentLoaded fires before deferred scripts execute in practice, but
  // the spec only guarantees deferred scripts run before DOMContentLoaded
  // completes. By the time this IIFE runs (deferred, bottom-of-list), the
  // document is already interactive — check readyState defensively.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedule);
  } else {
    schedule();
  }
})();
