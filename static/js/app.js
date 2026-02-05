// app.js

// Color themes for the UI
var COLOR_THEMES = [
    { name: 'Spotify Green', accent: '#1ed760', accentRgb: '30, 215, 96', hover: '#6bfc61', hoverRgb: '107, 252, 97' },
    { name: 'Purple', accent: '#b366ff', accentRgb: '179, 102, 255', hover: '#cc99ff', hoverRgb: '204, 153, 255' },
    { name: 'Blue', accent: '#1db4d4', accentRgb: '29, 180, 212', hover: '#5dd3e8', hoverRgb: '93, 211, 232' },
    { name: 'Pink', accent: '#ff66b2', accentRgb: '255, 102, 178', hover: '#ff99cc', hoverRgb: '255, 153, 204' },
    { name: 'Orange', accent: '#ff9933', accentRgb: '255, 153, 51', hover: '#ffb366', hoverRgb: '255, 179, 102' },
    { name: 'Red', accent: '#ff4d4d', accentRgb: '255, 77, 77', hover: '#ff8080', hoverRgb: '255, 128, 128' },
    { name: 'Gold', accent: '#ffd700', accentRgb: '255, 215, 0', hover: '#ffe44d', hoverRgb: '255, 228, 77' },
    { name: 'Cyan', accent: '#00ffff', accentRgb: '0, 255, 255', hover: '#66ffff', hoverRgb: '102, 255, 255' },
    { name: 'White', accent: '#ffffff', accentRgb: '255, 255, 255', hover: '#e0e0e0', hoverRgb: '224, 224, 224' },
];
var currentColorIndex = 0;

function changeColors() {
    currentColorIndex = (currentColorIndex + 1) % COLOR_THEMES.length;
    var theme = COLOR_THEMES[currentColorIndex];
    document.documentElement.style.setProperty('--accent-color', theme.accent);
    document.documentElement.style.setProperty('--accent-color-rgb', theme.accentRgb);
    document.documentElement.style.setProperty('--accent-hover', theme.hover);
    document.documentElement.style.setProperty('--accent-hover-rgb', theme.hoverRgb);
    // Save preference
    try {
        localStorage.setItem('andre-color-theme', currentColorIndex);
    } catch(e) {}
}

function loadSavedColorTheme() {
    try {
        var saved = localStorage.getItem('andre-color-theme');
        if (saved !== null) {
            currentColorIndex = parseInt(saved, 10);
            if (currentColorIndex >= 0 && currentColorIndex < COLOR_THEMES.length) {
                var theme = COLOR_THEMES[currentColorIndex];
                document.documentElement.style.setProperty('--accent-color', theme.accent);
                document.documentElement.style.setProperty('--accent-color-rgb', theme.accentRgb);
                document.documentElement.style.setProperty('--accent-hover', theme.hover);
                document.documentElement.style.setProperty('--accent-hover-rgb', theme.hoverRgb);
            }
        }
    } catch(e) {}
}

function is_hohoholiday(){
    var now = new Date();
    return now.getMonth() == 11 &&
            now.getDate() > 16 &&
            now.getDate() < 26;
}

function is_world_cup(){
    var now = new Date();
    return now.getFullYear() == 2014 &&
            ((now.getMonth() == 5 && now.getDate() >= 12) ||
             (now.getMonth() == 6 && now.getDate() <= 13))
}

function is_roshhashanah(){
    var now = new Date();
    return now.getFullYear() == 2017 &&
        now.getMonth() == 8 &&
        now.getDate() > 19 &&
        now.getDate() < 23;
}

var Socket = function(url){

    _.extend(this,{events:{}, url:url, msg_queue:[]});
    this.reconnect = _.throttle(this.reconnect, 1000);
    _.bindAll(this, 'emit', 'reconnect');
    this.reconnect()
    this.schedule_timeout();
    return this;
};

_.extend(Socket.prototype, {
    schedule_timeout: function(){
        if(this._tid){
            clearTimeout(this._tid);
        }
        var that=this;
        this._tid = setTimeout(function(){that._heartbeat()}, 2000);
    },
    on: function(ev, callback){
        if(this.events[ev]){
            this.events[ev].push(callback);
        }else{
            this.events[ev] = [callback];
        }
    },
    emit: function(){
        if(!this._s || this._s.readyState != 1){
            this.msg_queue.push(_.toArray(arguments));
            return;
        }
        var that = this,
            msg = '1'+JSON.stringify(_.toArray(arguments));
        setTimeout(function(){
            that.schedule_timeout();
            that._s.send(msg);
        }, 0);
    },
    _heartbeat: function(){
        this.schedule_timeout();
        if(!this._s || this._s.readyState != 1){
            return;
        }
        this._s.send("0");
        this._tid = null;
    },
    reconnect: function(){
        this._s = new WebSocket(this.url);
        var that = this;
        _.each(this.socket_callbacks, function(v, k){
                that._s[k] = _.bind(v, that);
            });
    },
    socket_callbacks: {
        onmessage: function(ev){
            var T = ev.data[0];
            if(T == '0'){
                return;
            }
            if(T == '1'){
                args = JSON.parse(ev.data.substr(1));
                name = args.shift()
                if(this.events[name]){
                    for(var i=0;i<this.events[name].length;++i){
                        this.events[name][i].apply(window, args);
                    }
                }
                return;
            }
        },
        onopen: function(ev){
            while(this.msg_queue.length > 0){
                var args = this.msg_queue.shift();
                this.emit.apply(this, args);
            }
        },
        onerror: function(ev){
            //console.log('onerror', ev);
        },
        onclose: function(ev){
            this.reconnect();
        },
    },
});

console.log(location.hostname);
let proto = 'wss';
if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
    proto = 'ws';
}
socket = new Socket(proto + '://'+location.host+'/socket/');

var Song = Backbone.Model.extend({
});

var Playlist = Backbone.Collection.extend({
    model: Song
});

