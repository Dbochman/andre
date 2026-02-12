"""Nests helpers and manager.

This module provides helper functions for nest key generation, membership
tracking, and cleanup logic, plus the NestManager class for CRUD operations.
"""
import datetime
import json
import logging
import os
import random

import redis

from config import CONF

logger = logging.getLogger(__name__)

# Character set for nest codes: unambiguous uppercase + digits (no 0/O/1/I/L)
CODE_CHARS = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'

# Friendly auto-generated nest names (sonic/audio themed)
NEST_NAMES = (
    'WaveyNest', 'BassNest', 'VibesNest', 'FunkNest', 'GrooveNest',
    'TrebleNest', 'ReverbNest', 'TempoNest', 'RiffNest', 'SynthNest',
    'LoopNest', 'BeatNest', 'ChordNest', 'FaderNest', 'SubNest',
    'DropNest', 'PulseNest', 'ToneNest', 'MixNest', 'TrackNest',
    'SampleNest', 'BreakNest', 'HookNest', 'BridgeNest', 'VerseNest',
    'ChorusNest', 'MelodyNest', 'RhythmNest', 'HarmonyNest', 'CadenceNest',
    'OctaveNest', 'PitchNest', 'GainNest', 'ClipNest', 'FlangerNest',
    'PhaserNest', 'DistortNest', 'WahNest', 'CrunchNest', 'FuzzNest',
    'BoostNest', 'SlapNest', 'SnapNest', 'PopNest', 'ClickNest',
    'BoomNest', 'HissNest', 'BuzzNest', 'TwangNest', 'StompNest',
)

# Default seed for main nest and custom-named nests (Billy Joel - Piano Man)
_DEFAULT_SEED = ('spotify:track:3utq2FgD1pkmIoaWfjXWAU', None)

