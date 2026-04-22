/**
 * keystore.js — IndexedDB wrapper for Olm account and session pickles.
 *
 * Security model (Blueprint v2.1):
 * - Master key: 32 random bytes from sodium.randombytes_buf(32), stored in
 *   IndexedDB pm_master_key store as base64url-no-padding. Auto-generated on
 *   first visit; loaded directly on subsequent visits. No password. No KDF at
 *   this layer.
 * - Pickle key derived via HKDF-SHA256(master_key, salt=0x00*32,
 *   info="MYCHAT_OLM_PICKLE_v1", len=32). Module-local only.
 * - Each pickle is AEAD-encrypted with the pickle key (libsodium secretbox).
 *   AAD distinguishes accounts from sessions to prevent cross-swap attacks.
 * - master_key Uint8Array is zeroed immediately after HKDF derivation.
 * - master_key is never assigned to any global, never returned, never passed
 *   to any function outside this module except as the IKM argument to HKDF.
 * - On any AEAD failure: throw — never silently return null.
 * - Plaintext pickles never touch IndexedDB, localStorage, or cookies.
 *
 * API (all async):
 *   init(userId)               — generates or loads master key, derives pickle_key, opens DB
 *   lock()                     — zeros pickle_key, closes DB
 *   getAccountPickle()         — returns decrypted account pickle bytes
 *   putAccountPickle(bytes)    — encrypts and stores account pickle
 *   getSessionPickle(convId)   — returns decrypted session pickle bytes
 *   putSessionPickle(convId, bytes) — encrypts and stores session pickle
 *   deleteSession(convId)      — removes session from DB
 *   wipeAll()                  — deleteDatabase + redirect
 *   _getPickleKeyForOlm()      — internal: base64 pickle key for Olm's own pickle()
 */

'use strict';

