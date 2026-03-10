import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class EndLoop(Exception):
    pass


@pytest.fixture
def fake_redis():
    try:
        import fakeredis
    except ImportError:
        pytest.skip("fakeredis not installed")
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def db(fake_redis, monkeypatch):
    monkeypatch.setenv("SKIP_SPOTIFY_PREFETCH", "1")
    from db import DB

    return DB(init_history_to_redis=False, redis_client=fake_redis)


def test_clear_now_playing_state_removes_all_player_keys(db, fake_redis):
    fake_redis.set(db._key("MISC|now-playing"), "1")
    fake_redis.set(db._key("MISC|current-done"), "done")
    fake_redis.set(db._key("MISC|started-on"), "started")
    fake_redis.set(db._key("MISC|now-playing-done"), "legacy")

    db._clear_now_playing_state()

    assert fake_redis.exists(db._key("MISC|now-playing")) == 0
    assert fake_redis.exists(db._key("MISC|current-done")) == 0
    assert fake_redis.exists(db._key("MISC|started-on")) == 0
    assert fake_redis.exists(db._key("MISC|now-playing-done")) == 0


def test_get_now_playing_stale_reference_clears_player_state(db, fake_redis):
    fake_redis.set(db._key("MISC|now-playing"), "1")
    fake_redis.set(db._key("MISC|current-done"), "done")
    fake_redis.set(db._key("MISC|started-on"), "started")

    assert db.get_now_playing() == {"paused": False}
    assert fake_redis.exists(db._key("MISC|now-playing")) == 0
    assert fake_redis.exists(db._key("MISC|current-done")) == 0
    assert fake_redis.exists(db._key("MISC|started-on")) == 0


def test_queue_size_with_purge_filters_stale_members(db, fake_redis):
    fake_redis.zadd(db._key("MISC|priority-queue"), {"1": 10, "2": 20})
    fake_redis.hset(db._key("QUEUE|2"), mapping={"trackid": "spotify:track:2"})

    assert db.queue_size(purge_stale=True) == 1
    assert fake_redis.zrange(db._key("MISC|priority-queue"), 0, -1) == ["2"]


def test_master_player_short_track_uses_explicit_cleanup(db, monkeypatch):
    monkeypatch.setattr(db, "get_now_playing", lambda: {})

    songs = iter([{"id": "1", "trackid": "spotify:track:abc", "duration": 4, "src": "spotify"}])

    def fake_pop_next():
        try:
            return next(songs)
        except StopIteration:
            raise EndLoop

    calls = []
    monkeypatch.setattr(db, "pop_next", fake_pop_next)
    monkeypatch.setattr(db, "_complete_song", lambda song: calls.append(("complete", song["id"])))
    monkeypatch.setattr(db, "_clear_now_playing_state", lambda: calls.append(("clear", None)))

    with pytest.raises(EndLoop):
        db.master_player()

    assert calls == [("complete", "1"), ("clear", None)]


def test_master_player_stale_song_cleanup_runs_before_advancing(db, monkeypatch):
    monkeypatch.setattr(db, "get_now_playing", lambda: {"id": "1", "trackid": "spotify:track:abc", "src": "spotify"})

    calls = []
    monkeypatch.setattr(db, "_complete_song", lambda song: calls.append(("complete", song["id"])))
    monkeypatch.setattr(db, "_clear_now_playing_state", lambda: calls.append(("clear", None)))
    monkeypatch.setattr(db, "pop_next", lambda: (_ for _ in ()).throw(EndLoop()))

    with pytest.raises(EndLoop):
        db.master_player()

    assert calls == [("complete", "1"), ("clear", None)]


def test_master_player_bender_fill_failures_back_off(db, monkeypatch):
    from config import CONF
    import db as db_module

    monkeypatch.setattr(CONF, "USE_BENDER", True, raising=False)
    monkeypatch.setattr(CONF, "MAX_BENDER_MINUTES", 999, raising=False)
    monkeypatch.setattr(db, "get_now_playing", lambda: {})
    monkeypatch.setattr(db, "pop_next", lambda: {})
    monkeypatch.setattr(db, "bender_streak", lambda: 0)
    monkeypatch.setattr(db, "get_fill_song", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise EndLoop

    monkeypatch.setattr(db_module.time, "sleep", fake_sleep)

    with pytest.raises(EndLoop):
        db.master_player()

    assert sleeps == [2, 4, 6]


def test_nest_cleanup_loop_uses_effective_queue_size(monkeypatch):
    monkeypatch.setenv("SKIP_SPOTIFY_PREFETCH", "1")
    mp = importlib.import_module("master_player")

    calls = {"queue_size": [], "deleted": [], "queue_sizes": []}

    class FakeDB:
        def __init__(self, nest_id, init_history_to_redis=False, redis_client=None):
            self.nest_id = nest_id
            calls["queue_size"].append((nest_id, init_history_to_redis, redis_client))

        def queue_size(self, purge_stale=False):
            calls["queue_sizes"].append((self.nest_id, purge_stale))
            return 0

    class FakeManager:
        def __init__(self):
            self._r = object()

        def list_nests(self):
            return [
                ("nest1", {"is_main": False, "last_activity": "2026-03-10T00:00:00"}),
                ("main", {"is_main": True}),
            ]

        def delete_nest(self, nest_id):
            calls["deleted"].append(nest_id)

    monkeypatch.setattr(mp, "DB", FakeDB)
    monkeypatch.setattr(mp, "count_active_members", lambda redis_client, nest_id: 0)
    monkeypatch.setattr(mp, "should_delete_nest", lambda metadata, members, queue_size, now: queue_size == 0)
    monkeypatch.setattr(mp.time, "sleep", lambda seconds: (_ for _ in ()).throw(EndLoop()))

    with pytest.raises(EndLoop):
        mp.nest_cleanup_loop(nest_manager=FakeManager(), interval_seconds=60)

    assert calls["queue_sizes"] == [("nest1", True)]
    assert calls["deleted"] == ["nest1"]
