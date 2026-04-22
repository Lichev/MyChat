/**
 * hub-shell.js
 * Shell-level JS for the hub layout. Handles:
 *  1. Tab switcher + keyboard navigation (Rooms/Users panel swap)
 *  2. chat_info_json fetch → populate #userList (guarded: only when present)
 *  3. appendFriendToSidebar (called by hub.html dashboard JS after accept)
 *  4. ?view=users auto-activation on page load
 *
 * Context is read directly from json_script elements injected by hub_shell.html
 * (type="application/json" — not executable JS, CSP-safe without unsafe-inline):
 *   #shell-ctx-csrf                  — CSRF token string
 *   #shell-ctx-active-tab            — 'rooms' | 'users' | 'account'
 *   #shell-ctx-chat-info-url         — URL for the chat_info endpoint
 *   #shell-ctx-profile-url-template  — URL with 'USERNAME' placeholder
 */
(function() {
  'use strict';

  /* Read context from json_script elements (XSS-safe, CSP-compliant). */
  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  var CSRF                     = readJson('shell-ctx-csrf') || '';
  var serverActiveTab          = readJson('shell-ctx-active-tab') || 'rooms';
  var chatInfoUrl              = readJson('shell-ctx-chat-info-url') || '';
  var publicProfileUrlTemplate = readJson('shell-ctx-profile-url-template') || '';
  /* PM conversation URL template — '0' placeholder is replaced by friend.id */
  var pmConversationUrlTemplate = readJson('shell-ctx-pm-url-template') || '';

  /* ── Tab switcher: only active in rooms/users mode (both panels present) ── */
  var tabList = document.querySelector('[role="tablist"]');
  /* Collect only <button role="tab"> — the Account <a> in rooms/users mode
     is excluded from the keyboard-nav roving tabindex because it's a link,
     not a panel trigger. */
  var tabs = tabList
    ? Array.prototype.slice.call(tabList.querySelectorAll('button[role="tab"]'))
    : [];
  var panels = tabs.map(function(t) {
    var id = t.getAttribute('aria-controls');
    return id ? document.getElementById(id) : null;
  });

  function activateTab(index) {
    tabs.forEach(function(t, i) {
      var isActive = i === index;
      t.setAttribute('aria-selected', String(isActive));
      t.setAttribute('tabindex', isActive ? '0' : '-1');
      t.classList.toggle('sidebar-tab--active', isActive);
      if (panels[i]) {
        panels[i].hidden = !isActive;
        if (isActive) panels[i].scrollTop = 0;
      }
    });
  }

  /* Wire click on each button tab */
  tabs.forEach(function(tab, index) {
    tab.addEventListener('click', function() { activateTab(index); });
  });

  /* Keyboard nav (arrow keys, Home, End) — roving tabindex within button tabs */
  if (tabList && tabs.length > 0) {
    tabList.addEventListener('keydown', function(e) {
      var current = tabs.indexOf(document.activeElement);
      if (current === -1) return;
      var next = current;
      if (e.key === 'ArrowRight')     { next = (current + 1) % tabs.length; }
      else if (e.key === 'ArrowLeft') { next = (current - 1 + tabs.length) % tabs.length; }
      else if (e.key === 'Home')      { next = 0; }
      else if (e.key === 'End')       { next = tabs.length - 1; }
      else                            { return; }
      e.preventDefault();
      activateTab(next);
      tabs[next].focus();
    });
  }

  /* ── ?view=users auto-activation on load ── */
  /* If the server set active_tab="users" (via ?view=users), activate the
     Users tab visually. The server already sets aria-selected on the markup,
     but we still need the JS panel state to match. */
  if (serverActiveTab === 'users') {
    var usersTabIndex = -1;
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].id === 'tab-users') { usersTabIndex = i; break; }
    }
    if (usersTabIndex !== -1) {
      activateTab(usersTabIndex);
    }
  }

  /* ── appendFriendToSidebar — called by hub.html dashboard JS after a
     friend-request accept. Guarded: #userList only exists in rooms/users mode. ── */
  window.appendFriendToSidebar = function(friend) {
    var userList = document.getElementById('userList');
    if (!userList) return;
    /* Remove skeleton/empty-state on first real entry */
    var skeleton = document.getElementById('userListSkeleton');
    if (skeleton) skeleton.remove();
    var emptyLi = userList.querySelector('.empty-state');
    if (emptyLi) emptyLi.remove();

    var profileUrl = publicProfileUrlTemplate.replace('USERNAME', encodeURIComponent(friend.username));
    var li  = document.createElement('li');
    var a   = document.createElement('a');
    a.href      = profileUrl;
    a.className = 'user-row';

    var img = document.createElement('img');
    img.src       = friend.avatar || '';
    img.alt       = friend.username;
    img.className = 'user-row__avatar';

    var info = document.createElement('div');
    info.className = 'user-row__info';

    var nameSpan = document.createElement('span');
    nameSpan.className   = 'user-row__name';
    nameSpan.textContent = friend.username;

    var previewSpan = document.createElement('span');
    previewSpan.className   = 'user-row__preview';
    previewSpan.textContent = friend.last_dm_preview ? friend.last_dm_preview : '';

    info.appendChild(nameSpan);
    info.appendChild(previewSpan);
    a.appendChild(img);
    a.appendChild(info);
    li.appendChild(a);

    /* Private chat link — shown alongside profile link if PM URL is configured */
    if (pmConversationUrlTemplate && friend.id) {
      var pmUrl = pmConversationUrlTemplate.replace('/0/', '/' + encodeURIComponent(friend.id) + '/');
      var pmLink = document.createElement('a');
      pmLink.href      = pmUrl;
      pmLink.className = 'user-row__pm-link';
      pmLink.title     = 'Private encrypted chat with ' + friend.username;
      pmLink.setAttribute('aria-label', 'Open end-to-end encrypted chat with ' + friend.username);
      /* Lock icon built via DOM API (no innerHTML) */
      var svgNS = 'http://www.w3.org/2000/svg';
      var lockSvg = document.createElementNS(svgNS, 'svg');
      lockSvg.setAttribute('width', '12');
      lockSvg.setAttribute('height', '12');
      lockSvg.setAttribute('viewBox', '0 0 14 14');
      lockSvg.setAttribute('fill', 'none');
      lockSvg.setAttribute('aria-hidden', 'true');
      lockSvg.style.flexShrink = '0';
      var rect = document.createElementNS(svgNS, 'rect');
      rect.setAttribute('x', '2'); rect.setAttribute('y', '6');
      rect.setAttribute('width', '10'); rect.setAttribute('height', '7');
      rect.setAttribute('rx', '1.5');
      rect.setAttribute('stroke', 'currentColor'); rect.setAttribute('stroke-width', '1.3');
      var path = document.createElementNS(svgNS, 'path');
      path.setAttribute('d', 'M4.5 6V4.5a2.5 2.5 0 015 0V6');
      path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '1.3');
      path.setAttribute('stroke-linecap', 'round');
      lockSvg.appendChild(rect);
      lockSvg.appendChild(path);
      pmLink.appendChild(lockSvg);
      /* Wrap in a styled container */
      pmLink.style.cssText = [
        'display:inline-flex',
        'align-items:center',
        'justify-content:center',
        'width:24px',
        'height:24px',
        'border-radius:var(--r-sm)',
        'background:rgba(124,58,237,0.1)',
        'border:1px solid rgba(124,58,237,0.2)',
        'color:var(--accent-glow)',
        'text-decoration:none',
        'flex-shrink:0',
        'transition:background var(--dur-fast)',
        'margin-left:auto',
      ].join(';');
      li.style.cssText = 'display:flex;align-items:center;gap:var(--s-2)';
      li.appendChild(pmLink);
    }

    userList.appendChild(li);
  };

  /* ── chat_info_json fetch → hydrate #userList (sidebar Users panel)
     Guarded: only run when #userList is in the DOM. On account-mode pages
     the Users partial isn't rendered so we skip entirely. ── */
  var userList = document.getElementById('userList');
  if (userList) {
    window.addEventListener('DOMContentLoaded', function() {
      fetch(chatInfoUrl, { headers: { 'X-CSRFToken': CSRF } })
        .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function(data) {
          /* Clear skeleton */
          var skeleton = document.getElementById('userListSkeleton');
          if (skeleton) skeleton.remove();

          if (data.friends && data.friends.length > 0) {
            data.friends.forEach(function(friend) {
              window.appendFriendToSidebar(friend);
            });
          } else {
            /* Re-fetch userList ref in case DOM updated */
            var ul = document.getElementById('userList');
            if (ul) {
              var li = document.createElement('li');
              li.className   = 'empty-state';
              li.textContent = 'No friends yet — search for users to add them';
              ul.appendChild(li);
            }
          }
        })
        .catch(function(err) { console.error('Shell chat_info fetch error:', err); });
    });
  }

}());
