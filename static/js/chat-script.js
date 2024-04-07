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

    let messageSender = data.username;
    let currentUser = userName; // Assuming userName holds the current user's username

    if (data.message) {
        let currentDate = new Date();
        let formattedTimestamp = currentDate.toLocaleString('en-US', { month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: 'numeric', hour12: true });

        let listItem = document.createElement('li');

        if (messageSender === currentUser) {
            listItem.classList.add('clearfix');
            listItem.innerHTML = `
                <div class="message-data align-right">
                    <span class="message-data-time">${formattedTimestamp}</span>&nbsp;&nbsp;
                    <span class="message-data-name">${messageSender}  </span><i class="fa fa-circle me"></i>
                </div>
                <div class="message other-message float-right">${data.message}</div>`;
        } else {
            listItem.innerHTML = `
                <div class="message-data">
                    <span class="message-data-name"><i class="fa fa-circle online"></i>${messageSender}</span>
                    <span class="message-data-time">${formattedTimestamp}</span>
                </div>
                <div class="message my-message">${data.message}</div>`;
        }

        let chatHistory = document.querySelector('.chat-history ul');
        chatHistory.appendChild(listItem);
        scrollToBottom();
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