var PlaylistView = Backbone.View.extend({
    initialize: function(){
        this.listenTo(this.collection, "all", this.render);
    },
    render: function(){
        var that = this;
        this.$el.empty();
        this.collection.each(function(obj){
            if(obj.get("playlist_src")){
                var psv = new PlaylistSrcView({model:obj});
            }else{
                var psv = new PlaylistSongView({model:obj});
            }
            that.$el.append(psv.render());
        });
        _window_resize();
        return this.$el;
    }
});


function addCommentsClickHandlers () {
  $('body').on('click', '.comment-button', function (evt) {
    evt.stopPropagation();
    var $commentButton = $(evt.currentTarget);
    var songID = $commentButton.attr('data-song-id');
    var inNowPlaying = $commentButton.attr('data-in-now-playing');
    var songModel = getSongModelByID(songID);
    var formattedComments = getFormattedCommentsForSongModel(songModel); 

    var inputClasses = [];

    var placement = 'left';
    if (inNowPlaying) {
      placement = 'bottom';
      inputClasses.push('hidden');
    }

    $commentButton.popover({
      html: true,
      content: TEMPLATES.comments_popover({
        comments: formattedComments,
        songID: songID,
        inputClasses: inputClasses.join(' '),
      }),
      placement: placement,
      trigger: 'manual',
      container: 'body',
    });

    $commentButton.popover('show');
  });

  $('body').on('click', function (e) {
    //did not click a popover toggle or popover
    if ($(e.target).data('toggle') !== 'popover'
        && $(e.target).parents('.popover.in').length === 0) { 
          removeAllPopovers();
        }
  });

}

function removeAllPopovers () {
  $('.popover.in').remove();
}

function getSongModelByID (songID) {
  if (now_playing.id === songID) {
    return now_playing;
  }
  return playlist.get(songID);
}

function getFormattedCommentsForSongModel (songModel) {
  var formattedComments = [];
  _.each(songModel.get('comments'), function(rawComment) {
    var date = new Date(0);
    date.setUTCSeconds(rawComment.time/1000);
    var formattedTime = addZero(date.getHours()) + ':' + addZero(date.getSeconds());

    var formattedComment = {
      body: rawComment.body,
      user: rawComment.user,
      time: formattedTime,
    };
    formattedComments.push(formattedComment);
  });
  return formattedComments;
}

function addZero(i) {
  if (i < 10) {
    i = "0" + i;
  }
  return i;
}

function addCommentInputKeyPressHandler () {
  $('body').on('click', '.comment-input', function (evt) {
    var $commentInput = $(evt.currentTarget);
    $commentInput.on('keypress', function(evt) {
      if (evt.keyCode === 13) {
        evt.stopPropagation();
        var comment = $commentInput.val();
        var songID = $commentInput.attr('data-song-id');
        postComment(songID, comment);
        removeAllPopovers();
      }
    });
  });
}

function postComment (songID, comment) {
  socket.emit('add_comment', songID, user, comment);
}

var VOTED = {};

var PlaylistSongView = Backbone.View.extend({
    tagName: 'div',
    events: {
        'click .vote-up':'vote_up',
        'click .vote-down':'vote_down',
        'click .kill':'kill_song',
        'click .jam':'jam_song',
    },
    jam_song: function(){
        socket.emit('jam', this.model.id);
    },
    kill_song: function(){
        if(this.model.get("user") === user){
            socket.emit("kill", this.model.id);
            return;
        }
        var msg = 'Are you sure you want to remove "'+this.model.get("title")+'" from the queue?',
            id = this.model.id;
        confirm_dialog(msg, function(){
            socket.emit('kill', id);
        });
    },
    vote_up: function(){
        socket.emit('vote', this.model.id, true);
        VOTED[this.model.id] = true;
        this.render();
    },
    vote_down: function(){
        socket.emit('vote', this.model.id, false);
    if (this.model.get("user") != user) {
          VOTED[this.model.id] = true;
    }
        this.render();
    },
    render: function(){
        this.$el.html(TEMPLATES.playlist_item(this.model.toJSON()));
        return this.$el;
    },
});

var PlaylistSrcView = Backbone.View.extend({
    tagName: 'div',
    className: 'playlist-src-item',
    events: {'click .queue': 'queue',
         'click .spotify-uri': 'spot_uri',
         'click .bender-filter': 'filter',
         'click .dm-join' : 'dm_join',
         'click .dm-leave' : 'dm_leave'
    },
    spot_uri: function() {
        console.log("spotify-uri")
        var id = this.model.get('trackid');
        window.open(id);
    },
    queue: function() {
        var id = this.model.get('trackid');
        socket.emit('benderQueue', id);
    },
    filter: function() {
        var id = this.model.get('trackid');
        socket.emit('benderFilter', id);
    },
    dm_join: function() {
    window.open("/joinleave_dm");
    },
    dm_leave: function() {
    socket.emit('dm_leave');
    },
    // kill_playlist: function(){
    //     socket.emit('kill_src');
    // },
    // change_playlist: function(){
    //     var input = prompt("Which playlist do you want?");
    //     if(input.trim().length < 4){
    //         return;
    //     }
    //     $('#left-col-menu [data-id=add-song]').click();
    //     if(input.search('http:') == 0){
    //         rdio_url(input).then(function(data){
    //             if(data.type !== 'p'){
    //                 return;
    //             }
    //             $('#search-results').empty()
    //                 .append(TEMPLATES.search_result_playlist(data));
    //         });
    //         return;
    //     }
    //     rdio_search(input, ["Playlists"]).then(function(data){
    //         var $target = $('#search-results');
    //         $target.empty();
    //         for(var i=0;i<data.results.length;++i){
    //             $target.append(TEMPLATES.search_result_playlist(data.results[i]));
    //         }
    //     });
    // },
    render: function(){
        this.$el.html(TEMPLATES.playlist_source(this.model.toJSON()));
        return this.$el;
    }
});

