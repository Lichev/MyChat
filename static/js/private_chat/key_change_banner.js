/**
 * key_change_banner.js — Blocking banner for peer key rotation alarm.
 *
 * When pm.key_rotate_alarm arrives for the current peer:
 * 1. Show a blocking red banner (modal overlay) — user cannot send messages.
 * 2. Delete the current session from IndexedDB (forces fresh X3DH on next send).
 * 3. Require explicit user acknowledgement before allowing next send.
 *
 * PM_SOCKET must be initialised before this module runs.
 * PM_KEYSTORE must be unlocked.
 *
 * init(convId, onAcknowledged) — registers the alarm handler.
 *   convId: the conversation's IndexedDB key.
 *   onAcknowledged: called after the user clicks "I understand".
 */

'use strict';

(function (global) {

  function init(convId, peerUid, onAcknowledged) {
    global.PM_SOCKET.on('pm.key_rotate_alarm', async function (data) {
      if (!data || !data.payload) return;

      // Ignore OTPK replenishment alarms (handled in ui.js).
      if (data.payload.remaining_otpks !== undefined) {
        return;
      }

      // Ignore key rotations from OTHER peers.
      if (String(data.payload.user_id) !== String(peerUid)) {
        return;
      }

      // Remove the stale session so the next send triggers fresh X3DH.
      try {
        await global.PM_KEYSTORE.deleteSession(convId);
      } catch (e) {
        console.error('[PM] key_change_banner: failed to delete session', e);
      }

      _showBanner(onAcknowledged);
    });
  }

  function _showBanner(onAcknowledged) {
    // Remove any existing banner first.
    const existing = document.getElementById('pm-key-change-banner');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id        = 'pm-key-change-banner';
    overlay.className = 'pm-key-change-banner';
    overlay.setAttribute('role', 'alertdialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'pm-kcb-title');
    overlay.setAttribute('aria-describedby', 'pm-kcb-desc');

    // Icon
    const icon = document.createElement('div');
    icon.className = 'pm-kcb__icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '⚠';  // WARNING SIGN

    // Title
    const title = document.createElement('h2');
    title.id        = 'pm-kcb-title';
    title.className = 'pm-kcb__title';
    title.textContent = 'Security alert: peer\'s keys changed';

    // Body
    const desc = document.createElement('p');
    desc.id        = 'pm-kcb-desc';
    desc.className = 'pm-kcb__desc';
    desc.textContent =
      'The identity keys for this conversation have changed. ' +
      'This may indicate the peer switched devices or rotated their keys. ' +
      'The current session has been cleared. ' +
      'Verify the safety number with your peer before continuing.';

    // Acknowledge button
    const btn = document.createElement('button');
    btn.className   = 'pm-kcb__btn';
    btn.textContent = 'I understand — start fresh session';
    btn.addEventListener('click', function () {
      overlay.remove();
      if (typeof onAcknowledged === 'function') onAcknowledged();
    });

    overlay.appendChild(icon);
    overlay.appendChild(title);
    overlay.appendChild(desc);
    overlay.appendChild(btn);

    document.body.appendChild(overlay);

    // Trap focus inside the banner.
    btn.focus();
  }

  global.PM_KEY_CHANGE_BANNER = { init };
})(window);
