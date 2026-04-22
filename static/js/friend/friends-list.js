(function() {
  'use strict';

  function readJson(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  var profileUrlTemplate = readJson('friends-ctx-profile-url-tpl') || '';
  if (!profileUrlTemplate) return;

  document.querySelectorAll('.view-profile-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var username = this.dataset.username;
      if (!username) return;
      window.location.href = profileUrlTemplate.replace('USERNAME', encodeURIComponent(username));
    });
  });
}());
