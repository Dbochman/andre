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
if not os.environ.get('SKIP_SPOTIFY_PREFETCH'):
    auth.get_access_token()

# SoundCloud OAuth token cache (shared across all uses)
_soundcloud_token = None
_soundcloud_token_expires = 0

def get_soundcloud_token():
    """Get a valid SoundCloud OAuth token using client_credentials flow."""
    global _soundcloud_token, _soundcloud_token_expires

    # Return cached token if still valid (with 60s buffer)
    if _soundcloud_token and time.time() < _soundcloud_token_expires - 60:
        return _soundcloud_token

    # Fetch new token
    if not CONF.SOUNDCLOUD_CLIENT_ID or not CONF.SOUNDCLOUD_CLIENT_SECRET:
        logger.warning("SoundCloud not configured: missing client_id or client_secret")
        return None

    try:
        resp = requests.post('https://api.soundcloud.com/oauth2/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': CONF.SOUNDCLOUD_CLIENT_ID,
                'client_secret': CONF.SOUNDCLOUD_CLIENT_SECRET,
            },
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        _soundcloud_token = data['access_token']
        _soundcloud_token_expires = time.time() + data.get('expires_in', 3600)
        logger.info("Fetched new SoundCloud OAuth token (expires in %ds)", data.get('expires_in', 3600))
        return _soundcloud_token
    except Exception as e:
        logger.error("Failed to get SoundCloud token: %s", e)
        return None

# Global rate limit tracker - uses Redis for persistence across container restarts
_rate_limit_redis = None

def _get_rate_limit_redis():
    """Get a Redis connection for rate limit tracking."""
    global _rate_limit_redis
    if _rate_limit_redis is None:
        _rate_limit_redis = redis.StrictRedis(
            host=CONF.REDIS_HOST or 'localhost',
            port=CONF.REDIS_PORT or 6379,
            password=CONF.REDIS_PASSWORD or None,
            decode_responses=True
        )
    return _rate_limit_redis

def is_spotify_rate_limited():
    """Check if we're currently rate limited by Spotify (persisted in Redis)."""
    try:
        r = _get_rate_limit_redis()
        ttl = r.ttl('MISC|spotify-rate-limited')
        if ttl and ttl > 0:
            logger.debug("Spotify rate limited for %d more seconds", ttl)
            return True
        return False
    except Exception as e:
        logger.warning("Error checking rate limit: %s", e)
        return False

def set_spotify_rate_limit(retry_after_seconds):
    """Set the rate limit expiry time (stored in Redis)."""
    try:
        r = _get_rate_limit_redis()
        r.setex('MISC|spotify-rate-limited', int(retry_after_seconds), '1')
        logger.warning("Spotify rate limited for %d seconds", retry_after_seconds)
    except Exception as e:
        logger.warning("Error setting rate limit: %s", e)

