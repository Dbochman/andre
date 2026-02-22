"""Fire-and-forget Slack webhook notifications for EchoNest.

Posts deploy alerts, now-playing updates, and airhorn events to a Slack channel.
If SLACK_WEBHOOK_URL is not configured, all functions are silent no-ops.
"""

import json
import logging
import threading

import requests

from config import CONF

logger = logging.getLogger(__name__)


def _get_url():
    return getattr(CONF, 'SLACK_WEBHOOK_URL', None) or None


def post(text, blocks=None):
    """Fire-and-forget post to Slack. Never raises."""
    url = _get_url()
    if not url:
        return

    payload = {'text': text}
    if blocks:
        payload['blocks'] = blocks

    def _send():
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception:
            logger.debug("slack.post failed", exc_info=True)

    threading.Thread(target=_send, daemon=True).start()


def notify_deploy():
    """Post deploy notification with resync reminder.

    Rate-limited to once per 5 minutes via Redis to prevent Slack spam
    during crash loops.
    """
    try:
        import redis
        r = redis.StrictRedis(
            host=getattr(CONF, 'REDIS_HOST', None) or 'localhost',
            port=getattr(CONF, 'REDIS_PORT', None) or 6379,
            password=getattr(CONF, 'REDIS_PASSWORD', None) or None,
            decode_responses=True,
        )
        # SET NX with 5-min TTL — only succeeds if key doesn't exist
        if not r.set('SLACK|deploy_cooldown', '1', nx=True, ex=300):
            logger.debug("notify_deploy suppressed (cooldown active)")
            return
    except Exception:
        # Redis unavailable — send anyway (better one extra than none)
        pass
    post("\U0001f504 EchoNest is restarting \u2014 you may need to resync audio.")


def _parse_data(song):
    """Parse the raw API response from the song's data field."""
    data = song.get('data', '')
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return {}
    return data if isinstance(data, dict) else {}


def _track_url(song):
    """Build a track URL based on the song source."""
    src = song.get('src', '')
    trackid = song.get('trackid', '')
    if src == 'spotify' and trackid:
        return f"https://open.spotify.com/track/{trackid.split(':')[-1]}"
    if src == 'soundcloud':
        permalink = song.get('permalink_url', '')
        if permalink:
            return permalink
        if trackid:
            return f"https://soundcloud.com/tracks/{trackid}"
    if src == 'youtube' and trackid:
        return f"https://www.youtube.com/watch?v={trackid}"
    return ''


def _artist_url(song):
    """Extract the artist's profile URL based on the song source."""
    src = song.get('src', '')
    data = _parse_data(song)
    if src == 'spotify':
        artists = data.get('artists', [])
        if artists:
            return artists[0].get('external_urls', {}).get('spotify', '')
    elif src == 'soundcloud':
        user = data.get('user', {})
        if isinstance(user, dict):
            return user.get('permalink_url', '')
    elif src == 'youtube':
        snippet = data.get('snippet', {})
        if isinstance(snippet, dict):
            channel_id = snippet.get('channelId', '')
            if channel_id:
                return f"https://www.youtube.com/channel/{channel_id}"
    return ''


def notify_now_playing(song):
    """Post now-playing update with album art, title, artist, who added it."""
    if not song or not _get_url():
        return

    title = song.get('title', 'Unknown')
    artist = song.get('artist', 'Unknown')
    user = song.get('user', '')
    img = song.get('img', '')

    track_link = _track_url(song)
    artist_link = _artist_url(song)

    title_display = f"<{track_link}|{title}>" if track_link else f"*{title}*"
    artist_display = f"<{artist_link}|{artist}>" if artist_link else f"*{artist}*"

    big_img = song.get('big_img', '') or img

    text = f"\U0001f3b5 Now Playing: {title} by {artist}\nAdded by {user}"

    block = {
        'type': 'section',
        'text': {
            'type': 'mrkdwn',
            'text': f"\U0001f3b5 Now Playing: *{title_display}* by *{artist_display}*\nAdded by {user}",
        },
    }

    if big_img:
        block['accessory'] = {
            'type': 'image',
            'image_url': big_img,
            'alt_text': f"{title} album art",
        }

    post(text, blocks=[block])


def notify_airhorn(user, airhorn_name, song_title, song_artist):
    """Post airhorn event."""
    if not _get_url():
        return

    text = (
        f"\U0001f4ef {user} blasted the *{airhorn_name}* airhorn!\n"
        f"\U0001f3b5 During: {song_title} \u2014 {song_artist}"
    )
    post(text)


def notify_pause(user):
    """Post when playback is paused."""
    post(f"\u23f8\ufe0f {user} paused playback.")


def notify_skip(user, song_title, song_artist):
    """Post when a song is skipped."""
    post(f"\u23ed\ufe0f {user} skipped *{song_title}* by *{song_artist}*")


def notify_unpause(user):
    """Post when playback is unpaused."""
    post(f"\u25b6\ufe0f {user} unpaused playback.")


def notify_nest_created(nest):
    """Post when a new nest is created."""
    if not nest or not _get_url():
        return

    name = nest.get('name', nest.get('code', '???'))
    creator = nest.get('creator', '')
    code = nest.get('code', '')

    text = f"\U0001fab9 New nest created: *{name}* (code: `{code}`) by {creator}"
    post(text)
