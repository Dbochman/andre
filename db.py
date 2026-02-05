from gevent import monkey;monkey.patch_all()
import time
import datetime
import json
import random
import string
import random
import uuid
import logging
import pickle
import base64
import smtplib
import hashlib
import os
import traceback
import requests
import redis
import re

import spotipy.oauth2, spotipy.client

from flask import render_template
from config import CONF
from history import PlayHistory

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
if CONF.DEBUG:
    logger.setLevel(logging.DEBUG)
    logging.getLogger('pyen').setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
    logging.getLogger('pyen').setLevel(logging.INFO)

STOPWORDS = set(['the', 'and', 'for', ])

# Base64-wrapped pickle helpers for storing binary data in decode_responses=True Redis
def pickle_dump_b64(obj):
    """Serialize object with pickle and encode as base64 string for Redis storage."""
    return base64.b64encode(pickle.dumps(obj)).decode('ascii')

def pickle_load_b64(data):
    """Decode base64 string and deserialize with pickle."""
    if data is None:
        return None
    if isinstance(data, bytes):
        data = data.decode('ascii')
    return pickle.loads(base64.b64decode(data))

server_tokens = spotipy.oauth2.SpotifyClientCredentials(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET)
spotify_client = spotipy.client.Spotify(client_credentials_manager=server_tokens)

auth = spotipy.oauth2.SpotifyClientCredentials(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET)
auth.get_access_token()


def _now():
    return datetime.datetime.now()

def _log_file_for_today():
    return datetime.datetime.strftime(_now(), CONF.LOG_DIR + '/play_log_%Y_%m_%d.json')

def _log_play(song_json):
    play_logger = _log_file_for_today()
    try:
        with open(play_logger, "a", encoding="utf-8") as _appendable_log:
            _appendable_log.write(song_json + '\n')
    except Exception as _e:
        logger.error('failed to log %s' % song_json)

def _clean_song(song):
    REMOVABLE_FIELDS = ('background_color', 'foreground_color', 'big_img', 'img', 'data')
    for field in REMOVABLE_FIELDS:
        song.pop(field, None)
    return song

ytre = re.compile("PT((\\d+)H)?((\\d+)M)?(\\d+)S")
def parse_yt_duration(d):
    m = ytre.match(d)
    print(d)
    if m:
        duration = int(m.group(5))

        hours = m.group(2)

        if hours:
            duration += int(hours) * 3600

        minutes = m.group(4)
        if minutes:
            duration += int(minutes) * 60
        return duration
    return 0