var NowPlayingView = Backbone.View.extend({
    events: {
        'click .jam': 'jam',
        'click .ytube': 'ytube',
        'click .spot': 'spot',
        'click .cloud': 'cloud',
    },
    initialize: function(){
        this.listenTo(this.model, 'all', this.render);
    },
    ytube: function(){
        var id = this.model.get('trackid');
        window.open('http://www.youtube.com/watch?v='+id, '_blank')
    },
    cloud: function(){
        var id = this.model.get('trackid');
        // get the SC URL from the trackID
        api_url = 'http://api.soundcloud.com/tracks/'+id+'.json?client_id=8267fd360bf3864e78a43456a6b26d74';

        $.ajax({url:api_url,
                    dataType:'json',
                    data:{}
                }).then(function(data){ window.open( data.permalink_url,'_blank');});
    },
    jam: function(){
        socket.emit('jam', this.model.id);
    },
    spot: function(){
        var id = this.model.get('trackid');
        window.open(id);
    },
    render: function(){
        // Handle paused state
        if (playerpaused) {
            // Render paused content (intentionally omits #playing-buttons and comment button)
            this.$el.html(
                '<div id="now-playing-person" style="background-image:url(/static/theechonestcom.png);"></div>' +
                '<div id="now-playing-text">' +
                    '<h1>PAUSED</h1>' +
                    '<h2>"Bite my shiny metal pause button!"</h2>' +
                '</div>' +
                '<div id="now-playing-jammers"></div>'
            );

            // Show current song's album art with pause overlay
            if (this.model && this.model.get('big_img')) {
                $('#now-playing-album').css('background-image', 'url(' + this.model.get('big_img') + ')');
            } else {
                $('#now-playing-album').css('background-image', '');
            }

            $('#now-playing-album').addClass('paused');
            this.$el.removeClass("autoplay");
            _window_resize();
            return this.$el;
        }

        // Normal render when not paused
        if(!this.model || !this.model.get("title")){
            return;
        }
        this.$el.html(TEMPLATES.now_playing(this.model.toJSON()));
        $('#now-playing-album').css('background-image',
                                    'url('+this.model.get("big_img")+')')
        $('#now-playing-album').removeClass('paused');
        this.$el.css({'background-color':
                        '#'+this.model.get("background_color"),
                        'color':'#'+this.model.get('foreground_color')});
        this.$el.toggleClass("autoplay", this.model.get("auto"))
        _window_resize();
        return this.$el;
    }
});

var playlist = new Playlist();
var now_playing = new Song();

Date.prototype.timeNow = function(){
  var hours = this.getHours() == 0 ? '12' : (this.getHours() < 13) ? this.getHours() : this.getHours() - 12;
  var minutes = this.getMinutes() == 0 ? '00' : ((this.getMinutes() < 10 ? "0" : "") + this.getMinutes())
  return hours + ":" + minutes + " " + (this.getHours() >= 12 ? "PM" : "AM");
};

function update_playlist(data) {
    // calc ETA times before we render
    var start = new Date();

    if (!isNaN(remaining) && remaining > 0) {
      start.setTime(start.getTime() + remaining*1000);
    } else {
      // on first load, update_playlist will happen before we have
      // a player position. so, we setTimeout and then update clocks
      // again. it's a little hinky and I'm not crazy about the way
      // it looks when there's a song transition
      setTimeout(update_playlist, 1000, data);
      remaining = -1;
    } 

    for (var i = 0; i < data.length; i++) {
      obj = data[i];
      obj.eta = remaining > 0 ? start.timeNow() : '--:--';
      start.setTime(start.getTime() + obj.duration*1000)
    }
    playlist.reset(data);
}

socket.on('playlist_update', function(data){
    console.log("playlist_update", data);
    update_playlist(data);
});

function update_comments_for_song (songID, comments) {
  var songModel = playlist.get(songID);
  songModel.set('comments', comments);
}

socket.on('comments_for_song', function(songID, comments){
  update_comments_for_song(songID, comments);
});

SHOW_NOTIFICATIONS = false;
PLAYING_SRC = null;


var volume = 100;
var yt_volume_adjust = 0.75;

var params = { autoplay: 1, controls: 0, enablejsapi: 1, rel: 0 };

var ytready = false;
Y = null;

function onYouTubeIframeAPIReady(){
    Y = new YT.Player("ytapiplayer", {
          height: '400',
          width: '400',
          // videoId: videoID,
          playerVars: params,
          events: {
            'onError': onYTError,
            // 'onReady': onYTPlayerReady(pos),
          },
        });
    ytready = true;

    if(!is_player) {
        $('#make-player').text("sync spotify");
    }
}

function onYTError(event) {
    console.log("YT error: " + event.data);
}

function onYTPlayerReady(pos) {
    console.log(pos);
    return function(event) {
        event.target.seekTo(pos);
        event.target.setVolume(volume * yt_volume_adjust);
        event.target.playVideo();
    }
}

function fix_player(src, id, pos, paused){
    console.log(src, id, pos, paused);
    if (typeof(id) === 'undefined') { return; } // nobody handles this well
    if (paused) {
        sc_player.stop();
        if (ytready) {
            Y.stopVideo();
        }
        spotify_stop();
        return;
    }
    if(src != PLAYING_SRC){
        PLAYING_SRC = src;
        if (src == 'youtube'){
            sc_player.stop();
            spotify_stop();
        } else if(src == 'spotify'){
            if (ytready) {
                Y.stopVideo();
            }
            sc_player.stop();
        } else if(src == 'soundcloud'){
            if (ytready) {
                Y.stopVideo();
            }
            spotify_stop();
        }
    }

    // For Spotify: only sync once per track to avoid choppy audio
    // Track the last synced track ID to prevent repeated sync calls
    if (src == 'spotify') {
      $('#ytapiplayer').data('youtube_hidden', 'true');
      $('#ytapiplayer').css('z-index', '900');

      // Only sync if this is a new track we haven't synced to yet
      if (last_synced_spotify_track != id) {
        last_synced_spotify_track = id;
        console.log("Syncing to Spotify track:", id, "at position:", pos);
        spotify_play(id, pos);
        spotify_volume(volume);
      }
    }
    if (src == 'soundcloud'){
      var playing = sc_player.playing_track_id;
      if (!playing || playing != id) {
        // make sure to hide YT player
        $('#ytapiplayer').data('youtube_hidden', 'true');
        $('#ytapiplayer').css('z-index', '900');
        sc_player.play(id, pos);
        sc_player.set_volume(volume);
      }
    } else if (src == 'youtube'){
        if (ytready) {
            var playing = Y.getVideoUrl().match(/v=.*?($|&)/);
            playing = playing?playing[0].split('=').pop():playing;
            var playstate = Y.getPlayerState();
            if (playstate != -1 && playstate != 1 && playstate != 3){
                playing = null;
            }
            if(!playing || playing != id){
                $('#ytapiplayer').data('youtube_hidden', 'false');
                $('#ytapiplayer').css('z-index', '1100');
                Y.loadVideoById(id, pos);
                Y.setVolume(volume * yt_volume_adjust);
            }
        }
    }
}


