/**
 * global-ui.js
 * Global UI interactions loaded on every page via base.html.
 *
 * Handles:
 *  - Search toggle (trigger button + Ctrl+K shortcut + Escape)
 *  - Avatar dropdown (click toggle + outside-click close + Escape close)
 *  - Toast auto-dismiss (5 s timeout + manual close button)
 */
(function() {
  'use strict';

  /* ── Search toggle ──────────────────────────────────────────────── */
  var trigger  = document.getElementById('searchTrigger');
  var bar      = document.getElementById('searchBar');
  var closeBtn = document.getElementById('searchClose');
  var input    = document.getElementById('globalSearch');

  if (trigger && bar) {
    function openSearch() {
      bar.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      if (input) input.focus();
    }
    function closeSearch() {
      bar.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    }
    trigger.addEventListener('click', openSearch);
    if (closeBtn) closeBtn.addEventListener('click', closeSearch);

    document.addEventListener('keydown', function(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        bar.hidden ? openSearch() : closeSearch();
      }
      if (e.key === 'Escape') closeSearch();
    });
  }

  /* ── Avatar dropdown ────────────────────────────────────────────── */
  var avatarBtn = document.getElementById('navAvatarBtn');
  var dropdown  = document.getElementById('navDropdown');

  if (avatarBtn && dropdown) {
    avatarBtn.addEventListener('click', function() {
      var open = !dropdown.hidden;
      dropdown.hidden = open;
      avatarBtn.setAttribute('aria-expanded', String(!open));
    });
    document.addEventListener('click', function(e) {
      var wrap = document.getElementById('navAvatarWrap');
      if (wrap && !wrap.contains(e.target)) {
        dropdown.hidden = true;
        avatarBtn.setAttribute('aria-expanded', 'false');
      }
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && !dropdown.hidden) {
        dropdown.hidden = true;
        avatarBtn.setAttribute('aria-expanded', 'false');
        avatarBtn.focus();
      }
    });
  }

  /* ── Toast auto-dismiss ─────────────────────────────────────────── */
  document.querySelectorAll('.toast').forEach(function(toast) {
    var close = toast.querySelector('.toast__close');
    if (close) close.addEventListener('click', function() { toast.remove(); });
    setTimeout(function() {
      toast.style.opacity = '0';
      setTimeout(function() { toast.remove(); }, 400);
    }, 5000);
  });
}());
