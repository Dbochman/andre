from gevent import monkey
monkey.patch_all()

import os.path
import logging
import json
import datetime
import hashlib
import functools
import hmac
import secrets
import string
import urllib.parse
import urllib.request
import socket as psocket
import re
import gevent
import redis
import requests
import time
import psycopg2

import spotipy.oauth2
import spotipy

from flask import Flask, request, render_template, session, redirect, jsonify, make_response, Response, stream_with_context
from flask_assets import Environment, Bundle

from config import CONF
from db import DB, is_spotify_rate_limited, set_spotify_rate_limit, handle_spotify_exception
from nests import pubsub_channel, NestManager, refresh_member_ttl, member_key, members_key
import analytics
import slack

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Add ProxyFix for reverse proxy support (HTTPS detection, real client IP)
if not CONF.DEBUG:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

assets = Environment(app)
app.config['GOOGLE_DOMAIN'] = 'spotify.com'
app.url_map.strict_slashes = False
#auth = GoogleAuth(app)

print(CONF)

# Notify Slack on container start (every deploy rebuilds the container)
slack.notify_deploy()

def _get_authenticated_email():
    """Get authenticated email from session or dev bypass."""
    email = session.get('email')
    if email:
        return email
    if CONF.DEBUG and CONF.DEV_AUTH_EMAIL and request.host.split(':')[0] in ('localhost', '127.0.0.1'):
        session['email'] = CONF.DEV_AUTH_EMAIL
        session['fullname'] = 'Dev User'
        return session['email']
    return None


def _log_action(action, email, **extra):
    """Structured audit log for security-relevant actions."""
    logger.info("AUDIT action=%s email=%s ip=%s ua=%s %s",
                action, email, request.remote_addr,
                request.headers.get('User-Agent', '-'),
                ' '.join(f'{k}={v}' for k, v in extra.items()))


def _check_rate_limit(r, email, action, limit, window=3600):
    """Per-user action rate limiting via Redis incr/expire. Returns True if allowed."""
    key = f'RATE|{action}|{email}'
    count = r.incr(key)
    if count == 1:
        r.expire(key, window)
    return count <= limit

def _parse_session_cookie():
    """Parse the session cookie manually when Flask's session isn't available."""
    from itsdangerous import URLSafeTimedSerializer, BadSignature
    import http.cookies
    import hashlib

    cookie_header = request.headers.get('Cookie', '')
    if not cookie_header:
        return None

    # Parse cookies
    cookies = http.cookies.SimpleCookie()
    try:
        cookies.load(cookie_header)
    except Exception as e:
        logger.warning('Failed to parse cookies: %s', e)
        return None

    if 'session' not in cookies:
        return None

    session_cookie = cookies['session'].value

    # Flask uses itsdangerous to sign the session
    try:
        serializer = URLSafeTimedSerializer(
            app.secret_key,
            salt='cookie-session',
            signer_kwargs={'key_derivation': 'hmac', 'digest_method': hashlib.sha1}
        )
        data = serializer.loads(session_cookie)
        return data
    except BadSignature as e:
        logger.warning('Invalid session signature: %s', e)
        return None
    except Exception as e:
        logger.warning('Failed to decode session: %s', e)
        return None

def _handle_websocket():
    """Handle WebSocket connections in before_request (before Flask route dispatch).

    Supports:
      /socket       -> nest_id="main"
      /socket/<id>  -> nest_id=<id> (validated via NestManager)
    """
    ws = request.environ.get('wsgi.websocket')

    if ws is None:
        return 'WebSocket required', 400

    # Flask's session isn't properly initialized for WebSocket requests
    # Parse the session cookie manually
    session_data = _parse_session_cookie()
    email = session_data.get('email') if session_data else None

    if not email:
        logger.warning('WebSocket unauthorized - no email in session')
        return 'Unauthorized', 401

    # Extract nest_id from path: /socket -> main, /socket/<id> -> id
    path = request.path.rstrip('/')
    parts = path.split('/')
    # /socket -> ['', 'socket'], /socket/ABC -> ['', 'socket', 'ABC']
    if len(parts) >= 3 and parts[2]:
        nest_id = parts[2]
        # Validate nest exists
        if nest_manager and nest_manager.get_nest(nest_id) is None:
            logger.warning('WebSocket: nest %s not found', nest_id)
            return 'Nest not found', 404
    else:
        nest_id = "main"

    MusicNamespace(email, 0, nest_id=nest_id).serve()
    return ''

def _handle_volume_websocket():
    """Handle volume WebSocket connections.

    Supports:
      /volume       -> nest_id="main"
      /volume/<id>  -> nest_id=<id> (validated via NestManager)
    """
    if request.environ.get('wsgi.websocket') is None:
        return 'WebSocket required', 400

    # Extract nest_id from path: /volume -> main, /volume/<id> -> id
    path = request.path.rstrip('/')
    parts = path.split('/')
    # /volume -> ['', 'volume'], /volume/ABC -> ['', 'volume', 'ABC']
    if len(parts) >= 3 and parts[2]:
        nest_id = parts[2]
        if nest_manager and nest_manager.get_nest(nest_id) is None:
            return 'Nest not found', 404
    else:
        nest_id = "main"

    VolumeNamespace(nest_id=nest_id).serve()
    return ''

def __setup_bundles():
    for name, conf in CONF.get('BUNDLES', {}).items():
        files = conf['files']
        if 'prefix' in conf:
            files = [os.path.join(conf['prefix'], f) for f in files]
        bundle = Bundle(*files, **conf.get('kwargs', {}))
        assets.register(name, bundle)
__setup_bundles()

d = DB(False)
logger.setLevel(logging.DEBUG)

# Initialize NestManager for nest CRUD operations
try:
    nest_manager = NestManager()
except Exception as e:
    logger.warning("NestManager init failed (nests disabled): %s", e)
    nest_manager = None

auth = spotipy.oauth2.SpotifyClientCredentials(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET)
auth.get_access_token()

# SoundCloud OAuth token cache (shared across all users)
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

#keeping a list of airhorns for mobile client
airhorns = set()

if CONF.DEBUG:
    logger.debug("DEBUG MODE ON")
    app.debug = True
    assets.debug = True

app.secret_key = CONF.SECRET_KEY
# Session cookie settings for browser compatibility
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = not CONF.DEBUG  # Secure cookies over HTTPS in production

