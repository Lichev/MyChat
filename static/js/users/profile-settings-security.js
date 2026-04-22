/**
 * profile-settings-security.js
 * Externalises the inline onclick="return confirm(...)" on the rotate-key
 * form submit button from profile-settings-security.html.
 *
 * This was the last remaining inline event handler on that page. Removing it
 * allows the CSP script-src to drop 'unsafe-inline' (Step 3 requirement).
 *
 * No json_script data is needed — the confirmation text is static.
 * The button is found by its type="submit" inside the rotate-key form.
 */

'use strict';

(function () {
  document.addEventListener('DOMContentLoaded', function () {
    // The rotate-key form contains a hidden input name="action" value="rotate_key".
    var rotateForm = document.querySelector('form input[name="action"][value="rotate_key"]');
    if (!rotateForm) return;
    var form   = rotateForm.closest('form');
    var button = form ? form.querySelector('button[type="submit"]') : null;
    if (!button) return;

    // Remove any existing onclick (belt-and-suspenders in case template still
    // has one during transition period).
    button.removeAttribute('onclick');

    button.addEventListener('click', function (e) {
      var confirmed = window.confirm(
        'Generate a new recovery key? Your current key will be permanently invalidated.'
      );
      if (!confirmed) {
        e.preventDefault();
        e.stopPropagation();
      }
    });
  });
})();