# Maps each nest name to (spotify_track_uri, genre_keyword) for themed Bender seeding.
# Genre keywords are from Spotify's recognized genre taxonomy.
NEST_SEED_MAP = {
    'WaveyNest':    ('spotify:track:5GUYJTQap5F3RDQiCOJhrS', 'new wave'),        # Duran Duran - Hungry Like the Wolf
    'BassNest':     ('spotify:track:3MODES4TNtygekLl146Dxd', 'bass music'),       # Bassnectar - Bass Head
    'VibesNest':    ('spotify:track:5le4sn0iMcnKU56bdmNzso', 'chill'),            # Roy Ayers Ubiquity - Everybody Loves The Sunshine
    'FunkNest':     ('spotify:track:4XRkQloZFcRrCONN7ZQ49Y', 'funk'),             # Parliament - Give Up The Funk
    'GrooveNest':   ('spotify:track:1TfqLAPs4K3s2rJMoCokcS', 'groove'),           # Earth Wind & Fire - September
    'TrebleNest':   ('spotify:track:1vrd6UOGamcKNGnSHJQlSt', 'classical'),        # Vivaldi - Four Seasons Spring
    'ReverbNest':   ('spotify:track:2pQ4A6w5HSurB5WiaLFhcF', 'shoegaze'),         # My Bloody Valentine - Only Shallow
    'TempoNest':    ('spotify:track:3yfqSUWxFvZELEM4PmlwIR', 'drum and bass'),    # Pendulum - Slam
    'RiffNest':     ('spotify:track:57bgtoPSgt236HzfBOd8kj', 'hard rock'),        # AC/DC - Thunderstruck
    'SynthNest':    ('spotify:track:3MrRksHupTVEQ7YbA0FsZK', 'synthpop'),         # Depeche Mode - Enjoy the Silence
    'LoopNest':     ('spotify:track:6nek1Nin9q48AVZcWs9e9D', 'trip hop'),         # Massive Attack - Teardrop
    'BeatNest':     ('spotify:track:7GhIk7Il098yCjg4BQjzvb', 'hip hop'),          # J Dilla - Workinonit
    'ChordNest':    ('spotify:track:4gphxUgq0JSFv2BCLhNDiE', 'jazz'),             # Bill Evans - Waltz for Debby
    'FaderNest':    ('spotify:track:2PpruBYCo4H7WOBJ7Q2EwM', 'deep house'),       # Larry Heard - Can You Feel It
    'SubNest':      ('spotify:track:4rwpZEcnalkuhPyGkEdhu0', 'dubstep'),          # Skrillex - Scary Monsters and Nice Sprites
    'DropNest':     ('spotify:track:5HQVUIKwCEXpe7JIHyY734', 'edm'),              # Skrillex - Bangarang
    'PulseNest':    ('spotify:track:7xQYVjs4wZNdCwO0EeAWMC', 'techno'),           # Underworld - Born Slippy (Nuxx)
    'ToneNest':     ('spotify:track:4u7EnebtmKWzUH433cf5Qv', 'soul'),             # Marvin Gaye - What's Going On
    'MixNest':      ('spotify:track:4uLU6hMCjMI75M1A2tKUQC', 'dance'),            # Daft Punk - One More Time
    'TrackNest':    ('spotify:track:0pqnGHJpmpxLKifKRmU6WP', 'electronic'),       # Aphex Twin - Windowlicker
    'SampleNest':   ('spotify:track:5Z01UMMf7V1o0MzF86s6WJ', 'boom bap'),         # DJ Shadow - Building Steam
    'BreakNest':    ('spotify:track:40riOy7x9W7GXjyGp4pjAv', 'breakbeat'),        # The Prodigy - Firestarter
    'HookNest':     ('spotify:track:7lPN2DXiMsVn7XUKtOW1CS', 'pop'),              # Michael Jackson - Billie Jean
    'BridgeNest':   ('spotify:track:6dGnYIeXmHdcikdzNNDMm2', 'progressive rock'), # Pink Floyd - Another Brick
    'VerseNest':    ('spotify:track:3n3Ppam7vgaVa1iaRUc9Lp', 'singer-songwriter'),# Elliott Smith - Between the Bars
    'ChorusNest':   ('spotify:track:3qiyyUfYe7CRYLucrPmulD', 'anthem'),           # Queen - Bohemian Rhapsody
    'MelodyNest':   ('spotify:track:3BQHpFgAp4l80e1XslIjNI', 'indie pop'),        # The Smiths - There Is a Light
    'RhythmNest':   ('spotify:track:2r0KlAVemiB1TyTqgCh5ve', 'afrobeat'),         # Fela Kuti - Zombie
    'HarmonyNest':  ('spotify:track:5jgFfDIR6FR0gvlA56Nakr', 'a cappella'),       # Pentatonix - Daft Punk Medley
    'CadenceNest':  ('spotify:track:2tUBqZG2AbRi7Q0BIrVrEj', 'neo soul'),         # Erykah Badu - On & On
    'OctaveNest':   ('spotify:track:1B75hgRqe7A4fwee3g3Wmu', 'opera'),            # Pavarotti - Nessun Dorma
    'PitchNest':    ('spotify:track:17QTsL4K9B9v4rI8CAIdfC', 'barbershop'),       # The Beach Boys - God Only Knows
    'GainNest':     ('spotify:track:7iN1s7xHE4ifF5povM6A48', 'metal'),            # Metallica - Enter Sandman
    'ClipNest':     ('spotify:track:7dt6x5M1jzdTEt8oCbisTK', 'lo-fi'),            # Mac DeMarco - Chamber of Reflection
    'FlangerNest':  ('spotify:track:37Tmv4NnfQeb0ZgUC4fOJj', 'psychedelic rock'), # Tame Impala - The Less I Know
    'PhaserNest':   ('spotify:track:6habFhsOp2NvshLv26DqMb', 'space rock'),       # Muse - Knights of Cydonia
    'DistortNest':  ('spotify:track:5ghIJDpPoe3CfHMGu71E6T', 'grunge'),           # Nirvana - Smells Like Teen Spirit
    'WahNest':      ('spotify:track:0wJoRiX5K5BxlqZTolB2LD', 'blues rock'),       # Jimi Hendrix - Voodoo Child
    'CrunchNest':   ('spotify:track:124Y9LPRCAz3q2OP0iCvcJ', 'punk rock'),        # The Clash - London Calling
    'FuzzNest':     ('spotify:track:5CQ30WqJwcep0pYcV4AMNc', 'stoner rock'),      # Black Sabbath - Paranoid
    'BoostNest':    ('spotify:track:0VjIjW4GlUZAMYd2vXMi3b', 'power pop'),        # Weezer - Buddy Holly
    'SlapNest':     ('spotify:track:3ZOEytgrvLwQaqXreDs2Jx', 'slap house'),       # Red Hot Chili Peppers - Can't Stop
    'SnapNest':     ('spotify:track:0VgkVdmE4gld66l8iyGjgx', 'trap'),             # Future - Mask Off
    'PopNest':      ('spotify:track:2Fxmhks0bxGSBdJ92vM42m', 'pop'),              # Britney Spears - Toxic
    'ClickNest':    ('spotify:track:553HOkDZQktOEBKvxTBPS1', 'minimal techno'),   # Plastikman (Richie Hawtin) - Spastik
    'BoomNest':     ('spotify:track:5YoITs1m0q8UOQ4AW7N5ga', 'reggaeton'),         # Daddy Yankee - Gasolina
    'HissNest':     ('spotify:track:4LRPiXqCikLlN15c3yImP7', 'ambient'),          # Brian Eno - Music for Airports
    'BuzzNest':     ('spotify:track:2EoOZnxNgtmZaD8uUmz2nD', 'industrial'),       # Nine Inch Nails - Head Like a Hole
    'TwangNest':    ('spotify:track:5rDkA2TFOImbiVenmnE9r4', 'country'),          # Johnny Cash - Ring of Fire
    'StompNest':    ('spotify:track:3dPQuX8Gs42Y7b454ybpMR', 'garage rock'),      # The White Stripes - Seven Nation Army
}


