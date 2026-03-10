import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


def test_set_song_in_queue_has_no_ttl(db, fake_redis):
    db.set_song_in_queue("1", {"src": "spotify", "trackid": "spotify:track:abc", "duration": 180})

    assert fake_redis.ttl(db._key("QUEUE|1")) == -1


def test_add_song_vote_key_has_no_ttl(db, fake_redis, monkeypatch):
    monkeypatch.setattr(db, "_score_track", lambda userid, force_first, song: 0)

    song_id = db._add_song(
        "user@example.com",
        {
            "src": "spotify",
            "trackid": "spotify:track:abc",
            "duration": 180,
            "title": "Song",
            "artist": "Artist",
        },
        force_first=False,
    )

    assert fake_redis.ttl(db._key(f"QUEUE|{song_id}")) == -1
    assert fake_redis.ttl(db._key(f"QUEUE|VOTE|{song_id}")) == -1


def test_kill_song_deletes_associated_song_state(db, fake_redis):
    fake_redis.zadd(db._key("MISC|priority-queue"), {"1": 10})
    fake_redis.hset(db._key("QUEUE|1"), mapping={"trackid": "spotify:track:abc", "src": "spotify"})
    fake_redis.sadd(db._key("QUEUE|VOTE|1"), "user@example.com")
    fake_redis.zadd(db._key("QUEUEJAM|1"), {"jammer@example.com": 1})
    fake_redis.sadd(db._key("QUEUEJAM_TB|1"), "throwback@example.com")
    fake_redis.zadd(db._key("COMMENTS|1"), {"user@example.com||hi": 1})

    db.kill_song("1", "user@example.com")

    assert fake_redis.zrank(db._key("MISC|priority-queue"), "1") is None
    for key in db._song_state_keys("1"):
        assert fake_redis.exists(key) == 0


def test_nuke_queue_deletes_associated_song_state(db, fake_redis):
    fake_redis.zadd(db._key("MISC|priority-queue"), {"1": 10, "2": 20})
    for sid in ("1", "2"):
        fake_redis.hset(db._key(f"QUEUE|{sid}"), mapping={"trackid": f"spotify:track:{sid}", "src": "spotify"})
        fake_redis.sadd(db._key(f"QUEUE|VOTE|{sid}"), "user@example.com")
        fake_redis.zadd(db._key(f"QUEUEJAM|{sid}"), {"jammer@example.com": 1})
        fake_redis.sadd(db._key(f"QUEUEJAM_TB|{sid}"), "throwback@example.com")
        fake_redis.zadd(db._key(f"COMMENTS|{sid}"), {"user@example.com||hi": 1})

    db.nuke_queue("user@example.com")

    assert fake_redis.exists(db._key("MISC|priority-queue")) == 0
    for sid in ("1", "2"):
        for key in db._song_state_keys(sid):
            assert fake_redis.exists(key) == 0


def test_complete_song_logs_and_deletes_by_queue_song_id(db, fake_redis, monkeypatch):
    calls = []
    fake_redis.hset(db._key("QUEUE|1"), mapping={"trackid": "spotify:track:abc", "src": "spotify"})
    fake_redis.sadd(db._key("QUEUE|VOTE|1"), "user@example.com")
    fake_redis.hset(db._key("QUEUE|spotify:track:abc"), mapping={"trackid": "wrong-key"})

    monkeypatch.setattr(db, "log_finished_song", lambda song: calls.append(song["id"]))

    db._complete_song({"id": "1", "trackid": "spotify:track:abc", "src": "spotify"})

    assert calls == ["1"]
    assert fake_redis.exists(db._key("QUEUE|1")) == 0
    assert fake_redis.exists(db._key("QUEUE|VOTE|1")) == 0
    assert fake_redis.exists(db._key("QUEUE|spotify:track:abc")) == 1


def test_pop_next_does_not_add_ttl_to_song_hash(db, fake_redis):
    db.set_song_in_queue("1", {"id": "1", "src": "spotify", "trackid": "spotify:track:abc", "duration": 180})
    fake_redis.zadd(db._key("MISC|priority-queue"), {"1": 10})

    song = db.pop_next()

    assert song["id"] == "1"
    assert fake_redis.get(db._key("MISC|now-playing")) == "1"
    assert fake_redis.ttl(db._key("QUEUE|1")) == -1
