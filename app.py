from gevent import monkey
monkey.patch_all()

import os.path
import logging
import json
import datetime
import hashlib
import urllib
import urllib2
import socket as psocket
import gevent
import redis
import requests
import time
import sets
import psycopg2

import spotipy.oauth2
import spotipy

from flask import Flask, request, render_template, session, redirect, jsonify, make_response
from flask.ext.assets import Environment, Bundle

from config import CONF
from db import DB

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
assets = Environment(app)
app.config['GOOGLE_DOMAIN'] = 'spotify.com'
#auth = GoogleAuth(app) 

print CONF

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
                if not msg and msg != '0':
                    break
                T = msg[0]
                if T == '1':
                    data = json.loads(msg[1:]) if len(msg) > 1 else None
                    if not data:
                        continue
                    event = data[0]
                    args = data[1:]
                    getattr(self, 'on_' + event.replace('-', '_'))(*args)
                elif T == '0':
                    pass
                else:
                    print T, msg
                    print 'Invalid msg type'
                    return
        finally:
            self._ws.close()
            gevent.killall(self._children)


class MusicNamespace(WebSocketManager):
    def __init__(self, email, penalty):
        super(MusicNamespace, self).__init__()
        print "MusicNamespace init"
        try:
            os.makedirs(CONF.OAUTH_CACHE_PATH)
        except Exception:
            pass
        self.logger = app.logger
        self.email = email
        print self.email 
        self.penalty = penalty
        self.auth = spotipy.oauth2.SpotifyOAuth(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI,
                                                "prosecco:%s" % email, scope="streaming user-read-currently-playing", cache_path="%s/%s" % (CONF.OAUTH_CACHE_PATH, email))
        self.spawn(self.listener)
        self.log('New namespace for {0}'.format(self.email))

    def listener(self):
        r = redis.StrictRedis().pubsub()
        r.subscribe('MISC|update-pubsub')
        for m in r.listen():
            if m['type'] != 'message':
                continue
            m = m['data']

            if m == 'playlist_update':
                self.on_fetch_playlist()
            elif m == 'now_playing_update':
                self.on_fetch_now_playing()
                self.on_fetch_playlist()
            elif m.startswith('pp|'):
                #self.log('sending position update to {0}'.format(self.email))
                _, src, track, pos = m.split('|', 3)
#                logger.debug(session['spotify_token'])
                self.emit('player_position', src, track, int(pos))
            elif m.startswith('v|'):
                _, msg = m.split('|', 1)
                self.emit('volume', msg)
            elif m.startswith('do_airhorn'):
                _, v, c = m.split('|', 2)
                self.logger.info('about to emit')
                self.emit('do_airhorn', v, c)
            elif m.startswith('no_airhorn'):
                _, msg = m.split('|', 1)
                self.emit('no_airhorn', json.loads(msg))
            elif m == 'update_freehorn':
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
        token = auth.get_access_token()
        self.emit('search_token_update', dict(token=auth.token_info['access_token'],
                                            time_left=int(auth.token_info['expires_at'] - time.time())))

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
        r = redis.StrictRedis().pubsub()
        r.subscribe('MISC|update-pubsub')
        for m in r.listen():
            if m['type'] != 'message':
                continue
            if m['data'].startswith('v|'):
                _, msg = m['data'].split('|', 1)
                self.emit('volume', msg)


@app.context_processor
def inject_config():
    return dict(CONF=CONF)

SAFE_PATHS = (u'/login/', u'/logout/', u'/playing/', u'/queue/', u'/volume/',
              u'/guest', u'/guest/', u'/api/jammit/',
              u'/authentication/callback', u'/token', u'/last/', u'/airhorns/', u'/z/')
SAFE_PARAM_PATHS = (u'/history', u'/user_history', u'/user_jam_history', u'/search/v2', u'/add_song',
    u'/blast_airhorn', u'/airhorn_list', u'/queue/', u'/jam')
VALID_HOSTS = (u'localhost:5000', unicode(CONF.HOSTNAME))


@app.before_request
def require_auth():
    if request.host not in VALID_HOSTS:
        return redirect('http://%s' % CONF.HOSTNAME)
    if request.path in SAFE_PATHS:
        return
    for param_path in SAFE_PARAM_PATHS:
        if request.path.startswith(param_path):
            return
    if request.path.startswith('/static/'):
        return
    if 'email' not in session:
        default_email = 'test@spotify.com';
        default_names = ['testy', 'mctesterface'];

        session['email'] = request.headers.get('sso-mail', request.args.get('useremail', default_email))
        session['fullname'] = request.headers.get('sso-givenname', default_names[0]) + ' ' + request.headers.get('sso-surname', default_names[1])
        return


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
    REDIRECT_URI = "http://localhost:5000/authentication/callback"
    SPOTIFY_REDIRECT_URI = "http://localhost:5000/authentication/spotify_callback"
else:
    REDIRECT_URI = "http://%s/authentication/callback" % CONF.HOSTNAME
    SPOTIFY_REDIRECT_URI = "http://%s/authentication/spotify_callback" % CONF.HOSTNAME

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
        urllib.urlencode(args))
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
    token = r['access_token']
    user = requests.get('https://www.googleapis.com/oauth2/v1/userinfo',
                        params=dict(access_token=token), verify=False).json()
    if not user['email'].endswith('@spotify.com'):
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
    MusicNamespace(session['email'], 0).serve()
    return ''


@app.route('/volume/')
def volume():
    print 'VOLUME IN'
    VolumeNamespace().serve()
    return ''


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
    print request.values
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
    sp = spotipy.Spotify(auth=auth.get_access_token())
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
