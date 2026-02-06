var sc_player = window.sc_player || {};

sc_player.playing_track_id = -1;
sc_player.audio = null;

sc_player.playing = function() {
    return sc_player.playing_track_id != -1;
};

sc_player.play = function(track_id, pos) {
    if (sc_player.playing()) {
        sc_player.stop();
    }
    sc_player.playing_track_id = track_id;
    console.log("Requesting stream for SoundCloud track:", track_id);

    // Request stream URL from server via WebSocket
    socket.emit('get_soundcloud_stream', track_id);
    // Store position to seek to once stream URL arrives
    sc_player._pending_pos = pos || 0;
};

sc_player._play_stream = function(stream_url, pos) {
    if (!stream_url) {
        console.error('No stream URL available');
        sc_player.stop();
        return;
    }

    sc_player.audio = new Audio(stream_url);
    sc_player.audio.currentTime = pos || 0;
    sc_player.audio.play().catch(function(e) {
        console.error('SoundCloud playback error:', e);
    });
};

sc_player.stop = function() {
    if (sc_player.audio) {
        sc_player.audio.pause();
        sc_player.audio = null;
    }
    sc_player.playing_track_id = -1;
    sc_player._pending_pos = 0;
};

sc_player.set_volume = function(vol) {
    if (sc_player.audio) {
        sc_player.audio.volume = vol / 100;
    }
};

// WebSocket handler for stream URL (called when server resolves stream)
socket.on('soundcloud_stream', function(data) {
    if (data.track_id == sc_player.playing_track_id) {
        console.log("Got SoundCloud stream URL for track:", data.track_id);
        sc_player._play_stream(data.stream_url, sc_player._pending_pos);
    }
});

socket.on('soundcloud_stream_error', function(data) {
    console.error('SoundCloud stream error:', data.error);
    if (data.track_id == sc_player.playing_track_id) {
        sc_player.stop();
    }
});
