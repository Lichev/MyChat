/**
 * socket.js — WebSocket client for ws/pm/<peer_id>/
 *
 * Responsibilities:
 * - Connect to the PM WebSocket endpoint.
 * - Reconnect with exponential backoff (cap 30 s).
 * - Marshal outbound JSON events (does NOT do any crypto).
 * - Dispatch inbound events to registered handlers via PM_SOCKET.on(type, fn).
 * - Enqueue outbound messages while disconnected; flush on reconnect.
 *
 * Inbound events handled:
 *   envelope.deliver, envelope.send.ack, envelope.ack.confirm,
 *   prekey.bundle, identity.fingerprint.response,
 *   pm.key_rotate_alarm, pm.wipe, error
 *
 * Outbound methods:
 *   sendEnvelope(ciphertext_b64, message_type, otpk_id_used)
 *   sendAck(envelope_id, decrypt_error)
 *   requestPrekey()
 *   publishPrekeys(keys)
 *   rotateKey(ik_curve, ik_ed, spk_pub, spk_sig)
 *   requestFingerprint()
 *   sendJson(obj)   — low-level escape hatch
 */

'use strict';

(function (global) {
  const INITIAL_BACKOFF_MS = 500;
  const MAX_BACKOFF_MS     = 30000;
  const BACKOFF_FACTOR     = 2;

  let _ws           = null;
  let _peerId       = null;
  let _backoff      = INITIAL_BACKOFF_MS;
  let _reconnectTimer = null;
  let _outqueue     = [];          // messages buffered while disconnected
  let _handlers     = {};          // event type → [fn]
  let _connected    = false;
  let _destroyed    = false;

  function _wsUrl(peerId) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + window.location.host + '/ws/pm/' + peerId + '/';
  }

  function _dispatch(type, data) {
    const fns = _handlers[type] || [];
    fns.forEach(function (fn) {
      try { fn(data); } catch (e) {
        console.error('[PM_SOCKET] handler error for', type, e);
      }
    });
    // Also dispatch to wildcard handlers.
    (_handlers['*'] || []).forEach(function (fn) {
      try { fn(type, data); } catch (e) {
        console.error('[PM_SOCKET] wildcard handler error', e);
      }
    });
  }

  function _flushQueue() {
    const pending = _outqueue.slice();
    _outqueue = [];
    pending.forEach(function (msg) {
      try { _ws.send(JSON.stringify(msg)); } catch (e) {
        console.error('[PM_SOCKET] flush send error', e);
        _outqueue.push(msg); // put back if send failed
      }
    });
  }

  function _connect() {
    if (_destroyed) return;
    const url = _wsUrl(_peerId);
    _ws = new WebSocket(url);

    _ws.onopen = function () {
      _connected = true;
      _backoff = INITIAL_BACKOFF_MS;
      _flushQueue();
      _dispatch('_connected', {});
    };

    _ws.onmessage = function (e) {
      let data;
      try {
        data = JSON.parse(e.data);
      } catch (err) {
        console.error('[PM_SOCKET] JSON parse error', err);
        return;
      }
      if (!data || typeof data.type !== 'string') {
        console.warn('[PM_SOCKET] received message without type field');
        return;
      }
      _dispatch(data.type, data);
    };

    _ws.onerror = function (e) {
      console.warn('[PM_SOCKET] WS error', e);
    };

    _ws.onclose = function (e) {
      _connected = false;
      _dispatch('_disconnected', { code: e.code });
      if (!_destroyed) {
        _reconnectTimer = setTimeout(function () {
          _backoff = Math.min(_backoff * BACKOFF_FACTOR, MAX_BACKOFF_MS);
          _connect();
        }, _backoff);
      }
    };
  }

  // ── Public API ────────────────────────────────────────────────────────

  /** Initialise and connect. Call once. */
  function init(peerId) {
    if (_peerId !== null) {
      throw new Error('PM_SOCKET already initialised.');
    }
    _peerId = peerId;
    _connect();
  }

  /** Register an event handler. type = WS event type string or '*'. */
  function on(type, fn) {
    if (!_handlers[type]) _handlers[type] = [];
    _handlers[type].push(fn);
  }

  /** Remove a previously registered handler. */
  function off(type, fn) {
    if (!_handlers[type]) return;
    _handlers[type] = _handlers[type].filter(function (f) { return f !== fn; });
  }

  /** Low-level: send any JSON object. Queues if not connected. */
  function sendJson(obj) {
    if (_connected && _ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify(obj));
    } else {
      _outqueue.push(obj);
    }
  }

  /** Send an encrypted envelope to the peer. */
  function sendEnvelope(ciphertext_b64, message_type, otpk_id_used) {
    sendJson({
      type:          'envelope.send',
      ciphertext_b64,
      message_type,
      otpk_id_used:  otpk_id_used || null,
    });
  }

  /** ACK receipt and decryption of an envelope. */
  function sendAck(envelope_id, decrypt_error) {
    sendJson({
      type:          'envelope.ack',
      envelope_id,
      decrypt_error: !!decrypt_error,
    });
  }

  /** Request the peer's prekey bundle from the server. */
  function requestPrekey() {
    sendJson({ type: 'prekey.request' });
  }

  /** Publish a batch of one-time prekeys. */
  function publishPrekeys(keys) {
    sendJson({ type: 'prekey.publish', keys });
  }

  /** Trigger emergency IK rotation. */
  function rotateKey(ik_pub_curve25519, ik_pub_ed25519, spk_pub, spk_sig) {
    sendJson({ type: 'key.rotate', ik_pub_curve25519, ik_pub_ed25519, spk_pub, spk_sig });
  }

  /** Request the peer's identity fingerprint for safety-number derivation. */
  function requestFingerprint() {
    sendJson({ type: 'identity.fingerprint' });
  }

  /** Tear down — stop reconnects. */
  function destroy() {
    _destroyed = true;
    if (_reconnectTimer) clearTimeout(_reconnectTimer);
    if (_ws) _ws.close();
  }

  global.PM_SOCKET = {
    init,
    on,
    off,
    sendJson,
    sendEnvelope,
    sendAck,
    requestPrekey,
    publishPrekeys,
    rotateKey,
    requestFingerprint,
    destroy,
  };
})(window);