function spotify_play(id, pos, retries=5) {
    // Use position_ms in the play request to start at the correct position
    // This works better than a separate seek call, especially for podcasts
    var playData = {
        "uris": [id]
    };

    // Only set position if we have a valid position > 0
    if (pos && pos > 0) {
        playData.position_ms = pos * 1000;
    }

    $.ajax('https://api.spotify.com/v1/me/player/play', {
        method: 'PUT',
        headers: {
            Authorization: "Bearer " + auth_token
        },
        contentType: 'application/json',
        data: JSON.stringify(playData)
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error("spotify_play error:", textStatus, errorThrown);
        // If play fails and we have retries, try again after a short delay
        if (retries > 0) {
            setTimeout(function() {
                spotify_play(id, pos, retries - 1);
            }, 1000);
        }
    });
}

// Helper to resume Spotify playback with guards
function resume_spotify_if_needed() {
    // Only resume if: we have a token, we're the player, not paused, and source is Spotify
    if (!auth_token || !is_player || playerpaused) {
        return;
    }
    var src = now_playing.get('src');
    if (src !== 'spotify') {
        return;
    }
    $.ajax('https://api.spotify.com/v1/me/player/play', {
        method: 'PUT',
        headers: {
            Authorization: "Bearer " + auth_token
        }
    });
}

search_token = null;
search_token_clear = 0;
socket.on('search_token_update', function(data){
    console.log("got a search token! assigning");
    search_token = data['token'];
    clearTimeout(search_token_clear);
    search_token_clear = setTimeout(function() { 
        search_token = null;
        search_token_clear = 0;
        socket.emit('fetch_search_token');
    }, data['time_left']*1000 + 5);
});

var auth_token_clear = 0;
socket.on('auth_token_update', function(data){
    console.log("got a token! assigning");
    auth_token = data['token'];
    clearTimeout(auth_token_clear);
    auth_token_clear = setTimeout(function() {
        auth_token = null;
        auth_token_clear = 0;
        socket.emit('fetch_auth_token');
    }, data['time_left']*1000);
    // Resume Spotify playback now that we have a token
    resume_spotify_if_needed();
});

socket.on('auth_token_refresh', function(data){
    console.log("server says call spotify_connect again");
    spotify_connect(data);
});

socket.on('now_playing_update', function(data){
    playerpaused = data.paused;

    // Update button states
    if (playerpaused) {
        $('#pause-button').text('unpause everything');
        $('#airhorn-unpause-btn').show();
        document.title = "PAUSED | Andre";
    } else {
        $('#pause-button').text('pause everything');
        $('#airhorn-unpause-btn').hide();
    }

    // Always keep now_playing model in sync - this triggers view re-render
    if (data.title) {
        console.log(data);
        now_playing.clear({silent:true});
        now_playing.set(data);
        if (!playerpaused) {
            var display_artist = data.secondary_text || data.artist;
            document.title = data.title + " - " + display_artist + " | Andre";
        }
    } else if (playerpaused) {
        // Paused with no title data - trigger render anyway
        now_playing.trigger('change');
    } else {
        // Unpause without title - restore from model if available
        var title = now_playing.get('title');
        var artist = now_playing.get('secondary_text') || now_playing.get('artist');
        if (title && artist) {
            document.title = title + " - " + artist + " | Andre";
        }
    }

    // Notifications (only when playing)
    if (!playerpaused && data.title) {
        if(window.webkitNotifications
                && window.webkitNotifications.checkPermission() == 0
                && SHOW_NOTIFICATIONS){
            var note = window.webkitNotifications.createNotification(data.img,
                                                data.title, data.artist);
                note.show();
                setTimeout(function(){note.close();}, 7000);
        }
    }

    // Player sync logic
    if(is_player){
        fix_player(now_playing.get('src'), now_playing.get('trackid'), data.pos, playerpaused);
    }

    // Update skip button text based on content type
    var isPodcast = data.type === 'episode';
    $('#kill-playing').text(isPodcast ? 'skip playing podcast' : 'skip playing song');
});

var ALIGNMENT_OFF_COUNT = 0;

function yt_duration_to_time(n){
    var re = /PT((\d+)M)?((\d+)S)?/;
    var m = n.match(re);
    if (m === null) {
        console.log("something ain't right");
    }
    var min = m[2], sec = m[4];
    if (min === undefined) {
        min = '0';
    }
    if (sec === undefined) {
        sec = "00";
    } else if (sec < 10) {
        sec = "0"+sec;
    }

    return min + ":" + sec;
}

function seconds_to_time(n){
    var min = Math.floor(n / 60),
        seconds = n % 60;
    if(min < 10){
        min = '0'+min;
    }else{
        min = ''+min;
    }
    if(seconds < 10){
        seconds = '0'+seconds;
    }else{
        seconds = ''+seconds;
    }
    return min + ":" + seconds;
}