class ProseccoAPIError(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['message'] = self.message
        return rv


@app.errorhandler(ProseccoAPIError)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response



class WebSocketManager(object):
    def __init__(self):
        self._ws = request.environ.get('wsgi.websocket')
        self._children = []

    def spawn(self, f, *args, **kwargs):
        child = gevent.spawn(f, *args, **kwargs)
        self._children.append(child)
        return child

    def emit(self, *args):
        msg = '1' + json.dumps(args)
        self._ws.send(msg)

    def serve(self):
        try:
            while True:
                msg = None
                with gevent.Timeout(30, False):
                    msg = self._ws.receive()
                if msg is None:
                    # Timeout - check if connection is still open
                    if getattr(self._ws, 'closed', False):
                        break
                    # No message yet (timeout); keep connection open
                    continue
                if msg == '':
                    if getattr(self._ws, 'closed', False):
                        break
                    continue
                if isinstance(msg, bytes):
                    msg = msg.decode('utf-8', 'ignore')
                T = msg[0]
                if T == '1':
                    data = json.loads(msg[1:]) if len(msg) > 1 else None
                    if not data:
                        continue
                    event = data[0]
                    args = data[1:]
                    try:
                        getattr(self, 'on_' + event.replace('-', '_'))(*args)
                    except Exception:
                        logger.exception('Socket handler error for event: %s', event)
                elif T == '0':
                    pass  # Heartbeat
                else:
                    return
        except Exception:
            logger.exception('WebSocket error')
        finally:
            self._on_disconnect()
            try:
                self._ws.close()
            except Exception:
                pass
            gevent.killall(self._children)

    def _on_disconnect(self):
        """Hook called when WebSocket disconnects. Override in subclass."""
        pass


class MusicNamespace(WebSocketManager):
    def __init__(self, email, penalty, nest_id="main"):
        super(MusicNamespace, self).__init__()
        try:
            os.makedirs(CONF.OAUTH_CACHE_PATH)
        except Exception:
            pass
        self.logger = app.logger
        self.email = email
        self.penalty = penalty
        self.nest_id = nest_id
        # Create a per-nest DB instance
        self.db = DB(init_history_to_redis=False, nest_id=nest_id)
        self.auth = spotipy.oauth2.SpotifyOAuth(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
                                                "prosecco:%s" % email, scope="streaming user-read-currently-playing user-read-playback-state user-modify-playback-state", cache_path="%s/%s" % (CONF.OAUTH_CACHE_PATH, email))
        # Join nest on connect
        if nest_manager:
            try:
                nest_manager.join_nest(nest_id, email)
            except Exception:
                logger.exception('Failed to join nest %s', nest_id)
        self.spawn(self.listener)
        self.log('New namespace for {0} (nest={1})'.format(self.email, self.nest_id))
        _log_action('ws_connect', self.email, nest=self.nest_id)
        analytics.track(self.db._r, 'ws_connect', self.email)

    def _on_disconnect(self):
        """Leave nest on WebSocket disconnect."""
        _log_action('ws_disconnect', self.email, nest=self.nest_id)
        analytics.track(self.db._r, 'ws_disconnect', self.email)
        if nest_manager:
            try:
                nest_manager.leave_nest(self.nest_id, self.email)
            except Exception:
                logger.exception('Failed to leave nest %s', self.nest_id)
        # Delete member TTL key
        try:
            mk = member_key(self.nest_id, self.email)
            self.db._r.delete(mk)
        except Exception:
            pass
        # Remove from MEMBERS set
        try:
            mkey = members_key(self.nest_id)
            self.db._r.srem(mkey, self.email)
        except Exception:
            pass

    def serve(self):
        """Override serve to add membership heartbeat TTL refresh."""
        import time as _time
        # Initial heartbeat on connect
        try:
            refresh_member_ttl(self.db._r, self.nest_id, self.email, 90)
        except Exception:
            logger.exception('Failed initial heartbeat for %s', self.email)

        last_heartbeat = _time.time()
        try:
            while True:
                msg = None
                with gevent.Timeout(30, False):
                    msg = self._ws.receive()

                # Refresh heartbeat every 30 seconds
                now = _time.time()
                if now - last_heartbeat >= 30:
                    try:
                        refresh_member_ttl(self.db._r, self.nest_id, self.email, 90)
                    except Exception:
                        logger.exception('Failed heartbeat for %s', self.email)
                    last_heartbeat = now

                if msg is None:
                    if getattr(self._ws, 'closed', False):
                        break
                    continue
                if msg == '':
                    if getattr(self._ws, 'closed', False):
                        break
                    continue
                if isinstance(msg, bytes):
                    msg = msg.decode('utf-8', 'ignore')
                T = msg[0]
                if T == '1':
                    data = json.loads(msg[1:]) if len(msg) > 1 else None
                    if not data:
                        continue
                    event = data[0]
                    args = data[1:]
                    try:
                        getattr(self, 'on_' + event.replace('-', '_'))(*args)
                    except Exception:
                        logger.exception('Socket handler error for event: %s', event)
                elif T == '0':
                    pass  # Heartbeat
                else:
                    return
        except Exception:
            logger.exception('WebSocket error')
        finally:
            self._on_disconnect()
            try:
                self._ws.close()
            except Exception:
                pass
            gevent.killall(self._children)

    def listener(self):
        r = redis.StrictRedis(host=CONF.REDIS_HOST or 'localhost', port=CONF.REDIS_PORT or 6379, password=CONF.REDIS_PASSWORD or None, decode_responses=True).pubsub()
        r.subscribe(pubsub_channel(self.nest_id))
        for m in r.listen():
            if m['type'] != 'message':
                continue
            msg = m['data']

            if msg == 'playlist_update':
                self.on_fetch_playlist()
            elif msg == 'now_playing_update':
                self.on_fetch_now_playing()
                self.on_fetch_playlist()
            elif msg.startswith('pp|'):
                #self.log('sending position update to {0}'.format(self.email))
                _, src, track, pos = msg.split('|', 3)
#                logger.debug(session['spotify_token'])
                self.emit('player_position', src, track, int(pos))
            elif msg.startswith('v|'):
                _, vol = msg.split('|', 1)
                self.emit('volume', vol)
            elif msg.startswith('do_airhorn'):
                _, v, c = msg.split('|', 2)
                self.logger.info('about to emit')
                self.emit('do_airhorn', v, c)
            elif msg.startswith('no_airhorn'):
                _, data = msg.split('|', 1)
                self.emit('no_airhorn', json.loads(data))
            elif msg == 'update_freehorn':
                self.emit('free_horns', self.db.get_free_horns(self.email))
            elif msg.startswith('member_update|'):
                _, count_str = msg.split('|', 1)
                try:
                    self.emit('member_update', int(count_str))
                except (ValueError, TypeError):
                    pass

    def log(self, msg, debug=True):
        if debug:
            self.logger.debug(msg)
        else:
            self.logger.info(msg)

    def _safe_db_call(self, fn, *args, **kwargs):
        """Call a DB method, catching RuntimeError for nest guard checks and transient Spotify errors."""
        try:
            return fn(*args, **kwargs)
        except RuntimeError as e:
            msg = str(e)
            if "being deleted" in msg:
                self.emit('error', {'message': 'This nest is being deleted'})
                return None
            if "Queue is full" in msg:
                max_depth = getattr(CONF, 'NEST_MAX_QUEUE_DEPTH', 25) or 0
                limit_note = f' (max {max_depth} songs)' if max_depth > 0 else ''
                self.emit('error', {'message': f'Queue is full{limit_note}'})
                return None
            raise
        except (ConnectionError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logger.warning("Spotify connection error in %s: %s", fn.__name__, e)
            set_spotify_rate_limit(30)  # Back off 30 seconds
            self.emit('error', {'message': 'Spotify is temporarily unavailable, try again in a moment'})
            return None
        except Exception as e:
            if handle_spotify_exception(e):
                self.emit('error', {'message': 'Spotify rate limited, try again later'})
                return None
            logger.exception("Unexpected error in %s", fn.__name__)
            self.emit('error', {'message': 'Something went wrong, try again'})
            return None

    def on_request_volume(self):
        self.emit('volume', str(self.db.get_volume()))

    def on_change_volume(self, vol):
        result = self._safe_db_call(self.db.set_volume, vol)
        if result is not None:
            self.emit('volume', str(result))

    def on_add_song(self, song_id, src):
        logger.info('on_add_song called: song_id=%s, src=%s, email=%s', song_id, src, self.email)
        if not _check_rate_limit(self.db._r, self.email, 'add_song', 50):
            self.emit('error', {'message': 'Rate limit reached — max 50 songs/hour'})
            return
        result = None
        if src == 'spotify':
            self.log(
                'add_spotify_song "{0}" "{1}"'.format(self.email, song_id))
            result = self._safe_db_call(self.db.add_spotify_song, self.email, song_id, penalty=self.penalty)
        elif src == 'youtube':
            logger.info('Adding YouTube song: %s for user %s', song_id, self.email)
            result = self._safe_db_call(self.db.add_youtube_song, self.email, song_id, penalty=self.penalty)
        elif src == 'soundcloud':
            self.log(
                'add_soundcloud_song "{0}" "{1}"'.format(self.email, song_id))
            result = self._safe_db_call(self.db.add_soundcloud_song, self.email, song_id, penalty=self.penalty)

        if result not in (None, False):
            analytics.track(self.db._r, 'song_add', self.email)

    def on_fetch_playlist(self):
        self.emit('playlist_update', self.db.get_queued())

    def on_fetch_now_playing(self):
        self.emit('now_playing_update', self.db.get_now_playing())

    def on_fetch_search_token(self):
        logger.debug("fetch search token")
        # Check rate limit before providing token (prevents frontend from hammering API)
        if is_spotify_rate_limited():
            logger.debug("Spotify rate limited - not providing search token")
            self.emit('search_token_update', dict(token=None, error="rate_limited", time_left=0))
            return
        token_info = auth.get_access_token()
        # Handle get_access_token returning dict in newer spotipy versions
        if isinstance(token_info, dict):
            access_token = token_info.get('access_token')
            expires_at = token_info.get('expires_at', time.time() + 3600)
        else:
            access_token = auth.token_info['access_token']
            expires_at = auth.token_info['expires_at']
        self.emit('search_token_update', dict(token=access_token,
                                            time_left=int(expires_at - time.time())))

    def on_fetch_auth_token(self):
        logger.debug("fetch auth token")
        token = self.auth.get_cached_token()
        if token:
            logger.debug("update")
            self.emit('auth_token_update', dict(token=token['access_token'],
                                                time_left=int(token['expires_at'] - time.time())))
        else:
            logger.debug("refresh")
            analytics.track(self.db._r, 'spotify_oauth_stale', self.email)
            self.emit('auth_token_refresh', self.auth.get_authorize_url())

    def on_fetch_airhorns(self):
        self.emit('airhorns', self.db.get_horns())

    def on_vote(self, id, up):
        self.log('Vote from {0} on {1} {2}'.format(self.email, id, up))
        if self._safe_db_call(self.db.vote, self.email, id, up) not in (None, False):
            analytics.track(self.db._r, 'vote', self.email)

    def on_kill(self, id):
        self.log('Kill {0} ({2}) from {1}'.format(id, self.email, self.db.get_song_from_queue(id).get('user')))
        self._safe_db_call(self.db.kill_song, id, self.email)

    def on_kill_playing(self):
        self.log('Kill playing ({1}) from {0}'.format(self.email, self.db.get_now_playing().get('user')))
        self._safe_db_call(self.db.kill_playing, self.email)

    def on_nuke_queue(self):
        self.log('Queue nuke from {0}'.format(self.email))
        self._safe_db_call(self.db.nuke_queue, self.email)

    def on_airhorn(self, name):
        self.log('Airhorn {0}, {1}'.format(self.email, name))
        if not _check_rate_limit(self.db._r, self.email, 'airhorn', 20):
            self.emit('error', {'message': 'Rate limit reached — max 20 airhorns/hour'})
            return
        if self._safe_db_call(self.db.airhorn, self.email, name=name) not in (None, False):
            analytics.track(self.db._r, 'airhorn', self.email)

    def on_free_airhorn(self):
        self.log('Free Airhorn {0}'.format(self.email))
        self._safe_db_call(self.db.free_airhorn, self.email)

    # def on_add_playlist(self, key, shuffled):
    #     self.log('Add playlist from {0} {1}'.format(self.email, key))
    #     d.add_playlist(self.email, key, shuffled)

    # def on_kill_src(self):
    #     self.log('Killed playlist from {0}'.format(self.email))
    #     d.kill_playlist()

    def on_jam(self, id):
        self.log('{0} jammed {1}'.format(self.email, id))
        if self._safe_db_call(self.db.jam, id, self.email) not in (None, False):
            analytics.track(self.db._r, 'jam', self.email)

    def on_benderQueue(self, id):
        self.log('{0} benderqueues {1}'.format(self.email, id))
        self._safe_db_call(self.db.benderqueue, id, self.email)

    def on_benderFilter(self, id):
        self.log('{0} benderfilters {1}'.format(self.email, id))
        self._safe_db_call(self.db.benderfilter, id, self.email)

    def on_get_free_horns(self):
        self.emit('free_horns', self.db.get_free_horns(self.email))

    def on_pause(self):
        self.log('Pause button! {0}'.format(self.email))
        self._safe_db_call(self.db.pause, self.email)

    def on_unpause(self):
        self.log('Unpause button! {0}'.format(self.email))
        self._safe_db_call(self.db.unpause, self.email)

    def on_add_comment(self, song_id, user_id, comment):
        # Ignore client-supplied user_id — use authenticated identity
        if not _check_rate_limit(self.db._r, self.email, 'comment', 30):
            self.emit('error', {'message': 'Rate limit reached — max 30 comments/hour'})
            return
        self.log("Add comment from {}!".format(self.email))
        self._safe_db_call(self.db.add_comment, song_id, self.email, comment)

    def on_get_comments_for_song(self, song_id):
        comments = self.db.get_comments(song_id)
        self.emit('comments_for_song', song_id, comments)

    def on_loaded_airhorn(self, name):
        airhorns.add(name.encode('ascii','ignore'))

    def on_resolve_soundcloud(self, url):
        """Resolve a SoundCloud URL to track metadata."""
        token = get_soundcloud_token()
        if not token:
            self.emit('soundcloud_error', {'error': 'SoundCloud not configured'})
            return

        try:
            # Resolve URL to track
            resp = requests.get(
                'https://api.soundcloud.com/resolve',
                params={'url': url},
                headers={'Authorization': f'OAuth {token}'},
                allow_redirects=True,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            # Handle different object types (track, playlist, etc.)
            if data.get('kind') != 'track':
                self.emit('soundcloud_error', {'error': 'Only tracks are supported'})
                return

            # Extract relevant fields
            track_data = {
                'id': data.get('id'),
                'title': data.get('title'),
                'artist': data.get('user', {}).get('username'),
                'duration': data.get('duration', 0) // 1000,  # Convert ms to seconds
                'artwork_url': data.get('artwork_url'),
                'permalink_url': data.get('permalink_url'),
                'streamable': data.get('streamable', False),
            }
            self.emit('soundcloud_resolved', track_data)
        except requests.exceptions.HTTPError as e:
            logger.warning("SoundCloud resolve HTTP error: %s", e)
            self.emit('soundcloud_error', {'error': 'Track not found or unavailable'})
        except Exception as e:
            logger.error("SoundCloud resolve error: %s", e)
            self.emit('soundcloud_error', {'error': 'Failed to resolve track'})

    def on_get_soundcloud_stream(self, track_id):
        """Get stream URL for a SoundCloud track."""
        token = get_soundcloud_token()
        if not token:
            self.emit('soundcloud_stream_error', {'error': 'SoundCloud not configured', 'track_id': track_id})
            return

        try:
            # Get track streams
            resp = requests.get(
                f'https://api.soundcloud.com/tracks/{track_id}/streams',
                headers={'Authorization': f'OAuth {token}'},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            # Prefer http_mp3_128_url for broad compatibility
            stream_url = data.get('http_mp3_128_url') or data.get('hls_mp3_128_url')
            if not stream_url:
                logger.warning("No stream URL found for SoundCloud track %s", track_id)
                self.emit('soundcloud_stream_error', {'error': 'No stream available', 'track_id': track_id})
                return

            # The stream URL requires OAuth and redirects to a signed CDN URL
            # Follow the redirect to get the direct playable URL
            stream_resp = requests.get(
                stream_url,
                headers={'Authorization': f'OAuth {token}'},
                allow_redirects=False,
                timeout=10
            )

            if stream_resp.status_code in (301, 302, 303, 307, 308):
                # Get the redirect location - this is the direct CDN URL
                direct_url = stream_resp.headers.get('Location')
                if direct_url:
                    logger.debug("SoundCloud stream redirect for track %s: %s", track_id, direct_url[:100])
                    self.emit('soundcloud_stream', {'track_id': track_id, 'stream_url': direct_url})
                    return

            # If no redirect, try using the original URL (shouldn't happen)
            logger.warning("SoundCloud stream no redirect for track %s, using original URL", track_id)
            self.emit('soundcloud_stream', {'track_id': track_id, 'stream_url': stream_url})

        except requests.exceptions.HTTPError as e:
            logger.warning("SoundCloud stream HTTP error for track %s: %s", track_id, e)
            self.emit('soundcloud_stream_error', {'error': 'Stream not available', 'track_id': track_id})
        except Exception as e:
            logger.error("SoundCloud stream error for track %s: %s", track_id, e)
            self.emit('soundcloud_stream_error', {'error': 'Failed to get stream URL', 'track_id': track_id})

class VolumeNamespace(WebSocketManager):
    def log(self, msg, debug=True):
        if debug:
            self.logger.debug(msg)
        else:
            self.logger.info(msg)

    def __init__(self, *args, nest_id="main", **kwargs):
        super(VolumeNamespace, self).__init__(*args, **kwargs)
        self.logger = app.logger
        self.nest_id = nest_id
        self.db = DB(init_history_to_redis=False, nest_id=nest_id)
        self.log('new volume listener for nest {0}! {1}'.format(nest_id, request.remote_addr), False)
        self.spawn(self.listener)

    def on_request_volume(self):
        self.emit('volume', str(self.db.get_volume()))

    def on_change_volume(self, vol):
        self.emit('volume', str(self.db.set_volume(vol)))

    def listener(self):
        r = redis.StrictRedis(host=CONF.REDIS_HOST or 'localhost', port=CONF.REDIS_PORT or 6379, password=CONF.REDIS_PASSWORD or None, decode_responses=True).pubsub()
        r.subscribe(pubsub_channel(self.nest_id))
        for m in r.listen():
            if m['type'] != 'message':
                continue
            data = m['data']
            if data.startswith('v|'):
                _, vol = data.split('|', 1)
                self.emit('volume', vol)


@app.context_processor
def inject_config():
    return dict(CONF=CONF)

SAFE_PATHS = ('/login/', '/login/google', '/logout/', '/playing/', '/queue/', '/volume/',
              '/signup/', '/signup', '/api/jammit/', '/health', '/stats',
              '/authentication/callback', '/token', '/last/', '/airhorns/', '/z/',
              '/sync/link')
SAFE_PARAM_PATHS = ('/history', '/user_history', '/user_jam_history', '/search/v2', '/youtube/lookup', '/youtube/playlist',
    '/airhorn_list', '/queue/', '/api/')
VALID_HOSTS = ('localhost:5000', 'localhost:5001', '127.0.0.1:5000', '127.0.0.1:5001',
               str(CONF.HOSTNAME) if CONF.HOSTNAME else '',
               str(CONF.ECHONEST_DOMAIN) if getattr(CONF, 'ECHONEST_DOMAIN', None) else '')


@app.before_request
def require_auth():
    # Handle WebSocket upgrades BEFORE Flask route dispatch
    # gevent-websocket requires handling at this level, not in Flask routes
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        if request.path.startswith('/socket'):
            logger.debug(f"WebSocket upgrade request for /socket")
            return _handle_websocket()
        elif request.path.startswith('/volume'):
            logger.debug(f"WebSocket upgrade request for /volume")
            return _handle_volume_websocket()

    if CONF.HOSTNAME and request.host not in VALID_HOSTS:
        return redirect('http://%s' % CONF.HOSTNAME)
    if request.path in SAFE_PATHS:
        return
    for param_path in SAFE_PARAM_PATHS:
        if request.path.startswith(param_path):
            return
    if request.path.startswith('/static/'):
        return
    if 'email' not in session:
        # Dev-only bypass: only works in DEBUG mode on localhost
        if CONF.DEBUG and CONF.DEV_AUTH_EMAIL:
            host = request.host.split(':')[0]
            if host in ('localhost', '127.0.0.1'):
                session['email'] = CONF.DEV_AUTH_EMAIL
                session['fullname'] = 'Dev User'
                return
        # Redirect to login for unauthenticated requests
        _log_action('auth_redirect', '-', path=request.path)
        return redirect('/login/')


_ALLOWED_ORIGINS = set()
if CONF.HOSTNAME:
    _ALLOWED_ORIGINS.add(f'https://{CONF.HOSTNAME}')
    _ALLOWED_ORIGINS.add(f'http://{CONF.HOSTNAME}')
if CONF.DEBUG:
    _ALLOWED_ORIGINS |= {
        'http://localhost:5000', 'http://localhost:5001',
        'http://127.0.0.1:5000', 'http://127.0.0.1:5001',
    }


@app.after_request
def add_cors_header(response):
    origin = request.environ.get('HTTP_ORIGIN')
    if origin and origin in _ALLOWED_ORIGINS:
        response.headers.set('Access-Control-Allow-Origin', origin)
        response.headers.set('Access-Control-Allow-Credentials', 'true')
    return response

# Determine protocol and host for OAuth redirect URIs
# In production behind reverse proxy, use HTTPS even if DEBUG is true
_is_localhost = CONF.HOSTNAME and CONF.HOSTNAME.startswith(('localhost', '127.0.0.1'))
if _is_localhost:
    # Local development - use HTTP
    REDIRECT_URI = "http://{}/authentication/callback".format(CONF.HOSTNAME)
    SPOTIFY_REDIRECT_URI = "http://{}/authentication/spotify_callback".format(CONF.HOSTNAME)
else:
    # Production - use HTTPS (behind reverse proxy)
    REDIRECT_URI = "https://{}/authentication/callback".format(CONF.HOSTNAME)
    SPOTIFY_REDIRECT_URI = "https://{}/authentication/spotify_callback".format(CONF.HOSTNAME)

logger.info('OAuth redirect URIs: %s, %s', REDIRECT_URI, SPOTIFY_REDIRECT_URI)

# ---------------------------------------------------------------------------
# Auth decorators (must be defined before routes that use them)
# ---------------------------------------------------------------------------

API_EMAIL = 'openclaw@api'

# Cache for linked users set (refreshed every 60s to avoid Redis round-trip on every request)
_linked_users_cache = {'users': set(), 'ts': 0}


def _compute_user_token(email):
    """Compute deterministic per-user sync token: HMAC-SHA256(SECRET_KEY, "sync:" + email)."""
    return hmac.new(
        CONF.SECRET_KEY.encode() if isinstance(CONF.SECRET_KEY, str) else CONF.SECRET_KEY,
        ('sync:' + email).encode(),
        'sha256',
    ).hexdigest()


def _get_linked_users():
    """Return set of linked user emails, cached for 60s."""
    now = time.time()
    if now - _linked_users_cache['ts'] > 60:
        try:
            _linked_users_cache['users'] = d._r.smembers('SYNC_LINKED_USERS') or set()
        except Exception:
            pass
        _linked_users_cache['ts'] = now
    return _linked_users_cache['users']


def require_api_token(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        from flask import g
        configured_token = CONF.ECHONEST_API_TOKEN
        if not configured_token:
            return jsonify(error='API token not configured on server'), 503

        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            resp = jsonify(error='Missing or malformed Authorization header')
            resp.status_code = 401
            resp.headers['WWW-Authenticate'] = 'Bearer'
            return resp

        provided_token = auth_header[7:]  # strip "Bearer "

        # Check shared API token first (fast path)
        if secrets.compare_digest(provided_token, configured_token):
            g.auth_email = API_EMAIL
            _log_action('api_auth_ok', API_EMAIL, path=request.path)
            return f(*args, **kwargs)

        # Check per-user sync tokens
        for email in _get_linked_users():
            expected = _compute_user_token(email)
            if secrets.compare_digest(provided_token, expected):
                g.auth_email = email
                _log_action('api_auth_ok', email, path=request.path)
                return f(*args, **kwargs)

        _log_action('api_auth_fail', '-', path=request.path)
        return jsonify(error='Invalid API token'), 403

    return decorated


def require_session_or_api_token(f):
    """Allow access via session auth (browser) OR API token (programmatic).
    Sets g.auth_email to the authenticated user's email."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        from flask import g
        # Check session auth first (browser users)
        email = _get_authenticated_email()
        if email:
            g.auth_email = email
            return f(*args, **kwargs)
        # Fall back to API token auth
        configured_token = CONF.ECHONEST_API_TOKEN
        auth_header = request.headers.get('Authorization', '')
        if configured_token and auth_header.startswith('Bearer '):
            provided_token = auth_header[7:]
            if secrets.compare_digest(provided_token, configured_token):
                g.auth_email = API_EMAIL
                return f(*args, **kwargs)
        resp = jsonify(error='Authentication required')
        resp.status_code = 401
        return resp
    return decorated


@app.route('/health')
def health():
    return jsonify(status='ok')

@app.route('/bounce/', methods=['GET'])
def bounce():
    return redirect(request.headers.get("Referer"), code=303)

@app.route('/z/', methods=['GET'])
def z():
    conn = psycopg2.connect("dbname='echonest_database' user='postgres'  host='db'")
    cur = conn.cursor()
    cur.execute("""SELECT username from userdata""")
    rows  = cur.fetchall()
    output = "hi\n"
    for row in rows:
        output += row[0] + "\n"
    return output

@app.route('/login/')
def login():
    return render_template('login.html')


@app.route('/login/google')
def login_google():
    args = dict(scope="email profile", redirect_uri=REDIRECT_URI,
                response_type="code", client_id=CONF.GOOGLE_CLIENT_ID,
                approval_prompt="auto", access_type="online")
    url = "https://accounts.google.com/o/oauth2/auth?{}".format(
        urllib.parse.urlencode(args))
    return redirect(url)


@app.route('/authentication/callback')
def auth_callback():
    params = dict(code=request.values['code'],
                  client_id=CONF.GOOGLE_CLIENT_ID,
                  client_secret=CONF.GOOGLE_CLIENT_SECRET,
                  redirect_uri=REDIRECT_URI,
                  grant_type="authorization_code")
    r = requests.post("https://accounts.google.com/o/oauth2/token",
                      data=params).json()
    if 'access_token' not in r:
        logger.error('OAuth failed: %s', r)
        return redirect('/login/')
    token = r['access_token']
    user = requests.get('https://www.googleapis.com/oauth2/v1/userinfo',
                        params=dict(access_token=token)).json()

    # Check email domain against allowed list (empty list = allow all)
    email = user.get('email', '')
    allowed_domains = CONF.ALLOWED_EMAIL_DOMAINS or []
    # Ensure it's a list (handle case where config has a single string)
    if isinstance(allowed_domains, str):
        allowed_domains = [allowed_domains]

    if allowed_domains:
        email_allowed = any(email.endswith('@' + domain) for domain in allowed_domains)
        if not email_allowed:
            logger.warning('Login rejected for email: %s (allowed domains: %s)', email, allowed_domains)
            failure_message = 'Sorry, {} is not on the guest list. Ask the host to add your domain.'.format(email)
            return make_response(
                render_template('login.html', failure=True, failure_message=failure_message),
                403)

    for k1, k2 in (('email', 'email',), ('fullname', 'name'),):
        session[k1] = user[k2]

    _log_action('login', email)
    analytics.track(d._r, 'login', email)

    # If already linked to Spotify, go home; otherwise prompt to connect.
    cache_path = "%s/%s" % (CONF.OAUTH_CACHE_PATH, email)
    sp_auth = spotipy.oauth2.SpotifyOAuth(
        CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
        "prosecco:%s" % email,
        scope="streaming user-read-currently-playing user-read-playback-state user-modify-playback-state",
        cache_path=cache_path)
    if sp_auth.get_cached_token():
        return redirect('/')
    return render_template('spotify_prompt.html', email=email)


@app.route('/logout/')
def logout():
    session.clear()
    return 'Logged Out, thank you!'


@app.route('/spotify_connect/')
def spotify_connect():
    return render_template('spotify_connect.html')


@app.route('/spotify_connect/authorize')
def spotify_authorize():
    """Redirect to Spotify OAuth; clear cache only when force=1."""
    email = session.get('email')
    if not email:
        return redirect('/login/')
    analytics.track(d._r, 'spotify_oauth_reconnect', email)
    cache_path = "%s/%s" % (CONF.OAUTH_CACHE_PATH, email)
    if request.args.get('force') == '1':
        try:
            os.remove(cache_path)
        except OSError:
            pass
    auth = spotipy.oauth2.SpotifyOAuth(
        CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
        "prosecco:%s" % email,
        scope="streaming user-read-currently-playing user-read-playback-state user-modify-playback-state",
        cache_path=cache_path)
    return redirect(auth.get_authorize_url())


@app.route('/authentication/spotify_callback/')
def spotify_callback():
    try:
        os.makedirs(CONF.OAUTH_CACHE_PATH)
    except Exception:
        pass
    auth = spotipy.oauth2.SpotifyOAuth(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
                                       "prosecco:%s" % session['email'], scope="streaming user-read-currently-playing user-read-playback-state user-modify-playback-state", cache_path="%s/%s" % (CONF.OAUTH_CACHE_PATH, session['email']))
    auth.get_access_token(request.values['code'])
    analytics.track(d._r, 'spotify_oauth_refresh', session['email'])
    return redirect('/spotify_connect/')

USEFUL_PROPS = ('artist', 'big_img', 'id', 'img', 'src', 'title', 'trackid', 'user',)


@app.route('/playing/')
def playing():
    playing = d.get_now_playing()
    rv = {}
    for k in USEFUL_PROPS + ('starttime', 'endtime', 'jam', 'comments', 'paused', 'pos'):
        rv[k] = playing.get(k, '')
    now = datetime.datetime.now()
    rv['now'] = datetime.datetime.now().isoformat()
    return jsonify(**rv)


@app.route('/queue/')
def queue():
    queue = d.get_queued()
    return jsonify(queue=[{k: x.get(k, '') for k in USEFUL_PROPS} for x in queue])


@app.route('/queue/<int:id>')
def queue_specific(id):
    queue = d.get_queued()
    for q in queue:
        x = q
        if x.get("id") == str(id):
            break
    else:
        raise ProseccoAPIError("No entry with that id", status_code=404)

    return jsonify({k: x.get(k, '') for k in USEFUL_PROPS + ('starttime', 'endtime', 'jam', 'comments', 'paused', 'pos')})


@app.route('/')
def main():
    return render_template('main.html',
                           nest_id='main', nest_code='main',
                           nest_name='Home Nest', is_main_nest=True)


@app.route('/nest/<code>')
def nest_page(code):
    """Render the main page scoped to a specific nest."""
    if nest_manager is None:
        return 'Nests not available', 503
    nest = nest_manager.get_nest(code)
    if nest is None:
        return 'Nest not found', 404
    return render_template('main.html',
                           nest_id=nest.get('nest_id', code),
                           nest_code=code,
                           nest_name=nest.get('name', ''),
                           is_main_nest=False)


@app.route('/socket/')
def socket():
    # WebSocket connections are handled in before_request hook
    # This route is a fallback for non-WebSocket requests
    return 'WebSocket required', 400


@app.route('/volume/')
def volume():
    # WebSocket connections are handled in before_request hook
    # This route is a fallback for non-WebSocket requests
    return 'WebSocket required', 400


@app.route('/get_volume/')
def get_volume():
    return str(d.get_volume())


@app.route('/api/jammit/')
def jambutton():
    d.jam(d.get_now_playing()['id'], 'jambutton@echonest.com')
    return ''


@app.route('/jam', methods=['POST'])
@require_session_or_api_token
def jam():
    from flask import g
    id = request.values['id']
    email = g.auth_email
    app.logger.debug('Jam {0}, {1}'.format(email, id))
    _log_action('jam', email, song_id=id)
    d.jam(id, email)

    resp = jsonify({"success": True})
    resp.status_code = 200

    return resp


@app.route('/signup/', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')

    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''
    confirm = request.form.get('confirm') or ''

    # Basic email format validation
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return render_template('signup.html', error='Please enter a valid email address.')

    if len(password) < 6:
        return render_template('signup.html', error='Password must be at least 6 characters.', email=email)

    if password != confirm:
        return render_template('signup.html', error='Passwords do not match.', email=email)

    # Rate limit: 5 signups per hour per IP
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    rate_key = 'SIGNUP_RATE|{}'.format(client_ip)
    r = redis.StrictRedis(host=CONF.REDIS_HOST or 'localhost', port=CONF.REDIS_PORT or 6379,
                          password=CONF.REDIS_PASSWORD or None, decode_responses=True)
    attempts = r.get(rate_key)
    if attempts and int(attempts) >= 5:
        return render_template('signup.html', error='Too many signups from this address. Please try again later.', email=email)

    if d.guest_exists(email):
        return render_template('signup.html', error='An account with this email already exists. Try signing in instead.', email=email)

    d.create_guest(email, password)

    # Increment rate limit counter
    pipe = r.pipeline()
    pipe.incr(rate_key)
    pipe.expire(rate_key, 3600)  # 1 hour TTL
    pipe.execute()

    session['email'] = email
    session['fullname'] = 'Guest'
    analytics.track(d._r, 'signup', email)
    return redirect('/')



# , content_type="application/javascript")
@app.route('/config.js', methods=['GET'])
def configjs():
    r = make_response(render_template('config.js'))
    r.headers['Content-type'] = 'application/javascript'
    return r


@app.route('/userimg/<address>/img.png')
def user_img(address):
    return redirect(d.get_user_img(address))


@app.route("/last/")
def last_played():
    rv = {}
    last_played = d.get_last_played()
    if last_played:
        last_played = json.loads(last_played)
        for k in USEFUL_PROPS + ('endtime', 'jam', 'airhorn'):
            rv[k] = last_played.get(k, '')
        rv['now'] = datetime.datetime.now().isoformat()

    return jsonify(**rv)


@app.route("/airhorns/")
def current_airhorns():
    summarized_airhorns = []
    stored_airhorns = d.get_current_airhorns()
    if stored_airhorns:
        for dumped_airhorn in stored_airhorns:
            airhorn = json.loads(dumped_airhorn)
            summarized_airhorn = {}
            for k in ('when', 'free', 'artist', 'title', 'user'):
                summarized_airhorn[k] = airhorn.get(k, '')
            summarized_airhorn['now'] = datetime.datetime.now().isoformat()
            summarized_airhorns.append(summarized_airhorn)
    return jsonify(current_airhorns=summarized_airhorns)


@app.route('/history/<int:n_plays>')
def history_api(n_plays):
    # get the last N recorded plays and return as a list of JSON objects
    plays = d.get_historian().get_plays(n_plays)
    return jsonify(plays=plays, n_requested=n_plays, n_retrieved=len(plays))


@app.route('/user_history/<string:userid>')
def user_history_api(userid):
    if not (userid.endswith('@spotify.com') or userid.endswith('@echonest.com')):
        raise ProseccoAPIError(
            "invalid user ID '%ss'; must be a spotify.com or echonest.com e-mail address" % userid)
    plays = d.get_historian().get_user_plays(userid)
    return jsonify(plays=plays, userid_requested=userid, n_retrieved=len(plays))


@app.route('/user_jam_history/<string:userid>')
def user_jam_history_api(userid):
    if not (userid.endswith('@spotify.com') or userid.endswith('@echonest.com')):
        raise ProseccoAPIError(
            "invalid user ID '%ss'; must be a spotify.com or echonest.com e-mail address" % userid)
    jams = d.get_historian().get_user_jams(userid)
    return jsonify(jams=jams, userid_requested=userid, n_retrieved=len(jams))


@app.route('/search/v2', methods=['GET'])
def search_spotify():
    q = request.values['q']

    # Check if we're rate limited before making API call
    if is_spotify_rate_limited():
        resp = jsonify({"error": "Spotify rate limited. Please try again later."})
        resp.status_code = 429
        return resp

    # Handle get_access_token returning dict in newer spotipy versions
    token = auth.get_access_token()
    if isinstance(token, dict):
        token = token.get('access_token', token)
    sp = spotipy.Spotify(auth=token)

    try:
        search_result = sp.search(q, 10)
        analytics.track(d._r, 'spotify_api_search')
    except spotipy.exceptions.SpotifyException as e:
        if handle_spotify_exception(e):
            resp = jsonify({"error": "Spotify rate limited. Please try again later."})
            resp.status_code = 429
            return resp
        analytics.track(d._r, 'spotify_api_error')
        raise

    parsed_result = []
    items = search_result.get('tracks', {}).get('items')
    for track in items:
        current_track = {}
        current_track['uri'] = track.get('uri', "")
        current_track['track_name'] = track.get('name', "")
        artists = track.get('album', {}).get('artists', [])
        if len(artists) > 0:
            current_track['artist'] = artists[0].get('name', "")
        images = track.get('album', {}).get('images', "")
        if len(images) > 0:
            current_track['images'] = images[0]

        parsed_result.append(current_track)

    return jsonify(parsed_result)


@app.route('/youtube/lookup', methods=['GET'])
def youtube_lookup():
    """Lookup YouTube video metadata by ID. Proxies request to hide API key."""
    video_id = request.values.get('id')
    if not video_id:
        return jsonify({"error": "Missing video ID"}), 400

    # Validate video ID format (11 alphanumeric chars with - and _)
    import re
    if not re.match(r'^[\w-]{11}$', video_id):
        return jsonify({"error": "Invalid video ID format"}), 400

    if not CONF.YT_API_KEY or CONF.YT_API_KEY == 'your-youtube-api-key':
        return jsonify({"error": "YouTube API not configured"}), 503

    try:
        response = requests.get('https://www.googleapis.com/youtube/v3/videos',
            params={
                'id': video_id,
                'part': 'snippet,contentDetails',
                'key': CONF.YT_API_KEY
            },
            timeout=10)

        if response.status_code == 403:
            logger.warning("YouTube API quota exceeded or key invalid")
            return jsonify({"error": "YouTube API quota exceeded"}), 429

        if response.status_code != 200:
            logger.error("YouTube API error: %d %s", response.status_code, response.text)
            return jsonify({"error": "YouTube API error"}), response.status_code

        return jsonify(response.json())

    except requests.exceptions.Timeout:
        return jsonify({"error": "YouTube API timeout"}), 504
    except Exception as e:
        logger.error("YouTube lookup error: %s", str(e))
        return jsonify({"error": "Internal error"}), 500


@app.route('/youtube/playlist', methods=['GET'])
def youtube_playlist():
    """Lookup YouTube playlist items. Returns video metadata for up to 20 items."""
    import re
    playlist_id = request.values.get('id')
    if not playlist_id:
        return jsonify({"error": "Missing playlist ID"}), 400

    if not re.match(r'^[\w-]+$', playlist_id):
        return jsonify({"error": "Invalid playlist ID format"}), 400

    if not CONF.YT_API_KEY or CONF.YT_API_KEY == 'your-youtube-api-key':
        return jsonify({"error": "YouTube API not configured"}), 503

    try:
        # Step 1: Get playlist items (video IDs)
        pl_response = requests.get('https://www.googleapis.com/youtube/v3/playlistItems',
            params={
                'playlistId': playlist_id,
                'part': 'contentDetails',
                'maxResults': 20,
                'key': CONF.YT_API_KEY
            },
            timeout=10)

        if pl_response.status_code == 404:
            return jsonify({"error": "Playlist not found"}), 404
        if pl_response.status_code == 403:
            return jsonify({"error": "YouTube API quota exceeded"}), 429
        if pl_response.status_code != 200:
            return jsonify({"error": "YouTube API error"}), pl_response.status_code

        pl_data = pl_response.json()
        video_ids = [item['contentDetails']['videoId'] for item in pl_data.get('items', [])]

        if not video_ids:
            return jsonify({"items": []})

        # Step 2: Get full video metadata (snippet + contentDetails)
        vid_response = requests.get('https://www.googleapis.com/youtube/v3/videos',
            params={
                'id': ','.join(video_ids),
                'part': 'snippet,contentDetails',
                'key': CONF.YT_API_KEY
            },
            timeout=10)

        if vid_response.status_code != 200:
            return jsonify({"error": "YouTube API error"}), vid_response.status_code

        return jsonify(vid_response.json())

    except requests.exceptions.Timeout:
        return jsonify({"error": "YouTube API timeout"}), 504
    except Exception as e:
        logger.error("YouTube playlist lookup error: %s", str(e))
        return jsonify({"error": "Internal error"}), 500


@app.route('/add_song', methods=['POST'])
@require_session_or_api_token
def add_song_v2():
    from flask import g
    track_uri = request.values['track_uri']
    email = g.auth_email
    app.logger.debug('add_spotify_song "{0}" "{1}"'.format(email, track_uri))
    _log_action('add_song', email, track_uri=track_uri)
    d.add_spotify_song(email, track_uri, penalty=0)

    resp = jsonify({"success": True})
    resp.status_code = 200

    return resp


@app.route('/blast_airhorn', methods=['POST'])
@require_session_or_api_token
def blast_airhorn():
    from flask import g
    airhorn_name = request.values['name']
    email = g.auth_email
    app.logger.debug('Airhorn {0}, {1}'.format(email, airhorn_name))
    _log_action('blast_airhorn', email, name=airhorn_name)
    d.airhorn(userid=email, name=airhorn_name)

    resp = jsonify({"success": True})
    resp.status_code = 200

    return resp


@app.route('/airhorn_list', methods=['GET'])
def airhorn_list():
    airhorns_list = list(airhorns)
    resp = jsonify(airhorns_list)

    return resp


# ---------------------------------------------------------------------------
# Admin stats dashboard
# ---------------------------------------------------------------------------

def _is_admin(email):
    admin_emails = CONF.ADMIN_EMAILS or []
    if isinstance(admin_emails, str):
        admin_emails = [e.strip() for e in admin_emails.split(',')]
    return email in admin_emails


@app.route('/stats')
def public_stats():
    today_stats = analytics.get_daily_stats(d._r)
    dau_today = analytics.get_daily_active_users(d._r)
    dau_trend = analytics.get_dau_trend(d._r, days=7)
    all_users = analytics.get_user_stats(d._r, days=7)
    known_users = analytics.get_known_user_count(d._r)
    spotify_api = analytics.get_spotify_api_stats(d._r, days=7)
    spotify_oauth = analytics.get_spotify_oauth_stats(d._r, days=7)

    # "You vs Others" only available when logged in
    email = session.get('email')
    my_stats = {}
    others_stats = {}
    others_count = 0
    event_types = ['song_add', 'vote', 'jam', 'airhorn', 'login', 'ws_connect']
    for u in all_users:
        if email and u['email'] == email:
            my_stats = u
        else:
            others_count += 1
            for et in event_types:
                others_stats[et] = others_stats.get(et, 0) + u.get(et, 0)

    return render_template('stats.html',
                           today=today_stats,
                           dau_count=len(dau_today),
                           dau_trend=dau_trend,
                           my_stats=my_stats,
                           others_stats=others_stats,
                           others_count=others_count,
                           known_users=known_users,
                           logged_in=bool(email),
                           spotify_api=spotify_api,
                           spotify_oauth=spotify_oauth)


@app.route('/admin/stats')
def admin_stats_redirect():
    return redirect('/stats')


@app.route('/help')
def help_page():
    guide_path = os.path.join(os.path.dirname(__file__), 'docs', 'GETTING_STARTED.md')
    try:
        with open(guide_path, 'r') as f:
            md = f.read()
        guide_html = _markdown_to_html(md)
    except Exception:
        guide_html = '<p>Guide not available.</p>'
    return render_template('help.html', guide_html=guide_html)


def _markdown_to_html(text):
    """Minimal markdown-to-HTML for the getting started guide."""
    import re
    lines = text.split('\n')
    html_lines = []
    in_list = None  # 'ol' or 'ul'
    in_table = False
    in_p = False

    def inline(s):
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', s)
        s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
        return s

    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append(f'</{in_list}>')
            in_list = None

    def close_p():
        nonlocal in_p
        if in_p:
            html_lines.append('</p>')
            in_p = False

    def close_table():
        nonlocal in_table
        if in_table:
            html_lines.append('</tbody></table>')
            in_table = False

    for line in lines:
        stripped = line.strip()

        # blank line
        if not stripped:
            close_list()
            close_p()
            continue

        # headings
        m = re.match(r'^(#{1,3})\s+(.*)', stripped)
        if m:
            close_list()
            close_p()
            close_table()
            level = len(m.group(1))
            html_lines.append(f'<h{level}>{inline(m.group(2))}</h{level}>')
            continue

        # table separator row (skip)
        if re.match(r'^\|[\s\-:|]+\|$', stripped):
            continue

        # table header row
        if stripped.startswith('|') and not in_table:
            close_list()
            close_p()
            cells = [c.strip() for c in stripped.strip('|').split('|')]
            html_lines.append('<table><thead><tr>')
            for c in cells:
                html_lines.append(f'<th>{inline(c)}</th>')
            html_lines.append('</tr></thead><tbody>')
            in_table = True
            continue

        # table data row
        if stripped.startswith('|') and in_table:
            cells = [c.strip() for c in stripped.strip('|').split('|')]
            html_lines.append('<tr>')
            for c in cells:
                html_lines.append(f'<td>{inline(c)}</td>')
            html_lines.append('</tr>')
            continue

        # close table if non-table line
        if in_table and not stripped.startswith('|'):
            close_table()

        # ordered list
        m = re.match(r'^(\d+)\.\s+(.*)', stripped)
        if m:
            close_p()
            if in_list != 'ol':
                close_list()
                html_lines.append('<ol>')
                in_list = 'ol'
            html_lines.append(f'<li>{inline(m.group(2))}</li>')
            continue

        # unordered list
        m = re.match(r'^[-*]\s+(.*)', stripped)
        if m:
            close_p()
            if in_list != 'ul':
                close_list()
                html_lines.append('<ul>')
                in_list = 'ul'
            html_lines.append(f'<li>{inline(m.group(1))}</li>')
            continue

        # list continuation (indented under a list item)
        if in_list and line.startswith('   '):
            last = html_lines[-1]
            if last.endswith('</li>'):
                html_lines[-1] = last[:-5] + ' ' + inline(stripped) + '</li>'
            continue

        # paragraph
        close_list()
        if not in_p:
            html_lines.append('<p>')
            in_p = True
        html_lines.append(inline(stripped))

    close_list()
    close_p()
    close_table()
    return '\n'.join(html_lines)


# ---------------------------------------------------------------------------
# REST API (token-authenticated, for programmatic access e.g. OpenClaw)
# ---------------------------------------------------------------------------

@app.route('/api/queue/remove', methods=['POST'])
@require_api_token
def api_queue_remove():
    body = request.get_json(silent=True) or {}
    song_id = body.get('id')
    if not song_id:
        return jsonify(error='Missing required field: id'), 400
    d.kill_song(song_id, API_EMAIL)
    return jsonify(ok=True)


@app.route('/api/queue/skip', methods=['POST'])
@require_api_token
def api_queue_skip():
    d.kill_playing(API_EMAIL)
    return jsonify(ok=True)


@app.route('/api/queue/vote', methods=['POST'])
@require_api_token
def api_queue_vote():
    body = request.get_json(silent=True) or {}
    song_id = body.get('id')
    if not song_id:
        return jsonify(error='Missing required field: id'), 400
    up = body.get('up', True)
    # Normalize: accept bool, string, or int
    if isinstance(up, str):
        up = up.lower() in ('true', '1', 'yes')
    else:
        up = bool(up)
    d.vote(API_EMAIL, song_id, up)
    return jsonify(ok=True)


@app.route('/api/queue/pause', methods=['POST'])
@require_api_token
def api_queue_pause():
    d.pause(API_EMAIL)
    return jsonify(ok=True)


@app.route('/api/queue/resume', methods=['POST'])
@require_api_token
def api_queue_resume():
    d.unpause(API_EMAIL)
    return jsonify(ok=True)


@app.route('/api/queue/clear', methods=['POST'])
@require_api_token
def api_queue_clear():
    d.nuke_queue(API_EMAIL)
    return jsonify(ok=True)


@app.route('/api/add_song', methods=['POST'])
@require_api_token
def api_add_song():
    from flask import g
    body = request.get_json(silent=True) or {}
    track_uri = body.get('track_uri')
    if not track_uri:
        return jsonify(error='Missing required field: track_uri'), 400
    email = getattr(g, 'auth_email', API_EMAIL)
    new_id = d.add_spotify_song(email, track_uri, penalty=0)
    if new_id:
        return jsonify(ok=True, id=new_id)
    return jsonify(error='Failed to add song'), 500


# ---------------------------------------------------------------------------
# Spotify Connect (device control) API
# ---------------------------------------------------------------------------

SPOTIFY_CONNECT_SCOPE = "streaming user-read-currently-playing user-read-playback-state user-modify-playback-state"


def _get_spotify_client():
    """Build a Spotify client from the cached OAuth token for ECHONEST_SPOTIFY_EMAIL.

    Returns (spotipy.Spotify, None) on success or (None, error_string) on failure.
    """
    email = CONF.ECHONEST_SPOTIFY_EMAIL
    if not email:
        return None, "ECHONEST_SPOTIFY_EMAIL not configured"

    try:
        os.makedirs(CONF.OAUTH_CACHE_PATH)
    except Exception:
        pass

    sp_auth = spotipy.oauth2.SpotifyOAuth(
        CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
        "prosecco:%s" % email, scope=SPOTIFY_CONNECT_SCOPE,
        cache_path="%s/%s" % (CONF.OAUTH_CACHE_PATH, email))

    token_info = sp_auth.get_cached_token()
    if not token_info:
        analytics.track(d._r, 'spotify_oauth_stale', email)
        return None, "No cached Spotify token for %s — visit the web UI and click 'sync audio' first" % email

    return spotipy.Spotify(auth=token_info['access_token']), None


@app.route('/api/spotify/devices', methods=['GET'])
@require_api_token
def api_spotify_devices():
    sp, err = _get_spotify_client()
    if sp is None:
        return jsonify(error=err), 503
    try:
        result = sp.devices()
        analytics.track(d._r, 'spotify_api_devices')
        return jsonify(result)
    except spotipy.exceptions.SpotifyException as e:
        analytics.track(d._r, 'spotify_api_error')
        logger.error("Spotify devices error: %s", e)
        return jsonify(error=str(e)), 502


@app.route('/api/spotify/transfer', methods=['POST'])
@require_api_token
def api_spotify_transfer():
    sp, err = _get_spotify_client()
    if sp is None:
        return jsonify(error=err), 503

    body = request.get_json(silent=True) or {}
    device_id = body.get('device_id')
    if not device_id:
        return jsonify(error='Missing required field: device_id'), 400

    play = body.get('play', True)
    try:
        sp.transfer_playback(device_id, force_play=bool(play))
        analytics.track(d._r, 'spotify_api_transfer')
        return jsonify(ok=True)
    except spotipy.exceptions.SpotifyException as e:
        analytics.track(d._r, 'spotify_api_error')
        logger.error("Spotify transfer error: %s", e)
        return jsonify(error=str(e)), 502


@app.route('/api/spotify/status', methods=['GET'])
@require_api_token
def api_spotify_status():
    sp, err = _get_spotify_client()
    if sp is None:
        return jsonify(error=err), 503
    try:
        playback = sp.current_playback()
        analytics.track(d._r, 'spotify_api_status')
        return jsonify(playback)
    except spotipy.exceptions.SpotifyException as e:
        analytics.track(d._r, 'spotify_api_error')
        logger.error("Spotify status error: %s", e)
        return jsonify(error=str(e)), 502


# ---------------------------------------------------------------------------
# Rich read endpoints + SSE event stream
# ---------------------------------------------------------------------------

API_QUEUE_PROPS = ('id', 'title', 'artist', 'trackid', 'src', 'user', 'img', 'big_img',
                   'duration', 'vote', 'jam', 'comments', 'score', 'auto')

API_PLAYING_PROPS = ('id', 'title', 'artist', 'trackid', 'src', 'user', 'img', 'big_img',
                     'duration', 'vote', 'jam', 'comments', 'starttime', 'endtime',
                     'paused', 'pos', 'type')


def _pick(obj, keys):
    """Extract *keys* from dict *obj*, defaulting missing values to ''."""
    return {k: obj.get(k, '') for k in keys}


def _serialize_queue():
    queue = d.get_queued()
    return [_pick(x, API_QUEUE_PROPS) for x in queue]


def _serialize_playing():
    playing = d.get_now_playing()
    rv = _pick(playing, API_PLAYING_PROPS)
    rv['now'] = datetime.datetime.now().isoformat()
    return rv


@app.route('/api/queue', methods=['GET'])
@require_api_token
def api_queue():
    return jsonify(queue=_serialize_queue(), now=datetime.datetime.now().isoformat())


@app.route('/api/playing', methods=['GET'])
@require_api_token
def api_playing():
    return jsonify(**_serialize_playing())


@app.route('/api/stats', methods=['GET'])
def api_stats():
    """Concise JSON analytics snapshot. Public for aggregate data;
    Bearer token required to include per-user email details."""
    days = min(int(request.args.get('days', 7)), 90)
    today_stats = analytics.get_daily_stats(d._r)
    dau_today = analytics.get_daily_active_users(d._r)
    dau_trend = analytics.get_dau_trend(d._r, days=days)
    known_users = analytics.get_known_user_count(d._r)

    spotify_api = analytics.get_spotify_api_stats(d._r, days=days)
    spotify_oauth = analytics.get_spotify_oauth_stats(d._r, days=days)

    # Check if caller provided a valid API token — emails only with auth
    authenticated = False
    configured_token = CONF.ECHONEST_API_TOKEN
    if configured_token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            provided_token = auth_header[7:]
            authenticated = secrets.compare_digest(provided_token, configured_token)

    if not authenticated:
        # Strip email addresses from stale_users, keep just the counts
        spotify_oauth['stale_users'] = [
            {'count': u['count'], 'date': u['date']}
            for u in spotify_oauth.get('stale_users', [])
        ]

    return jsonify(
        today=today_stats,
        dau=len(dau_today),
        dau_trend=[{'date': date, 'users': count} for date, count in dau_trend],
        known_users=known_users,
        spotify_api=spotify_api,
        spotify_oauth=spotify_oauth,
    )


@app.route('/sync/link')
def sync_link_page():
    """Show a linking code for echonest-sync account linking.

    Requires Google session auth. If not logged in, redirect to login.
    """
    email = _get_authenticated_email()
    if not email:
        return redirect('/login/google')

    # Generate 6-char uppercase alphanumeric code
    code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))

    # Store in Redis with 5 min TTL
    link_data = json.dumps({'email': email, 'name': session.get('fullname', '')})
    d._r.setex(f'SYNC_LINK|{code}', 300, link_data)

    return render_template('sync_link.html', code=code, email=email)


@app.route('/api/sync-link', methods=['POST'])
@require_api_token
def api_sync_link():
    """Exchange a linking code for a per-user sync token."""
    # Rate limit: 10 attempts per IP per hour
    ip = request.remote_addr or 'unknown'
    rate_key = f'SYNC_TOKEN_RATE|{ip}'
    attempts = d._r.incr(rate_key)
    if attempts == 1:
        d._r.expire(rate_key, 3600)
    if attempts > 10:
        return jsonify(error='rate_limited'), 429

    body = request.get_json(silent=True) or {}
    code = (body.get('code') or '').strip().upper()
    if not code:
        return jsonify(error='missing_code'), 400

    # Look up the linking code
    redis_key = f'SYNC_LINK|{code}'
    link_data = d._r.get(redis_key)
    if not link_data:
        return jsonify(error='invalid_or_expired_code'), 404

    # Single-use: delete immediately
    d._r.delete(redis_key)

    data = json.loads(link_data)
    email = data['email']
    name = data.get('name', '')

    # Generate deterministic per-user token
    user_token = _compute_user_token(email)

    # Track this linked user
    d._r.sadd('SYNC_LINKED_USERS', email)

    # Invalidate cache so the token works immediately
    _linked_users_cache['ts'] = 0

    return jsonify(email=email, name=name, user_token=user_token)


@app.route('/api/sync-token', methods=['POST'])
def api_sync_token():
    """Exchange an invite code for an API token (echonest-sync desktop app).

    No @require_api_token — the invite code IS the authentication.
    Rate limited to 10 attempts per IP per hour.
    """
    # Rate limit: 10 attempts per IP per hour
    ip = request.remote_addr or 'unknown'
    rate_key = f'SYNC_TOKEN_RATE|{ip}'
    attempts = d._r.incr(rate_key)
    if attempts == 1:
        d._r.expire(rate_key, 3600)
    if attempts > 10:
        return jsonify(error='rate_limited'), 429

    body = request.get_json(silent=True) or {}
    invite_code = (body.get('invite_code') or '').strip()

    if not invite_code:
        return jsonify(error='missing_code'), 400

    valid_codes = CONF.SYNC_INVITE_CODES or []
    if invite_code not in valid_codes:
        return jsonify(error='invalid_code'), 401

    configured_token = CONF.ECHONEST_API_TOKEN
    if not configured_token:
        return jsonify(error='server_not_configured'), 503

    hostname = CONF.HOSTNAME or request.host
    scheme = 'https' if (request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https') else 'http'
    server_url = f'{scheme}://{hostname}'

    return jsonify(token=configured_token, server=server_url)


@app.route('/api/events', methods=['GET'])
@require_api_token
def api_events():
    def generate():
        r = redis.StrictRedis(
            host=CONF.REDIS_HOST or 'localhost',
            port=CONF.REDIS_PORT or 6379,
            password=CONF.REDIS_PASSWORD or None,
            decode_responses=True,
        ).pubsub()
        r.subscribe(pubsub_channel("main"))
        try:
            while True:
                msg = None
                with gevent.Timeout(15, False):
                    msg = r.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg is None:
                    # keepalive
                    yield ': keepalive\n\n'
                    continue
                data = msg.get('data')
                if not isinstance(data, str):
                    continue

                if data == 'playlist_update':
                    payload = json.dumps(_serialize_queue())
                    yield 'event: queue_update\ndata: %s\n\n' % payload
                elif data == 'now_playing_update':
                    payload = json.dumps(_serialize_playing())
                    yield 'event: now_playing\ndata: %s\n\n' % payload
                    # Also send queue update like the WebSocket does
                    q_payload = json.dumps(_serialize_queue())
                    yield 'event: queue_update\ndata: %s\n\n' % q_payload
                elif data.startswith('pp|'):
                    _, src, track, pos = data.split('|', 3)
                    payload = json.dumps({'src': src, 'trackid': track, 'pos': int(pos)})
                    yield 'event: player_position\ndata: %s\n\n' % payload
                elif data.startswith('v|'):
                    _, vol = data.split('|', 1)
                    payload = json.dumps({'volume': int(vol)})
                    yield 'event: volume\ndata: %s\n\n' % payload
                elif data.startswith('do_airhorn|'):
                    _, vol, name = data.split('|', 2)
                    payload = json.dumps({'volume': float(vol), 'name': name})
                    yield 'event: airhorn\ndata: %s\n\n' % payload
        except GeneratorExit:
            pass
        finally:
            r.unsubscribe()
            r.close()

    resp = Response(stream_with_context(generate()), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


# ---------------------------------------------------------------------------
# Nests API (token-authenticated, for managing nests)
# ---------------------------------------------------------------------------

# Reserved words that cannot be used as vanity codes
_VANITY_RESERVED = frozenset({
    'api', 'socket', 'login', 'signup', 'static', 'assets',
    'health', 'status', 'metrics', 'terms', 'privacy',
    'admin', 'nest', 'nests', 'volume', 'queue', 'playing',
    'logout', 'guest', 'main',
})

import re
_VANITY_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9-]*$')


def _validate_vanity_code(code):
    """Validate a vanity code. Returns (ok, error_message)."""
    if not code:
        return True, None
    if len(code) < 3:
        return False, "Vanity code must be at least 3 characters"
    if len(code) > 24:
        return False, "Vanity code must be at most 24 characters"
    if code.lower() in _VANITY_RESERVED:
        return False, f"'{code}' is a reserved word"
    if not _VANITY_RE.match(code):
        return False, "Vanity code must start with a letter and contain only letters, digits, and hyphens"
    return True, None


@app.route('/api/nests', methods=['POST'])
@require_session_or_api_token
def api_nests_create():
    from flask import g
    if nest_manager is None:
        return jsonify(error='Nests not available'), 503
    body = request.get_json(silent=True) or {}
    name = body.get('name')
    seed_track = body.get('seed_track')
    creator = g.auth_email
    try:
        nest = nest_manager.create_nest(creator, name=name, seed_track=seed_track)
        slack.notify_nest_created(nest)
        return jsonify(nest)
    except ValueError as e:
        return jsonify(error='invalid_request', message=str(e)), 400
    except Exception as e:
        logger.error("Error creating nest: %s", e)
        return jsonify(error='internal_error', message=str(e)), 500


@app.route('/api/nests', methods=['GET'])
@require_session_or_api_token
def api_nests_list():
    if nest_manager is None:
        return jsonify(error='Nests not available'), 503
    nests_list = nest_manager.list_nests()
    result = []
    for nest_id, meta in nests_list:
        # Include now-playing summary and member count
        try:
            nest_db = DB(init_history_to_redis=False, nest_id=nest_id)
            np = nest_db.get_now_playing()
            if np and np.get('title'):
                meta['now_playing'] = {
                    'title': np.get('title', ''),
                    'artist': np.get('secondary_text') or np.get('artist', ''),
                }
            else:
                meta['now_playing'] = None
        except Exception:
            meta['now_playing'] = None
        try:
            mkey = members_key(nest_id)
            meta['member_count'] = nest_manager._r.scard(mkey)
        except Exception:
            meta['member_count'] = 0
        result.append(meta)
    return jsonify(nests=result)


@app.route('/api/nests/<code>', methods=['GET'])
@require_session_or_api_token
def api_nests_get(code):
    if nest_manager is None:
        return jsonify(error='Nests not available'), 503
    nest = nest_manager.get_nest(code)
    if nest is None:
        return jsonify(error='not_found', message='Nest not found.'), 404
    # Include member count for frontend display
    mkey = members_key(code)
    try:
        nest['member_count'] = nest_manager._r.scard(mkey)
    except Exception:
        nest['member_count'] = 0
    return jsonify(nest)


@app.route('/api/nests/<code>', methods=['PATCH'])
@require_session_or_api_token
def api_nests_update(code):
    from flask import g
    if nest_manager is None:
        return jsonify(error='Nests not available'), 503
    nest = nest_manager.get_nest(code)
    if nest is None:
        return jsonify(error='not_found', message='Nest not found.'), 404

    # Only the creator can update a nest (field is 'creator' in all nest metadata)
    if g.auth_email != nest.get('creator'):
        return jsonify(error='forbidden', message='Only the nest creator can update it.'), 403

    body = request.get_json(silent=True) or {}

    # Update name if provided
    if 'name' in body:
        nest['name'] = body['name']

    # Store updated metadata (use nest_id, not the URL code, to avoid duplicates)
    nest_manager._r.hset('NESTS|registry', nest['nest_id'], json.dumps(nest))
    return jsonify(nest)


@app.route('/api/nests/<code>', methods=['DELETE'])
@require_session_or_api_token
def api_nests_delete(code):
    if nest_manager is None:
        return jsonify(error='Nests not available'), 503
    nest = nest_manager.get_nest(code)
    if nest is None:
        return jsonify(error='not_found', message='Nest not found.'), 404
    if nest.get('is_main'):
        return jsonify(error='forbidden', message='Cannot delete the main nest.'), 403
    nest_manager.delete_nest(code)
    return jsonify(ok=True)


# Catch-all for bare nest codes: echone.st/X7K2P → /nest/X7K2P
# Must be registered LAST so it doesn't shadow other routes.
import re
_NEST_CODE_RE = re.compile(r'^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{5}$')


@app.route('/<path:code>')
def nest_code_catchall(code):
    """Resolve bare nest codes or slugs to the nest page."""
    if _NEST_CODE_RE.match(code.upper()):
        return redirect('/nest/' + code.upper())
    # Try slug lookup (e.g., echone.st/friday-vibes)
    if nest_manager is not None:
        from nests import slugify
        slug = slugify(code)
        if slug:
            nest = nest_manager.get_nest(slug)
            if nest:
                return redirect('/nest/' + nest['code'])
    abort(404)
