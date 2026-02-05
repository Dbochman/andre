from gevent import monkey
monkey.patch_all()

import os.path
import logging
import json
import datetime
import hashlib
import urllib.parse
import urllib.request
import socket as psocket
import gevent
import redis
import requests
import time
import psycopg2

import spotipy.oauth2
import spotipy

from flask import Flask, request, render_template, session, redirect, jsonify, make_response
from flask_assets import Environment, Bundle

from config import CONF
from db import DB

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

def _handle_websocket():
    """Handle WebSocket connections in before_request (before Flask route dispatch)."""
    if request.environ.get('wsgi.websocket') is None:
        return 'WebSocket required', 400
    email = _get_authenticated_email()
    if not email:
        return 'Unauthorized', 401
    MusicNamespace(email, 0).serve()
    return ''

def _handle_volume_websocket():
    """Handle volume WebSocket connections."""
    if request.environ.get('wsgi.websocket') is None:
        return 'WebSocket required', 400
    VolumeNamespace().serve()
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

auth = spotipy.oauth2.SpotifyClientCredentials(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET)
auth.get_access_token()

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
        self._ws.send('1' + json.dumps(args))

    def serve(self):
        try:
            while True:
                msg = None
                with gevent.Timeout(30, False):
                    msg = self._ws.receive()
                if msg is None:
                    # Timeout - check if connection is still open
                    if getattr(self._ws, 'closed', False):
                        logger.info('WebSocket closed by client')
                        break
                    # No message yet (timeout); keep connection open
                    continue
                if msg == '' and msg != '0':
                    if getattr(self._ws, 'closed', False):
                        logger.info('WebSocket closed by client')
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
                    pass
                else:
                    print(T, msg)
                    print('Invalid msg type')
                    return
        except Exception:
            logger.exception('WebSocket fatal error')
        finally:
            try:
                self._ws.close()
            except Exception:
                logger.exception('WebSocket close failed')
            gevent.killall(self._children)


class MusicNamespace(WebSocketManager):
    def __init__(self, email, penalty):
        super(MusicNamespace, self).__init__()
        print("MusicNamespace init")
        try:
            os.makedirs(CONF.OAUTH_CACHE_PATH)
        except Exception:
            pass
        self.logger = app.logger
        self.email = email
        print(self.email) 
        self.penalty = penalty
        self.auth = spotipy.oauth2.SpotifyOAuth(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
                                                "prosecco:%s" % email, scope="streaming user-read-currently-playing", cache_path="%s/%s" % (CONF.OAUTH_CACHE_PATH, email))
        self.spawn(self.listener)
        self.log('New namespace for {0}'.format(self.email))

    def listener(self):
        r = redis.StrictRedis(host=CONF.REDIS_HOST or 'localhost', port=CONF.REDIS_PORT or 6379, decode_responses=True).pubsub()
        r.subscribe('MISC|update-pubsub')
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
                self.emit('free_horns', d.get_free_horns(self.email))

    def log(self, msg, debug=True):
        if debug:
            self.logger.debug(msg)
        else:
            self.logger.info(msg)

    def on_request_volume(self):
        self.emit('volume', str(d.get_volume()))

    def on_change_volume(self, vol):
        self.emit('volume', str(d.set_volume(vol)))

    def on_add_song(self, song_id, src):
        if src == 'spotify':
            self.log(
                'add_spotify_song "{0}" "{1}"'.format(self.email, song_id))
            d.add_spotify_song(self.email, song_id, penalty=self.penalty)
        elif src == 'youtube':
            self.log('add_youtube_song "{0}" "{1}"'.format(self.email, song_id))
            d.add_youtube_song(self.email, song_id, penalty=self.penalty)
        elif src == 'soundcloud':
            self.log(
                'add_soundcloud_song "{0}" "{1}"'.format(self.email, song_id))
            d.add_soundcloud_song(self.email, song_id, penalty=self.penalty)
        # self.log(d.get_queued()[-1])

    def on_fetch_playlist(self):
        self.emit('playlist_update', d.get_queued())

    def on_fetch_now_playing(self):
        self.emit('now_playing_update', d.get_now_playing())

    def on_fetch_search_token(self):
        logger.debug("fetch search token")
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
            self.emit('auth_token_refresh', self.auth.get_authorize_url())

    def on_fetch_airhorns(self):
        self.emit('airhorns', d.get_horns())

    def on_vote(self, id, up):
        self.log('Vote from {0} on {1} {2}'.format(self.email, id, up))
        d.vote(self.email, id, up)

    def on_kill(self, id):
        self.log('Kill {0} ({2}) from {1}'.format(id, self.email, d.get_song_from_queue(id).get('user')))
        d.kill_song(id, self.email)

    def on_kill_playing(self):
        self.log('Kill playing ({1}) from {0}'.format(self.email, d.get_now_playing().get('user')))
        d.kill_playing(self.email)

    def on_nuke_queue(self):
        self.log('Queue nuke from {0}'.format(self.email))
        d.nuke_queue(self.email)

    def on_airhorn(self, name):
        self.log('Airhorn {0}, {1}'.format(self.email, name))
        d.airhorn(self.email, name=name)

    def on_free_airhorn(self):
        self.log('Free Airhorn {0}'.format(self.email))
        d.free_airhorn(self.email)

    # def on_add_playlist(self, key, shuffled):
    #     self.log('Add playlist from {0} {1}'.format(self.email, key))
    #     d.add_playlist(self.email, key, shuffled)

    # def on_kill_src(self):
    #     self.log('Killed playlist from {0}'.format(self.email))
    #     d.kill_playlist()

    def on_jam(self, id):
        self.log('{0} jammed {1}'.format(self.email, id))
        d.jam(id, self.email)

    def on_benderQueue(self, id):
        self.log('{0} benderqueues {1}'.format(self.email, id))
        d.benderqueue(id, self.email)

    def on_benderFilter(self, id):
        self.log('{0} benderfilters {1}'.format(self.email, id))
        d.benderfilter(id, self.email)

    def on_get_free_horns(self):
        self.emit('free_horns', d.get_free_horns(self.email))

    def on_pause(self):
        self.log('Pause button! {0}'.format(self.email))
        d.pause(self.email)

    def on_unpause(self):
        self.log('Unpause button! {0}'.format(self.email))
        d.unpause(self.email)

    def on_add_comment(self, song_id, user_id, comment):
        self.log("Add comment from {}!".format(user_id))
        d.add_comment(song_id, user_id, comment)

    def on_get_comments_for_song(self, song_id):
        comments = d.get_comments(song_id)
        self.emit('comments_for_song', song_id, comments)

    def on_loaded_airhorn(self, name):
        airhorns.add(name.encode('ascii','ignore'))