(function (global) {
  const DB_NAME         = 'private_chat';
  const DB_VERSION      = 4;           // bumped to v4 to add pm_messages store
  const STORE_ACCOUNTS  = 'olm_accounts';
  const STORE_SESSIONS  = 'olm_sessions';
  const STORE_MASTER    = 'pm_master_key';
  const STORE_MESSAGES  = 'pm_messages';
  const MASTER_KEY_KEY  = 'master_key'; // string literal key inside STORE_MASTER
  const ACCOUNT_KEY     = 'self';
  const PICKLE_INFO     = 'MYCHAT_OLM_PICKLE_v1';

  // Module-local state — never exposed to window.
  let _selfUid   = null;   // current authenticated user ID
  let _pickleKey = null;   // Uint8Array(32) | null
  let _db        = null;   // IDBDatabase | null

  // ── Helpers ──────────────────────────────────────────────────────────

  function _requireUnlocked() {
    if (!_selfUid || !_pickleKey || !_db) {
      throw new Error('Keystore is locked. Call init() first.');
    }
  }

  function _convIdStore(convId) {
    return 'olm_session_' + convId;
  }

  /**
   * Open (or upgrade) the IndexedDB database to version 4.
   * onupgradeneeded creates all four stores if missing.
   */
  function _openDb() {
    return new Promise(function (resolve, reject) {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        const db = e.target.result;
        if (!db.objectStoreNames.contains(STORE_ACCOUNTS)) {
          db.createObjectStore(STORE_ACCOUNTS);
        }
        if (!db.objectStoreNames.contains(STORE_SESSIONS)) {
          db.createObjectStore(STORE_SESSIONS);
        }
        if (!db.objectStoreNames.contains(STORE_MASTER)) {
          db.createObjectStore(STORE_MASTER);
        }
        if (!db.objectStoreNames.contains(STORE_MESSAGES)) {
          db.createObjectStore(STORE_MESSAGES);
        }
      };
      req.onsuccess = function (e) { resolve(e.target.result); };
      req.onerror   = function (e) { reject(e.target.error); };
    });
  }

  /**
   * Encrypt plaintext bytes with the pickle key.
   * Uses libsodium secretbox (XSalsa20-Poly1305).
   * AAD is included in nonce derivation by being embedded in the
   * output object — libsodium secretbox does not take explicit AAD,
   * so we prefix the AAD string as a length-prefixed header inside
   * the authenticated plaintext.
   *
   * Format stored: { ciphertext_b64, nonce_b64, version: 1 }
   */
  function _encrypt(plaintextBytes, aad) {
    const sodium = window.sodium;
    const aadBytes   = sodium.from_string(aad);
    // Prepend aad length (2 bytes big-endian) + aad bytes to plaintext.
    const lenBuf = new Uint8Array(2);
    lenBuf[0] = (aadBytes.length >> 8) & 0xff;
    lenBuf[1] =  aadBytes.length       & 0xff;
    const combined = new Uint8Array(2 + aadBytes.length + plaintextBytes.length);
    combined.set(lenBuf,         0);
    combined.set(aadBytes,       2);
    combined.set(plaintextBytes, 2 + aadBytes.length);

    const nonce = sodium.randombytes_buf(sodium.crypto_secretbox_NONCEBYTES);
    const ciphertext = sodium.crypto_secretbox_easy(combined, nonce, _pickleKey);
    return {
      ciphertext_b64: sodium.to_base64(ciphertext),
      nonce_b64:      sodium.to_base64(nonce),
      version:        1,
    };
  }

  /**
   * Decrypt stored entry. Throws on any authentication failure.
   * Never silently returns null.
   */
  function _decrypt(entry, aad) {
    if (!entry || entry.version !== 1) {
      throw new Error('Keystore: unknown entry format (version mismatch).');
    }
    const sodium     = window.sodium;
    const ciphertext = sodium.from_base64(entry.ciphertext_b64);
    const nonce      = sodium.from_base64(entry.nonce_b64);
    const combined   = sodium.crypto_secretbox_open_easy(ciphertext, nonce, _pickleKey);
    if (!combined) {
      throw new Error('Keystore: AEAD decryption failed (bad key or tampered data).');
    }
    // Verify AAD prefix.
    const aadBytes = sodium.from_string(aad);
    const storedLen = (combined[0] << 8) | combined[1];
    if (storedLen !== aadBytes.length) {
      throw new Error('Keystore: AAD length mismatch.');
    }
    for (let i = 0; i < aadBytes.length; i++) {
      if (combined[2 + i] !== aadBytes[i]) {
        throw new Error('Keystore: AAD content mismatch.');
      }
    }
    return combined.slice(2 + aadBytes.length);
  }

  /** Generic IDB get. */
  function _idbGet(storeName, key) {
    return new Promise(function (resolve, reject) {
      try {
        const tx = _db.transaction(storeName, 'readonly');
        const req = tx.objectStore(storeName).get(key);
        req.onsuccess = function (e) { resolve(e.target.result); };
        req.onerror   = function (e) { reject(e.target.error); };
      } catch (e) {
        // Store doesn't exist yet (e.g. version ghost or race).
        resolve(null);
      }
    });
  }

  /** Generic IDB put. */
  function _idbPut(storeName, key, value) {
    return new Promise(function (resolve, reject) {
      try {
        const tx = _db.transaction(storeName, 'readwrite');
        const req = tx.objectStore(storeName).put(value, key);
        req.onsuccess = function ()  { resolve(); };
        req.onerror   = function (e) { reject(e.target.error); };
      } catch (e) {
        reject(e);
      }
    });
  }

  /** Generic IDB delete. */
  function _idbDelete(storeName, key) {
    return new Promise(function (resolve, reject) {
      try {
        const tx = _db.transaction(storeName, 'readwrite');
        const req = tx.objectStore(storeName).delete(key);
        req.onsuccess = function ()  { resolve(); };
        req.onerror   = function (e) { reject(e.target.error); };
      } catch (e) {
        resolve(); // Store missing? Nothing to delete.
      }
    });
  }

  /** Generic IDB clear. */
  function _idbClear(storeName) {
    return new Promise(function (resolve, reject) {
      try {
        const tx = _db.transaction(storeName, 'readwrite');
        const req = tx.objectStore(storeName).clear();
        req.onsuccess = function ()  { resolve(); };
        req.onerror   = function (e) { reject(e.target.error); };
      } catch (e) {
        resolve(); // Store missing? Nothing to clear.
      }
    });
  }

  // ── Public API ────────────────────────────────────────────────────────

  /**
   * Blueprint v2.1 entry point — no password, no KDF at the master-key layer.
   *
   * First visit: generates 32 random bytes via sodium.randombytes_buf(32),
   *   writes them to pm_master_key store as base64url-no-padding, then calls
   *   navigator.storage.persist() and shows a non-dismissible warning banner
   *   if permission is denied.
   *
   * Subsequent visits: reads the stored record and decodes the raw bytes.
   *
   * In both cases: derives _pickleKey via HKDF-SHA256 (UNCHANGED from v2),
   *   then zeros the master_key Uint8Array.
   *
   * @param {number|string} userId — used to isolate master key and account state.
   * @returns {{ isNewMasterKey: boolean }}
   */
   async function init(userId) {
    if (!userId) throw new Error('PM_KEYSTORE: userId is required');
    _selfUid = String(userId);

    await window.PM_CRYPTO_READY;
    const sodium = window.sodium;

    // Open the database (creates/upgrades to version 3).
    _db = await _openDb();


    // Read master_key record for THIS user.
    const record = await _idbGet(STORE_MASTER, _selfUid);

    let masterKey;
    let isNewMasterKey = false;

    if (!record) {
      console.info('[PM_KEYSTORE] No master key for user ' + _selfUid + ' — generating fresh');
      // ── First visit: generate and persist a fresh master key ──────────
      // sodium.randombytes_buf(32) draws from the OS CSPRNG via libsodium.
      // Never derived from a password. Never transmitted.
      masterKey = sodium.randombytes_buf(32);

      const keyRecord = {
        key_b64: sodium.to_base64(masterKey, sodium.base64_variants.URLSAFE_NO_PADDING),
        version: 1,
      };

      await _idbPut(STORE_MASTER, _selfUid, keyRecord);
      isNewMasterKey = true;

      // ── New Master Key: Clear existing ciphertexts for this user ──────
      // To ensure no cross-user pollution (or legacy v1/v2 mismatches),
      // we remove any old record for this user.
      await _idbDelete(STORE_ACCOUNTS, _selfUid);

      // Request persistent storage immediately after the first write.
      // This is the only callsite; the load path deliberately skips it.
      try {
        const granted = await navigator.storage.persist();
        if (!granted) {
          // Warn in the application logger equivalent (console.warn, no key material).
          console.warn('[PM_KEYSTORE] storage.persist denied — IndexedDB data may be evicted under storage pressure');
          // Show a non-dismissible banner (does not block chat).
          _showPersistDeniedBanner();
        }
      } catch (persistErr) {
        // navigator.storage.persist() is not available in all environments.
        console.warn('[PM_KEYSTORE] storage.persist() unavailable:', persistErr.message);
      }
    } else {
      // ── Subsequent visits: load the existing master key ───────────────
      masterKey = sodium.from_base64(record.key_b64, sodium.base64_variants.URLSAFE_NO_PADDING);
      isNewMasterKey = false;
    }

    // ── Pickle key derivation — UNCHANGED from Blueprint v2 ─────────────
    // HKDF-SHA256(IKM=master_key, salt=0x00*32, info="MYCHAT_OLM_PICKLE_v1", len=32)
    // Implemented manually because crypto_kdf_hkdf_sha256_extract/expand are
    // not exported in this version of libsodium-wrappers-sumo.
    // RFC 5869: HKDF-Extract: PRK = HMAC-SHA256(salt, IKM)
    //           HKDF-Expand:  T(1) = HMAC-SHA256(PRK, info || 0x01)
    //           Output: first 32 bytes of T(1)
    const hkdfSalt  = new Uint8Array(32); // zero-filled per blueprint
    const infoBytes = sodium.from_string(PICKLE_INFO);

    // HKDF-Extract: PRK = HMAC-SHA256(hkdfSalt, masterKey)
    // libsodium: crypto_auth_hmacsha256(message, key) = HMAC-SHA256(key, message)
    // So: crypto_auth_hmacsha256(masterKey, hkdfSalt) = HMAC-SHA256(hkdfSalt, masterKey) = PRK
    const prk = sodium.crypto_auth_hmacsha256(masterKey, hkdfSalt);

    // HKDF-Expand: T(1) = HMAC-SHA256(PRK, info || 0x01), output = T(1)[0:32]
    const expandInput = new Uint8Array(infoBytes.length + 1);
    expandInput.set(infoBytes, 0);
    expandInput[infoBytes.length] = 0x01;
    _pickleKey = sodium.crypto_auth_hmacsha256(expandInput, prk);
    // _pickleKey is 32 bytes (HMAC-SHA256 output length = 32) — matches desired keylen.

    // Zero master key immediately — it must not persist in any variable.
    masterKey.fill(0);
    prk.fill(0);

    return { isNewMasterKey };
  }

  /**
   * Show a non-dismissible storage-eviction warning banner.
   * Sits above the message list. Uses the same design tokens as the rest of
   * the private-chat UI (.pm-persist-denied-banner class defined in
   * private-chat.css). Does not block chat functionality.
   */
  function _showPersistDeniedBanner() {
    // Idempotent — don't insert twice if somehow called again.
    if (document.getElementById('pm-persist-denied-banner')) return;

    const banner = document.createElement('div');
    banner.id        = 'pm-persist-denied-banner';
    banner.className = 'pm-persist-denied-banner';
    banner.setAttribute('role', 'alert');
    banner.setAttribute('aria-live', 'polite');

    const icon = document.createElement('span');
    icon.className = 'pm-persist-denied-banner__icon';
    icon.setAttribute('aria-hidden', 'true');
    // Using the same lock icon as the e2ee-strip (&#x1F512;) for visual consistency.
    icon.textContent = '⚠️'; // warning sign

    const text = document.createElement('span');
    text.className = 'pm-persist-denied-banner__text';
    // Exact copy from blueprint Addendum § "Storage eviction…"
    text.textContent = 'This browser may delete your encrypted keys without warning. To prevent this, bookmark this site or grant storage permission in your browser settings.';

    banner.appendChild(icon);
    banner.appendChild(text);

    // Insert before the message list (or as first child of body as fallback).
    const msgList = document.getElementById('pm-message-list');
    if (msgList && msgList.parentNode) {
      msgList.parentNode.insertBefore(banner, msgList);
    } else {
      // Fallback: prepend to body — still non-dismissible and visible.
      document.body.insertBefore(banner, document.body.firstChild);
    }
  }

  /** Zero pickle_key and close database connection. */
  function lock() {
    if (_pickleKey) {
      _pickleKey.fill(0);
      _pickleKey = null;
    }
    if (_db) {
      _db.close();
      _db = null;
    }
    _selfUid = null;
  }

  /** Get the decrypted Olm Account pickle bytes. Returns null if not found. */
  async function getAccountPickle() {
    _requireUnlocked();
    const entry = await _idbGet(STORE_ACCOUNTS, _selfUid);
    if (!entry) return null;
    return _decrypt(entry, 'olm_account');
  }

  /** Encrypt and persist the Olm Account pickle. */
  async function putAccountPickle(plaintextBytes) {
    _requireUnlocked();
    const entry = _encrypt(plaintextBytes, 'olm_account');
    await _idbPut(STORE_ACCOUNTS, _selfUid, entry);
  }

  /** Get the decrypted Olm Session pickle bytes for a conversation. Returns null if not found. */
  async function getSessionPickle(convId) {
    _requireUnlocked();
    // Asymmetric key: userId + ":" + convId
    const entry = await _idbGet(STORE_SESSIONS, _selfUid + ':' + convId);
    if (!entry) return null;
    return _decrypt(entry, _convIdStore(convId));
  }

  /** Encrypt and persist the Olm Session pickle for a conversation. */
  async function putSessionPickle(convId, plaintextBytes) {
    _requireUnlocked();
    // Asymmetric key: userId + ":" + convId
    const entry = _encrypt(plaintextBytes, _convIdStore(convId));
    await _idbPut(STORE_SESSIONS, _selfUid + ':' + convId, entry);
  }

  /** Remove a session pickle from IndexedDB (on key-change alarm). */
  async function deleteSession(convId) {
    _requireUnlocked();
    await _idbDelete(STORE_SESSIONS, _selfUid + ':' + convId);
  }

  /** Encrypt and persist a chat message. messageObj: {text, isOwn, ts, username, avatarUrl} */
  async function putMessage(convId, messageObj) {
    _requireUnlocked();
    const sodium = window.sodium;
    const plaintextBytes = sodium.from_string(JSON.stringify(messageObj));
    const entry = _encrypt(plaintextBytes, _convIdStore(convId));

    // Key format: selfUid:convId:timestamp_uuid (ensures isolation and ordering)
    const storageKey = _selfUid + ':' + convId + ':' + Date.now() + '_' + sodium.to_base64(sodium.randombytes_buf(4));
    await _idbPut(STORE_MESSAGES, storageKey, entry);
  }

  /** Retrieve and decrypt all messages for a conversation. */
  async function getMessages(convId) {
    _requireUnlocked();
    const prefix = _selfUid + ':' + convId + ':';

    return new Promise(function (resolve, reject) {
      const results = [];
      try {
        const tx = _db.transaction(STORE_MESSAGES, 'readonly');
        const store = tx.objectStore(STORE_MESSAGES);
        const range = IDBKeyRange.bound(prefix, prefix + '\uffff');
        const req = store.openCursor(range);

        req.onsuccess = function (e) {
          const cursor = e.target.result;
          if (cursor) {
            try {
              const decrypted = _decrypt(cursor.value, _convIdStore(convId));
              results.push(JSON.parse(window.sodium.to_string(decrypted)));
            } catch (err) {
              console.warn('[PM_KEYSTORE] failed to decrypt historical message — skipping', err);
            }
            cursor.continue();
          } else {
            resolve(results);
          }
        };
        req.onerror = function (e) { reject(e.target.error); };
      } catch (e) {
        resolve([]); // store missing or locked
      }
    });
  }

  /**
   * Panic-wipe: delete the entire database immediately (before any server call).
   * deleteDatabase removes ALL stores including pm_master_key. On next visit,
   * init() finds no record and generates a fresh key. See blueprint § "Panic-wipe".
   * Then redirect to /.
   */
  async function wipeAll() {
    lock();
    await new Promise(function (resolve, reject) {
      const req = indexedDB.deleteDatabase(DB_NAME);
      req.onsuccess = resolve;
      req.onerror   = reject;
      req.onblocked = resolve; // proceed even if blocked
    });
    // Also clear any pm_* keys from localStorage as belt-and-suspenders.
    try {
      Object.keys(localStorage)
        .filter(function (k) { return k.startsWith('pm_'); })
        .forEach(function (k) { localStorage.removeItem(k); });
    } catch (_) {}
    window.location.href = '/';
  }

  /**
   * Internal accessor: returns a base64-encoded copy of the pickle_key for
   * use as Olm's own pickle() password. This is the same key that wraps the
   * AEAD at rest — Olm uses it as an internal obfuscation layer. The actual
   * security comes from keystore's AEAD wrapping around the whole pickle blob.
   * Only olm_session.js should call this.
   */
  function _getPickleKeyForOlm() {
    _requireUnlocked();
    // Return base64 string — Olm's pickle() accepts strings.
    return window.sodium.to_base64(_pickleKey);
  }

  // Expose as module-local singleton via global namespace.
  global.PM_KEYSTORE = {
    init,
    lock,
    getAccountPickle,
    putAccountPickle,
    getSessionPickle,
    putSessionPickle,
    deleteSession,
    putMessage,
    getMessages,
    wipeAll,
    // Internal: only for olm_session.js.
    _getPickleKeyForOlm,
  };
})(window);