def get_nest_seed_info(nest_name):
    """Look up themed seed track and genre keyword for a nest name.

    Strips numeric suffixes for overflow names (e.g. "BassNest2" → "BassNest").
    Returns (spotify_track_uri, genre_keyword) tuple, or _DEFAULT_SEED for unknown names.
    """
    if nest_name in NEST_SEED_MAP:
        return NEST_SEED_MAP[nest_name]

    # Strip trailing digits for overflow names like "BassNest2"
    import re
    base_name = re.sub(r'\d+$', '', nest_name)
    if base_name in NEST_SEED_MAP:
        return NEST_SEED_MAP[base_name]

    return _DEFAULT_SEED


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def _nest_prefix(nest_id):
    """Return the Redis key prefix for a given nest."""
    return f"NEST:{nest_id}|"


# Legacy key mapping: maps old bare keys to their NEST:main| equivalents
# Used by migrate_keys.py and tests
legacy_key_mapping = {
    "MISC|now-playing": "NEST:main|MISC|now-playing",
    "MISC|priority-queue": "NEST:main|MISC|priority-queue",
    "MISC|current-done": "NEST:main|MISC|current-done",
    "MISC|started-on": "NEST:main|MISC|started-on",
    "MISC|paused": "NEST:main|MISC|paused",
    "MISC|force-jump": "NEST:main|MISC|force-jump",
    "MISC|master-player": "NEST:main|MISC|master-player",
    "MISC|player-now": "NEST:main|MISC|player-now",
    "MISC|playlist-plays": "NEST:main|MISC|playlist-plays",
    "MISC|last-queued": "NEST:main|MISC|last-queued",
    "MISC|last-bender-track": "NEST:main|MISC|last-bender-track",
    "MISC|bender_streak_start": "NEST:main|MISC|bender_streak_start",
    "MISC|now-playing-done": "NEST:main|MISC|now-playing-done",
    "MISC|last-played": "NEST:main|MISC|last-played",
    "MISC|volume": "NEST:main|MISC|volume",
    "MISC|update-pubsub": "NEST:main|MISC|update-pubsub",
    "MISC|backup-queue": "NEST:main|MISC|backup-queue",
    "MISC|backup-queue-data": "NEST:main|MISC|backup-queue-data",
    "MISC|guest-login": "NEST:main|MISC|guest-login",
    "MISC|guest-login-expire": "NEST:main|MISC|guest-login-expire",
    "AIRHORNS": "NEST:main|AIRHORNS",
}


def pubsub_channel(nest_id):
    """Return the pub/sub channel name for a given nest."""
    return f"NEST:{nest_id}|MISC|update-pubsub"


def members_key(nest_id):
    """Return the Redis key for the set of members in a nest."""
    return f"NEST:{nest_id}|MEMBERS"


def member_key(nest_id, email):
    """Return the Redis key for an individual member's heartbeat TTL."""
    return f"NEST:{nest_id}|MEMBER:{email}"


def deleting_key(nest_id):
    """Return the Redis key for the nest deletion-in-progress flag."""
    return f"NEST:{nest_id}|DELETING"


