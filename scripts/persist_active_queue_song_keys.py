#!/usr/bin/env python3
from gevent import monkey
monkey.patch_all()

import sys

from db import DB
from nests import NestManager


def all_nest_ids(redis_client):
    nest_ids = {"main"}
    try:
        manager = NestManager(redis_client=redis_client)
        nest_ids.update(nid for nid, _meta in manager.list_nests())
    except Exception:
        pass
    return sorted(nest_ids)


def persist_active_song_keys():
    base_db = DB(init_history_to_redis=False)
    redis_client = base_db._r

    persisted = 0
    inspected = 0

    for nest_id in all_nest_ids(redis_client):
        db = DB(init_history_to_redis=False, nest_id=nest_id, redis_client=redis_client)
        song_ids = set(redis_client.zrange(db._key('MISC|priority-queue'), 0, -1))
        now_playing = redis_client.get(db._key('MISC|now-playing'))
        if now_playing:
            song_ids.add(now_playing)

        for song_id in song_ids:
            for key in db._song_state_keys(song_id):
                inspected += 1
                ttl = redis_client.ttl(key)
                if ttl > 0:
                    redis_client.persist(key)
                    persisted += 1

    print("Inspected %d keys, persisted %d keys" % (inspected, persisted))


if __name__ == "__main__":
    try:
        persist_active_song_keys()
    except KeyboardInterrupt:
        sys.exit(1)
