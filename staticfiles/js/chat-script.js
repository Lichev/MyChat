// chat-script.js — WebSocket handler for MyChat room view

const roomName = JSON.parse(document.getElementById('json-roomname').textContent);
const userName = JSON.parse(document.getElementById('json-username').textContent);

const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const chatSocket = new WebSocket(
  wsProtocol + '//' + window.location.host + '/ws/' + roomName + '/'
);

// Safely escape HTML to prevent XSS when rendering user-generated content.
function escapeHtml(str) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(String(str)));
  return div.innerHTML;
}

function formatTimestamp(isoString) {
  const date = isoString ? new Date(isoString) : new Date();
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true
  });
}

function buildMessageRow(message, sender, isOwn, isoTimestamp, avatarUrl) {
  const ts  = formatTimestamp(isoTimestamp);
  const row = document.createElement('div');
  row.className = 'msg-row ' + (isOwn ? 'msg-row--outgoing' : 'msg-row--incoming');

  // Use textContent for user data — never innerHTML with user input
  const content     = document.createElement('div');
  content.className = 'msg-content';

  const meta      = document.createElement('div');
  meta.className  = 'msg-meta';

  const nameSpan  = document.createElement('span');
  nameSpan.className = 'msg-name';
  nameSpan.textContent = isOwn ? 'You' : sender;   // safe assignment

  const timeSpan  = document.createElement('span');
  timeSpan.textContent = ts;

  if (isOwn) {
    meta.appendChild(nameSpan);
    meta.appendChild(timeSpan);
  } else {
    meta.appendChild(nameSpan);
    meta.appendChild(timeSpan);
  }

  const bubble      = document.createElement('div');
  bubble.className  = 'msg-bubble ' + (isOwn ? 'msg-bubble--outgoing' : 'msg-bubble--incoming');
  bubble.textContent = message;   // textContent prevents XSS

  content.appendChild(meta);
  content.appendChild(bubble);

  let placeholder;
  if (avatarUrl) {
    placeholder = document.createElement('img');
    placeholder.src = avatarUrl;
    placeholder.alt = isOwn ? 'Your avatar' : sender;
    placeholder.className = 'msg-avatar';
    placeholder.width = 32;
    placeholder.height = 32;
  } else {
    placeholder = document.createElement('span');
    placeholder.className = 'msg-avatar--placeholder';
    placeholder.setAttribute('aria-hidden', 'true');
  }

  if (isOwn) {
    row.appendChild(content);
    row.appendChild(placeholder);
  } else {
    row.appendChild(placeholder);
    row.appendChild(content);
  }

  return row;
}

chatSocket.onmessage = function(e) {
  let data;
  try {
    data = JSON.parse(e.data);
  } catch (err) {
    console.error('WebSocket message parse error:', err);
    return;
  }

  if (!data.message) {
    return;
  }

  const chatMessages = document.getElementById('chatMessages');
  if (!chatMessages) return;

  const isOwn = data.username === userName;
  const row   = buildMessageRow(data.message, data.username, isOwn, data.timestamp, data.sender_avatar);
  chatMessages.appendChild(row);
  scrollToBottom();
};

chatSocket.onclose = function() {
  // WebSocket closed — could trigger a reconnect UI
};

chatSocket.onerror = function(err) {
  console.error('WebSocket error:', err);
};

/* Send on form submit (button click or Enter key) */
const form         = document.getElementById('chatForm');
const messageInput = document.getElementById('message-to-send');

function sendMessage() {
  if (!messageInput) return;
  const message = messageInput.value.trim();
  if (!message) return;

  chatSocket.send(JSON.stringify({
    message: message,
    username: userName,
    room: roomName
  }));

  messageInput.value = '';
  messageInput.focus();
}

// Form submit handles both button click and Enter key in the text input.
// A separate keydown listener for Enter is intentionally omitted — it would
// double-fire with the submit event in some browsers, sending the message twice.
if (form) {
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    sendMessage();
  });
}

function scrollToBottom() {
  const chatMessages = document.getElementById('chatMessages');
  if (chatMessages) {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }
}

scrollToBottom();
