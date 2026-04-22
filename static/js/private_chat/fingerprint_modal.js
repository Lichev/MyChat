/**
 * fingerprint_modal.js — Safety number verification modal.
 *
 * When user clicks the "Safety #" pill in the topbar:
 * 1. Request peer's identity keys via identity.fingerprint WS event.
 * 2. Compute the 60-digit safety number locally (PM_SAFETY_NUMBER).
 * 3. Render the number in the modal along with a QR code.
 * 4. Render the QR from base64url(selfIk || peerIk || selfUid || peerUid).
 *
 * Depends on: PM_SOCKET, PM_SAFETY_NUMBER, PM_CRYPTO_READY
 * QR: uses qrcode-generator vendored at /static/vendor/qrcode-generator/1.4.4/qrcode.js
 *
 * init(selfIkEd25519, selfUid, peerId) — wire the pill button.
 */

'use strict';

(function (global) {

  function init(selfIkEd25519, selfUid, peerId) {
    const pillBtn = document.getElementById('pm-safety-pill');
    if (!pillBtn) return;

    pillBtn.addEventListener('click', function () {
      _requestAndShow(selfIkEd25519, selfUid, peerId);
    });
  }

  function _requestAndShow(selfIk, selfUid, peerId) {
    // Show loading state immediately.
    _renderModal('Loading…', null, null);

    // Register one-shot handler for the response.
    function onResponse(data) {
      global.PM_SOCKET.off('identity.fingerprint.response', onResponse);
      _computeAndRender(selfIk, selfUid, data.ik_pub_ed25519, data.peer_id);
    }

    global.PM_SOCKET.on('identity.fingerprint.response', onResponse);
    global.PM_SOCKET.requestFingerprint();
  }

  async function _computeAndRender(selfIk, selfUid, peerIk, peerUid) {
    try {
      const digits = await global.PM_SAFETY_NUMBER.compute(selfIk, selfUid, peerIk, peerUid);
      const formatted = global.PM_SAFETY_NUMBER.format(digits);
      const qrPayload = _buildQrPayload(selfIk, peerIk, selfUid, peerUid);
      _renderModal(formatted, qrPayload, digits);
    } catch (e) {
      _renderModal('Error computing safety number: ' + e.message, null, null);
    }
  }

  function _buildQrPayload(selfIk, peerIk, selfUid, peerUid) {
    // QR payload: base64url(selfIk_bytes || peerIk_bytes || selfUid_utf8 || '|' || peerUid_utf8)
    const sodium   = global.sodium;
    // Olm identity keys are standard base64 (no padding) — decode with the
    // matching variant, not libsodium-js's URL-safe default.
    const olmVariant = sodium.base64_variants.ORIGINAL_NO_PADDING;
    const selfBytes = sodium.from_base64(selfIk, olmVariant);
    const peerBytes = sodium.from_base64(peerIk, olmVariant);
    const enc       = new TextEncoder();
    const selfUidB  = enc.encode(String(selfUid));
    const peerUidB  = enc.encode(String(peerUid));
    const sep       = enc.encode('|');

    const combined = new Uint8Array(
      selfBytes.length + peerBytes.length + selfUidB.length + sep.length + peerUidB.length
    );
    let off = 0;
    combined.set(selfBytes,  off); off += selfBytes.length;
    combined.set(peerBytes,  off); off += peerBytes.length;
    combined.set(selfUidB,   off); off += selfUidB.length;
    combined.set(sep,        off); off += sep.length;
    combined.set(peerUidB,   off);

    // base64url (no padding)
    return sodium.to_base64(combined, sodium.base64_variants.URLSAFE_NO_PADDING);
  }

  function _renderModal(safetyText, qrPayload, rawDigits) {
    // Remove any existing modal.
    const existing = document.getElementById('pm-fingerprint-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id        = 'pm-fingerprint-overlay';
    overlay.className = 'pm-fingerprint-modal-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'pm-fp-title');

    const modal = document.createElement('div');
    modal.className = 'pm-fingerprint-modal';

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.className   = 'pm-fingerprint-modal__close';
    closeBtn.setAttribute('aria-label', 'Close safety number dialog');
    closeBtn.textContent = '×'; // ×
    closeBtn.addEventListener('click', function () { overlay.remove(); });

    // Title
    const title = document.createElement('h2');
    title.id        = 'pm-fp-title';
    title.className = 'pm-fingerprint-modal__title';
    title.textContent = 'Safety Number';

    // Instructions
    const instr = document.createElement('p');
    instr.className = 'pm-fingerprint-modal__instructions';
    instr.textContent =
      'Compare these digits with your peer in person or over a verified channel. ' +
      'If they match, this conversation is secure.';

    // Safety number display
    const numEl = document.createElement('pre');
    numEl.className = 'pm-fingerprint-modal__number';
    numEl.setAttribute('aria-label', 'Safety number');
    numEl.textContent = safetyText; // textContent — safe, derived from hash not user input

    modal.appendChild(closeBtn);
    modal.appendChild(title);
    modal.appendChild(instr);
    modal.appendChild(numEl);

    // QR code (only when we have a payload and qrcode library is loaded)
    if (qrPayload && typeof global.qrcode === 'function') {
      const qrContainer = document.createElement('div');
      qrContainer.className = 'pm-fingerprint-modal__qr';
      qrContainer.setAttribute('aria-label', 'QR code of safety number keys');

      try {
        const qr = global.qrcode(4, 'M');  // type number 4, error correction M
        qr.addData(qrPayload);
        qr.make();
        // createImgTag returns an <img> HTML string — we set its src via DOM.
        const img = new Image();
        // Manually create the QR as a canvas to avoid innerHTML.
        const moduleCount = qr.getModuleCount();
        const cellSize    = 4;
        const canvas      = document.createElement('canvas');
        canvas.width      = moduleCount * cellSize;
        canvas.height     = moduleCount * cellSize;
        const ctx         = canvas.getContext('2d');
        for (let row = 0; row < moduleCount; row++) {
          for (let col = 0; col < moduleCount; col++) {
            ctx.fillStyle = qr.isDark(row, col) ? '#a78bfa' : '#0d0f14';
            ctx.fillRect(col * cellSize, row * cellSize, cellSize, cellSize);
          }
        }
        qrContainer.appendChild(canvas);
      } catch (e) {
        // QR render failure is non-fatal; number is still shown.
        const errMsg = document.createElement('p');
        errMsg.className = 'pm-fingerprint-modal__qr-error';
        errMsg.textContent = 'QR generation failed.';
        qrContainer.appendChild(errMsg);
      }

      modal.appendChild(qrContainer);
    }

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Close on overlay backdrop click.
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) overlay.remove();
    });

    // Trap focus.
    closeBtn.focus();
  }

  global.PM_FINGERPRINT_MODAL = { init };
})(window);
