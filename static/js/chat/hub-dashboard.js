/**
 * hub-dashboard.js
 *
 * Dashboard-specific JS for /chat/ (extends hub_shell.html).
 * Handles:
 *   - Sidebar search → unified search endpoint, inline results
 *   - Pending friend-request accept/reject
 *   - Dashboard data load (friends, groups, requests counters)
 *   - Add-friend, friend-card rendering
 *
 * Context is read from json_script elements (CSP-safe, no inline executable JS):
 *   #hub-ctx-csrf                   — CSRF token string
 *   #hub-ctx-chat-info-url          — URL for the chat_info endpoint
 *   #hub-ctx-search-unified-url     — URL for the unified search endpoint
 *   #hub-ctx-create-room-url        — URL for the create_room page
 *   #hub-ctx-room-detail-url-tpl    — URL template with '/0/' placeholder for room id
 *   #hub-ctx-profile-url-tpl        — URL template with 'USERNAME' placeholder
 *   #hub-ctx-friend-add-url-tpl     — URL template with 'USERNAME' placeholder
 *   #hub-ctx-friend-accept-url-tpl  — URL template with '0' placeholder for request id
 *   #hub-ctx-friend-reject-url-tpl  — URL template with '0' placeholder for request id
 */
(function() {
  'use strict';

  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  var CSRF                     = readJson('hub-ctx-csrf') || '';
  var chatInfoUrl              = readJson('hub-ctx-chat-info-url') || '';
  var searchUnifiedUrl         = readJson('hub-ctx-search-unified-url') || '';
  var roomDetailUrlTemplate    = readJson('hub-ctx-room-detail-url-tpl') || '';
  var profileUrlTemplate       = readJson('hub-ctx-profile-url-tpl') || '';
  var friendAddUrlTemplate     = readJson('hub-ctx-friend-add-url-tpl') || '';
  var friendAcceptUrlTemplate  = readJson('hub-ctx-friend-accept-url-tpl') || '';
  var friendRejectUrlTemplate  = readJson('hub-ctx-friend-reject-url-tpl') || '';

  function debounce(fn, delay) {
    var t;
    return function() {
      var args = arguments, ctx = this;
      clearTimeout(t);
      t = setTimeout(function() { fn.apply(ctx, args); }, delay);
    };
  }

  function xhrHeaders() {
    return { 'X-CSRFToken': CSRF, 'X-Requested-With': 'XMLHttpRequest' };
  }

  /* ── DOM refs ── */
  var dashboardView     = document.getElementById('dashboardView');
  var searchResults     = document.getElementById('searchResults');
  var searchGroupsGrid  = document.getElementById('searchGroupsGrid');
  var searchUsersGrid   = document.getElementById('searchUsersGrid');
  var searchGroupsEmpty = document.getElementById('searchGroupsEmpty');
  var searchUsersEmpty  = document.getElementById('searchUsersEmpty');
  var friendsGrid       = document.getElementById('row-list-friends');
  var groupsGrid        = document.getElementById('row-list-groups');
  var requestsSection   = document.getElementById('pending-requests-section');
  var requestsList      = document.getElementById('pending-requests-list');
  var friendsCount      = document.getElementById('friends-length');
  var groupsCount       = document.getElementById('groups-length');
  var requestsCount     = document.getElementById('requests-length');

  function showSearch() {
    if (dashboardView) dashboardView.hidden = true;
    if (searchResults) searchResults.hidden = false;
  }
  function showDashboard() {
    if (dashboardView) dashboardView.hidden = false;
    if (searchResults) searchResults.hidden = true;
  }

  /* ── Sidebar search ── */
  var searchInput       = document.getElementById('searchTerminal');
  var sidebarSearchForm = document.getElementById('sidebarSearchForm');

  if (searchInput && searchResults && dashboardView) {
    if (sidebarSearchForm) {
      sidebarSearchForm.addEventListener('submit', function(e) { e.preventDefault(); });
    }
    searchInput.addEventListener('input', debounce(function() {
      var term = this.value.trim();
      if (!term) { showDashboard(); return; }
      showSearch();
      fetch(searchUnifiedUrl + '?q=' + encodeURIComponent(term), {
        headers: { 'X-CSRFToken': CSRF }
      })
        .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function(data) { renderSearchResults(data); })
        .catch(function(err) { console.error('Search error:', err); });
    }, 300));
  }

  /* ── Unified search results renderer ── */
  function renderSearchResults(data) {
    /* Clear via DOM ops rather than innerHTML='' for safety */
    while (searchGroupsGrid && searchGroupsGrid.firstChild) searchGroupsGrid.removeChild(searchGroupsGrid.firstChild);
    if (searchGroupsEmpty) searchGroupsEmpty.hidden = true;

    if (data.rooms && data.rooms.length) {
      data.rooms.forEach(function(room) {
        var li = document.createElement('li');
        var a  = document.createElement('a');
        a.href      = roomDetailUrlTemplate.replace('/0/', '/' + encodeURIComponent(room.id) + '/');
        a.className = 'room-item';
        var img = document.createElement('img');
        img.src = room.room_picture_url;
        img.alt = room.name;
        img.className = 'room-item__img';
        var details = document.createElement('div');
        details.className = 'room-item__details';
        var nameSpan = document.createElement('span');
        nameSpan.className   = 'room-item__name';
        nameSpan.textContent = room.name;
        details.appendChild(nameSpan);
        a.appendChild(img); a.appendChild(details);
        li.appendChild(a);
        searchGroupsGrid.appendChild(li);
      });
    } else if (searchGroupsEmpty) {
      searchGroupsEmpty.hidden = false;
    }

    while (searchUsersGrid && searchUsersGrid.firstChild) searchUsersGrid.removeChild(searchUsersGrid.firstChild);
    if (searchUsersEmpty) searchUsersEmpty.hidden = true;

    if (data.users && data.users.length) {
      data.users.forEach(function(user) { renderSearchUserCard(user); });
    } else if (searchUsersEmpty) {
      searchUsersEmpty.hidden = false;
    }
  }

  function renderSearchUserCard(user) {
    var row = document.createElement('div');
    row.className        = 'search-user-row';
    row.dataset.userId   = user.id;
    row.dataset.username = user.username;

    var avatarWrap = document.createElement('a');
    avatarWrap.href      = profileUrlTemplate.replace('USERNAME', encodeURIComponent(user.username));
    avatarWrap.className = 'search-user-row__identity';

    var img = document.createElement('img');
    img.src       = user.avatar;
    img.alt       = user.username;
    img.className = 'search-user-row__avatar';

    var nameSpan = document.createElement('span');
    nameSpan.className   = 'search-user-row__name';
    nameSpan.textContent = user.username;

    avatarWrap.appendChild(img);
    avatarWrap.appendChild(nameSpan);
    row.appendChild(avatarWrap);
    row.appendChild(buildUserActionBtn(user));

    searchUsersGrid.appendChild(row);
  }

  function buildUserActionBtn(user) {
    var btn = document.createElement('button');
    btn.className = 'search-user-btn';

    if (user.is_friend) {
      btn.textContent = 'Friends';
      btn.className  += ' search-user-btn--info';
      btn.disabled    = true;
    } else if (user.has_pending_outgoing_request) {
      btn.textContent = 'Pending';
      btn.className  += ' search-user-btn--muted';
      btn.disabled    = true;
    } else if (user.has_pending_incoming_request) {
      btn.textContent = 'Accept';
      btn.className  += ' search-user-btn--primary';
      btn.addEventListener('click', function() {
        showDashboard();
        var section = document.getElementById('pending-requests-section');
        if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    } else {
      btn.textContent = 'Add friend';
      btn.className  += ' search-user-btn--primary';
      btn.addEventListener('click', function() {
        btn.disabled    = true;
        btn.textContent = '…';
        var url = friendAddUrlTemplate.replace('USERNAME', encodeURIComponent(user.username));
        fetch(url, { method: 'POST', headers: xhrHeaders() })
          .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function() {
            btn.textContent = 'Pending';
            btn.className   = btn.className.replace('search-user-btn--primary', 'search-user-btn--muted');
            btn.disabled    = true;
          })
          .catch(function(err) {
            console.error('Add friend error:', err);
            btn.disabled    = false;
            btn.textContent = 'Add friend';
          });
      });
    }
    return btn;
  }

  /* ── Pending request card + delegated accept/reject handler ── */
  function buildRequestCard(req) {
    var card = document.createElement('div');
    card.className           = 'request-card';
    card.dataset.requestId   = req.request_id;

    var img = document.createElement('img');
    img.src       = req.sender_avatar;
    img.alt       = req.sender_username;
    img.className = 'request-card__avatar';

    var nameSpan = document.createElement('span');
    nameSpan.className   = 'request-card__name';
    nameSpan.textContent = req.sender_username;

    var actions = document.createElement('div');
    actions.className = 'request-card__actions';

    var acceptBtn = document.createElement('button');
    acceptBtn.className            = 'btn btn-primary btn-sm';
    acceptBtn.dataset.action       = 'accept';
    acceptBtn.dataset.requestId    = req.request_id;
    acceptBtn.textContent          = 'Accept';

    var rejectBtn = document.createElement('button');
    rejectBtn.className            = 'btn btn-ghost btn-sm';
    rejectBtn.dataset.action       = 'reject';
    rejectBtn.dataset.requestId    = req.request_id;
    rejectBtn.textContent          = 'Reject';

    actions.appendChild(acceptBtn);
    actions.appendChild(rejectBtn);
    card.appendChild(img);
    card.appendChild(nameSpan);
    card.appendChild(actions);
    return card;
  }

  if (requestsList) {
    requestsList.addEventListener('click', function(e) {
      var btn = e.target.closest('[data-action]');
      if (!btn) return;
      var action    = btn.dataset.action;
      var requestId = btn.dataset.requestId;
      var card      = btn.closest('.request-card');
      if (!requestId || !card) return;

      var url;
      if (action === 'accept') {
        url = friendAcceptUrlTemplate.replace('/0/', '/' + encodeURIComponent(requestId) + '/');
        fetch(url, { method: 'POST', headers: xhrHeaders() })
          .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function(data) {
            card.remove();
            decrementCount(requestsCount);
            checkRequestsSectionEmpty();
            if (data.new_friend) {
              appendFriendCard(data.new_friend);
              /* appendFriendToSidebar is exposed on window by hub-shell.js */
              if (typeof window.appendFriendToSidebar === 'function') {
                window.appendFriendToSidebar(data.new_friend);
              }
              incrementCount(friendsCount);
            }
          })
          .catch(function(err) { console.error('Accept error:', err); });

      } else if (action === 'reject') {
        url = friendRejectUrlTemplate.replace('/0/', '/' + encodeURIComponent(requestId) + '/');
        fetch(url, { method: 'POST', headers: xhrHeaders() })
          .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function() {
            card.remove();
            decrementCount(requestsCount);
            checkRequestsSectionEmpty();
          })
          .catch(function(err) { console.error('Reject error:', err); });
      }
    });
  }

  function checkRequestsSectionEmpty() {
    if (requestsList && requestsList.children.length === 0 && requestsSection) {
      requestsSection.hidden = true;
    }
  }

  function decrementCount(el) {
    if (!el) return;
    var n = parseInt(el.textContent, 10);
    if (!isNaN(n) && n > 0) el.textContent = String(n - 1);
  }

  function incrementCount(el) {
    if (!el) return;
    var n = parseInt(el.textContent, 10);
    if (!isNaN(n)) el.textContent = String(n + 1);
  }

  function appendFriendCard(friend) {
    if (!friendsGrid) return;
    var placeholder = friendsGrid.querySelector('p');
    if (placeholder) placeholder.remove();

    var card = document.createElement('a');
    card.href      = profileUrlTemplate.replace('USERNAME', encodeURIComponent(friend.username));
    card.className = 'friend-card';
    var img = document.createElement('img');
    img.src = friend.avatar || '';
    img.alt = friend.username;
    var nameSpan = document.createElement('span');
    nameSpan.className   = 'friend-card__name';
    nameSpan.textContent = friend.username;
    card.appendChild(img);
    card.appendChild(nameSpan);
    friendsGrid.appendChild(card);
  }

  /* ── Dashboard data load ── */
  window.addEventListener('DOMContentLoaded', function() {
    if (!chatInfoUrl) return;
    fetch(chatInfoUrl, { headers: { 'X-CSRFToken': CSRF } })
      .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function(data) {
        /* Pending requests */
        if (data.pending_requests && data.pending_requests.length > 0) {
          if (requestsSection) requestsSection.hidden = false;
          data.pending_requests.forEach(function(req) {
            if (requestsList) requestsList.appendChild(buildRequestCard(req));
          });
        }
        if (requestsCount) requestsCount.textContent = String(data.requests_count || 0);

        /* Friends */
        if (friendsCount) friendsCount.textContent = String(data.friends.length);
        data.friends.forEach(function(friend) { appendFriendCard(friend); });
        if (!data.friends.length && friendsGrid) {
          var p = document.createElement('p');
          p.style.cssText   = 'padding:var(--s-4);color:var(--text-3);font-size:var(--font-size-sm)';
          p.textContent     = 'No friends yet — search for users to add them';
          friendsGrid.appendChild(p);
        }

        /* Groups */
        if (groupsCount) groupsCount.textContent = String(data.groups_data.length);
        data.groups_data.forEach(function(group) {
          var card = document.createElement('a');
          card.href      = '#';
          card.className = 'friend-card';
          var img = document.createElement('img');
          img.src = group.avatar;
          img.alt = group.name;
          var nameSpan = document.createElement('span');
          nameSpan.className   = 'friend-card__name';
          nameSpan.textContent = group.name;
          card.appendChild(img);
          card.appendChild(nameSpan);
          if (groupsGrid) groupsGrid.appendChild(card);
        });
        if (!data.groups_data.length && groupsGrid) {
          var p2 = document.createElement('p');
          p2.style.cssText   = 'padding:var(--s-4);color:var(--text-3);font-size:var(--font-size-sm)';
          p2.textContent     = 'No groups yet';
          groupsGrid.appendChild(p2);
        }
      })
      .catch(function(err) { console.error('Dashboard load error:', err); });
  });

}());
