// chat.js

let roomName = JSON.parse(document.getElementById('json-roomname').textContent);
let userName = JSON.parse(document.getElementById('json-username').textContent);

let chatSocket = new WebSocket(
    'ws://'
    + window.location.host
    + '/ws/'
    + roomName
    + '/'
);

chatSocket.onmessage = function (e) {
    console.log('onmessage');

    let data = JSON.parse(e.data);

    if (data.message) {
        let currentDate = new Date();
        let formattedTimestamp = currentDate.toLocaleString('en-US', { month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: 'numeric', hour12: true });


        let listItem = document.createElement('li');
        listItem.classList.add('clearfix');

        let messageDataDiv = document.createElement('div');
        messageDataDiv.classList.add('message-data', 'align-right');

        let messageDataTimeSpan = document.createElement('span');
        messageDataTimeSpan.classList.add('message-data-time');
        messageDataTimeSpan.textContent = formattedTimestamp;

        let messageDataNameSpan = document.createElement('span');
        messageDataNameSpan.classList.add('message-data-name');
        messageDataNameSpan.textContent = data.username;
        messageDataNameSpan.textContent += ' ';

        let messageDataCircleIcon = document.createElement('i');
        messageDataCircleIcon.classList.add('fa', 'fa-circle', 'me');

        let messageContentDiv = document.createElement('div');
        messageContentDiv.classList.add('message', 'other-message', 'float-right');
        messageContentDiv.textContent = data.message;

        messageDataDiv.appendChild(messageDataTimeSpan);
        messageDataDiv.appendChild(document.createTextNode('\u00A0\u00A0'));
        messageDataDiv.appendChild(messageDataNameSpan);
        messageDataDiv.appendChild(messageDataCircleIcon);

        listItem.appendChild(messageDataDiv);
        listItem.appendChild(messageContentDiv);

        let chatHistory = document.querySelector('.chat-history ul');
        chatHistory.appendChild(listItem);
        scrollToBottom();
        console.log('done');
    } else {
        alert('The message was empty!');
    }
};

chatSocket.onclose = function (e) {
    console.log('onclose');
};

document.querySelector('#chat-message-submit').onclick = function (e) {
    e.preventDefault();

    let messageInputDom = document.querySelector('#message-to-send');
    let message = messageInputDom.value;
    console.log({
        'message': message,
        'username': userName,
        'room': roomName
    });

    chatSocket.send(JSON.stringify({
        'message': message,
        'username': userName,
        'room': roomName
    }));

    messageInputDom.value = '';

    return false;
};

function scrollToBottom() {
    let chatHistory = document.querySelector('.chat-history');
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

scrollToBottom();