class DB(object):
    def __init__(self, init_history_to_redis=True):
        logger.info('Creating DB object')
        redis_host = CONF.REDIS_HOST or 'localhost'
        redis_port = CONF.REDIS_PORT or 6379
        self._r = redis.StrictRedis(host=redis_host, port=redis_port, decode_responses=True)
        self._h = PlayHistory(self)
        if init_history_to_redis:
            self._h.init_history()
        self._oauth_token = None
        self._oauth_token_expires = datetime.datetime(2000,1,1,1)
        try:
            os.makedirs(CONF.LOG_DIR)
            logger.info('Created log directory: %s' % CONF.LOG_DIR)
        except OSError:
            if os.path.isdir(CONF.LOG_DIR):
                logger.info('Log directory already exists: %s' % CONF.LOG_DIR)
            else:
                raise

    def big_scrobble(self, email, tid):
        #add played song to FILTER "set"
        self._r.setex("FILTER|%s"% tid, CONF.BENDER_FILTER_TIME, 1)

    def _grab_fill_in_songs(self, depth=0):
        """
        Bender's recommendation engine using Artist Top Tracks + Album Tracks.

        Spotify deprecated recommendations (Nov 2024) and related-artists APIs.
        This approach uses still-working endpoints:
        1. Gets the seed from last-queued, last Bender track, or now-playing
        2. Fetches top tracks from the seed artist(s)
        3. Gets other tracks from the same album
        4. Searches for artist name to find more variety
        5. Loops continuously with the last track as new seed
        """
        # Try multiple seed sources for continuity
        seed_song = None

        # 1. Last user-queued track
        seed_song = self._r.get('MISC|last-queued')

        # 2. Last Bender track (for continuous discovery)
        if not seed_song:
            seed_song = self._r.get('MISC|last-bender-track')

        # 3. Currently playing track
        if not seed_song:
            now_playing_id = self._r.get('MISC|now-playing')
            if now_playing_id:
                now_playing_data = self._r.hget('QUEUE|{}'.format(now_playing_id), 'trackid')
                if now_playing_data:
                    seed_song = now_playing_data

        # 4. Ultimate fallback - Billy Joel (only if nothing else available)
        if not seed_song:
            seed_song = "spotify:track:3utq2FgD1pkmIoaWfjXWAU"

        # Extract track ID from URI
        seed_song = seed_song.split(":")[-1]
        logger.debug("Bender seed song: %s" % seed_song)

        market = CONF.BENDER_REGIONS[0] if CONF.BENDER_REGIONS else 'US'

        # Get the seed track details
        try:
            song_deets = spotify_client.track(seed_song)
            seed_artists = [(a['id'], a['name']) for a in song_deets.get('artists', [])]
            album_id = song_deets.get('album', {}).get('id')
        except Exception:
            logger.warning("Error getting track details for seed: %s", seed_song)
            logger.warning(traceback.format_exc())
            return []

        out_tracks = []
        seed_song_uri = "spotify:track:" + seed_song

        # Strategy 1: Get top tracks from each artist
        for artist_id, artist_name in seed_artists[:2]:
            try:
                top_tracks = spotify_client.artist_top_tracks(artist_id, country=market)
                for track in top_tracks.get('tracks', []):
                    track_uri = track['uri']
                    if track_uri == seed_song_uri:
                        continue
                    if self._r.get("FILTER|%s" % track_uri):
                        continue
                    out_tracks.append(track_uri)
                logger.debug("Got %d top tracks from %s", len(top_tracks.get('tracks', [])), artist_name)
            except Exception:
                logger.warning("Error getting top tracks for artist: %s", artist_id)

        # Strategy 2: Get other tracks from the same album
        if album_id:
            try:
                album_tracks = spotify_client.album_tracks(album_id)
                for track in album_tracks.get('items', []):
                    track_uri = track['uri']
                    if track_uri == seed_song_uri:
                        continue
                    if self._r.get("FILTER|%s" % track_uri):
                        continue
                    if track_uri not in out_tracks:
                        out_tracks.append(track_uri)
                logger.debug("Got %d album tracks", len(album_tracks.get('items', [])))
            except Exception:
                logger.warning("Error getting album tracks for: %s", album_id)

        # Strategy 3: Search for artist name to find collaborations and similar
        if seed_artists:
            artist_name = seed_artists[0][1]
            try:
                search_results = spotify_client.search(artist_name, limit=20, type='track', market=market)
                for track in search_results.get('tracks', {}).get('items', []):
                    track_uri = track['uri']
                    if track_uri == seed_song_uri:
                        continue
                    if self._r.get("FILTER|%s" % track_uri):
                        continue
                    if track_uri not in out_tracks:
                        out_tracks.append(track_uri)
                logger.debug("Got %d tracks from search", len(search_results.get('tracks', {}).get('items', [])))
            except Exception:
                logger.warning("Error searching for artist: %s", artist_name)

        # Strategy 4: Throwback - pull from historical plays on same day of week
        # These are stored separately with original user info
        try:
            throwback_plays = self._h.get_throwback_plays(limit=20)
            throwback_added = 0
            for play in throwback_plays:
                track_uri = play.get('trackid')
                original_user = play.get('user', 'the@echonest.com')
                if track_uri == seed_song_uri:
                    continue
                if self._r.get("FILTER|%s" % track_uri):
                    continue
                if track_uri not in out_tracks:
                    # Store throwback with original user in a separate queue
                    self._r.rpush('MISC|throwback-songs', track_uri)
                    self._r.hset('MISC|throwback-users', track_uri, original_user)
                    throwback_added += 1
            if throwback_added > 0:
                self._r.expire('MISC|throwback-songs', 60*20)
                self._r.expire('MISC|throwback-users', 60*20)
            logger.debug("Got %d throwback tracks from history", throwback_added)
        except Exception:
            logger.warning("Error getting throwback tracks: %s", traceback.format_exc())

        # Remove duplicates and shuffle for variety
        out_tracks = list(dict.fromkeys(out_tracks))  # Preserve order, remove dupes
        random.shuffle(out_tracks)
        out_tracks = out_tracks[:20]

        logger.debug("Bender found %d tracks total", len(out_tracks))
        return out_tracks

    def ensure_fill_songs(self):
        num_songs = self._r.llen('MISC|fill-songs')
        if num_songs > 0:
            return

        songs = self._grab_fill_in_songs()
        logger.debug("ensure_fill_songs got: %s", songs)
        if songs:
            self._r.rpush('MISC|fill-songs', *songs)
            # Store the last track as seed for next round of discovery
            self._r.set('MISC|last-bender-track', songs[-1])
        else:
            logger.warning("Bender couldn't find any tracks - recommendations exhausted")

    def get_fill_song(self):
        song = self._r.lpop('MISC|backup-queue')
        if song:
            return self._r.hget('MISC|backup-queue-data', 'user'), song
        self._r.delete('MISC|backup-queue-data')

        # Check throwback queue first - these have original user attribution
        throwback_song = self._r.lpop('MISC|throwback-songs')
        if throwback_song:
            original_user = self._r.hget('MISC|throwback-users', throwback_song) or 'the@echonest.com'
            self._r.hdel('MISC|throwback-users', throwback_song)
            logger.debug("returning throwback song %s from %s", throwback_song, original_user)
            self._r.set('MISC|last-bender-track', throwback_song)
            return original_user, throwback_song

        song = self._r.lpop('MISC|fill-songs')
        attempts = 0
        while not song and attempts < 5:
            attempts += 1
            songs = self._grab_fill_in_songs()
            logger.debug("get_fill_song attempt %d got: %s", attempts, songs)
            if songs:
                self._r.rpush('MISC|fill-songs', *songs)
                self._r.expire('MISC|fill-songs', 60*20)
                # Store last track as seed for continuous discovery
                self._r.set('MISC|last-bender-track', songs[-1])
            # Check throwback again after refill
            throwback_song = self._r.lpop('MISC|throwback-songs')
            if throwback_song:
                original_user = self._r.hget('MISC|throwback-users', throwback_song) or 'the@echonest.com'
                self._r.hdel('MISC|throwback-users', throwback_song)
                logger.debug("returning throwback song %s from %s", throwback_song, original_user)
                self._r.set('MISC|last-bender-track', throwback_song)
                return original_user, throwback_song
            song = self._r.lpop('MISC|fill-songs')

        if song:
            logger.debug("returning song %s", song)
            # Update last-bender-track so next batch continues from here
            self._r.set('MISC|last-bender-track', song)
            return 'the@echonest.com', song
        else:
            logger.error("Bender exhausted all recommendation sources")
            # Return None to signal no song available
            return None, None

    def bender_streak(self):
        now = self.player_now()
        try:
            then = pickle_load_b64(self._r.get('MISC|bender_streak_start'))
            if then is None:
                then = _now()
            logger.debug("bender streak is %s seconds, now %s then %s" % ((now - then).total_seconds(), now, then))
        except Exception as _e:
            logger.debug("Exception getting MISC|bender_streak_start: %s; assuming no streak" % _e)
            then = _now()

        return (now - then).total_seconds()


    def master_player(self):
        id = str(uuid.uuid4())
        n = self._r.setnx('MISC|master-player', id)
        while not n:
            time.sleep(5)
            n = self._r.setnx('MISC|master-player', id)
        self._r.expire('MISC|master-player', 5)
        #I'm the player.
        logger.info('Grabbing player')
        while True:

            song = self.get_now_playing()
            finish_on = self._r.get('MISC|current-done')
            if finish_on and pickle_load_b64(finish_on) > self.player_now():
                done = pickle_load_b64(finish_on)
            else:
                if song:
                    self.log_finished_song(song)
                    

                song = self.pop_next()
                if not song:
                    logger.debug("streak start set %s"%self._r.setnx('MISC|bender_streak_start', pickle_dump_b64(self.player_now())))
                    if (not CONF.USE_BENDER) or (self.bender_streak() <= CONF.MAX_BENDER_MINUTES * 60):
                        got_song = False
                        while not got_song:
                            try:
                                song = self.get_fill_song()
                                self.add_spotify_song(*song, scrobble=False)
                                got_song = True
                            except Exception:
                                logger.warn("couldn't add spotify song:" + str(song) )
                                logger.warn(traceback.format_exc())
                                continue
                        continue
                    else:
                        time.sleep(0.5)
                        continue
                if song['duration'] < 5:
                    continue
                done = self.player_now() + \
                    datetime.timedelta(seconds=song['duration'],
                                       milliseconds=1000)

            id = song['trackid']
            expire_on = int((done - self.player_now()).total_seconds())

            self._r.setex('MISC|current-done',
                          expire_on,
                          pickle_dump_b64(done))
            self._r.set('MISC|started-on',
                          self.player_now().isoformat())
            while self.player_now() < done:
                paused = self._r.get('MISC|paused')
                while paused:
                    logger.info("paused, sleeping 1s")
                    time.sleep(1)
                    paused = self._r.get('MISC|paused')
                self._r.expire('MISC|master-player', 5)
                if self._r.get('MISC|force-jump'):
                    self._r.delete('MISC|force-jump')
                    break
                self._add_now(1)
                time.sleep(1)
                remaining = int((done-self.player_now()).total_seconds())
                self._msg('pp|{0}|{1}|{2}'.format(song['src'], id, song['duration'] - remaining))
            self._r.delete('MISC|current-done')
            self._r.delete('QUEUE|VOTE|{0}'.format(id))
            self._r.delete('QUEUE|{0}'.format(id))

    def player_now(self):
        t = self._r.get('MISC|player-now')
        if t:
            try:
