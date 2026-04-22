/**
 * ui.js — DOM bootstrapper for the private-chat conversation view.
 *
 * Boot sequence (Blueprint v2.1 — auto-key, no password prompt):
 * 1. Wait for DOMContentLoaded.
 * 2. Await PM_CRYPTO_READY (libsodium + Olm).
 * 3. Check IndexedDB for existing account — if absent, show first-device warning.
 * 4. Await PM_KEYSTORE.init() — generates or loads master key, derives pickle_key.
 *    No user interaction required.
 * 5. Await PM_OLM_SESSION.loadOrCreateAccount() — load or create Olm account.
 * 6. If new account: publish identity to server via session.init + key.rotate + prekey.publish.
 * 7. Open WebSocket (PM_SOCKET.init).
 * 8. Wire socket event handlers (envelope.deliver, acks, wipe, key_rotate_alarm).
 * 9. Wire key_change_banner and fingerprint_modal.
 * 10. Wire send form.
 *
 * Security: textContent only. No innerHTML for user-provided data.
 * Mirrors chat-script.js pattern exactly.
 */

'use strict';

(function () {

  // ── Bootstrap data (from json_script elements in template) ────────────
  function _getData(id) {
    const el = document.getElementById(id);
    if (!el) throw new Error('Missing data element #' + id);
    return JSON.parse(el.textContent);
  }

  // ── Message list (in-memory — never persisted) ─────────────────────
  const _messages = [];

  // ── Module state ───────────────────────────────────────────────────
  let _account  = null;  // Olm.Account
  let _selfUid  = null;
  let _peerUid  = null;
  let _convId   = null;
  let _selfIkEd = null;  // Ed25519 identity key (base64)
  let _sendLocked = true; // locked until key-change banner dismissed

  // ── DOM helpers ────────────────────────────────────────────────────

  function _getEl(id) { return document.getElementById(id); }

  function _buildMessageRow(plaintext, senderUsername, isOwn, avatarUrl) {
    const ts  = new Date().toLocaleString('en-US', {
      hour: 'numeric', minute: '2-digit', hour12: true,
    });

    const row = document.createElement('div');
    row.className = 'msg-row ' + (isOwn ? 'msg-row--outgoing' : 'msg-row--incoming');

    const content = document.createElement('div');
    content.className = 'msg-content';

    const meta = document.createElement('div');
    meta.className = 'msg-meta';

    const nameSpan = document.createElement('span');
    nameSpan.className   = 'msg-name';
    nameSpan.textContent = isOwn ? 'You' : senderUsername;

    const timeSpan = document.createElement('span');
    timeSpan.textContent = ts;

    meta.appendChild(nameSpan);
    meta.appendChild(timeSpan);

    const bubble = document.createElement('div');
    bubble.className  = 'msg-bubble msg-bubble--encrypted ' +
                        (isOwn ? 'msg-bubble--outgoing' : 'msg-bubble--incoming');
    bubble.textContent = plaintext; // textContent — never innerHTML

    content.appendChild(meta);
    content.appendChild(bubble);

    let avatarEl;
    if (avatarUrl) {
      avatarEl     = document.createElement('img');
      avatarEl.src = avatarUrl;
      avatarEl.alt = isOwn ? 'Your avatar' : senderUsername;
      avatarEl.className = 'msg-avatar';
      avatarEl.width  = 32;
      avatarEl.height = 32;
    } else {
      avatarEl = document.createElement('span');
      avatarEl.className = 'msg-avatar--placeholder';
      avatarEl.setAttribute('aria-hidden', 'true');
    }

    if (isOwn) {
      row.appendChild(content);
      row.appendChild(avatarEl);
    } else {
      row.appendChild(avatarEl);
      row.appendChild(content);
    }

    return row;
  }

  function _appendMessage(plaintext, senderUsername, isOwn, avatarUrl, persist = true) {
    const msgList = _getEl('pm-message-list');
    if (!msgList) return;
    const row = _buildMessageRow(plaintext, senderUsername, isOwn, avatarUrl);
    msgList.appendChild(row);
    // Auto-scroll to bottom.
    msgList.scrollTop = msgList.scrollHeight;
    // Store in memory.
    const msgObj = { text: plaintext, senderUsername, isOwn, avatarUrl, ts: Date.now() };
    _messages.push(msgObj);

    // Persist to encrypted IndexedDB.
    if (persist) {
      window.PM_KEYSTORE.putMessage(_convId, msgObj).catch(function (e) {
        console.error('[PM_UI] failed to persist message', e);
      });
    }
  }

  /** Load and decrypt chat history from IndexedDB. */
  async function _loadHistory() {
    const history = await window.PM_KEYSTORE.getMessages(_convId);
    // history is already chronologically sorted by the IDB cursor.
    for (const msg of history) {
      // Append without re-persisting (persist=false).
      _appendMessage(msg.text, msg.senderUsername, msg.isOwn, msg.avatarUrl, false);
    }
    console.info('[PM_UI] hydrated history:', history.length, 'messages');
  }

  // ── First-device warning ───────────────────────────────────────────

  function _showFirstDeviceWarning() {
    const card = _getEl('pm-first-device-warning');
    if (card) card.hidden = false;
  }

  function _hideFirstDeviceWarning() {
    const card = _getEl('pm-first-device-warning');
    if (card) card.hidden = true;
  }

  // ── Outbound flow ──────────────────────────────────────────────────

  async function _sendMessage(plaintext) {
    if (_sendLocked) {
      console.warn('[PM_UI] send locked — key change banner not acknowledged');
      return;
    }

    const selfCtx = _getData('pm-ctx-self');
    const peerCtx = _getData('pm-ctx-peer');

    // Check for existing session. If absent, queue and trigger X3DH.
    const sessionPickle = await window.PM_KEYSTORE.getSessionPickle(_convId);
    let otpkIdUsed = null;

    if (!sessionPickle) {
      _pendingQueue.push(plaintext);
      _appendMessage(plaintext, selfCtx.username, true, selfCtx.avatar_url);
      await _initiateOutboundSession();
      return; // _onPrekeyBundle drains _pendingQueue after session is ready
    }

    try {
      const { ciphertext_b64, message_type } = await window.PM_OLM_SESSION.encrypt(
        _selfUid, _peerUid, plaintext, _account
      );
      window.PM_SOCKET.sendEnvelope(ciphertext_b64, message_type, otpkIdUsed);
    } catch (e) {
      console.error('[PM_UI] encrypt error', e);
      _showSendError('Encryption failed: ' + e.message);
      return;
    }

    // Optimistically render (will be confirmed by send.ack).
    _appendMessage(plaintext, selfCtx.username, true, selfCtx.avatar_url);
  }

  // Queue for messages buffered while X3DH is in flight.
  // Array (not a single variable) so rapid sends before session ready are all preserved.
  let _pendingQueue = [];
  let _x3dhInFlight = false; // guard against duplicate prekey.request triggers
  let _pendingOnBundle = null; // module-scope ref so it can be off()'d from outside the closure

  // ── Retry-with-backoff state ───────────────────────────────────────
  let _retryTimer = null;
  let _retryDelay = 10_000;
  const _RETRY_MAX = 60_000;

  async function _initiateOutboundSession() {
    if (_x3dhInFlight) return; // already waiting for a bundle
    _x3dhInFlight = true;
    _pendingOnBundle = function onBundle(data) {
      if (_pendingOnBundle) {
        window.PM_SOCKET.off('prekey.bundle', _pendingOnBundle);
      }
      _pendingOnBundle = null;
      _x3dhInFlight = false;
      _onPrekeyBundle(data.bundle);
    };
    window.PM_SOCKET.on('prekey.bundle', _pendingOnBundle);
    window.PM_SOCKET.requestPrekey();
  }

  function _unwindPendingBundleWait() {
    if (_pendingOnBundle) {
      window.PM_SOCKET.off('prekey.bundle', _pendingOnBundle);
      _pendingOnBundle = null;
    }
    _x3dhInFlight = false;
  }

  function _scheduleRetry() {
    if (_retryTimer) return;
    if (_pendingQueue.length === 0) return;
    _retryTimer = setTimeout(async function () {
      _retryTimer = null;
      _retryDelay = Math.min(_retryDelay * 2, _RETRY_MAX);
      if (_pendingQueue.length === 0) return;
      await _initiateOutboundSession();
    }, _retryDelay);
  }

  function _cancelRetry() {
    if (_retryTimer) { clearTimeout(_retryTimer); _retryTimer = null; }
    _retryDelay = 10_000;
  }

  function _showWaitingForPeer() {
    const el = _getEl('pm-send-waiting');
    if (el) el.hidden = false;
  }

  function _hideWaitingForPeer() {
    const el = _getEl('pm-send-waiting');
    if (el) el.hidden = true;
  }

  async function _onPrekeyBundle(bundle) {
    const selfCtx = _getData('pm-ctx-self');

    let convId;
    try {
      // outboundSession now returns only { convId } — session is freed internally.
      ({ convId } = await window.PM_OLM_SESSION.outboundSession(
        _selfUid, _peerUid, bundle, _account
      ));
      _convId = convId;
    } catch (e) {
      console.error('[PM_UI] outbound session setup failed', e);
      _showSendError('Session setup failed: ' + e.message);
      _pendingQueue = []; // drop queued messages — session could not be established
      return;
    }

    // Session established — hide waiting indicator and cancel any pending retry timer.
    _hideWaitingForPeer();
    _cancelRetry();

    // Drain the pending queue in order.
    const queued = _pendingQueue.slice();
    _pendingQueue = [];
    for (const text of queued) {
      try {
        const { ciphertext_b64, message_type } = await window.PM_OLM_SESSION.encrypt(
          _selfUid, _peerUid, text, _account
        );
        // Message was already rendered optimistically in _sendMessage's queue-path.
        // Only ship the ciphertext — do NOT call _appendMessage again here.
        window.PM_SOCKET.sendEnvelope(ciphertext_b64, message_type, bundle.otpk_id || null);
      } catch (e) {
        console.error('[PM_UI] encrypt error during queue drain', e);
        _showSendError('Encryption failed: ' + e.message);
        break; // stop draining on first failure — ratchet state may be inconsistent
      }
    }
  }

  // ── Inbound flow ───────────────────────────────────────────────────

  async function _onEnvelopeDeliver(data) {
    const peerCtx  = _getData('pm-ctx-peer');
    const selfCtx  = _getData('pm-ctx-self');
    let plaintext;

    try {
      plaintext = await window.PM_OLM_SESSION.decrypt(
        _selfUid, data.sender_id, data.message_type, data.ciphertext_b64, _account
      );
    } catch (e) {
      console.error('[PM_UI] decrypt error', e);
      // ACK with decrypt_error=true so server cleans up.
      window.PM_SOCKET.sendAck(data.envelope_id, true);
      return;
    }

    // Plaintext lives in memory only — render immediately.
    const isOwn = (String(data.sender_id) === String(_selfUid));
    _appendMessage(
      plaintext,
      isOwn ? selfCtx.username : peerCtx.username,
      isOwn,
      isOwn ? selfCtx.avatar_url : peerCtx.avatar_url
    );

    // ACK successful decryption — server deletes the envelope.
    window.PM_SOCKET.sendAck(data.envelope_id, false);
  }

  // ── Error display ──────────────────────────────────────────────────

  function _showSendError(msg) {
    const el = _getEl('pm-send-error');
    if (!el) return;
    el.textContent = msg; // textContent — safe
    el.hidden = false;
    setTimeout(function () { el.hidden = true; }, 5000);
  }

  // ── Main boot ─────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', async function () {
    // Load context from json_script data blocks.
    let selfCtx, peerCtx;
    try {
      selfCtx = _getData('pm-ctx-self');
      peerCtx = _getData('pm-ctx-peer');
    } catch (e) {
      console.error('[PM_UI] missing context data', e);
      return;
    }

    _selfUid = selfCtx.user_id;
    _peerUid = peerCtx.user_id;
    _convId  = window.PM_OLM_SESSION
      ? window.PM_OLM_SESSION.getConvId(_selfUid, _peerUid)
      : String(Math.min(_selfUid, _peerUid)) + '_' + String(Math.max(_selfUid, _peerUid));

    // 1. Await crypto ready.
    try {
      await window.PM_CRYPTO_READY;
    } catch (e) {
      console.error('[PM_UI] crypto init failed', e);
      return;
    }

    // 2. Check if an account already exists in IndexedDB (before keystore init).
    let hasExistingAccount = false;
    try {
      await new Promise(function (resolve, reject) {
        const req = indexedDB.open('private_chat', DB_VERSION_PROBE);
        req.onsuccess = function (e) {
          const db = e.target.result;
          if (!db.objectStoreNames.contains('olm_accounts')) {
            db.close();
            resolve();
            return;
          }
          const tx = db.transaction('olm_accounts', 'readonly');
          const store = tx.objectStore('olm_accounts');
          // Keyed by _selfUid for isolation.
          const get = store.get(String(_selfUid));
          get.onsuccess = function (ev) {
            hasExistingAccount = !!ev.target.result;
            db.close();
            resolve();
          };
          get.onerror = function () { db.close(); resolve(); };
        };
        req.onerror = function () { resolve(); };
        req.onupgradeneeded = function (e) {
          const db = e.target.result;
          if (!db.objectStoreNames.contains('olm_accounts')) {
            db.createObjectStore('olm_accounts');
          }
          if (!db.objectStoreNames.contains('olm_sessions')) {
            db.createObjectStore('olm_sessions');
          }
          if (!db.objectStoreNames.contains('pm_master_key')) {
            db.createObjectStore('pm_master_key');
          }
          if (!db.objectStoreNames.contains('pm_messages')) {
            db.createObjectStore('pm_messages');
          }
        };
      });
    } catch (_) {}

    // 3. Show first-device warning if no account exists yet.
    if (!hasExistingAccount) {
      _showFirstDeviceWarning();
    }

    // 4. Init keystore — auto-generates or loads master key, derives pickle_key.
    //    No password prompt. No user interaction.
    try {
      await window.PM_KEYSTORE.init(_selfUid);
    } catch (e) {
      console.error('[PM_UI] keystore init failed', e);
      return;
    }

    // Hide first-device warning after successful keystore init.
    _hideFirstDeviceWarning();

    // 5. Load or create the Olm account.
    let isNew;
    try {
      const result = await window.PM_OLM_SESSION.loadOrCreateAccount();
      _account = result.account;
      isNew    = result.isNew;
    } catch (e) {
      console.error('[PM_UI] account load failed', e);
      // ── Recovery: decryption error ────────────────────────────────────
      // If we see "wrong secret key" or AEAD failure, our master key is
      // out of sync with the stored ciphertexts.
      const errMsg = String(e.message || '');
      if (errMsg.includes('wrong secret key') || errMsg.includes('AEAD decryption failed')) {
        console.error('[PM_UI] Decryption mismatch detected — manual wipe may be required');
      }
      return;
    }

    // Load history from encrypted local storage.
    try {
      await _loadHistory();
    } catch (e) {
      console.warn('[PM_UI] failed to load history', e);
    }

    // Extract self identity key.
    const ikPair = window.PM_OLM_SESSION.getIdentityKeys(_account);
    _selfIkEd = ikPair.ed25519;

    // 7. Wire inbound handlers BEFORE init so we don't drop pending envelopes.
    window.PM_SOCKET.on('envelope.deliver', _onEnvelopeDeliver);

    window.PM_SOCKET.on('pm.wipe', async function (data) {
      // Peer wiped — wipe our own IndexedDB too.
      await window.PM_KEYSTORE.wipeAll();
    });

    window.PM_SOCKET.on('pm.key_rotate_alarm', async function (data) {
      if (data.payload && data.payload.remaining_otpks !== undefined) {
        // Our OTPK pool is low — replenish silently.
        console.info('[PM_UI] OTPK pool low — replenishing...');
        await window.PM_OLM_SESSION.publishInitialKeys(window.PM_SOCKET, _account);
      }
    });

    window.PM_SOCKET.on('error', function (data) {
      console.error('[PM_SOCKET] server error:', data.code, data.detail);
      if (data && data.code === 'prekey_not_found') {
        _unwindPendingBundleWait();
        _showWaitingForPeer();
        _scheduleRetry();
      }
    });

    // 8. If new account: register identity keys + OTPKs with server on first connect.
    if (isNew) {
      window.PM_SOCKET.on('_connected', async function onFirstConnect() {
        window.PM_SOCKET.off('_connected', onFirstConnect);

        // 1. session.init — creates pm_privatesession server-side.
        window.PM_SOCKET.sendJson({ type: 'session.init' });

        // 2. key.rotate — registers IK + SPK (this is also the first-registration path).
        //    Olm's SPK in this implementation = Curve25519 IK (blueprint § "SPK").
        //    The SPK sig = Ed25519 signature over spk_pub (ik_curve).
        //    We compute the signature using the Olm account.
        const idKeys = JSON.parse(_account.identity_keys());
        // Olm's sign() method signs arbitrary data with the account's Ed25519 key.
        const spkSig = _account.sign(idKeys.curve25519);
        window.PM_SOCKET.rotateKey(
          idKeys.curve25519,  // ik_pub_curve25519
          idKeys.ed25519,     // ik_pub_ed25519
          idKeys.curve25519,  // spk_pub = ik_curve (per blueprint)
          spkSig              // Ed25519 sig over spk_pub
        );

        // 3. prekey.publish — registers 100 OTPKs.
        await window.PM_OLM_SESSION.publishInitialKeys(window.PM_SOCKET, _account);
      });
    }

    // 9. Initialise WebSocket.
    window.PM_SOCKET.init(_peerUid);
    _sendLocked = false;

    // 10. Key-change banner.
    window.PM_KEY_CHANGE_BANNER.init(_convId, _peerUid, function () {
      _sendLocked = false;
    });
    _sendLocked = false; // explicitly unlock after init (banner only locks on alarm)

    // Fingerprint modal — wires #pm-safety-pill (topbar).
    window.PM_FINGERPRINT_MODAL.init(_selfIkEd, _selfUid, _peerUid);
    // Also wire the strip pill to delegate to the topbar pill (no inline onclick).
    const stripPill = _getEl('pm-safety-pill-strip');
    const topbarPill = _getEl('pm-safety-pill');
    if (stripPill && topbarPill) {
      stripPill.addEventListener('click', function () { topbarPill.click(); });
    }

    // 10. Wire send form.
    const form  = _getEl('pm-send-form');
    const input = _getEl('pm-send-input');
    if (form && input) {
      form.addEventListener('submit', async function (e) {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        await _sendMessage(text);
      });
    }

    // Panic-wipe button.
    // Order per blueprint: POST server wipe first (notifies peers), then wipeAll
    // (deletes local IndexedDB + redirects). If POST fails or times out, still
    // wipe locally — the client must not retain key material even if server is
    // unreachable.
    const wipeBtn = _getEl('pm-panic-wipe-btn');
    if (wipeBtn) {
      wipeBtn.addEventListener('click', async function () {
        const confirmed = window.confirm(
          'Panic wipe: this will permanently delete all your encrypted messages and identity keys on this device and notify all peers. Continue?'
        );
        if (!confirmed) return;

        const csrfToken = (() => {
          const el = document.getElementById('pm-ctx-csrf');
          return el ? JSON.parse(el.textContent) : '';
        })();

        // POST server wipe first (3-second timeout).
        const controller = new AbortController();
        const timeoutId  = setTimeout(function () { controller.abort(); }, 3000);
        try {
          await fetch('/pm/panic-wipe/', {
            method:      'POST',
            headers:     { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            signal:      controller.signal,
          });
        } catch (_) {
          // Server unreachable or timed out — still wipe locally.
        } finally {
          clearTimeout(timeoutId);
        }

        // Wipe local IndexedDB and redirect regardless of server outcome.
        await window.PM_KEYSTORE.wipeAll();
      });
    }

    // Free the long-lived Olm.Account on page unload to release WASM memory.
    window.addEventListener('beforeunload', function () {
      if (_account) {
        try { _account.free(); } catch (_) {}
        _account = null;
      }
    });
  });

  // DB version constant used for the existence probe above.
  // Must match DB_VERSION in keystore.js (both version 4).
  const DB_VERSION_PROBE = 4;

})();
