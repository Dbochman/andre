from datetime import datetime
import dateutil.parser
import logging
import os.path
import simplejson as json
from simplejson import JSONDecodeError

from config import CONF
from glob import glob

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
if CONF.DEBUG:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)

DAILY_MIX_USER = 'dailymix@spotify.com'

class PlayHistory(object):
    def __init__(self, db):
        self._db = db
        self._epoch = datetime(1970,1,1,0,0,0)

    def add_play(self, play, initial_init=False):
        '''
        allows plays either as dicts or json dumps thereof (e.g. as read from a file)

        '''
        if isinstance(play, str):
            json_play = play
            endtime = self.play_endtime(json.loads(play))
        else:
            json_play = json.dumps(play, sort_keys=True)
            endtime = self.play_endtime(play)

        if self._db._r.zscore('playhistory', json_play):
            return # play already in redis
        # New redis-py API: zadd(key, {member: score})
        self._db._r.zadd('playhistory', {json_play: endtime})
        if not initial_init:
            logger.debug("added play; store is now %d plays" % self.num_plays())

    def play_endtime(self, play):
        if isinstance(play, str):
            play = json.loads(play)
        endtime = dateutil.parser.parse(play['endtime'])
        return (endtime - self._epoch).total_seconds()

    def num_plays(self):
        return self._db._r.zcard('playhistory')

    def get_play(self, play_index):
        '''
        return the play stored in the history store with the integer ID
        play_index.  note, this index isn't the ID that the item has on
        the current prosecco queue

        '''
        play = self._db._r.zrange('playhistory', play_index, play_index)
        try:
            return json.loads(play[0])
        except Exception as _e:
            logger.debug('Exception deserializing play: %s' % play)
            logger.debug(_e)
            return {}

    def init_history(self):
        logger.info('Initialize play history store from %s' % CONF.LOG_DIR)
        if not os.path.isdir(CONF.LOG_DIR):
            logger.error('Play history dir %s does not exist.  Cannot initialize history.' % CONF.LOG_DIR)
            return

        play_log_files = glob(CONF.LOG_DIR + '/play_log_*.json')
        start = datetime.now()
        logger.info("History init starting at %s" % start)
        map(self._store_play_log_file, play_log_files)
        logger.info("History init took %s" % (datetime.now() - start))

    def _store_play_log_file(self, play_log_filename):
        with open(play_log_filename) as plf:
            for line in plf:
                try:
                    self.add_play(json.loads(line), True)
                except JSONDecodeError as _jde:
                    logger.warning('Skipping broken play from file %s -- line is: "%s"'
                                   % (play_log_filename, line))

    def _jams(self, play):
        return [jam['user'] if type(jam)==dict else jam for jam in play['jam']]

    def get_historian(self):
        return self._h

    def get_plays(self, n_plays, recent_plays=True):
        min = 0
        max = n_plays + 1

        if recent_plays:
            highest_play = self.num_plays()
            min = highest_play - n_plays
            max = highest_play

        plays = self._db._r.zrange('playhistory', min, max)
        response = []
        for play in plays:
            try:
                response.append(json.loads(play))
            except Exception as _e:
                logger.debug('Exception deserializing play: %s' % play)
                logger.debug(_e)

        return response

    def get_user_plays(self, userid):
        all_plays = self.get_plays(self.num_plays(), True)
        user_plays = []
        for play in all_plays:
            if DAILY_MIX_USER in self._jams(play):
                continue

            if play['user'] == userid:
                user_plays.append(play)
        return user_plays

    def get_user_jams(self, userid):
        all_plays = self.get_plays(self.num_plays(), True)
        user_jams = []
        for play in all_plays:
            if userid in self._jams(play):
                user_jams.append(play)
        return user_jams

    def get_throwback_plays(self, day_of_week=None, limit=50):
        """
        Get plays from the same day of the week from historical logs.

        Args:
            day_of_week: 0=Monday, 6=Sunday. If None, uses today.
            limit: Max number of tracks to return.

        Returns:
            List of track URIs from historical plays on matching days.
        """
        import os
        import random

        if day_of_week is None:
            day_of_week = datetime.now().weekday()

        # Find all log files for the matching day of week
        matching_files = []
        play_log_files = glob(CONF.LOG_DIR + '/play_log_*.json')

        for log_file in play_log_files:
            # Extract date from filename: play_log_YYYY_MM_DD.json
            basename = os.path.basename(log_file)
            try:
                parts = basename.replace('play_log_', '').replace('.json', '').split('_')
                if len(parts) == 3:
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                    file_date = datetime(year, month, day)
                    if file_date.weekday() == day_of_week:
                        matching_files.append(log_file)
            except (ValueError, IndexError):
                continue

        if not matching_files:
            logger.info("No throwback files found for day of week %d", day_of_week)
            return []

        logger.info("Found %d throwback files for day of week %d", len(matching_files), day_of_week)

        # Collect all plays from matching files
        all_plays = []
        for log_file in matching_files:
            try:
                with open(log_file, 'r') as f:
                    for line in f:
                        try:
                            play = json.loads(line.strip())
                            # Only include Spotify tracks with valid URIs
                            if play.get('src') == 'spotify' and play.get('trackid', '').startswith('spotify:track:'):
                                # Skip Benderbot plays for more variety
                                if play.get('user') != 'the@echonest.com':
                                    all_plays.append(play)
                        except JSONDecodeError:
                            continue
            except IOError:
                continue

        if not all_plays:
            logger.info("No valid throwback plays found")
            return []

        # Shuffle and deduplicate by track ID
        random.shuffle(all_plays)
        seen_tracks = set()
        unique_tracks = []
        for play in all_plays:
            track_id = play.get('trackid')
            if track_id and track_id not in seen_tracks:
                seen_tracks.add(track_id)
                unique_tracks.append(track_id)
                if len(unique_tracks) >= limit:
                    break

        logger.info("Returning %d throwback tracks", len(unique_tracks))
        return unique_tracks