class VolumeNamespace(WebSocketManager):
    def log(self, msg, debug=True):
        if debug:
            self.logger.debug(msg)
        else:
            self.logger.info(msg)

    def __init__(self, *args, **kwargs):
        super(VolumeNamespace, self).__init__(*args, **kwargs)
        self.logger = app.logger
        self.log('new volume listener! {0}'.format(request.remote_addr), False)
        self.spawn(self.listener)

    def on_request_volume(self):
        self.emit('volume', str(d.get_volume()))

    def on_change_volume(self, vol):
        self.emit('volume', str(d.set_volume(vol)))

    def listener(self):
        r = redis.StrictRedis(host=CONF.REDIS_HOST or 'localhost', port=CONF.REDIS_PORT or 6379, decode_responses=True).pubsub()
        r.subscribe('MISC|update-pubsub')
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

SAFE_PATHS = ('/login/', '/logout/', '/playing/', '/queue/', '/volume/',
              '/guest', '/guest/', '/api/jammit/', '/health',
              '/authentication/callback', '/token', '/last/', '/airhorns/', '/z/')
SAFE_PARAM_PATHS = ('/history', '/user_history', '/user_jam_history', '/search/v2', '/add_song',
    '/blast_airhorn', '/airhorn_list', '/queue/', '/jam')
VALID_HOSTS = ('localhost:5000', 'localhost:5001', '127.0.0.1:5000', '127.0.0.1:5001',
               str(CONF.HOSTNAME) if CONF.HOSTNAME else '')


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
        return redirect('/login/')


@app.after_request
def add_cors_header(response):
    unlikely_origin_string = 'lol origins are for wimps'
    origin = request.environ.get('HTTP_ORIGIN', unlikely_origin_string)
    response.headers.set('Access-Control-Allow-Credentials', 'true')
    if (origin != unlikely_origin_string):
        response.headers.set('Access-Control-Allow-Origin', origin)
        return response
    response.headers.set('Access-Control-Allow-Origin', '*')
    return response

if CONF.DEBUG:
    # Use HOSTNAME config even in debug mode
    host = CONF.HOSTNAME or 'localhost:5000'
    REDIRECT_URI = "http://{}/authentication/callback".format(host)
    SPOTIFY_REDIRECT_URI = "http://{}/authentication/spotify_callback".format(host)