def is_nest_deleting(redis_client, nest_id):
    """Check whether a nest is currently being deleted."""
    return redis_client.exists(deleting_key(nest_id)) == 1


def refresh_member_ttl(redis_client, nest_id, email, ttl_seconds=90):
    """Set/refresh a member's heartbeat TTL key.

    Args:
        redis_client: Redis connection (caller provides, e.g. db._r)
        nest_id: The nest identifier
        email: Member's email address
        ttl_seconds: TTL in seconds (default 90)
    """
    key = member_key(nest_id, email)
    redis_client.setex(key, ttl_seconds, "1")


def count_active_members(redis_client, nest_id):
    """Count active members by checking heartbeat TTL keys, pruning stale ones.

    Members in the MEMBERS set whose TTL key has expired are removed
    from the set. Returns the count of still-active members.

    Args:
        redis_client: Redis connection
        nest_id: The nest identifier

    Returns:
        int: Number of active members
    """
    mkey = members_key(nest_id)
    emails = redis_client.smembers(mkey)
    stale = []
    for email in emails:
        mk = member_key(nest_id, email)
        # Use ttl() instead of exists(): a key with TTL <= 0 or missing is stale
        if redis_client.ttl(mk) <= 0:
            stale.append(email)
    for email in stale:
        redis_client.srem(mkey, email)
    return len(emails) - len(stale)


def should_delete_nest(metadata, members, queue_size, now):
    """Determine whether a nest should be cleaned up.

    Args:
        metadata: dict with keys 'is_main', 'last_activity' (ISO string),
                  'ttl_minutes' (int)
        members: int count of active members
        queue_size: int count of songs in queue
        now: datetime.datetime representing current time

    Returns:
        True if the nest should be deleted, False otherwise.
    """
    # Never delete the main nest
    if metadata.get("is_main"):
        return False

    # Don't delete if there are active members
    if members > 0:
        return False

    # Don't delete if there are songs in the queue
    if queue_size > 0:
        return False

    # Check inactivity timeout
    last_activity_str = metadata.get("last_activity")
    ttl_minutes = metadata.get("ttl_minutes", getattr(CONF, 'NEST_MAX_INACTIVE_MINUTES', 5))

    if last_activity_str:
        last_activity = datetime.datetime.fromisoformat(last_activity_str)
        elapsed = (now - last_activity).total_seconds() / 60.0
        if elapsed >= ttl_minutes:
            return True

    return False


# ---------------------------------------------------------------------------
# NestManager class
# ---------------------------------------------------------------------------

# Global registry key (NOT nest-scoped)
_REGISTRY_KEY = 'NESTS|registry'


def _code_key(code):
    """Return the Redis key for a nest code lookup (global, NOT nest-scoped)."""
    return f'NESTS|code:{code}'


def _slug_key(slug):
    """Return the Redis key for a nest slug lookup (global, NOT nest-scoped)."""
    return f'NESTS|slug:{slug}'


def slugify(name):
    """Convert a nest name to a URL-safe slug.

    Lowercases, replaces spaces/special chars with hyphens, strips leading/trailing hyphens.
    """
    import re
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug


class NestManager:
    """Manages nest lifecycle: create, read, update, delete.

    Uses Redis hash at NESTS|registry for nest metadata and
    NESTS|code:{code} for code-to-nest_id lookup.
    """

    def __init__(self, redis_client=None):
        if redis_client is not None:
            self._r = redis_client
        else:
            redis_host = os.environ.get('REDIS_HOST', 'localhost')
            redis_port = int(os.environ.get('REDIS_PORT', 6379))
            redis_password = os.environ.get('REDIS_PASSWORD') or None
            self._r = redis.StrictRedis(
                host=redis_host, port=redis_port,
                password=redis_password, decode_responses=True
            )
        # Ensure main nest exists in registry
        self._ensure_main_nest()

    def _ensure_main_nest(self):
        """Initialize the main nest in the registry if not present."""
        existing = self._r.hget(_REGISTRY_KEY, 'main')
        if not existing:
            metadata = {
                'nest_id': 'main',
                'code': 'main',
                'name': 'Home Nest',
                'creator': 'system',
                'is_main': True,
                'created_at': datetime.datetime.now().isoformat(),
                'last_activity': datetime.datetime.now().isoformat(),
                'ttl_minutes': 0,  # Never expires
            }
            self._r.hset(_REGISTRY_KEY, 'main', json.dumps(metadata))

    def generate_code(self, length=5):
        """Generate a unique 5-character nest code.

        Uses CODE_CHARS (unambiguous chars) and checks for collisions.
        """
        for _ in range(100):  # Max attempts to avoid infinite loop
            code = ''.join(random.choice(CODE_CHARS) for _ in range(length))
            # Check if code is already in use
            if not self._r.exists(_code_key(code)):
                return code
        raise RuntimeError("Could not generate unique nest code after 100 attempts")

    def _pick_random_name(self):
        """Pick a random unused nest name from NEST_NAMES.

        If all names are taken, appends a numeric suffix to a random pick.
        """
        all_data = self._r.hgetall(_REGISTRY_KEY)
        used_names = set()
        for raw_meta in all_data.values():
            try:
                meta = json.loads(raw_meta)
                used_names.add(meta.get('name'))
            except (json.JSONDecodeError, TypeError):
                continue

        available = [n for n in NEST_NAMES if n not in used_names]
        if available:
            return random.choice(available)

        # All names taken — pick a random base and append a number
        base = random.choice(NEST_NAMES)
        suffix = 2
        while f'{base}{suffix}' in used_names:
            suffix += 1
        return f'{base}{suffix}'

    def _resolve_track_seed(self, seed_track):
        """Resolve a Spotify track URI to (seed_uri, genre_hint).

        Fetches track and artist metadata from Spotify to extract the
        primary genre. Returns (seed_track, genre) or (seed_track, None)
        if no genres found or on API error.
        """
        from db import spotify_client
        try:
            track_id = seed_track.split(':')[-1]
            track_data = spotify_client.track(track_id)
            artists = track_data.get('artists', [])
            if not artists:
                return (seed_track, None)
            artist_id = artists[0]['id']
            artist_data = spotify_client.artist(artist_id)
            genres = artist_data.get('genres', [])
            return (seed_track, genres[0]) if genres else (seed_track, None)
        except Exception:
            logger.warning("Failed to resolve seed track %s, storing URI only", seed_track)
            return (seed_track, None)

    def create_nest(self, creator_email, name=None, seed_track=None):
        """Create a new nest.

        Args:
            creator_email: Email of the creator
            name: Optional name for the nest
            seed_track: Optional Spotify track URI (spotify:track:xxx) to
                seed Bender recommendations for this nest

        Returns:
            dict with nest metadata including 'code'

        Raises:
            ValueError: If seed_track is provided but not a valid spotify:track: URI
        """
        if seed_track is not None:
            if not seed_track.startswith('spotify:track:'):
                raise ValueError("seed_track must be a spotify:track: URI")

        code = self.generate_code()
        nest_id = code  # Use code as nest_id for simplicity

        now = datetime.datetime.now().isoformat()
        metadata = {
            'nest_id': nest_id,
            'code': code,
            'name': name or self._pick_random_name(),
            'creator': creator_email,
            'is_main': False,
            'created_at': now,
            'last_activity': now,
            'ttl_minutes': getattr(CONF, 'NEST_MAX_INACTIVE_MINUTES', 5),
        }

        if seed_track is not None:
            seed_uri, genre_hint = self._resolve_track_seed(seed_track)
            metadata['seed_uri'] = seed_uri
            if genre_hint is not None:
                metadata['genre_hint'] = genre_hint

        # Generate slug from name (for custom names, gives a URL path)
        slug = slugify(metadata['name'])
        if slug:
            metadata['slug'] = slug

        # Store in registry hash (nest_id -> JSON metadata)
        self._r.hset(_REGISTRY_KEY, nest_id, json.dumps(metadata))
        # Store code lookup (code -> nest_id)
        self._r.set(_code_key(code), nest_id)
        # Store slug lookup (slug -> nest_id) if we have one
        if slug:
            self._r.set(_slug_key(slug), nest_id)

        return metadata

    def get_nest(self, nest_id):
        """Get nest metadata by nest_id, code, or slug.

        Returns dict or None if not found.
        """
        raw = self._r.hget(_REGISTRY_KEY, nest_id)
        if raw:
            return json.loads(raw)

        # Try looking up by code
        looked_up_id = self._r.get(_code_key(nest_id))
        if looked_up_id:
            raw = self._r.hget(_REGISTRY_KEY, looked_up_id)
            if raw:
                return json.loads(raw)

        # Try looking up by slug
        looked_up_id = self._r.get(_slug_key(nest_id))
        if looked_up_id:
            raw = self._r.hget(_REGISTRY_KEY, looked_up_id)
            if raw:
                return json.loads(raw)

        return None

    def list_nests(self):
        """List all registered nests.

        Returns list of (nest_id, metadata_dict) tuples.
        """
        all_data = self._r.hgetall(_REGISTRY_KEY)
        result = []
        for nest_id, raw_meta in all_data.items():
            try:
                meta = json.loads(raw_meta)
                # Add member count
                mkey = members_key(nest_id)
                meta['member_count'] = self._r.scard(mkey)
                result.append((nest_id, meta))
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid metadata for nest %s", nest_id)
                continue
        return result

    def delete_nest(self, nest_id):
        """Delete a nest and all its Redis keys.

        Sets a DELETING flag (30s TTL) to prevent writes during cleanup,
        then removes all nest keys using non-blocking unlink().

        Args:
            nest_id: The nest to delete
        """
        if nest_id == "main":
            logger.warning("Attempted to delete main nest — ignoring")
            return

        # Set DELETING flag with 30s TTL (auto-expires on crash)
        self._r.setex(deleting_key(nest_id), 30, "1")

        # Get metadata to find the code and slug
        raw = self._r.hget(_REGISTRY_KEY, nest_id)
        if raw:
            try:
                meta = json.loads(raw)
                code = meta.get('code', nest_id)
                self._r.delete(_code_key(code))
                slug = meta.get('slug')
                if slug:
                    self._r.delete(_slug_key(slug))
            except (json.JSONDecodeError, TypeError):
                pass

        # Remove from registry
        self._r.hdel(_REGISTRY_KEY, nest_id)

        # SCAN and unlink all NEST:{nest_id}|* keys (non-blocking)
        prefix = _nest_prefix(nest_id)
        cursor = 0
        while True:
            cursor, keys = self._r.scan(cursor, match=f"{prefix}*", count=200)
            if keys:
                self._r.unlink(*keys)
            if cursor == 0:
                break

        # Clean up the DELETING flag itself
        self._r.delete(deleting_key(nest_id))

    def touch_nest(self, nest_id):
        """Update the last_activity timestamp for a nest."""
        raw = self._r.hget(_REGISTRY_KEY, nest_id)
        if raw:
            try:
                meta = json.loads(raw)
                meta['last_activity'] = datetime.datetime.now().isoformat()
                self._r.hset(_REGISTRY_KEY, nest_id, json.dumps(meta))
            except (json.JSONDecodeError, TypeError):
                pass

    def join_nest(self, nest_id, email):
        """Add a member to a nest's MEMBERS set and broadcast update."""
        mkey = members_key(nest_id)
        self._r.sadd(mkey, email)
        self.touch_nest(nest_id)
        self._broadcast_member_update(nest_id)

    def leave_nest(self, nest_id, email):
        """Remove a member from a nest's MEMBERS set and delete TTL key."""
        mkey = members_key(nest_id)
        self._r.srem(mkey, email)
        # Also delete the member TTL key
        mk = member_key(nest_id, email)
        self._r.delete(mk)
        self._broadcast_member_update(nest_id)

    def _broadcast_member_update(self, nest_id):
        """Publish member_update event with current count on the nest's pubsub channel."""
        try:
            mkey = members_key(nest_id)
            count = self._r.scard(mkey)
            channel = pubsub_channel(nest_id)
            self._r.publish(channel, f"member_update|{count}")
        except Exception:
            logger.exception("Failed to broadcast member_update for nest %s", nest_id)


# ---------------------------------------------------------------------------
# Default NestManager instance (lazy-initialized)
# ---------------------------------------------------------------------------

_default_manager = None


def _get_default_manager():
    """Get or create the default NestManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = NestManager()
    return _default_manager


# ---------------------------------------------------------------------------
# Module-level join/leave wrappers
# ---------------------------------------------------------------------------

def join_nest(nest_id, email):
    """Add a member to a nest. Delegates to default NestManager."""
    return _get_default_manager().join_nest(nest_id, email)


def leave_nest(nest_id, email):
    """Remove a member from a nest. Delegates to default NestManager."""
    return _get_default_manager().leave_nest(nest_id, email)