#                logger.debug("player-now %s" % pickle_load_b64(t))
                return pickle_load_b64(t)
            except Exception:
                logger.error("exception loading current player time: %s", traceback.format_exc())
                logger.debug("at time (not from redis): %s " % _now())
                return _now()
        else:
            logger.debug("now (not from redis): %s" % _now())
            return _now()

    def _add_now(self, seconds):
        new_t = self.player_now() + datetime.timedelta(seconds=seconds)
#        logger.debug("updating time %s", new_t)
        self._r.setex('MISC|player-now', 12*3600, pickle_dump_b64(new_t))

    def _song_keywords(self, title):
        return set(x for x in title.lower().split()
                   if len(x) > 2 and x not in STOPWORDS)

    def _score_track(self, userid, force_first, song):
        if force_first:
            return 0

        userid = userid.lower()
        queued = self.get_queued()

        if len(queued) == 1:
            return 1.0

        # this counts how many tracks this user will have in the queue including this (so start from 1)
        this_user_songs_in_queue = 1
        for i in range(0, len(queued) - 1):
            x = queued[i]
            print(str(json.dumps(x)))
            if x.get('user','') == userid:
                this_user_songs_in_queue += 1

        # loop over all the tracks in the queue and count how many each user has queued
        user_seen_count = {}
        for i in range(0, len(queued) - 1):
            queued_song = queued[i]
            queuer = queued_song['user']

            # increase the count of tracks in queue for the user who queued this track
            if queuer in user_seen_count:
                user_seen_count[queuer] += 1
            else: # or initialize it to 1 if this is the first time we see them
                user_seen_count[queuer] = 1

            # if this track is someone's n+1th track and the requesting user is adding
            # their nth track, add the requesting user's track right before this track
            # no need to check if i > 0 because this can't be true until the second track in the queue
            if user_seen_count[queuer] == this_user_songs_in_queue + 1:
                return (queued[i-1]['score'] + queued_song['score']) / 2.0

        # if we get here it means that the track should be added last to the queue
        return queued[-2]['score'] + 1.0

    def get_user_img(self, userid):
        static = {'the@echonest.com' : '/static/theechonestcom.png',
                    'jambutton@echonest.com' : '/static/button.png', 
                    'dailymix@spotify.com' : '/static/DM.png',
                    'joeyd@spotify.com' : '/static/image.png',
		    'johndoelp@spotify.com' : '/static/wiggleface.gif',
                    'jsteinbach@spotify.com': '/static/bender_fur.jpg'}
        if userid in static:
            return static[userid]
        """
        pic_url = self._r.get('MISC|users|'+ userid)
        if pic_url:
            return pic_url
        if userid.endswith('@echonest.com'):
            r = requests.get('http://thewall.sandpit.us/img/'+userid)
            pic_url = r.json()['url']
            self._r.setex('MISC|users|'+userid, 10*60, pic_url)
            return pic_url
        """
        """
        #Ill advised; for folks not logged into spotify.net, it's a mess.
        if userid.endswith('@spotify.com'):
            return 'https://start.spotify.net/img/avatar/{}.jpg'.format(userid.split('@')[0])
        """
        grav = hashlib.md5(userid.strip().lower().encode('utf-8')).hexdigest()
        return 'http://www.gravatar.com/avatar/{0}?d=monsterid&s=180'.format(grav)

    def _add_song(self, userid, song, force_first, penalty=0):
        id = self._r.incr('MISC|playlist-plays')

        song.update(dict(background_color='222222',
                        foreground_color='F0F0FF',
                        user=userid, id = id, vote=0))
        self.set_song_in_queue(id, song)
        s_id = 'QUEUE|VOTE|{0}'.format(id)
        self._r.sadd(s_id, userid)
        self._r.expire(s_id, 24*60*60)
        score = self._score_track(userid, force_first, song) + penalty
        self._r.zadd('MISC|priority-queue', {str(id): score})
        self._msg('playlist_update')
        return str(id)

    def _pluck_youtube_img(self, doc, height):
        for img in doc['snippet']['thumbnails'].values():
            if img['height'] >= height:
                return img['url']
        return ""

    def add_soundcloud_song(self, userid, trackid, penalty=0):
        response = requests.get('http://api.soundcloud.com/tracks/{0}.json?client_id={1}'.format(trackid, CONF.SOUNDCLOUD_CLIENT_ID))
        track = response.json()
        if not track:
            return
        if 'user' not in track:
            logger.error("no user info in track. tried to add a private track? %s" % trackid)
            return
        artist = track['user']['username']

        if artist == 'Coldplay':
            logger.info('{0} tried to add "{1}" by Coldplay'.format(userid,
                            track['title']))
            return
        song = dict(data=response, src='soundcloud', trackid=trackid,
                    title=track['title'],
                    artist=artist,
                    duration=int(track['duration']) // 1000,
                    big_img=track['artwork_url'], auto=False,
                    img=track['artwork_url'])
        self._add_song(userid, song, False, penalty=penalty)

    def add_youtube_song(self, userid, trackid, penalty=0):
        response = requests.get('https://www.googleapis.com/youtube/v3/videos/',
                                params=dict(id=trackid, part='snippet,contentDetails', key=CONF.YT_API_KEY)).json()
        print(json.dumps(response))
        response = response['items'][0]
        if 'coldplay' in response['snippet']['title'].lower():
            logger.info('{0} tried to add "{1}" by Coldplay (YT)'.format(
                userid,
                response['snippet']['title']))
            return
        #TODO: Artist/Title? Scrobble?
        song = dict(data=response, src='youtube', trackid=trackid,
                    title=response['snippet']['title'],
                    artist=response['snippet']['channelTitle'] + '@youtube',
                    duration=parse_yt_duration(response['contentDetails']['duration']),
                    big_img=self._pluck_youtube_img(response, 360),
                    auto=False,
                    img=self._pluck_youtube_img(response, 90))
        self._add_song(userid, song, False, penalty=penalty)

    def get_fill_info(self, trackid):
        key = 'FILL-INFO|{0}'.format(trackid)

        raw_song = self._r.hgetall(key)
        if raw_song:
            return raw_song

        song = self.get_spotify_song(trackid, scrobble=False)
        # Serialize for Redis storage
        serialized = {}
        for k, v in song.items():
            if isinstance(v, (dict, list)):
                serialized[k] = json.dumps(v)
            elif v is None:
                serialized[k] = ''
            else:
                serialized[k] = str(v) if not isinstance(v, str) else v
        self._r.hset(key, mapping=serialized)
        self._r.expire(key, 20*60) # 20 minutes should be long enough -- if not, no worries, just refetch
        return song

    def get_spotify_song(self, trackid, scrobble):
        # Handle get_access_token returning dict in newer spotipy versions
        token = auth.get_access_token()
        if isinstance(token, dict):
            token = token.get('access_token', token)

        resp = requests.get(
            'https://api.spotify.com/v1/tracks/'+trackid.split(':')[-1],
            headers={'Authorization': 'Bearer ' + str(token)},
            timeout=10)

        if resp.status_code != 200:
            logger.error("Spotify API HTTP error %d fetching track %s", resp.status_code, trackid)
            raise Exception(f"Spotify API error: HTTP {resp.status_code}")

        response = resp.json()

        # Check for API errors in response body
        if 'error' in response:
            logger.error("Spotify API error fetching track %s: %s", trackid, response.get('error'))
            raise Exception(f"Spotify API error: {response.get('error', {}).get('message', 'Unknown error')}")

        big_img, img = self._extract_images(response.get('album', {}).get('images', []))

        song = dict(data=response, src='spotify', trackid=trackid,
                    title=response['name'],
                    artist=", ".join([a['name'] for a in response.get('artists', [])]),
                    duration=int(response.get('duration_ms', 0)) // 1000,
                    big_img=big_img,
                    auto=not scrobble,
                    img=img)

        logger.debug("get_spotify_song: %s", song['title'])
        return song

    def _extract_images(self, images_list):
        """Extract big and small image URLs from a list of image objects."""
        big_img = None
        img = None
        if images_list:
            num_images = len(images_list)
            if num_images > 0:
                big_img = images_list[0].get('url')
                img = big_img
            if num_images > 1:
                img = images_list[-1].get('url')
        return big_img, img

    def get_spotify_episode(self, episode_id):
        """Fetch episode metadata from Spotify API.

        Args:
            episode_id: Either a full URI (spotify:episode:xxx) or just the ID
        """
        token = auth.get_access_token()
        if isinstance(token, dict):
            token = token.get('access_token', token)

        # Extract ID if full URI was passed
        if ':' in episode_id:
            episode_id = episode_id.split(':')[-1]

        resp = requests.get(
            'https://api.spotify.com/v1/episodes/' + episode_id,
            headers={'Authorization': 'Bearer ' + str(token)},
            timeout=10)

        if resp.status_code != 200:
            logger.error("Spotify API HTTP error %d fetching episode %s", resp.status_code, episode_id)
            raise Exception(f"Spotify API error: HTTP {resp.status_code}")

        response = resp.json()

        # Check for API errors
        if 'error' in response:
            logger.error("Spotify API error fetching episode %s: %s", episode_id, response.get('error'))
            raise Exception(f"Spotify API error: {response.get('error', {}).get('message', 'Unknown error')}")

        if 'name' not in response:
            logger.error("Invalid episode response for %s: missing 'name' field", episode_id)
            raise Exception(f"Invalid episode data: missing required fields")

        big_img, img = self._extract_images(response.get('images', []))
        show_name = response.get('show', {}).get('name', '') if response.get('show') else ''

        episode = dict(
            data=response,
            src='spotify',
            trackid='spotify:episode:' + episode_id,
            title=response['name'],
            artist=show_name,
            secondary_text=show_name,
            show_name=show_name,
            publisher=response.get('show', {}).get('publisher', '') if response.get('show') else '',
            duration=int(response.get('duration_ms', 0)) // 1000,
            big_img=big_img,
            img=img,
            type='episode',
            auto=False,
        )

        logger.debug("get_spotify_episode: %s - %s", episode['title'], show_name)
        return episode

    def add_spotify_song(self, userid, trackid, penalty=0, force_first=False,
                         scrobble=True):
        # we use the metadata API to get track info even though
        # the actual search is using core JS- could cause mismatches down
        # the line. until we can make bender run on core JS it's the best
        # path
        logger.debug("adding spotify song %s", trackid)

        # Detect if this is an episode URI (format: spotify:episode:xxx)
        uri_parts = trackid.split(':')
        is_episode = len(uri_parts) >= 2 and uri_parts[1] == 'episode'

        if is_episode:
            song = self.get_spotify_episode(trackid)
        else:
            song = self.get_spotify_song(trackid, scrobble)

        new_id = self._add_song(userid, song, force_first, penalty)

        if scrobble and not is_episode:
            self.big_scrobble(userid, 'spotify:track:'+trackid.split(':')[-1])

        return new_id

    def num_jams(self, queued_song_jams_key):
        return self._r.zcard(queued_song_jams_key)

    def get_jams(self, queued_song_jams_key):
        jams_raw = self._r.zrange(queued_song_jams_key, 0, self.num_jams(queued_song_jams_key), withscores=True)
        jams = []
        for user, ts in jams_raw:
            jams.append({"user": user,
                         "time": datetime.datetime.fromtimestamp(ts).isoformat()})
        logger.debug("jams for %s: %s" % (queued_song_jams_key, jams))
        return jams

    def add_jam(self, queued_song_jams_key, userid):
        self._r.zadd(queued_song_jams_key, {userid.lower(): int(time.time())})
        logger.info("jammed by " +  userid)

    def remove_jam(self, queued_song_jams_key, userid):
        self._r.zrem(queued_song_jams_key, userid)
        logger.info("jam removed for " +  userid)

    def already_jammed(self, queued_song_jams_key, userid):
        jams_on_queued_song = self.get_jams(queued_song_jams_key)
        jammed = False
        for jam in jams_on_queued_song:
            if jam['user'] == userid:
                jammed = True
                logger.info(queued_song_jams_key + " already jammed by " + userid)
                break
        return jammed

    def jam(self, id, userid):
        queued_song_jams_key = 'QUEUEJAM|{0}'.format(id)
        userid = userid.lower()
        if self.already_jammed(queued_song_jams_key, userid):
            self.remove_jam(queued_song_jams_key, userid)
        else:
            self.add_jam(queued_song_jams_key, userid)
        self._r.expire(queued_song_jams_key, 24*60*60)

        if self._r.zrank('MISC|priority-queue', id) is not None:
            self._msg('playlist_update')
        else:
            self._msg('now_playing_update')
        if self.num_jams(queued_song_jams_key) >= CONF.FREE_AIRHORN:
            user = self.get_now_playing()['user']
            self._r.sadd('FREEHORN_{0}'.format(user), id)
            self._msg('update_freehorn')


    def add_comment(self, id, userid, text):
        comments_key = 'COMMENTS|{0}'.format(id)
        self._r.zadd(comments_key, {"{0}||{1}".format(userid.lower(), text): int(time.time())})
        self._r.expire(comments_key, 24*60*60)
        logger.info('comment by {0} at {1}: "{2}"'.format(userid, time.ctime(), text))
        self._msg('playlist_update')

    def get_comments(self, id):
        key = 'COMMENTS|{0}'.format(id)
        raw_comments = self._r.zrange(key, 0, self._r.zcard(key), withscores=True)
        comments = []
        for text, secs in raw_comments:
            parts = text.split('||')
            comments.append({'time': secs,
                             'user': parts[0],
                             'body': parts[1] if len(parts) > 1 else ''})
        logger.debug("comments for %s: %s" % (id, comments))
        return comments


    def benderqueue(self, trackId, userid):
        # Check throwback queue first
        throwbackFrontId = self._r.lindex('MISC|throwback-songs', 0)
        if trackId == throwbackFrontId:
            self._r.lpop('MISC|throwback-songs')
            original_user = self._r.hget('MISC|throwback-users', trackId) or 'the@echonest.com'
            self._r.hdel('MISC|throwback-users', trackId)
            newId = self.add_spotify_song(userid, throwbackFrontId)
            self.jam(newId, original_user)
            return

        frontId = self._r.lindex('MISC|fill-songs', 0)
        if trackId == frontId:
            self._r.lpop('MISC|fill-songs')
            newId = self.add_spotify_song(userid, frontId)
            self.jam(newId, 'the@echonest.com')

    def benderfilter(self, trackId, userid):
        # Check throwback queue first
        throwbackFrontId = self._r.lindex('MISC|throwback-songs', 0)
        logger.debug("benderfilter called: trackId=%s, throwbackFrontId=%s", trackId, throwbackFrontId)
        if trackId == throwbackFrontId:
            self._r.lpop('MISC|throwback-songs')
            self._r.hdel('MISC|throwback-users', trackId)
            self._r.setex('FILTER|%s' % trackId, CONF.BENDER_FILTER_TIME, 1)
            self._msg('playlist_update')
            logger.info("benderfilter (throwback) " + str(trackId) + " by " + userid)
            return

        frontId = self._r.lindex('MISC|fill-songs', 0)
        logger.debug("benderfilter checking fill-songs: frontId=%s", frontId)
        if trackId == frontId:
            #take this off bender's preview and add it to the filter
            self._r.lpop('MISC|fill-songs')
            self._r.setex('FILTER|%s' % frontId, CONF.BENDER_FILTER_TIME, 1)
            self._msg('playlist_update')
            logger.info("benderfilter " + str(frontId) + " by " + userid)
        else:
            logger.warning("benderfilter mismatch: trackId=%s != frontId=%s (throwback=%s)", trackId, frontId, throwbackFrontId)


    def get_song_from_queue(self, id):
        key = 'QUEUE|{0}'.format(id)
        data = self._r.hgetall(key)
        if 'duration' in data:
            try:
                data['duration'] = int(float(data['duration']))
            except (ValueError, TypeError):
                data['duration'] = 0
        if 'auto' in data:
            data['auto'] = (data['auto'] == 'True')
        else:
            data['auto'] = False
        data['jam'] = self.get_jams('QUEUEJAM|{0}'.format(id))
        data['comments'] = self.get_comments(id)
        return data or {}

    def set_song_in_queue(self, id, data):
        key = 'QUEUE|{0}'.format(id)
        # Redis requires string values - serialize complex types
        serialized_data = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                serialized_data[k] = json.dumps(v)
            elif isinstance(v, bool):
                serialized_data[k] = str(v)
            elif isinstance(v, datetime.datetime):
                serialized_data[k] = v.isoformat()
            elif v is None:
                serialized_data[k] = ''
            else:
                serialized_data[k] = str(v) if not isinstance(v, str) else v
        self._r.hset(key, mapping=serialized_data)
        self._r.expire(key, 24*60*60)

    def nuke_queue(self, email):
        self._r.zremrangebyrank('MISC|priority-queue', 0, -1)
        self._msg('playlist_update')

    def kill_song(self, id, email):
        self._r.zrem('MISC|priority-queue', id)
        self._msg('playlist_update')

    def get_additional_src(self):
        raw = self._r.hgetall('MISC|backup-queue-data')
        if not raw:
            # Avoid infinite loops if fill songs can't be fetched (e.g., invalid Spotify creds)
            for _ in range(5):
                try:
                    self.ensure_fill_songs()  # so we have something to preview
                except Exception as e:
                    logger.warning("Failed to ensure fill songs: %s", e)
                    break

                # Check throwback queue first - show original user
                throwbackSong = self._r.lindex('MISC|throwback-songs', 0)
                if throwbackSong:
                    try:
                        original_user = self._r.hget('MISC|throwback-users', throwbackSong) or 'the@echonest.com'
                        fillInfo = self.get_fill_info(throwbackSong)
                        title = fillInfo['title']
                        fillInfo['title'] = fillInfo['artist'] + " : " + title
                        # Show original user's name instead of Benderbot
                        fillInfo['name'] = original_user.split('@')[0] + " (throwback)"
                        fillInfo['user'] = original_user
                        fillInfo['playlist_src'] = True
                        fillInfo["dm_buttons"] = False
                        fillInfo["jam"] = []
                        return fillInfo
                    except Exception:
                        logger.error('throwback song not available: %s', throwbackSong)
                        logger.error('backtrace: %s', traceback.format_exc())
                        self._r.lpop('MISC|throwback-songs')
                        self._r.hdel('MISC|throwback-users', throwbackSong)
                        continue

                fillSong = self._r.lindex('MISC|fill-songs', 0)
                if not fillSong:
                    break
                # show bender preview!
                try:
                    fillInfo = self.get_fill_info(fillSong)
                    title = fillInfo['title']
                    fillInfo['title'] = fillInfo['artist'] + " : " + title
                    fillInfo['name'] = 'Benderbot'
                    fillInfo['user'] = 'the@echonest.com'
                    fillInfo['playlist_src'] = True
                    fillInfo["dm_buttons"] = False
                    fillInfo["jam"] = []
                    return fillInfo
                except Exception:
                    logger.error('song not available in this region: %s', fillSong)
                    logger.error('backtrace just to be sure: %s', traceback.format_exc())
                    self._r.lpop('MISC|fill-songs')

            # Fallback when fill songs are unavailable; prevents /queue timeout
            return {'playlist_src': True, 'name': 'Benderbot', 'user': 'the@echonest.com',
                    'title': 'No songs available', 'img': '', 'jam': [], 'dm_buttons': False}

        raw['playlist_src'] = True
        return raw

    def get_queued(self):
        songs = self._r.zrange('MISC|priority-queue', 0, -1, withscores=True)
        rv = []
        for k in songs:
            data = self.get_song_from_queue(k[0])
            if not data:
                continue
            data["score"] = k[1]
            rv.append(data)
        rv.append(self.get_additional_src())
        return rv

    def pop_next(self):
        while True:
            song = self._r.zrange('MISC|priority-queue', 0, 0)
            if not song:
                self._r.delete('MISC|now-playing')
                return {}
            song = song[0]
            self._r.zrem('MISC|priority-queue', song)
            data = self.get_song_from_queue(song)
            if (data and data['src'] == 'spotify'
                    and data['user'] != 'the@echonest.com'):
                #got something from a human, set last-queued and clear fill-songs
                self._r.set('MISC|last-queued', data['trackid'])
                self._r.delete('MISC|fill-songs')
                try:
                    self.ensure_fill_songs()
                except Exception as e:
                    logger.warning("Failed to ensure fill songs: %s", e)
                self._r.delete('MISC|bender_streak_start')

            if not data:
                continue

            self._r.expire('QUEUE|{0}'.format(song), 3*60*60)
            self._r.setex('MISC|now-playing', 2*60*60, song)
            self._r.setex('MISC|now-playing-done', data['duration'], song)
            self._msg('now_playing_update')
            return data

    def song_end_time(self, use_estimate=True):
        '''
        return end time for the current song.

        either use the estimate of when it will end (if it's still playing)
        or the current time, if we're logging that it's finished / been skipped
        '''
        end_time = None
        if use_estimate:
            end_time = self._r.get('MISC|current-done')
            if end_time:
                end_time = pickle_load_b64(end_time).isoformat()

        if not end_time:
            end_time = self.player_now().isoformat()
        return end_time

    def get_now_playing(self):
        rv = {}
        song = self._r.get('MISC|now-playing')
        if song:
            rv = self.get_song_from_queue(song)
            p_endtime = self._r.get('MISC|current-done')
            rv['starttime'] = self._r.get('MISC|started-on')
            rv['endtime'] = self.song_end_time(use_estimate=True)
            rv['pos'] = 0
            if p_endtime:
                remaining = (pickle_load_b64(p_endtime) - self.player_now()).total_seconds()
                rv['pos'] = int(max(0,rv['duration'] - remaining))

        paused = self._r.get('MISC|paused')
        rv['paused'] = False
        if paused:
            rv['paused'] = True
        return rv

    def get_last_played(self):
        return self._r.get('MISC|last-played')

    def get_current_airhorns(self):
        return self._r.lrange('AIRHORNS', 0, -1)

    def vote(self, userid, id, up):
        norm_color = [34, 34, 34]
        base_hot = [34, 34, 34]
        hot_color = [68, 68, 68]
        cold_color = [0, 0, 0]
        user = self.get_song_from_queue(id).get('user', '')
        self_down = user == userid and not up
        s_id = 'QUEUE|VOTE|{0}'.format(id)
        if (not self_down and
                (self._r.sismember(s_id, userid)
                 and userid.lower() not in CONF.SPECIAL_PEOPLE)):
            logger.info("not special, not self down, already voted")
            return

        self._r.sadd(s_id, userid)
        exist_rank = self._r.zrank('MISC|priority-queue', id)
        logger.info("existing rank is:" + str(exist_rank))
        if up:
            low_rank = exist_rank - 2
        else:
            low_rank = exist_rank + 1

        high_rank = low_rank + 1
        logger.info("low_rank:" + str(low_rank))
        logger.info("high_rank:" + str(high_rank))
        ids = self._r.zrange('MISC|priority-queue', max(low_rank, 0), high_rank)
        logger.info("ids:" + str(ids))
        if len(ids) == 0:
            return #nothing to do here
        low_id = ids[0]
        current_score = self._r.zscore('MISC|priority-queue', id)
        logger.info("current_score:" + str(current_score))
        low_score = self._r.zscore('MISC|priority-queue', low_id)
        logger.info("low_score:" + str(low_score))
        if len(ids) == 1:
            if low_rank == -1:
                #before first
                new_score = low_score - 120.0
            else:
                #after last
                new_score = low_score + 120.0
        else:
            high_id = ids[1]
            high_score = self._r.zscore('MISC|priority-queue', high_id)
            logger.info("high_score:" + str(high_score))
            new_score = (low_score + high_score) / 2

        queue_key = 'QUEUE|{0}'.format(id)

        if up:
            self._r.hincrby(queue_key, "vote", 1)
        elif not self_down:
            self._r.hincrby(queue_key, "vote", -1)

        votes = int(self._r.hget(queue_key, "vote"))

        steps = 5
        if votes > 0:
            other_color = hot_color
            base_color = base_hot
        else:
            # 0 goes here
            other_color = cold_color
            base_color = norm_color

        votes = abs(votes)
        votes = min(votes, 5)

        color_string = ""
        color_sum = 0
        for i in range(3):
            new_color = ((votes * other_color[i]) + ((steps - votes) * base_color[i])) // steps
            color_sum += new_color
            color_string += "{:02x}".format(int(new_color))



        # set background color
        self._r.hset(queue_key, "background_color", color_string)
        if color_sum > (130 * 3):
            self._r.hset(queue_key, "foreground_color", "0f0f0f")
        else:
            self._r.hset(queue_key, "foreground_color", "f0f0ff")

        size = new_score - current_score
        logger.info("size:" + str(size))
        self._r.zincrby('MISC|priority-queue', size, id)
        self._msg('playlist_update')

    def kill_playing(self, email):
        self._r.set('MISC|force-jump', 1)

    def pause(self, email):
        self._r.set('MISC|paused', 1)
        self._msg('now_playing_update')

    def unpause(self, email):
        self._r.delete('MISC|paused')
        self._msg('now_playing_update')

    def trim_horns(self):
        logger.debug("TRIM HORNS")
        expire = _now() - datetime.timedelta(seconds=CONF.AIRHORN_EXPIRE_SEC)
        logger.debug("now %s", _now())
        expire = expire.isoformat()
        logger.debug("expire %s", expire)
        horns = self.get_horns()
        if not horns or len(horns) < CONF.AIRHORN_LIST_MIN_LEN:
            logger.info('no airhorns currently; nothing to trim')
            return

        popped = 0
        for horn in horns:
            if horn['when'] < expire:
                self._r.lpop('AIRHORNS')
                popped += 1
                if popped >= CONF.AIRHORN_EXPIRE_COUNT or len(horns) - popped < CONF.AIRHORN_LIST_MIN_LEN:
                    break

    def get_horns(self):
        raw = self._r.lrange('AIRHORNS', 0, -1)
        rv = []
        for x in raw:
            rv.append(json.loads(x))
        rv.reverse()
        return rv

    def _do_horn(self, userid, free, name=None):
        playing = self.get_now_playing()
        if not playing:
            logger.warning("Cannot airhorn - no song playing")
            return
        horn = dict(img=playing.get('img', ''),
                    songid=playing.get('id', ''),
                    when=_now().isoformat(),
                    free=free, user=userid, artist=playing.get('artist', ''),
                    title=playing.get('title', ''))
        self._r.rpush('AIRHORNS', json.dumps(horn))
        self._msg('do_airhorn|0.4|%s' % name)  # volume of airhorn - may need to be tweaked, random choice for airhorn

    def airhorn(self, userid, name):
        self.trim_horns()
        horns = self.get_horns()
        if len([x for x in horns if not x['free']]) >= CONF.AIRHORN_MAX:
            return
        self._do_horn(userid, False, name)

    def free_airhorn(self, userid):
        self.trim_horns()
        s = self._r.spop('FREEHORN_{0}'.format(userid))
        if s:
            self._msg('update_freehorn')
            self._do_horn(userid, True)

    def get_free_horns(self, userid):
        return self._r.scard('FREEHORN_{0}'.format(userid))

    def get_volume(self):
        if not self._r.exists('MISC|volume'):
            self._r.set('MISC|volume', 95)

        rv = int(self._r.get('MISC|volume'))
        return rv

    def set_volume(self, new_vol):
        new_vol = max(0, int(new_vol))