remaining = 0;
socket.on('player_position', function(src, track, pos){
    var current_duration = now_playing.get("duration");

    if (isNaN(pos) || isNaN(current_duration)) {
        return; // don't update
    }
    
    $('#playing-progress').css('width', Math.floor(400*pos/current_duration));
    $('#progress-wrapper').attr('title', seconds_to_time(pos)+"/"+seconds_to_time(current_duration))

    // update the time remaining; this will cause ETAs to be updated for the queue
    remaining = current_duration-pos;

    if(is_player){
        fix_player(src, track, pos, playerpaused);
    }
});

function spotify_volume(vol, retries = 5) {
    // $.ajax('https://api.spotify.com/v1/me/player/volume?volume_percent=' + vol, {
    //     method: 'PUT',
    //     headers: {
    //         Authorization: "Bearer " + auth_token
    //     },
    //     statusCode: {
    //         202:function() {
    //             if (retries > 0) {
    //                 retries--;
    //                 console.log(retries);
    //                 setTimeout(spotify_volume, 5000, vol);
    //             }
    //         }
    //     }
    // });
}

socket.on('volume', function(data){
    var $this = $('#volume-tab').empty();
    console.log('volume: ' + data);
    volume = data;
    if (is_player) {
        spotify_volume(data);
        if (typeof sc_player !== 'undefined' && sc_player.set_volume) {
            sc_player.set_volume(data);
        }
        if (ytready) {
            Y.setVolume(data * yt_volume_adjust);
        }
    }

    $this.append(TEMPLATES.volume_chunk({"volume":data}));
});

socket.on('do_airhorn', function(vol, name){
    console.log('DO AIRHORN EVENT');
    sort_airhorns(); // completion of all airhorn loading is asynchronous!
    vol = parseFloat(vol) * volume / 100;
    if (is_player) {
        console.log('AIRHOOORN');
        // pick a random airhorn
        // holy wow, this is way more complicated than it should be
        //if (typeof index == 'undefined') {
        //    index = Math.floor(Math.random()*airhorns.length);
        //} else {
        //    index = Math.floor(parseFloat(index) * airhorns.length);
        //}
        console.log("AIRHORN NAME:" + name);
        var airhornData = airhorn_map[name];
        playSound(airhornData, vol);
    }
    else {
        console.log('We would airhorn, but this computer is not currently playing music!');
    }
    socket.emit('fetch_airhorns')
    refresh_airhorns();
});

socket.on('airhorns', function(data){
    $('#airhorn-history').html(TEMPLATES.horns({horns:data}));
});

socket.on('free_horns', function(data){
    if(data > 0){
        $('#do-free-airhorn').removeClass('disabled').html('free airhorn ('+data+')');
    }else{
        $('#do-free-airhorn').addClass('disabled');
    }
    console.log('free_horns', data);
});

function sort_airhorns() {
    if (airhorns.length == 0) {
        refresh_airhorns();
    }
    airhorns.sort(function(a, b) {
        if (a.duration < b.duration) {
            return -1;
        }
        if (b.duration < a.duration) {
            return 1;
        }
        return 0;
    });
}

function mute_all(ev){
    $('.volume-slider').each(function(){
        var $this = $(this),
            d = $this.data();
        $this.val(0);
        socket.emit('change_volume', 1);
    });
}

function volume_change(ev){
    var $this = $(this),
        d = $this.data();
    socket.emit('change_volume', parseInt($this.val()));
}

function NoResultsException(intent) {
    this.intent = intent;
}

function spotify_search(q){
    console.log("searching spotify for " + q);
    return $.ajax({
        url:'/search/',
        dataType:'json',
        data:{q:q}
    }).then(function(data) {
        var ids = []
        var tracks = data.tracks;
        var intent = data.intent.toLowerCase();
        if (data.tracks.length == 0) {
            return {'intent': intent, 'tracks': []};
        }
        
        if (intent == 'play') {
            ids.push(tracks[0].uri.split(":").slice(-1));
        } else {
            var ids = [];
            for (var i = 0; i < tracks.length; i++) {
                ids.push(tracks[i].uri.split(":").slice(-1));
            }
        }
        // turn track IDs into decorated entities from the API with
        // album art, etc etc 0- this will need to change once 
        // the endpoint returns more than just tracks
        return $.ajax({url:'https://api.spotify.com/v1/tracks',
                        dataType:'json',
                        headers:{Authorization:"Bearer "+search_token},
                        data:{"ids": ids.join()}}).then(function(data) {
                            return {'intent': intent, 'tracks': data.tracks};
                        });
    });
}
 
TEMPLATES = {};
function prep_templates(){
    $('script[type="underscore/template"]').each(function(){
        var $this = $(this);
        TEMPLATES[$this.attr("id")] = _.template($this.text());
    });
}

function soundcloud_render(tracks) {       
    var target = $('#soundcloud-results');        
    for (var i=0; i<tracks.length; ++i) {     
        target.append(TEMPLATES.search_result_soundcloud(tracks[i]));     
    }     
  }

function soundcloud_url_search(q) {
    SC.initialize({
        client_id: '8267fd360bf3864e78a43456a6b26d74'
    });
    SC.get('/resolve', {url: q }).then(function(data) {
        if (data.sharing == "public") {
            soundcloud_render([data]);        
        }
    });
}

function spotify_uri_search(q) {
    var segments = q.split(':');
    if (segments.length == 3) {
        var type = segments[1];
        var id = segments[2];
        if (type == 'track') {
            // track URI, look up the one track
            return $.ajax ({
                url:'https://api.spotify.com/v1/tracks/' + id,
                dataType: 'json',
                headers:{Authorization:"Bearer "+search_token},
            }); 
        } else if (type == 'album') {
            // album URL, look up tracks on the album
             return $.ajax ({
                url:'https://api.spotify.com/v1/albums/' + id,
                headers:{Authorization:"Bearer "+search_token},
                dataType: 'json'
            }).then(function(data) {
                // album info is only at the top level, but we want it
                // with each track (so they have album art).  So clone
                // the top level, unset its tracks, and attach the
                // resulting thing to each track.  Ugly.
                var available = [];
                var albumClone = JSON.parse( JSON.stringify(data));
                albumClone.tracks = []
                
                for (var i=0;i<data.tracks.items.length; ++i) {
                    data.tracks.items[i]['album'] = albumClone;
                    available.push(data.tracks.items[i]);
                }
                return available;
            });
        } else if (type == 'artist') {
            // artist URI, look up top tracks for the artist
            return $.ajax ({
                url:'https://api.spotify.com/v1/artists/' + id + '/top-tracks',
                dataType: 'json',
                headers:{Authorization:"Bearer "+search_token},
                data: {country:top_tracks_region} // top tracks REQUIRES a country
            }).then(function(data) {
                  return data.tracks;
                });
        }
    }
}