else:
    # Production uses HTTPS behind reverse proxy
    REDIRECT_URI = "https://%s/authentication/callback" % CONF.HOSTNAME
    SPOTIFY_REDIRECT_URI = "https://%s/authentication/spotify_callback" % CONF.HOSTNAME

@app.route('/health')
def health():
    return jsonify(status='ok')

@app.route('/bounce/', methods=['GET'])
def bounce():
    return redirect(request.headers.get("Referer"), code=303)

@app.route('/z/', methods=['GET'])
def z():
    conn = psycopg2.connect("dbname='andre_database' user='postgres'  host='db'")
    cur = conn.cursor()
    cur.execute("""SELECT username from userdata""")
    rows  = cur.fetchall()
    output = "hi\n"
    for row in rows:
        output += row[0] + "\n"
    return output

@app.route('/login/')
def login():
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

    # Check email domain against allowed list
    email = user.get('email', '')
    allowed_domains = CONF.ALLOWED_EMAIL_DOMAINS or []
    # Ensure it's a list (handle case where config has a single string)
    if isinstance(allowed_domains, str):
        allowed_domains = [allowed_domains]

    email_allowed = False
    for domain in allowed_domains:
        if email.endswith('@' + domain):
            email_allowed = True
            break

    if not email_allowed:
        logger.warning('Login rejected for email: %s (allowed domains: %s)', email, allowed_domains)
        return redirect('/login/')

    for k1, k2 in (('email', 'email',), ('fullname', 'name'),):
        session[k1] = user[k2]

    return redirect('/')


@app.route('/logout/')
def logout():
    session.clear()
    return 'Logged Out, thank you!'


@app.route('/spotify_connect/')
def spotify_connect():
    return render_template('spotify_connect.html')


@app.route('/authentication/spotify_callback/')
def spotify_callback():
    try:
        os.makedirs(CONF.OAUTH_CACHE_PATH)
    except Exception:
        pass
    auth = spotipy.oauth2.SpotifyOAuth(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
                                       "prosecco:%s" % session['email'], scope="streaming user-read-currently-playing", cache_path="%s/%s" % (CONF.OAUTH_CACHE_PATH, session['email']))
    auth.get_access_token(request.values['code'])
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
    return render_template('main.html')


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
def jam():
    id = request.values['id']
    email = request.values['email']
    app.logger.debug('Jam {0}, {1}'.format(email, id))
    d.jam(id, email)

    resp = jsonify({"success": True})
    resp.status_code = 200

    return resp

@app.route('/guest/', methods=['GET', 'POST'])
def guest():
    if request.method == 'GET':
        return render_template('guest_login.html', failure=False)
    print(request.values)
    email = d.try_login(request.values.get('email', ''),
                        request.values.get('passwd', ''))
    if not email:
        return render_template('guest_login.html', failure=True)
    session['email'] = email
    session['fullname'] = 'Guest'
    return redirect('/')


@app.route('/add_guest/', methods=['GET', 'POST'])
def add_guest():
    if not session['email'].endswith('@spotify.com'):
        return redirect('/')
    if request.method == 'GET':
        return render_template('add_guest.html')
    email = request.values['email']
    target = (datetime.datetime.now() +
              datetime.timedelta(days=int(request.values['days'])))
    msg = 'Adding {0} as a guest for {1} until {2}'
    msg = msg.format(email, session['email'], target)
    d.add_login(email, target)
    return msg


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
    # Handle get_access_token returning dict in newer spotipy versions
    token = auth.get_access_token()
    if isinstance(token, dict):
        token = token.get('access_token', token)
    sp = spotipy.Spotify(auth=token)
    search_result = sp.search(q, 25)

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


@app.route('/add_song', methods=['POST'])
def add_song_v2():
    track_uri = request.values['track_uri']
    email = request.values['email']
    app.logger.debug('add_spotify_song "{0}" "{1}"'.format(email, track_uri))
    d.add_spotify_song(email, track_uri, penalty=0)

    resp = jsonify({"success": True})
    resp.status_code = 200

    return resp


@app.route('/blast_airhorn', methods=['POST'])
def blast_airhorn():
    airhorn_name = request.values['name']
    email = request.values['email']
    app.logger.debug('Airhorn {0}, {1}'.format(email, airhorn_name))
    d.airhorn(userid=email, name=airhorn_name)

    resp = jsonify({"success": True})
    resp.status_code = 200

    return resp


@app.route('/airhorn_list', methods=['GET'])
def airhorn_list():
    airhorns_list = list(airhorns)
    resp = jsonify(airhorns_list)

    return resp
