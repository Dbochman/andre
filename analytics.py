"""Lightweight Redis-native analytics for EchoNest.

Key pattern: ANALYTICS|{event_type}|{YYYY-MM-DD}
All daily keys get 90-day TTL for auto-cleanup.
"""

import datetime
import logging

logger = logging.getLogger(__name__)

_TTL_DAYS = 90
_TTL_SECONDS = _TTL_DAYS * 86400


def _today():
    return datetime.date.today().isoformat()


def track(r, event_type, email=None, metadata=None):
    """Record an event. Fire-and-forget — failures are logged, never raised."""
    try:
        date = _today()
        pipe = r.pipeline(transaction=False)

        # Increment per-user counter for this event (sorted set)
        if email:
            event_key = f"ANALYTICS|{event_type}|{date}"
            pipe.zincrby(event_key, 1, email)
            pipe.expire(event_key, _TTL_SECONDS)

            # Track daily active users
            dau_key = f"ANALYTICS|dau|{date}"
            pipe.sadd(dau_key, email)
            pipe.expire(dau_key, _TTL_SECONDS)

            # Track globally known users (no TTL)
            pipe.sadd("ANALYTICS|known_users", email)

        # Increment daily total for this event type
        totals_key = f"ANALYTICS|totals|{date}"
        pipe.hincrby(totals_key, event_type, 1)
        pipe.expire(totals_key, _TTL_SECONDS)

        pipe.execute()
    except Exception:
        logger.debug("analytics.track failed for %s", event_type, exc_info=True)


def get_daily_stats(r, date=None):
    """Return {event_type: count} for a given day."""
    date = date or _today()
    raw = r.hgetall(f"ANALYTICS|totals|{date}")
    return {k: int(v) for k, v in raw.items()}


def get_daily_active_users(r, date=None):
    """Return set of emails active on a given day."""
    date = date or _today()
    return r.smembers(f"ANALYTICS|dau|{date}")


def get_user_stats(r, days=30):
    """Return per-user activity summary over N days.

    Returns list of dicts sorted by total activity descending:
    [{'email': '...', 'song_add': 5, 'vote': 12, ...}, ...]
    """
    today = datetime.date.today()
    user_totals = {}

    event_types = ['login', 'signup', 'ws_connect', 'song_add', 'vote', 'jam', 'airhorn']

    for day_offset in range(days):
        date = (today - datetime.timedelta(days=day_offset)).isoformat()
        for event_type in event_types:
            key = f"ANALYTICS|{event_type}|{date}"
            members = r.zrangebyscore(key, '-inf', '+inf', withscores=True)
            for email, score in members:
                if email not in user_totals:
                    user_totals[email] = {'email': email}
                user_totals[email][event_type] = user_totals[email].get(event_type, 0) + int(score)

    result = list(user_totals.values())
    result.sort(key=lambda u: sum(v for k, v in u.items() if k != 'email'), reverse=True)
    return result


def get_top_users(r, event_type, days=7):
    """Leaderboard for a specific event type over N days.

    Returns list of (email, count) sorted by count descending.
    """
    today = datetime.date.today()
    combined = {}

    for day_offset in range(days):
        date = (today - datetime.timedelta(days=day_offset)).isoformat()
        key = f"ANALYTICS|{event_type}|{date}"
        members = r.zrangebyscore(key, '-inf', '+inf', withscores=True)
        for email, score in members:
            combined[email] = combined.get(email, 0) + int(score)

    return sorted(combined.items(), key=lambda x: x[1], reverse=True)


def get_dau_trend(r, days=7):
    """Return list of (date_str, dau_count) for the last N days, oldest first."""
    today = datetime.date.today()
    trend = []
    for day_offset in range(days - 1, -1, -1):
        date = (today - datetime.timedelta(days=day_offset)).isoformat()
        count = r.scard(f"ANALYTICS|dau|{date}")
        trend.append((date, count))
    return trend


def get_known_user_count(r):
    """Return total number of unique users ever seen."""
    return r.scard("ANALYTICS|known_users")


# Spotify API event types tracked by the system
_SPOTIFY_API_EVENTS = (
    'spotify_api_search', 'spotify_api_track', 'spotify_api_artist',
    'spotify_api_artist_album_tracks', 'spotify_api_album_tracks',
    'spotify_api_get_track', 'spotify_api_get_episode',
    'spotify_api_devices', 'spotify_api_transfer', 'spotify_api_status',
    'spotify_api_rate_limited', 'spotify_api_error',
)

# Map event names to short display names (strip spotify_api_ prefix)
_SPOTIFY_API_SHORT = {e: e.replace('spotify_api_', '') for e in _SPOTIFY_API_EVENTS}


def get_spotify_api_stats(r, days=7):
    """Return Spotify API call stats: today's breakdown, total, and daily trend.

    Returns dict with keys: today (dict of short_name: count), total_today (int),
    trend (list of {date, calls}).
    """
    today = _today()
    today_raw = r.hgetall(f"ANALYTICS|totals|{today}")

    today_counts = {}
    for event, short in _SPOTIFY_API_SHORT.items():
        today_counts[short] = int(today_raw.get(event, 0))

    total_today = sum(today_counts.values())

    # Build daily trend
    current = datetime.date.today()
    trend = []
    for day_offset in range(days - 1, -1, -1):
        date = (current - datetime.timedelta(days=day_offset)).isoformat()
        day_raw = r.hgetall(f"ANALYTICS|totals|{date}")
        day_total = sum(int(day_raw.get(e, 0)) for e in _SPOTIFY_API_EVENTS)
        trend.append({'date': date, 'calls': day_total})

    return {
        'today': today_counts,
        'total_today': total_today,
        'trend': trend,
    }


# Spotify OAuth event types
_SPOTIFY_OAUTH_EVENTS = (
    'spotify_oauth_reconnect',  # User clicked reconnect button
    'spotify_oauth_refresh',    # OAuth callback completed (new token saved)
    'spotify_oauth_stale',      # Cached token missing or expired
)

_SPOTIFY_OAUTH_SHORT = {e: e.replace('spotify_oauth_', '') for e in _SPOTIFY_OAUTH_EVENTS}


def get_spotify_oauth_stats(r, days=7):
    """Return Spotify OAuth/auth stats: today's breakdown and daily trend.

    Helps diagnose user auth issues (stale tokens, reconnect frequency).
    """
    today = _today()
    today_raw = r.hgetall(f"ANALYTICS|totals|{today}")

    today_counts = {}
    for event, short in _SPOTIFY_OAUTH_SHORT.items():
        today_counts[short] = int(today_raw.get(event, 0))

    # Per-user breakdown of stale tokens (who's having problems?)
    stale_users = []
    current = datetime.date.today()
    for day_offset in range(days):
        date = (current - datetime.timedelta(days=day_offset)).isoformat()
        key = f"ANALYTICS|spotify_oauth_stale|{date}"
        members = r.zrangebyscore(key, '-inf', '+inf', withscores=True)
        for email, score in members:
            stale_users.append({'email': email, 'count': int(score), 'date': date})

    # Daily trend
    trend = []
    for day_offset in range(days - 1, -1, -1):
        date = (current - datetime.timedelta(days=day_offset)).isoformat()
        day_raw = r.hgetall(f"ANALYTICS|totals|{date}")
        day_counts = {short: int(day_raw.get(event, 0))
                      for event, short in _SPOTIFY_OAUTH_SHORT.items()}
        trend.append({'date': date, **day_counts})

    return {
        'today': today_counts,
        'stale_users': stale_users,
        'trend': trend,
    }
