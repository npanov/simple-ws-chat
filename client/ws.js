var server = 'ws://localhost:8765/';

function zPad(n) {
    if (n < 10) return '0' + n;
    else return n;
}

function timestamp() {
    var d = new Date();
    return zPad(d.getHours()) + ':' + zPad(d.getMinutes()) + ':' + zPad(d.getSeconds());
}

function write_to_mbox(message) {
    var line = '[' + timestamp() + '] ' + message + '<br>';
    $('#messages').append(line);
}

$(document).ready(function() {

    var socket = new WebSocket(server);

    socket.onerror = function(error) {
        console.log('WebSocket Error: ' + error);
    };

    socket.onopen = function(event) {
        write_to_mbox('Connected to: ' + server);
        $('#message').focus();
    };

    socket.onmessage = function(event) {
        write_to_mbox(event.data)
    };

    socket.onclose = function(event) {
        write_to_mbox('Disconnected from ' + server + '(server went away)');
    };

    $('#message-form').submit(function() {
        socket.send($('#message').val());
        $('#message').val('');
        return false;
    });

});