function youtube_url_search(q) {
    var id = q.match(/https?:\/\/(www.)?youtube.com\/watch\?v\=(.*)/)[2];
    return $.ajax({url:'https://www.googleapis.com/youtube/v3/videos',
        dataType:'json',
        data:{"part":"snippet,contentDetails", "key": yt_api_key, "id": id}});
}

function song_search_submit(ev){
    ev.preventDefault();
    var input = $(this).find('input').val();
    $('#qbd-search-results > div').empty();
    spotify_search("qbd magic "+input).then(function(data) {
        if (data.tracks.length < 1) {
            var target = $("#spotify-search-results");
            target.append(TEMPLATES.search_no_results(data));
        } 
        if (data.intent.toLowerCase() == 'play' && data.tracks.length > 0) {
            socket.emit('add_song', data.tracks[0].uri, 'spotify');
            $(window).scrollTop(0);
            return;
        }
        var target = $("#qbd-results");
        for (var i=0;i<data.tracks.length;++i){
            target.append(TEMPLATES.search_result_spotify(data.tracks[i]));
        }
    });
}

function uri_search_submit(ev){
    ev.preventDefault();
    var input = $(this).find('input').val();
    $('#search-results > div').empty();
    var sc_url_re = /https?:\/\/(www.)?soundcloud.com\/([^/]+)\/(.*)/;
    var yt_url_re = /https?:\/\/(www.)?youtube.com\/watch\?v\=(.*)/;
    var spotify_uri_re = /^spotify:/;
    if (spotify_uri_re.test(input)) {
        spotify_uri_search(input).then(function(data) {
            var target = $("#spotify-results");
            target.append(TEMPLATES.search_result_spotify(data));
        });
    } else if (yt_url_re.test(input)) {
        youtube_url_search(input).then(function(data) {
            var target = $('#youtube-results');
            for(var i=0;i<data.items.length;++i){     
                target.append(TEMPLATES.search_result_youtube(data.items[i]));        
            }
        });
    } else if (sc_url_re.test(input)) {
        soundcloud_url_search(input);
    } else {
        $.ajax({
            url:'https://api.spotify.com/v1/search',
            dataType:'json',
            headers:{Authorization:"Bearer "+search_token},
            data:{q:input,type:'track',limit:50}
        }).then(function(data){
            var available = [];
            for (var i=0;i<data.tracks.items.length; ++i) {
                available.push(data.tracks.items[i]);
            }
            return available;
        }).then(function(data) {
            var target = $("#spotify-results");
            for (var i=0;i<data.length;++i){
                target.append(TEMPLATES.search_result_spotify(data[i]));
            }
        });
    }
}

function podcast_search_submit(ev){
    ev.preventDefault();
    var input = $(this).find('input').val();
    $('#episode-results').empty();
    $('#podcast-help').hide();
    console.log("Searching podcasts for: " + input);
    $.ajax({
        url:'https://api.spotify.com/v1/search',
        dataType:'json',
        headers:{Authorization:"Bearer "+search_token},
        data:{q:input, type:'episode', limit:50, market:'US'}
    }).then(function(data){
        console.log("Podcast search response:", data);
        var episodes = [];
        if (data.episodes && data.episodes.items) {
            for (var i=0;i<data.episodes.items.length; ++i) {
                if (data.episodes.items[i]) {
                    episodes.push(data.episodes.items[i]);
                }
            }
        }
        // Sort by release date (most recent first)
        episodes.sort(function(a, b) {
            var dateA = a.release_date || '';
            var dateB = b.release_date || '';
            return dateB.localeCompare(dateA);
        });
        return episodes;
    }).then(function(data) {
        var target = $("#episode-results");
        if (data.length === 0) {
            target.append('<div class="search-item"><div class="text"><h4>No podcasts found</h4></div></div>');
            return;
        }
        for (var i=0;i<data.length;++i){
            target.append(TEMPLATES.search_result_episode(data[i]));
        }
    }).fail(function(jqXHR, textStatus, errorThrown) {
        console.error("Podcast search error:", textStatus, errorThrown, jqXHR.responseText);
        $("#episode-results").append('<div class="search-item"><div class="text"><h4>Search error: ' + textStatus + '</h4></div></div>');
    });
}

function song_search_click(ev){
    ev.preventDefault();
    var $this = $(this),
        key = $this.data('key'),
        src = $this.data('src');
    $('#youtube-results, #spotify-results, #soundcloud-results').empty();
    socket.emit('add_song', key, src);
    $(window).scrollTop(0);
}

is_player = false;
auth_token = null;
ignore_refresh = true;
last_synced_spotify_track = null;
function make_player(ev){
    is_player = !is_player;
    if(!is_player){
        if (ytready) {
            $('#make-player').text("sync spotify");
            Y.stopVideo();
        } else {
            $('#make-player').text("sync spotify");
        }
        sc_player.stop();
        spotify_stop();
        last_spotify_track = null;
        last_synced_spotify_track = null;
        $('#ytapiplayer').css('z-index', 900);
        return;
    }
    if (auth_token == null) {
        console.log("fetching auth token");
        ignore_refresh = false;
        socket.emit('fetch_auth_token');
    } else {
        // Start playing the current track/episode immediately
        var src = now_playing.get('src');
        var trackid = now_playing.get('trackid');
        var pos = now_playing.get('pos') || 0;
        if (src && trackid) {
            fix_player(src, trackid, pos, playerpaused);
        }
    }
    socket.emit('request_volume');

    $('#make-player').text('disconnect spotify');
}