def handle_spotify_exception(e):
    """Check if exception is a rate limit and set tracker. Returns True if rate limited."""
    if hasattr(e, 'http_status') and e.http_status == 429:
        retry_after = 3600  # Default 1 hour
        if hasattr(e, 'headers') and e.headers:
            retry_after = int(e.headers.get('Retry-After', 3600))
        set_spotify_rate_limit(retry_after)
        return True
    return False


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
    STRATEGY_WEIGHTS_DEFAULT = {
        'genre': 35, 'throwback': 30, 'artist_search': 25, 'top_tracks': 5, 'album': 5,
    }

    # Maps strategy name to its Redis cache key suffix (bare keys, resolved via _cache_key())
    _STRATEGY_CACHE_KEYS = {
        'genre': 'BENDER|cache:genre',
        'throwback': 'BENDER|cache:throwback',
        'artist_search': 'BENDER|cache:artist-search',
        'top_tracks': 'BENDER|cache:top-tracks',
        'album': 'BENDER|cache:album',
    }

    def _cache_key(self, strategy):
        """Resolve a strategy name to its nest-scoped Redis cache key."""
        bare = self._STRATEGY_CACHE_KEYS.get(strategy)
        if bare is None:
            return None
        return self._key(bare)

    def __init__(self, init_history_to_redis=True, nest_id="main", redis_client=None):
        logger.info('Creating DB object (nest_id=%s)', nest_id)
        self.nest_id = nest_id
        if redis_client is not None:
            self._r = redis_client
        else:
            redis_host = CONF.REDIS_HOST or 'localhost'
            redis_port = CONF.REDIS_PORT or 6379
            redis_password = CONF.REDIS_PASSWORD or None
            self._r = redis.StrictRedis(host=redis_host, port=redis_port, password=redis_password, decode_responses=True)
        if redis_client is None:
            self._h = PlayHistory(self)
            if init_history_to_redis:
                self._h.init_history()
        else:
            self._h = None
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

    def _key(self, key):
        """Prefix a Redis key with the nest namespace."""
        return f"NEST:{self.nest_id}|{key}"

    def _check_nest_active(self):
        """Raise RuntimeError if this nest is being deleted. Skips check for main."""
        if self.nest_id == "main":
            return
        from nests import is_nest_deleting
        if is_nest_deleting(self._r, self.nest_id):
            raise RuntimeError("Nest is being deleted")

    def big_scrobble(self, email, tid):
        #add played song to FILTER "set"
        self._r.setex(self._key("FILTER|%s"% tid), CONF.BENDER_FILTER_TIME, 1)

    # ── Bender: Per-Song Strategy Rotation ──────────────────────────

    def _resolve_seed_uri(self):
        """Resolve the best seed track URI for Bender recommendations.

        Checks last-queued → last-bender-track → now-playing → Billy Joel fallback.
        Returns a full spotify:track:xxx URI string.
        """
        def is_valid_track_seed(uri):
            if not uri:
                return False
            return ':episode:' not in uri

        candidate = self._r.get(self._key('MISC|last-queued'))
        if is_valid_track_seed(candidate):
            return candidate

        candidate = self._r.get(self._key('MISC|last-bender-track'))
        if is_valid_track_seed(candidate):
            return candidate

        now_playing_id = self._r.get(self._key('MISC|now-playing'))
        if now_playing_id:
            candidate = self._r.hget(self._key('QUEUE|{}'.format(now_playing_id)), 'trackid')
            if is_valid_track_seed(candidate):
                return candidate

        logger.debug("Using fallback seed (no valid track seeds found)")
        return "spotify:track:3utq2FgD1pkmIoaWfjXWAU"

    def _get_seed_info(self):
        """Fetch and cache seed artist metadata in BENDER|seed-info hash.

        Returns dict with keys: artist_id, artist_name, album_id, genres, seed_uri
        or None if unable to resolve.
        """
        seed_uri = self._resolve_seed_uri()
        track_id = seed_uri.split(":")[-1]

        # Check cache
        cached = self._r.hgetall(self._key('BENDER|seed-info'))
        if cached and cached.get('seed_uri') == seed_uri:
            cached['genres'] = json.loads(cached.get('genres', '[]'))
            return cached

        # Stale or missing — delete and re-fetch
        if cached:
            self._r.delete(self._key('BENDER|seed-info'))

        if is_spotify_rate_limited():
            logger.debug("_get_seed_info: Spotify rate limited")
            return None

        try:
            song_deets = spotify_client.track(track_id)
            artists = song_deets.get('artists', [])
            if not artists:
                return None
            artist_id = artists[0]['id']
            artist_name = artists[0]['name']
            album_id = song_deets.get('album', {}).get('id', '')

            # Fetch genres from artist endpoint
            artist_data = spotify_client.artist(artist_id)
            genres = artist_data.get('genres', [])
        except Exception as e:
            if handle_spotify_exception(e):
                return None
            logger.warning("Error getting seed info for %s: %s", track_id, e)
            return None

        info = {
            'artist_id': artist_id,
            'artist_name': artist_name,
            'album_id': album_id,
            'genres': json.dumps(genres),
            'seed_uri': seed_uri,
        }
        self._r.hset(self._key('BENDER|seed-info'), mapping=info)
        self._r.expire(self._key('BENDER|seed-info'), 60 * 20)

        info['genres'] = genres
        return info

    def _get_strategy_weights(self):
        """Return strategy weights dict from config or default."""
        weights = getattr(CONF, 'BENDER_STRATEGY_WEIGHTS', None)
        if weights and isinstance(weights, dict):
            return dict(weights)
        return dict(self.STRATEGY_WEIGHTS_DEFAULT)

    def _select_strategy_excluding(self, exclude_set):
        """Weighted random pick from strategies, filtering out exclude_set.

        Returns strategy name string or None if all exhausted.
        """
        weights = self._get_strategy_weights()
        remaining = {k: v for k, v in weights.items()
                     if k not in exclude_set and v > 0}
        if not remaining:
            return None
        strategies = list(remaining.keys())
        weight_values = [remaining[s] for s in strategies]
        return random.choices(strategies, weights=weight_values, k=1)[0]

    @property
    def _bender_fetch_limit(self):
        """Number of tracks to request from Spotify per cache fill."""
        return 5 if self.nest_id != "main" else 20

    def _fill_strategy_cache(self, strategy, seed_info):
        """Dispatch to the appropriate fetch method and cache results.

        Returns count of tracks cached.
        """
        if is_spotify_rate_limited() and strategy != 'throwback':
            return 0

        market = CONF.BENDER_REGIONS[0] if CONF.BENDER_REGIONS else 'US'
        seed_uri = seed_info.get('seed_uri', '') if seed_info else ''
        limit = self._bender_fetch_limit

        if strategy == 'throwback':
            return self._fill_throwback_cache()
        elif strategy == 'genre':
            uris = self._fetch_genre_tracks(seed_info, market, limit)
        elif strategy == 'artist_search':
            uris = self._fetch_artist_search_tracks(seed_info, market, limit)
        elif strategy == 'top_tracks':
            uris = self._fetch_top_tracks(seed_info, market)
        elif strategy == 'album':
            uris = self._fetch_album_tracks(seed_info)
        else:
            return 0

        # Filter: remove seed, FILTER'd tracks, and dedupe
        filtered = []
        seen = set()
        for uri in uris:
            if uri == seed_uri:
                continue
            if uri in seen:
                continue
            if self._r.get(self._key("FILTER|%s" % uri)):
                continue
            seen.add(uri)
            filtered.append(uri)

        random.shuffle(filtered)

        if not filtered:
            return 0

        cache_key = self._cache_key(strategy)
        self._r.rpush(cache_key, *filtered)
        self._r.expire(cache_key, 60 * 20)
        logger.debug("Cached %d tracks for strategy %s", len(filtered), strategy)
        return len(filtered)

    def _fetch_genre_tracks(self, seed_info, market, limit=20):
        """Search Spotify by one of the seed artist's genres."""
        if not seed_info:
            return []
        genres = seed_info.get('genres', [])
        if not genres:
            return []
        genre = random.choice(genres)
        try:
            results = spotify_client.search(q='genre:"%s"' % genre, type='track',
                                            limit=limit, market=market)
            return [t['uri'] for t in results.get('tracks', {}).get('items', [])]
        except Exception as e:
            if handle_spotify_exception(e):
                return []
            logger.warning("Error fetching genre tracks for '%s': %s", genre, e)
            return []

    def _fetch_artist_search_tracks(self, seed_info, market, limit=20):
        """Search Spotify by artist name to find collabs/features."""
        if not seed_info:
            return []
        artist_name = seed_info.get('artist_name', '')
        if not artist_name:
            return []
        try:
            results = spotify_client.search(artist_name, limit=limit,
                                            type='track', market=market)
            return [t['uri'] for t in results.get('tracks', {}).get('items', [])]
        except Exception as e:
            if handle_spotify_exception(e):
                return []
            logger.warning("Error searching for artist '%s': %s", artist_name, e)
            return []

    def _fetch_top_tracks(self, seed_info, market):
        """Get top tracks from the seed artist."""
        if not seed_info:
            return []
        artist_id = seed_info.get('artist_id', '')
        if not artist_id:
            return []
        try:
            result = spotify_client.artist_top_tracks(artist_id, country=market)
            return [t['uri'] for t in result.get('tracks', [])]
        except Exception as e:
            if handle_spotify_exception(e):
                return []
            logger.warning("Error getting top tracks for artist %s: %s", artist_id, e)
            return []

    def _fetch_album_tracks(self, seed_info):
        """Get tracks from the seed album."""
        if not seed_info:
            return []
        album_id = seed_info.get('album_id', '')
        if not album_id:
            return []
        try:
            result = spotify_client.album_tracks(album_id)
            return [t['uri'] for t in result.get('items', [])]
        except Exception as e:
            if handle_spotify_exception(e):
                return []
            logger.warning("Error getting album tracks for %s: %s", album_id, e)
            return []

    def _fill_throwback_cache(self):
        """Fill the throwback cache from historical play logs.

        Uses a pipeline for atomic track+user storage. Returns count cached.
        """
        try:
            throwback_plays = self._h.get_throwback_plays(limit=20)
        except Exception:
            logger.warning("Error getting throwback tracks: %s", traceback.format_exc())
            return 0

        if not throwback_plays:
            return 0

        pipe = self._r.pipeline()
        count = 0
        for play in throwback_plays:
            track_uri = play.get('trackid')
            original_user = play.get('user', 'the@echonest.com')
            if not track_uri:
                continue
            if self._r.get(self._key("FILTER|%s" % track_uri)):
                continue
            pipe.rpush(self._key('BENDER|cache:throwback'), track_uri)
            pipe.hset(self._key('BENDER|throwback-users'), track_uri, original_user)
            count += 1
        if count > 0:
            pipe.execute()
            self._r.expire(self._key('BENDER|cache:throwback'), 60 * 20)
            self._r.expire(self._key('BENDER|throwback-users'), 60 * 20)
        logger.debug("Cached %d throwback tracks", count)
        return count

    def _clear_all_bender_caches(self):
        """Delete all BENDER| cache keys."""
        keys = [self._key(k) for k in self._STRATEGY_CACHE_KEYS.values()] + [
            self._key('BENDER|seed-info'), self._key('BENDER|throwback-users'), self._key('BENDER|next-preview'),
        ]
        self._r.delete(*keys)

    def _peek_next_fill_song(self):
        """Non-consuming peek at the next Bender fill song.

        Returns (track_uri, user, strategy) or (None, None, None).
        Stores result in BENDER|next-preview for benderqueue/benderfilter.
        """
        # Check existing preview
        preview = self._r.hgetall(self._key('BENDER|next-preview'))
        if preview and preview.get('trackid'):
            track_uri = preview['trackid']
            if not self._r.get(self._key("FILTER|%s" % track_uri)):
                return track_uri, preview.get('user', 'the@echonest.com'), preview.get('strategy', '')

            # Preview is now filtered; clear it
            self._r.delete(self._key('BENDER|next-preview'))

        # Use weighted random selection, falling through on failure
        seed_info = None  # lazy-loaded
        tried = set()

        while True:
            strategy = self._select_strategy_excluding(tried)
            if not strategy:
                break

            cache_key = self._cache_key(strategy)
            if not cache_key:
                tried.add(strategy)
                continue

            track_uri = self._r.lindex(cache_key, 0)

            # If cache empty, try to fill it
            if not track_uri:
                if seed_info is None:
                    seed_info = self._get_seed_info()
                filled = self._fill_strategy_cache(strategy, seed_info)
                if filled > 0:
                    track_uri = self._r.lindex(cache_key, 0)

            if not track_uri:
                tried.add(strategy)
                continue

            # Skip if filtered — drain filtered tracks from front of cache
            if self._r.get(self._key("FILTER|%s" % track_uri)):
                while track_uri and self._r.get(self._key("FILTER|%s" % track_uri)):
                    self._r.lpop(cache_key)
                    track_uri = self._r.lindex(cache_key, 0)
                if not track_uri:
                    tried.add(strategy)
                    continue

            # Determine user
            if strategy == 'throwback':
                user = self._r.hget(self._key('BENDER|throwback-users'), track_uri) or 'the@echonest.com'
            else:
                user = 'the@echonest.com'

            # Store preview
            self._r.hset(self._key('BENDER|next-preview'), mapping={
                'trackid': track_uri,
                'user': user,
                'strategy': strategy,
            })
            return track_uri, user, strategy

        return None, None, None

    def ensure_queue_depth(self):
        """Top up the priority queue to MIN_QUEUE_DEPTH with Bender songs.

        Called after popping a song so there's always something on deck.
        Respects USE_BENDER and MAX_BENDER_MINUTES settings.
        """
        min_depth = getattr(CONF, 'MIN_QUEUE_DEPTH', None) or 3
        # Temporary nests keep a smaller buffer to reduce Spotify API pressure
        if self.nest_id != "main":
            min_depth = 1
        if not CONF.USE_BENDER:
            return
        queue_size = self._r.zcard(self._key('MISC|priority-queue'))
        if queue_size >= min_depth:
            return
        needed = min_depth - queue_size
        logger.info("Queue depth %d < %d, adding %d Bender tracks", queue_size, min_depth, needed)
        added = 0
        for _ in range(needed):
            if self.bender_streak() > CONF.MAX_BENDER_MINUTES * 60:
                logger.info("Bender streak limit reached, stopping backfill")
                break
            try:
                user, trackid = self.get_fill_song()
                if user and trackid:
                    self.add_spotify_song(user, trackid, scrobble=False)
                    added += 1
                else:
                    break
            except Exception:
                logger.warning("ensure_queue_depth: couldn't add song: %s", traceback.format_exc())
                break
        if added > 0:
            logger.info("Backfilled %d tracks to maintain queue depth", added)

    def ensure_fill_songs(self):
        """Lazy pre-warm: ensure at least one strategy cache has tracks."""
        for strategy in self._STRATEGY_CACHE_KEYS:
            cache_key = self._cache_key(strategy)
            if self._r.llen(cache_key) > 0:
                return  # At least one cache is warm

        # All caches empty — fill the first strategy that succeeds
        seed_info = self._get_seed_info()
        if not seed_info:
            logger.warning("ensure_fill_songs: couldn't resolve seed info")
            return

        weights = self._get_strategy_weights()
        for strategy in sorted(weights.keys(), key=lambda s: weights[s], reverse=True):
            if weights[strategy] <= 0:
                continue
            filled = self._fill_strategy_cache(strategy, seed_info)
            if filled > 0:
                logger.debug("ensure_fill_songs: pre-warmed %s with %d tracks", strategy, filled)
                return

        logger.warning("Bender couldn't find any tracks - all strategies exhausted")

    def get_fill_song(self):
        """Get the next fill song using per-song weighted strategy rotation.

        Consumes the previewed track first (if one exists) so the UI preview
        and the actual queue stay in sync. Falls back to weighted strategy
        rotation if no preview is available.

        Returns (user, track_uri) or (None, None) if all strategies exhausted.
        """
        # Check backup queue first (unchanged)
        song = self._r.lpop(self._key('MISC|backup-queue'))
        if song:
            return self._r.hget(self._key('MISC|backup-queue-data'), 'user'), song
        self._r.delete(self._key('MISC|backup-queue-data'))

        # Consume the preview if one exists — this is the track the UI is showing
        preview = self._r.hgetall(self._key('BENDER|next-preview'))
        if preview and preview.get('trackid'):
            track = preview['trackid']
            strategy = preview.get('strategy', '')
            user = preview.get('user', 'the@echonest.com')

            # Pop it from the strategy cache
            cache_key = self._cache_key(strategy)
            if cache_key:
                self._r.lpop(cache_key)
            if strategy == 'throwback':
                self._r.hdel(self._key('BENDER|throwback-users'), track)
            self._r.delete(self._key('BENDER|next-preview'))

            # Verify it's not filtered since the preview was created
            if not self._r.get(self._key("FILTER|%s" % track)):
                self._r.set(self._key('MISC|last-bender-track'), track)
                logger.info("get_fill_song: strategy=%s, track=%s, user=%s (from preview)", strategy, track, user)
                return user, track
            # If filtered, fall through to normal rotation below

        if is_spotify_rate_limited():
            # Throwback doesn't need Spotify API, try it directly
            track = self._r.lpop(self._key('BENDER|cache:throwback'))
            if track:
                user = self._r.hget(self._key('BENDER|throwback-users'), track) or 'the@echonest.com'
                self._r.hdel(self._key('BENDER|throwback-users'), track)
                self._r.set(self._key('MISC|last-bender-track'), track)
                logger.info("get_fill_song: strategy=throwback, track=%s, user=%s", track, user)
                return user, track
            # Try to fill throwback cache
            if self._fill_throwback_cache() > 0:
                track = self._r.lpop(self._key('BENDER|cache:throwback'))
                if track:
                    user = self._r.hget(self._key('BENDER|throwback-users'), track) or 'the@echonest.com'
                    self._r.hdel(self._key('BENDER|throwback-users'), track)
                    self._r.set(self._key('MISC|last-bender-track'), track)
                    logger.info("get_fill_song: strategy=throwback, track=%s, user=%s", track, user)
                    return user, track
            return None, None

        seed_info = self._get_seed_info()
        tried = set()

        while True:
            strategy = self._select_strategy_excluding(tried)
            if strategy is None:
                logger.error("Bender exhausted all recommendation strategies")
                return None, None

            cache_key = self._cache_key(strategy)
            track = self._r.lpop(cache_key)

            # If cache empty, try to fill it
            if not track:
                if seed_info:
                    self._fill_strategy_cache(strategy, seed_info)
                track = self._r.lpop(cache_key)

            # If still empty, this strategy is exhausted
            if not track:
                tried.add(strategy)
                continue

            # Check if track is filtered; drain cache for a clean one
            while track and self._r.get(self._key("FILTER|%s" % track)):
                if strategy == 'throwback':
                    self._r.hdel(self._key('BENDER|throwback-users'), track)
                track = self._r.lpop(cache_key)

            if not track:
                tried.add(strategy)
                continue

            # Determine user
            if strategy == 'throwback':
                user = self._r.hget(self._key('BENDER|throwback-users'), track) or 'the@echonest.com'
                self._r.hdel(self._key('BENDER|throwback-users'), track)
            else:
                user = 'the@echonest.com'

            self._r.set(self._key('MISC|last-bender-track'), track)
            logger.info("get_fill_song: strategy=%s, track=%s, user=%s", strategy, track, user)
            return user, track

    def bender_streak(self):
        now = self.player_now()
        try:
            then = pickle_load_b64(self._r.get(self._key('MISC|bender_streak_start')))
            if then is None:
                then = _now()
            logger.debug("bender streak is %s seconds, now %s then %s" % ((now - then).total_seconds(), now, then))
        except Exception as _e:
            logger.debug("Exception getting MISC|bender_streak_start: %s; assuming no streak" % _e)
            then = _now()

        return (now - then).total_seconds()


    def master_player(self):
        id = str(uuid.uuid4())
        n = self._r.setnx(self._key('MISC|master-player'), id)
        while not n:
            time.sleep(5)
            n = self._r.setnx(self._key('MISC|master-player'), id)
        self._r.expire(self._key('MISC|master-player'), 5)
        #I'm the player.
        logger.info('Grabbing player')
        while True:

            song = self.get_now_playing()
            finish_on = self._r.get(self._key('MISC|current-done'))
            if finish_on and pickle_load_b64(finish_on) > self.player_now():
                done = pickle_load_b64(finish_on)
            else:
                if song and song.get('id'):
                    self.log_finished_song(song)

                song = self.pop_next()
                if not song:
                    logger.debug("streak start set %s"%self._r.setnx(self._key('MISC|bender_streak_start'), pickle_dump_b64(self.player_now())))
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

            # Top up queue so there's always something on deck
            try:
                self.ensure_queue_depth()
            except Exception:
                logger.warning("ensure_queue_depth failed: %s", traceback.format_exc())

            id = song['trackid']
            expire_on = int((done - self.player_now()).total_seconds())

            self._r.setex(self._key('MISC|current-done'),
                          expire_on,
                          pickle_dump_b64(done))
            self._r.set(self._key('MISC|started-on'),
                          self.player_now().isoformat())
            while self.player_now() < done:
                paused = self._r.get(self._key('MISC|paused'))
                if paused:
                    logger.info("paused at %s", self.player_now())
                    while paused:
                        time.sleep(1)
                        self._r.expire(self._key('MISC|master-player'), 10)
                        paused = self._r.get(self._key('MISC|paused'))
                    # Recalculate done: player_now didn't advance while paused,
                    # so the remaining time is still correct, but we need to
                    # refresh the MISC|current-done TTL since real time passed.
                    remaining = int((done - self.player_now()).total_seconds())
                    done = self.player_now() + datetime.timedelta(seconds=remaining, milliseconds=500)
                    expire_on = max(remaining, 1)
                    self._r.setex(self._key('MISC|current-done'), expire_on, pickle_dump_b64(done))
                    logger.info("unpaused, %d seconds remaining", remaining)
                self._r.expire(self._key('MISC|master-player'), 5)
                if self._r.get(self._key('MISC|force-jump')):
                    self._r.delete(self._key('MISC|force-jump'))
                    break
                self._add_now(1)
                time.sleep(1)
                remaining = int((done-self.player_now()).total_seconds())
                self._msg('pp|{0}|{1}|{2}'.format(song['src'], id, song['duration'] - remaining))
            self._r.delete(self._key('MISC|current-done'))
            self._r.delete(self._key('QUEUE|VOTE|{0}'.format(id)))
            self._r.delete(self._key('QUEUE|{0}'.format(id)))

    def player_now(self):
        t = self._r.get(self._key('MISC|player-now'))
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
        self._r.setex(self._key('MISC|player-now'), 12*3600, pickle_dump_b64(new_t))

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

        # Auto-fill songs (Bender) always go to the end of the queue.
        # The fair-scheduling interleave is only for human-queued songs.
        if song.get('auto'):
            return queued[-2]['score'] + 1.0

        # this counts how many tracks this user will have in the queue including this (so start from 1)
        this_user_songs_in_queue = 1
        for i in range(0, len(queued) - 1):
            x = queued[i]
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
        self._check_nest_active()
        id = self._r.incr(self._key('MISC|playlist-plays'))

        song.update(dict(background_color='222222',
                        foreground_color='F0F0FF',
                        user=userid, id = id, vote=0))
        self.set_song_in_queue(id, song)
        s_id = self._key('QUEUE|VOTE|{0}'.format(id))
        self._r.sadd(s_id, userid)
        self._r.expire(s_id, 24*60*60)
        score = self._score_track(userid, force_first, song) + penalty
        self._r.zadd(self._key('MISC|priority-queue'), {str(id): score})
        self._msg('playlist_update')
        return str(id)

    def _pluck_youtube_img(self, doc, height):
        for img in doc['snippet']['thumbnails'].values():
            if img['height'] >= height:
                return img['url']
        return ""

    # Easter egg overrides for special tracks
    SOUNDCLOUD_OVERRIDES = {
        '424374522': {  # for use in discord - NSA BANGERS by Crustypunk&Kidkale
            'title': 'NSA Bangers',
            'artist': 'TOLKEINBLACK',
            'big_img': 'https://thumbnailer.mixcloud.com/unsafe/580x580/extaudio/6/8/c/9/fa7b-eaaf-49e2-baad-1edc21320911.jpg',
            'img': 'https://thumbnailer.mixcloud.com/unsafe/580x580/extaudio/6/8/c/9/fa7b-eaaf-49e2-baad-1edc21320911.jpg',
        },
    }

    def add_soundcloud_song(self, userid, trackid, penalty=0):
        token = get_soundcloud_token()
        if not token:
            logger.error("Cannot add SoundCloud song: no OAuth token available")
            return

        response = requests.get(
            'https://api.soundcloud.com/tracks/{0}'.format(trackid),
            headers={'Authorization': 'OAuth {}'.format(token)},
            timeout=10
        )
        if response.status_code != 200:
            logger.error("SoundCloud API error %d for track %s", response.status_code, trackid)
            return

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
                    img=track['artwork_url'],
                    permalink_url=track.get('permalink_url'))

        # Apply easter egg overrides
        if str(trackid) in self.SOUNDCLOUD_OVERRIDES:
            song.update(self.SOUNDCLOUD_OVERRIDES[str(trackid)])

        self._add_song(userid, song, False, penalty=penalty)

    def add_youtube_song(self, userid, trackid, penalty=0):
        if not CONF.YT_API_KEY or CONF.YT_API_KEY == 'your-youtube-api-key':
            logger.error("YouTube API key not configured")
            return

        try:
            resp = requests.get('https://www.googleapis.com/youtube/v3/videos/',
                                params=dict(id=trackid, part='snippet,contentDetails', key=CONF.YT_API_KEY),
                                timeout=10)

            if resp.status_code != 200:
                logger.error("YouTube API error %d for video %s", resp.status_code, trackid)
                return

            data = resp.json()

            if not data.get('items'):
                logger.warning("YouTube video not found: %s", trackid)
                return

            response = data['items'][0]

            if 'coldplay' in response['snippet']['title'].lower():
                logger.info('{0} tried to add "{1}" by Coldplay (YT)'.format(
                    userid,
                    response['snippet']['title']))
                return

            song = dict(data=response, src='youtube', trackid=trackid,
                        title=response['snippet']['title'],
                        artist=response['snippet']['channelTitle'] + '@youtube',
                        duration=parse_yt_duration(response['contentDetails']['duration']),
                        big_img=self._pluck_youtube_img(response, 360),
                        auto=False,
                        img=self._pluck_youtube_img(response, 90))
            self._add_song(userid, song, False, penalty=penalty)

        except requests.exceptions.Timeout:
            logger.error("YouTube API timeout for video %s", trackid)
        except Exception as e:
            logger.error("Error adding YouTube song %s: %s", trackid, str(e))

    def get_fill_info(self, trackid):
        key = self._key('FILL-INFO|{0}'.format(trackid))

        raw_song = self._r.hgetall(key)
        if raw_song:
            return raw_song

        # Don't make Spotify API calls when rate limited
        if is_spotify_rate_limited():
            logger.debug("get_fill_info: Spotify rate limited, raising exception")
            raise Exception("Spotify rate limited")

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
        self._check_nest_active()
        queued_song_jams_key = self._key('QUEUEJAM|{0}'.format(id))
        userid = userid.lower()
        if self.already_jammed(queued_song_jams_key, userid):
            self.remove_jam(queued_song_jams_key, userid)
        else:
            self.add_jam(queued_song_jams_key, userid)
        self._r.expire(queued_song_jams_key, 24*60*60)

        if self._r.zrank(self._key('MISC|priority-queue'), id) is not None:
            self._msg('playlist_update')
        else:
            self._msg('now_playing_update')
        if self.num_jams(queued_song_jams_key) >= CONF.FREE_AIRHORN:
            user = self.get_now_playing()['user']
            self._r.sadd(self._key('FREEHORN_{0}'.format(user)), id)
            self._msg('update_freehorn')


    def add_comment(self, id, userid, text):
        self._check_nest_active()
        comments_key = self._key('COMMENTS|{0}'.format(id))
        self._r.zadd(comments_key, {"{0}||{1}".format(userid.lower(), text): int(time.time())})
        self._r.expire(comments_key, 24*60*60)
        logger.info('comment by {0} at {1}: "{2}"'.format(userid, time.ctime(), text))
        self._msg('playlist_update')

    def get_comments(self, id):
        key = self._key('COMMENTS|{0}'.format(id))
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
        """Queue the previewed Bender song (user clicked 'queue' on preview card)."""
        self._check_nest_active()
        preview = self._r.hgetall(self._key('BENDER|next-preview'))
        if not preview or preview.get('trackid') != trackId:
            logger.warning("benderqueue mismatch: trackId=%s preview=%s", trackId, preview)
            return

        strategy = preview.get('strategy', '')
        cache_key = self._cache_key(strategy)
        if cache_key:
            self._r.lpop(cache_key)

        original_user = preview.get('user', 'the@echonest.com')
        if strategy == 'throwback':
            self._r.hdel(self._key('BENDER|throwback-users'), trackId)

        self._r.delete(self._key('BENDER|next-preview'))
        newId = self.add_spotify_song(userid, trackId)
        self.jam(newId, original_user)

    def benderfilter(self, trackId, userid):
        """Filter a Bender preview song and rotate to the next one."""
        self._check_nest_active()
        preview = self._r.hgetall(self._key('BENDER|next-preview'))

        # Clean up preview/cache state if it matches the filtered track
        if preview and preview.get('trackid') == trackId:
            strategy = preview.get('strategy', '')
            cache_key = self._cache_key(strategy)
            if cache_key:
                self._r.lpop(cache_key)
            if strategy == 'throwback':
                self._r.hdel(self._key('BENDER|throwback-users'), trackId)

        # Always clear the preview so a fresh one is generated on next get_additional_src
        self._r.delete(self._key('BENDER|next-preview'))
        self._r.setex(self._key('FILTER|%s' % trackId), CONF.BENDER_FILTER_TIME, 1)
        self._msg('playlist_update')
        logger.info("benderfilter %s by %s", trackId, userid)


    def get_song_from_queue(self, id):
        key = self._key('QUEUE|{0}'.format(id))
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
        data['jam'] = self.get_jams(self._key('QUEUEJAM|{0}'.format(id)))
        data['comments'] = self.get_comments(id)
        return data or {}

    def set_song_in_queue(self, id, data):
        key = self._key('QUEUE|{0}'.format(id))
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
        self._check_nest_active()
        self._r.zremrangebyrank(self._key('MISC|priority-queue'), 0, -1)
        self._msg('playlist_update')

    def kill_song(self, id, email):
        self._check_nest_active()
        self._r.zrem(self._key('MISC|priority-queue'), id)
        self._msg('playlist_update')

    def get_additional_src(self):
        raw = self._r.hgetall(self._key('MISC|backup-queue-data'))
        if not raw:
            # Use _peek_next_fill_song to find the next preview
            for _ in range(5):
                try:
                    self.ensure_fill_songs()
                except Exception as e:
                    logger.warning("Failed to ensure fill songs: %s", e)
                    break

                track_uri, user, strategy = self._peek_next_fill_song()
                if not track_uri:
                    break

                try:
                    fillInfo = self.get_fill_info(track_uri)
                    title = fillInfo['title']
                    fillInfo['title'] = fillInfo['artist'] + " : " + title

                    if strategy == 'throwback':
                        fillInfo['name'] = user.split('@')[0] + " (throwback)"
                        fillInfo['user'] = user
                    else:
                        fillInfo['name'] = 'Benderbot'
                        fillInfo['user'] = 'the@echonest.com'

                    fillInfo['playlist_src'] = True
                    fillInfo['dm_buttons'] = False
                    fillInfo['jam'] = []
                    return fillInfo
                except Exception:
                    logger.error('song not available: %s', track_uri)
                    logger.error('backtrace: %s', traceback.format_exc())
                    # Clear preview and pop from cache so we move to next
                    preview = self._r.hgetall(self._key('BENDER|next-preview'))
                    if preview:
                        strat = preview.get('strategy', '')
                        ck = self._cache_key(strat)
                        if ck:
                            self._r.lpop(ck)
                        if strat == 'throwback':
                            self._r.hdel(self._key('BENDER|throwback-users'), track_uri)
                        self._r.delete(self._key('BENDER|next-preview'))
                    continue

            # Fallback when fill songs are unavailable
            return {'playlist_src': True, 'name': 'Benderbot', 'user': 'the@echonest.com',
                    'title': 'No songs available', 'img': '', 'jam': [], 'dm_buttons': False}

        raw['playlist_src'] = True
        return raw

    def get_queued(self):
        songs = self._r.zrange(self._key('MISC|priority-queue'), 0, -1, withscores=True)
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
            song = self._r.zrange(self._key('MISC|priority-queue'), 0, 0)
            if not song:
                self._r.delete(self._key('MISC|now-playing'))
                return {}
            song = song[0]
            self._r.zrem(self._key('MISC|priority-queue'), song)
            data = self.get_song_from_queue(song)

            if (data and data['src'] == 'spotify'
                    and data['user'] != 'the@echonest.com'):
                #got something from a human, set last-queued and clear bender caches
                self._r.set(self._key('MISC|last-queued'), data['trackid'])
                self._clear_all_bender_caches()
                try:
                    self.ensure_fill_songs()
                except Exception as e:
                    logger.warning("Failed to ensure fill songs: %s", e)
                self._r.delete(self._key('MISC|bender_streak_start'))

            if not data:
                continue

            self._r.expire(self._key('QUEUE|{0}'.format(song)), 3*60*60)
            self._r.setex(self._key('MISC|now-playing'), 2*60*60, song)
            self._r.setex(self._key('MISC|now-playing-done'), data['duration'], song)
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
            end_time = self._r.get(self._key('MISC|current-done'))
            if end_time:
                end_time = pickle_load_b64(end_time).isoformat()

        if not end_time:
            end_time = self.player_now().isoformat()
        return end_time

    def get_now_playing(self):
        rv = {}
        song = self._r.get(self._key('MISC|now-playing'))
        if song:
            rv = self.get_song_from_queue(song)
            if not rv or not rv.get('trackid'):
                # Song data was cleaned up but MISC|now-playing is stale
                self._r.delete(self._key('MISC|now-playing'))
                rv = {}
            else:
                p_endtime = self._r.get(self._key('MISC|current-done'))
                rv['starttime'] = self._r.get(self._key('MISC|started-on'))
                rv['endtime'] = self.song_end_time(use_estimate=True)
                rv['pos'] = 0
                if p_endtime:
                    remaining = (pickle_load_b64(p_endtime) - self.player_now()).total_seconds()
                    rv['pos'] = int(max(0,rv['duration'] - remaining))

        paused = self._r.get(self._key('MISC|paused'))
        rv['paused'] = False
        if paused:
            rv['paused'] = True
        return rv

    def get_last_played(self):
        return self._r.get(self._key('MISC|last-played'))

    def get_current_airhorns(self):
        return self._r.lrange(self._key('AIRHORNS'), 0, -1)

    def vote(self, userid, id, up):
        self._check_nest_active()
        norm_color = [34, 34, 34]
        base_hot = [34, 34, 34]
        hot_color = [68, 68, 68]
        cold_color = [0, 0, 0]
        user = self.get_song_from_queue(id).get('user', '')
        self_down = user == userid and not up
        s_id = self._key('QUEUE|VOTE|{0}'.format(id))
        if (not self_down and
                (self._r.sismember(s_id, userid)
                 and userid.lower() not in CONF.SPECIAL_PEOPLE)):
            logger.info("not special, not self down, already voted")
            return

        self._r.sadd(s_id, userid)
        exist_rank = self._r.zrank(self._key('MISC|priority-queue'), id)
        logger.info("existing rank is:" + str(exist_rank))
        if up:
            low_rank = exist_rank - 2
        else:
            low_rank = exist_rank + 1

        high_rank = low_rank + 1
        logger.info("low_rank:" + str(low_rank))
        logger.info("high_rank:" + str(high_rank))
        ids = self._r.zrange(self._key('MISC|priority-queue'), max(low_rank, 0), high_rank)
        logger.info("ids:" + str(ids))
        if len(ids) == 0:
            return #nothing to do here
        low_id = ids[0]
        current_score = self._r.zscore(self._key('MISC|priority-queue'), id)
        logger.info("current_score:" + str(current_score))
        low_score = self._r.zscore(self._key('MISC|priority-queue'), low_id)
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
            high_score = self._r.zscore(self._key('MISC|priority-queue'), high_id)
            logger.info("high_score:" + str(high_score))
            new_score = (low_score + high_score) / 2

        queue_key = self._key('QUEUE|{0}'.format(id))

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
        self._r.zincrby(self._key('MISC|priority-queue'), size, id)
        self._msg('playlist_update')

    def kill_playing(self, email):
        self._check_nest_active()
        self._r.set(self._key('MISC|force-jump'), 1)

    def pause(self, email):
        self._check_nest_active()
        self._r.set(self._key('MISC|paused'), 1)
        self._msg('now_playing_update')

    def unpause(self, email):
        self._check_nest_active()
        self._r.delete(self._key('MISC|paused'))
        # If the song timer expired while paused, clear stale now-playing
        # so the player loop advances to the next track immediately.
        now_playing_id = self._r.get(self._key('MISC|now-playing'))
        current_done = self._r.get(self._key('MISC|current-done'))
        if now_playing_id and not current_done:
            song_data = self._r.hgetall(self._key('QUEUE|{}'.format(now_playing_id)))
            if not song_data or not song_data.get('trackid'):
                # Song data is gone, clean up the stale reference
                self._r.delete(self._key('MISC|now-playing'))
                logger.info("unpause: cleared stale now-playing %s (no song data)", now_playing_id)
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
                self._r.lpop(self._key('AIRHORNS'))
                popped += 1
                if popped >= CONF.AIRHORN_EXPIRE_COUNT or len(horns) - popped < CONF.AIRHORN_LIST_MIN_LEN:
                    break

    def get_horns(self):
        raw = self._r.lrange(self._key('AIRHORNS'), 0, -1)
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
        self._r.rpush(self._key('AIRHORNS'), json.dumps(horn))
        self._msg('do_airhorn|0.4|%s' % name)  # volume of airhorn - may need to be tweaked, random choice for airhorn

    def airhorn(self, userid, name):
        self._check_nest_active()
        self.trim_horns()
        horns = self.get_horns()
        if len([x for x in horns if not x['free']]) >= CONF.AIRHORN_MAX:
            return
        self._do_horn(userid, False, name)

    def free_airhorn(self, userid):
        self._check_nest_active()
        self.trim_horns()
        s = self._r.spop(self._key('FREEHORN_{0}'.format(userid)))
        if s:
            self._msg('update_freehorn')
            self._do_horn(userid, True)

    def get_free_horns(self, userid):
        return self._r.scard(self._key('FREEHORN_{0}'.format(userid)))

    def get_volume(self):
        if not self._r.exists(self._key('MISC|volume')):
            self._r.set(self._key('MISC|volume'), 95)

        rv = int(self._r.get(self._key('MISC|volume')))
        return rv

    def set_volume(self, new_vol):
        self._check_nest_active()
        new_vol = max(0, int(new_vol))
