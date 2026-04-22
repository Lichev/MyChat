/**
 * key-banner.js
 * Handles dismiss behaviour for the recovery-key reminder banner.
 *
 * Required data attribute on #keyBannerClose:
 *   data-dismiss-url  — the URL for the dismiss_key_banner POST endpoint.
 *                        Set via a data-* attribute in base.html so this file
 *                        contains no Django template tags.
 */
(function () {
  'use strict';

  var btn    = document.getElementById('keyBannerClose');
  var banner = document.getElementById('keyBanner');
  if (!btn || !banner) return;

  btn.addEventListener('click', function () {
    banner.style.transition = 'opacity 0.25s';
    banner.style.opacity    = '0';
    setTimeout(function () { banner.remove(); }, 260);

    var dismissUrl = btn.getAttribute('data-dismiss-url');
    if (!dismissUrl) return;

    var csrf = document.cookie.match(/csrftoken=([^;]+)/);
    fetch(dismissUrl, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf ? csrf[1] : '' },
      credentials: 'same-origin',
    });
  });
}());