function spotify_connect(url) {
    if (ignore_refresh) {
        return;
    }
    ignore_refresh = true;
    var win = window.open(url, "Spotify Connect", "height=400,width=500,menubar=no,toolbar=no,location=no,status=no");
    var timer = setInterval(function() {
        if (win.closed) {
            console.log('fetching auth token again');
            socket.emit('fetch_auth_token');
            clearInterval(timer);
        } else {
            console.log("why didn't the window close?!");
        }
    }, 1000);
}

var playerpaused = false;
function pause_button(){
    if (!playerpaused) {
        console.log("pause button");
        socket.emit("pause");
        spotify_stop();
    } else {
        console.log("unpause button");
        socket.emit("unpause");
    }
}
function spotify_stop() {
    last_spotify_track = null;
    $.ajax('https://api.spotify.com/v1/me/player/pause', {
        method: 'PUT',
        headers: {
            Authorization: "Bearer " + auth_token
        }
    });
}   

function do_nuke_queue(){
    var msg = "Do you want to blow away the entire queue?";
    confirm_dialog(msg, function(){
        socket.emit("nuke_queue");
    });
}
function do_airhorn(){
    // Ensure player is active and Spotify is playing before airhorning
    if (!is_player) {
        make_player();
    } else {
        resume_spotify_if_needed();
    }
    var msg = "Do you feel lucky punk?";
    if(is_hohoholiday()){
        msg="Are you Santa?";
    }
    confirm_airhorn(msg, function(airhorn_choice){
        console.log()
        socket.emit("airhorn", airhorn_choice);
    });
}
function do_free_airhorn(){
    // Ensure player is active and Spotify is playing before airhorning
    if (!is_player) {
        make_player();
    } else {
        resume_spotify_if_needed();
    }
    confirm_dialog("Is this awesome airhorn worthy?", function(){
        socket.emit('free_airhorn');
    });
}
function kill_playing(){
    var isPodcast = now_playing.get('type') === 'episode';
    var msg = isPodcast ? "Are you sure you want to skip this podcast?" : "Are you sure you want to skip this song?";
    confirm_dialog(msg, function(){
        socket.emit("kill_playing");
    });
}

function confirm_dialog(msg, callback){
    $('#page-container').append(TEMPLATES.confirm_content({msg:msg, callback: !!callback}));
    $('#confirm a.yes').on('click', function(){
        $('#confirm').remove();
        callback();
    });
    $('#confirm a.no, #confirm a.alert-close').on('click', function(){
        $('#confirm').remove();
    });
}

function confirm_airhorn(msg, callback){
    $('#page-container').append(TEMPLATES.confirm_airhorn({msg:msg, callback: !!callback, airhorns: _.keys(airhorn_map)}));
    $('#confirm a.yes').on('click', function(){
        var airhorn_choice = $('#airhorn-dropdown').val();
        $('#confirm').remove();
        callback(airhorn_choice);
    });
    $('#confirm a.no, #confirm a.alert-close').on('click', function(){
        $('#confirm').remove();
    });
}

var hover_offset = 0;

function _window_resize(){
    var $right = $('#right'),
            ww = $(window).width();
    $right.width(ww-400);
    $(".queue-item-text").css("width", ww-(400+65+72+43));
    $("#now-playing-text").css("width", $("#top-row").width()-(180+20));
    $("#now-playing-text h1").css("width", $("#top-row").width()-(180+60));
}
var window_resize = _.throttle(_window_resize, 100);
$(window).on('resize', window_resize);

function initialize_tabs(){
    $('.menu-item').on('click', function(){
        var $this = $(this),
            $target = $('#'+$this.data('id')+'-tab');
        $target.addClass('visible').siblings().removeClass('visible');
        $this.addClass('active').siblings().removeClass('active');
    });
}


var FEEL_SHAME = false;
function feel_shame(ev){
    ev.preventDefault();
    FEEL_SHAME = !FEEL_SHAME;
    playlist_view.render();
    now_playing_view.render();
    $('#feel-shame').text(FEEL_SHAME?'show shame':'hide shame');
}

var fill_sites = ['lorempixel.com', 'fillmurray.com',
                    'placecage.com', 'placebear.com', 'placekitten.com',
                    'baconmockup.com',]
function shame_image(width,height){
    return 'http://'+fill_sites[Math.floor(Math.random()*fill_sites.length)]
                    +'/'+width+'/'+height;
}

function show_notifications(){
    if(!window.webkitNotifications){
        alert("Your browser doesn't support this.");
        return;
    }
    SHOW_NOTIFICATIONS = !SHOW_NOTIFICATIONS;
    $('#show-notifications').text(SHOW_NOTIFICATIONS?'stop os notifications':'show os notifications');
    if (window.webkitNotifications.checkPermission() != 0) {
        window.webkitNotifications.requestPermission(function(){});
    }
}

function playlist_result_click(){
    var data = $(this).data();
    $('#search-results').empty();
    socket.emit('add_playlist', data.key, data.shuffled === 'yes')
}

// WebAudio playback & support functions
var context = null;
var airhorns = [];
var airhorn_map = {};

function playSound(buffer, volume) {
    var source = context.createBufferSource(); 
    source.buffer = buffer;    
    var gainNode = context.createGain();
    source.connect(gainNode);
    gainNode.connect(context.destination);
    gainNode.gain.value = volume;   
    source.start(0);                                                  
}

function onError() {
    console.log('Airhorn file did not load!  Try a refresh.');
}

function loadAirHorn(url) {
    console.log('loading ' + url);
    var request = new XMLHttpRequest();
    request.open('GET', url, true);
    request.responseType = 'arraybuffer';

    // Decode asynchronously
    if (url !== undefined) {
    }
    request.onload = function() {
        context.decodeAudioData(request.response, function(data) {
            airhorns.push(data);
            var url_segments = request.responseURL.split('/');
            var name = url_segments[url_segments.length-1].split('.')[0];
            airhorn_map[name] = data;
            socket.emit('loaded_airhorn', name)
            
        }, onError);
    }
    request.send();
}