#        print new_vol
        new_vol = min(100, new_vol)
        print("set_volume", new_vol)
        self._r.set('MISC|volume', new_vol)
        self._msg('v|'+str(new_vol))
        logger.info('set_volume in pct %s', new_vol)
        return new_vol

    def _msg(self, msg):
        self._r.publish('MISC|update-pubsub', msg)

    def try_login(self, email, passwd):
        email = email.lower()
        d = self._r.hget('MISC|guest-login-expire', email)
        if not d or pickle_load_b64(d) < _now():
            self._r.hdel('MISC|guest-login', email)
            return False
        full_pass = self._r.hget('MISC|guest-login', email)
        if full_pass and (full_pass == passwd):
            return email
        return None

    def send_email(self, target, subject, body):
        if isinstance(target, str):
            target = [target]
        msg = "To: {0}\nFrom: {1}\nSubject: {2}\n\n{3}"
        msg = msg.format(', '.join(target), CONF.SMTP_FROM,
                            subject, body)
        smtp = smtplib.SMTP(CONF.SMTP_HOST)
        smtp.login(CONF.SMTP_USER, CONF.SMTP_PASS)
        smtp.sendmail(CONF.SMTP_FROM, target, msg)


    def add_login(self, email, expires):
        email = email.lower()
        #Weak passwords, but humans will remember 'em.
        words = [x.strip() for x in open('/usr/share/dict/words').readlines()
                    if 4 < len(x) < 8]
        random.shuffle(words)
        passwd = ''.join(x.title() for x in words[:2])
        self._r.hset('MISC|guest-login-expire', email, pickle_dump_b64(expires))
        self._r.hset('MISC|guest-login', email, passwd)
        self.send_email(email, "Welcome to Andre!",
                        render_template('welcome_email.txt',
                            expires=expires, email=email,
                            passwd=passwd))

    def _airhorners_for_song_log(self, id):
        found_airhorns = []
        stored_airhorns = self._r.lrange('AIRHORNS', 0, -1)
        # list not set because airhorn stattos may want to see when users do multiple horns on a song
        for stored_airhorn in stored_airhorns:
            aj = json.loads(stored_airhorn)
            if 'songid' in aj and aj['songid'] == id:
                found_airhorns.append({'user': aj['user'],
                                       'when': aj['when'],
                                       'free': aj['free']})
        return found_airhorns

    def log_finished_song(self, song):
        if not "id" in song:
            #nothing to log here, people
            return

        id = song['id']
        song['endtime'] = self.song_end_time(False)
        song['jam'] = self.get_jams('QUEUEJAM|{0}'.format(id))
        song['airhorn'] = self._airhorners_for_song_log(id)
        cleaned_song = _clean_song(song)
        song_json = json.dumps(cleaned_song, sort_keys=True)
        self._r.set('MISC|last-played', song_json)
        _log_play(song_json)
        self._h.add_play(song_json)

    def get_historian(self):
        return self._h
