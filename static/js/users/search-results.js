(function() {
  'use strict';

  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  var CSRF               = readJson('users-search-ctx-csrf') || '';
  var profileUrlTpl      = readJson('users-search-ctx-profile-url-tpl') || '';
  var friendAddUrlTpl    = readJson('users-search-ctx-friend-add-url-tpl') || '';
  var friendCancelUrlTpl = readJson('users-search-ctx-friend-cancel-url-tpl') || '';
  var friendAcceptUrlTpl = readJson('users-search-ctx-friend-accept-url-tpl') || '';

  function reloadPage() { window.location.reload(); }

  function postAndReload(url) {
    if (!url) return;
    fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': CSRF, 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(reloadPage)
      .catch(function(err) { console.error('Friend action failed:', err); });
  }

  /* View profile — navigate to public profile URL */
  document.querySelectorAll('.view-profile-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var username = this.dataset.username;
      if (!username || !profileUrlTpl) return;
      window.location.href = profileUrlTpl.replace('USERNAME', encodeURIComponent(username));
    });
  });

  /* Add friend — POST to friendship_add_friend, then reload */
  document.querySelectorAll('.sendFriendRequest').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var username = this.dataset.username;
      if (!username || !friendAddUrlTpl) return;
      postAndReload(friendAddUrlTpl.replace('USERNAME', encodeURIComponent(username)));
    });
  });

  /* Cancel pending outgoing request — POST to friendship_cancel, then reload */
  document.querySelectorAll('.cancelFriendRequest').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var id = this.dataset.requestId;
      if (!id || !friendCancelUrlTpl) return;
      postAndReload(friendCancelUrlTpl.replace('PLACEHOLDER', encodeURIComponent(id)));
    });
  });

  /* Accept incoming request — POST to friendship_accept, then reload */
  document.querySelectorAll('.acceptFriendRequest').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var id = this.dataset.requestId;
      if (!id || !friendAcceptUrlTpl) return;
      postAndReload(friendAcceptUrlTpl.replace('PLACEHOLDER', encodeURIComponent(id)));
    });
  });
}());