#        print new_vol
        new_vol = min(100, new_vol)
        print("set_volume", new_vol)
        self._r.set(self._key('MISC|volume'), new_vol)
        self._msg('v|'+str(new_vol))
        logger.info('set_volume in pct %s', new_vol)
        return new_vol

    def _msg(self, msg):
        self._r.publish(self._key('MISC|update-pubsub'), msg)

    def try_login(self, email, passwd):
        email = email.lower()
        d = self._r.hget(self._key('MISC|guest-login-expire'), email)
        if not d or pickle_load_b64(d) < _now():
            self._r.hdel(self._key('MISC|guest-login'), email)
            return False
        full_pass = self._r.hget(self._key('MISC|guest-login'), email)
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
        self._r.hset(self._key('MISC|guest-login-expire'), email, pickle_dump_b64(expires))
        self._r.hset(self._key('MISC|guest-login'), email, passwd)
        self.send_email(email, "Welcome to Andre!",
                        render_template('welcome_email.txt',
                            expires=expires, email=email,
                            passwd=passwd))

    def _airhorners_for_song_log(self, id):
        found_airhorns = []
        stored_airhorns = self._r.lrange(self._key('AIRHORNS'), 0, -1)
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
        song['jam'] = self.get_jams(self._key('QUEUEJAM|{0}'.format(id)))
        song['airhorn'] = self._airhorners_for_song_log(id)
        cleaned_song = _clean_song(song)
        song_json = json.dumps(cleaned_song, sort_keys=True)
        self._r.set(self._key('MISC|last-played'), song_json)
        _log_play(song_json)
        self._h.add_play(song_json)

    def get_historian(self):
        return self._h
