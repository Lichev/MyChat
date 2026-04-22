/**
 * hub-shell.js
 * Shell-level JS for the hub layout. Handles:
 *  1. Tab switcher + keyboard navigation (Rooms/Users panel swap)
 *  2. chat_info_json fetch → populate #userList (guarded: only when present)
 *  3. appendFriendToSidebar (called by hub.html dashboard JS after accept)
 *  4. ?view=users / active_tab="conversation" auto-activation on page load
 *
 * Context is read directly from json_script elements injected by hub_shell.html
 * (type="application/json" — not executable JS, CSP-safe without unsafe-inline):
 *   #shell-ctx-csrf                  — CSRF token string
 *   #shell-ctx-active-tab            — 'rooms' | 'users' | 'account' | 'conversation'
 *   #shell-ctx-chat-info-url         — URL for the chat_info endpoint
 *   #shell-ctx-profile-url-template  — URL with 'USERNAME' placeholder
 *   #shell-ctx-pm-url-template       — URL with '0' placeholder for peer_id
 *   #shell-ctx-current-peer-id       — integer peer id (PM pages only) or ''
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
  /* Current peer id (set on /pm/chat/<id>/ pages only; empty string otherwise) */
  var currentPeerId = readJson('shell-ctx-current-peer-id');

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

  /* ── Auto-activate Users tab on load ── */
  /* If the server set active_tab="users" (via ?view=users) or "conversation"
     (PM pages), activate the Users tab/panel visually. The server already sets
     aria-selected on the markup, but we still need the JS panel hidden-state to
     match so _sidebar_users.html is visible. */
  if (serverActiveTab === 'users' || serverActiveTab === 'conversation') {
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

    /* Primary link: PM conversation URL when available, profile URL as fallback */
    var profileUrl = publicProfileUrlTemplate.replace('USERNAME', encodeURIComponent(friend.username));
    var primaryUrl = profileUrl;
    if (pmConversationUrlTemplate && friend.id) {
      primaryUrl = pmConversationUrlTemplate.replace('/0/', '/' + encodeURIComponent(friend.id) + '/');
    }

    var li  = document.createElement('li');
    var a   = document.createElement('a');
    a.href      = primaryUrl;
    a.className = 'user-row';

    /* Highlight the row whose id matches the current PM peer */
    if (currentPeerId !== null && currentPeerId !== '' &&
        String(friend.id) === String(currentPeerId)) {
      a.classList.add('user-row--active');
    }

    var img = document.createElement('img');
    img.src       = friend.avatar || '';
    img.alt       = friend.username;
    img.className = 'user-row__avatar';

    var info = document.createElement('div');
    info.className = 'user-row__info';

    /* Name + inline lock glyph on the same line */
    var nameRow = document.createElement('div');
    nameRow.className = 'user-row__name-row';

    var nameSpan = document.createElement('span');
    nameSpan.className   = 'user-row__name';
    nameSpan.textContent = friend.username;

    /* Small lock SVG marker — indicates E2EE; purely decorative (aria-hidden) */
    var svgNS   = 'http://www.w3.org/2000/svg';
    var lockSvg = document.createElementNS(svgNS, 'svg');
    lockSvg.setAttribute('width', '11');
    lockSvg.setAttribute('height', '11');
    lockSvg.setAttribute('viewBox', '0 0 14 14');
    lockSvg.setAttribute('fill', 'none');
    lockSvg.setAttribute('aria-hidden', 'true');
    lockSvg.setAttribute('class', 'user-row__lock');
    var lockRect = document.createElementNS(svgNS, 'rect');
    lockRect.setAttribute('x', '2');  lockRect.setAttribute('y', '6');
    lockRect.setAttribute('width', '10'); lockRect.setAttribute('height', '7');
    lockRect.setAttribute('rx', '1.5');
    lockRect.setAttribute('stroke', 'currentColor'); lockRect.setAttribute('stroke-width', '1.3');
    var lockPath = document.createElementNS(svgNS, 'path');
    lockPath.setAttribute('d', 'M4.5 6V4.5a2.5 2.5 0 015 0V6');
    lockPath.setAttribute('stroke', 'currentColor'); lockPath.setAttribute('stroke-width', '1.3');
    lockPath.setAttribute('stroke-linecap', 'round');
    lockSvg.appendChild(lockRect);
    lockSvg.appendChild(lockPath);

    nameRow.appendChild(nameSpan);
    nameRow.appendChild(lockSvg);

    var previewSpan = document.createElement('span');
    previewSpan.className   = 'user-row__preview';
    previewSpan.textContent = friend.last_dm_preview ? friend.last_dm_preview : '';

    info.appendChild(nameRow);
    info.appendChild(previewSpan);
    a.appendChild(img);
    a.appendChild(info);
    li.appendChild(a);

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