last_refresh = new Date(0);
function refresh_airhorns() {
    var this_refresh = new Date();
    if (Math.floor(this_refresh.getTime() / 86400000) == Math.floor(last_refresh.getTime() / 86400000) && airhorns.length > 0) {
        return;
    }
    last_refresh = this_refresh;
    airhorns = [];
    context = new AudioContext();
    if (context) {
        if(is_hohoholiday()){
            // we only have one horn, and it is the hohohorn
            loadAirHorn('/static/audio/hohoho.mp3');
        } else if (is_roshhashanah()) {
            // Shofars!
            loadAirHorn('/static/audio/tekiah.mp3');
            loadAirHorn('/static/audio/shevarim.mp3');
            loadAirHorn('/static/audio/teruah.mp3');
            loadAirHorn('/static/audio/gedolah.mp3');
        }else{
            loadAirHorn('/static/audio/airhorn.mp3');
            loadAirHorn('/static/audio/reemix.mp3');
            loadAirHorn('/static/audio/dj_airhorn.mp3');
            loadAirHorn('/static/audio/reload_shot.mp3');
            loadAirHorn('/static/audio/baking_soda.mp3');
            loadAirHorn('/static/audio/mk_toasty.mp3');
            loadAirHorn('/static/audio/eagle.wav');
            loadAirHorn('/static/audio/thankyou.mp3');
            loadAirHorn('/static/audio/davidleeroth.wav');
            loadAirHorn('/static/audio/downwiththesickness.wav');
            loadAirHorn('/static/audio/funkmaster.mp3');
            loadAirHorn('/static/audio/exclusive.mp3');
            loadAirHorn('/static/audio/heylisten.mp3');
            loadAirHorn('/static/audio/ilikeit.wav');
            loadAirHorn('/static/audio/brandnew.wav');
            loadAirHorn('/static/audio/kids.mp3');
            loadAirHorn('/static/audio/wednesday.wav');
            loadAirHorn('/static/audio/damnson.mp3');
            loadAirHorn('/static/audio/show-me-what-you-got.mp3');
            loadAirHorn('/static/audio/i-like-what-you-got.mp3');
            loadAirHorn('/static/audio/mah-man.mp3');
            loadAirHorn('/static/audio/morefire.mp3');
            loadAirHorn('/static/audio/Freddie.mp3');
            loadAirHorn('/static/audio/partypeople.wav');
            loadAirHorn('/static/audio/wow.wav');
            loadAirHorn('/static/audio/GoodNewsEveryone.mp3');
            loadAirHorn('/static/audio/eh-eh-oh-eh-oh.mp3');
	    loadAirHorn('/static/audio/vamos-a-bailar.mp3');
	    // sorry but you did not make the cut
            //loadAirHorn('/static/audio/wiggle.mp3');
            //loadAirHorn('/static/audio/fuck_all_yall.mp3');
            //loadAirHorn('/static/audio/vuvuzela.mp3');
            //loadAirHorn('/static/audio/boat.wav');
            //loadAirHorn('/static/audio/foghorn.mp3');
            //loadAirHorn('/static/audio/growl.mp3');
            //loadAirHorn('/static/audio/zillaroar.mp3');
        }
    }
    else {
        console.log('WebAudio is not supported, airhorn not loaded!')
    }
}

window.addEventListener('load', function(){
    window_resize();
    var $hover_menu = $('#hover-menu');
    hover_offset = $hover_menu.outerHeight() - $('#pull-down').height();
    hover_offset = -hover_offset;
    $hover_menu.css({top:hover_offset+'px'});
    $hover_menu.hover(function(){
        $hover_menu.css({top:'0px'});
    },function(){
        $hover_menu.css({top:hover_offset+'px'});
    });

    // Set up webaudio context
    window.AudioContext = window.AudioContext||window.webkitAudioContext;
    refresh_airhorns();

    prep_templates();

    $('#song-search').on('submit', song_search_submit);
    $('#uri-search').on('submit', uri_search_submit);
    $('#podcast-search').on('submit', podcast_search_submit);
    $('#qbd-results').on('click', '.search-result',
                         song_search_click);
    $('#search-results').on('click', '.search-result',
                            song_search_click);
    $('#podcast-search-results').on('click', '.search-result',
                            song_search_click);
    $('#mute-all').on('click', mute_all);
    $('#do-nuke-queue').on('click', do_nuke_queue);
    $('#pause-button').on('click', pause_button);
    $('#do-airhorn').on('click', do_airhorn);
    $('#do-free-airhorn').on('click', do_free_airhorn);
    $('#airhorn-unpause-btn').on('click', function(){
        console.log("unpause button (from airhorn area)");
        socket.emit("unpause");
        // Spotify playback resumes via fix_player when now_playing_update arrives
    });
    $('#kill-playing').on('click', kill_playing);
    $('#feel-shame').on('click', feel_shame);
    $('#show-notifications').on('click', show_notifications);
    $('#search-results').on('click', '.playlist-result',
                                    playlist_result_click);
    $('#make-player').on('click', make_player);
    $('#change-color').on('click', changeColors);

    // Load saved color theme
    loadSavedColorTheme();

    $('#volume-tab').on('change', 'input', _.throttle(volume_change, 300));

    playlist_view = new PlaylistView({collection: playlist,
                                            el:$('#queue')});
    playlist_view.render();
    now_playing_view = new NowPlayingView({model:now_playing, 
                                            el:$('#top-row')});
    now_playing_view.render();

    // Setup comment handling.
    addCommentsClickHandlers(); 
    addCommentInputKeyPressHandler();

    socket.emit('fetch_playlist');
    socket.emit('fetch_now_playing');
    socket.emit('request_volume');
    socket.emit('fetch_airhorns');
    socket.emit('get_free_horns');
    socket.emit('fetch_search_token');
    initialize_tabs();
});

