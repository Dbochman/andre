var sc_player = window.sc_player || {};
SC.initialize({
      client_id: '8267fd360bf3864e78a43456a6b26d74'
});

sc_player.playing_track_id = -1;
sc_player.stream = null;
sc_player.playing = function() {
    return sc_player.playing_track_id != -1;
}
sc_player.play = function(track_id, pos) {
    if (sc_player.playing()) {
        sc_player.stop();
    }
    sc_player.playing_track_id = track_id;
    console.log("/tracks/"+track_id);
    sc_player.stream = SC.stream("/tracks/"+track_id).then(function(sound){
        sound.options.protocols = ['http']
        sc_player.stream = sound;
        sound.play();
        sound.on("play-start", function() {
          sound.seek(pos*1000);
        })
    });
}
sc_player.stop = function() {
    try {
      if (sc_player.stream) {
          sc_player.stream.pause();
      }
    } catch (e) {
      console.log(e);
    }
    sc_player.playing_track_id = -1;
    sc_player.stream = null;
}
sc_player.set_volume = function(vol) {
    try {
        sc_player.stream.setVolume(vol/100);
    } catch (e) {
      console.log(e);
    }

}