/**
 * room-membership.js
 * Manages room membership (add on enter, remove on leave) for the chat room page.
 *
 * Reads context from data-* attributes on #room-membership-data (injected by
 * the template — no inline JS required, fully CSP-compliant):
 *   data-add-member-url    — URL for add_member_to_room
 *   data-remove-member-url — URL for remove_member_from_room
 *   data-csrf-token        — CSRF token value
 */
(function() {
  'use strict';

  var dataEl = document.getElementById('room-membership-data');
  if (!dataEl) return;

  var ctx = {
    addMemberUrl:    dataEl.getAttribute('data-add-member-url'),
    removeMemberUrl: dataEl.getAttribute('data-remove-member-url'),
    csrfToken:       dataEl.getAttribute('data-csrf-token'),
  };
  if (!ctx.addMemberUrl || !ctx.removeMemberUrl) return;

  var membersFetched = false;

  function updateMembersCount(count) {
    var el = document.getElementById('members-count');
    if (el) el.textContent = count;
  }

  /* Add member on enter */
  if (!membersFetched) {
    membersFetched = true;
    fetch(ctx.addMemberUrl, {
      method: 'POST',
      headers: { 'X-CSRFToken': ctx.csrfToken }
    })
      .then(function(r) { return r.json(); })
      .then(function(data) { updateMembersCount(data.members_count); })
      .catch(function(err) { console.error('Member add error:', err); });
  }

  /* Remove member on leave.
     navigator.sendBeacon does not support custom headers, so it cannot carry
     the X-CSRFToken header required by Django's CSRF middleware. Use fetch
     with keepalive:true instead — same fire-and-forget behaviour, CSRF-safe. */
  window.addEventListener('beforeunload', function() {
    fetch(ctx.removeMemberUrl, {
      method: 'POST',
      headers: { 'X-CSRFToken': ctx.csrfToken },
      keepalive: true
    });
  });
}());
