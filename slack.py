"""Fire-and-forget Slack webhook notifications for EchoNest.

Posts deploy alerts, now-playing updates, and airhorn events to a Slack channel.
If SLACK_WEBHOOK_URL is not configured, all functions are silent no-ops.
"""

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
    """Post deploy notification with resync reminder."""
    post("\U0001f504 EchoNest is restarting \u2014 you may need to resync audio.")


def notify_now_playing(song):
    """Post now-playing update with album art, title, artist, who added it."""
    if not song or not _get_url():
        return

    title = song.get('title', 'Unknown')
    artist = song.get('artist', 'Unknown')
    user = song.get('user', '')
    img = song.get('img', '')

    text = f"\U0001f3b5 Now Playing: *{title}* by *{artist}*\nAdded by {user}"

    blocks = [
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': f"\U0001f3b5 Now Playing: *{title}* by *{artist}*\nAdded by {user}",
            },
        },
    ]

    if img:
        blocks[0]['accessory'] = {
            'type': 'image',
            'image_url': img,
            'alt_text': f"{title} album art",
        }

    post(text, blocks=blocks)


def notify_airhorn(user, airhorn_name, song_title, song_artist):
    """Post airhorn event."""
    if not _get_url():
        return

    text = (
        f"\U0001f4ef {user} blasted the *{airhorn_name}* airhorn!\n"
        f"\U0001f3b5 During: {song_title} \u2014 {song_artist}"
    )
    post(text)


def notify_nest_created(nest):
    """Post when a new nest is created."""
    if not nest or not _get_url():
        return

    name = nest.get('name', nest.get('code', '???'))
    creator = nest.get('creator', '')
    code = nest.get('code', '')

    text = f"\U0001fab9 New nest created: *{name}* (code: `{code}`) by {creator}"
    post(text)
