/**
 * key-reveal.js
 * Interactivity for the recovery-key reveal page.
 *
 * Expects two JSON data elements (set via Django's json_script filter, which
 * is XSS-safe — it HTML-encodes the values and wraps them in a <script> tag
 * with type="application/json", which is not executable JS):
 *
 *   <script id="key-reveal-raw-key" type="application/json">"<raw_key>"</script>
 *   <script id="key-reveal-home-url" type="application/json">"<home_url>"</script>
 *
 * These replace the previous inline variable injection ({{ raw_key|escapejs }})
 * which was the data: URI double-exposure flagged in the blueprint.
 * json_script outputs are safe: they are typed as application/json (not
 * text/javascript) so browsers do not execute them, and Django HTML-encodes
 * the content, preventing script injection.
 */
(function () {
  'use strict';

  /* Read context from json_script elements (XSS-safe, CSP-compliant). */
  function readJsonScript(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  var RAW_KEY  = readJsonScript('key-reveal-raw-key');
  var HOME_URL = readJsonScript('key-reveal-home-url');

  if (!RAW_KEY || !HOME_URL) return;

  /* ── Chunk key into 4-char groups separated by dashes (display only) ── */
  function chunkKey(key) {
    return key.match(/.{1,4}/g).join('-');
  }
  var keyDisplay = document.getElementById('keyDisplay');
  if (keyDisplay) keyDisplay.textContent = chunkKey(RAW_KEY);

  /* ── Copy ────────────────────────────────────────────────────────── */
  var copyBtn   = document.getElementById('copyBtn');
  var copyLabel = document.getElementById('copyLabel');

  var COPY_ICON_HTML =
    '<svg id="copyIcon" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">' +
    '<rect x="4" y="4" width="8" height="8" rx="1.5" stroke="currentColor" stroke-width="1.3"/>' +
    '<path d="M2 10V2h8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>' +
    '</svg>';

  var CHECK_ICON_HTML =
    '<svg id="copyIcon" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">' +
    '<path d="M2 7l4 4 6-6" stroke="#10b981" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
    '</svg>';

  var copyTimeout = null;

  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(RAW_KEY).then(function () {
        var icon = copyBtn.querySelector('svg');
        if (icon) icon.outerHTML = CHECK_ICON_HTML;
        if (copyLabel) {
          copyLabel.textContent = 'Copied!';
          copyLabel.style.color = 'var(--online)';
        }
        clearTimeout(copyTimeout);
        copyTimeout = setTimeout(function () {
          var icon2 = copyBtn.querySelector('svg');
          if (icon2) icon2.outerHTML = COPY_ICON_HTML;
          if (copyLabel) {
            copyLabel.textContent = 'Copy key';
            copyLabel.style.color = '';
          }
        }, 2000);
      });
    });
  }

  /* ── Download ────────────────────────────────────────────────────── */
  var downloadBtn = document.getElementById('downloadBtn');
  if (downloadBtn) {
    downloadBtn.addEventListener('click', function () {
      var content =
        'Your MyChat recovery key:\n\n' +
        RAW_KEY +
        '\n\nStore this somewhere safe. This key cannot be retrieved later.';
      var blob = new Blob([content], { type: 'text/plain' });
      var url  = URL.createObjectURL(blob);
      var a    = document.createElement('a');
      a.href     = url;
      a.download = 'mychat-recovery-key.txt';
      document.body.appendChild(a);
      a.click();
      setTimeout(function () {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 100);
    });
  }

  /* ── Checkbox → enable Continue ─────────────────────────────────── */
  var checkbox    = document.getElementById('savedConfirm');
  var continueBtn = document.getElementById('continueBtn');

  if (checkbox && continueBtn) {
    checkbox.addEventListener('change', function () {
      if (checkbox.checked) {
        continueBtn.classList.add('is-enabled');
        continueBtn.removeAttribute('aria-disabled');
      } else {
        continueBtn.classList.remove('is-enabled');
        continueBtn.setAttribute('aria-disabled', 'true');
      }
    });

    /* ── Continue + history wipe ─────────────────────────────────── */
    continueBtn.addEventListener('click', function () {
      if (!continueBtn.classList.contains('is-enabled')) return;
      /* Replace current history entry so back-button cannot return here */
      history.replaceState(null, '', window.location.href);
      window.location.href = HOME_URL;
    });
  }

}());
