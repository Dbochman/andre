"""Nests helpers and manager (scaffold).

This module is intentionally minimal until implementation lands.
Tests import helpers from here; xfail tests will cover behavior.
"""

# Helper functions expected by tests (stubs)

legacy_key_mapping = {}


def pubsub_channel(nest_id):
    raise NotImplementedError


def members_key(nest_id):
    raise NotImplementedError


def member_key(nest_id, email):
    raise NotImplementedError


def refresh_member_ttl(nest_id, email, ttl_seconds=90):
    raise NotImplementedError


def should_delete_nest(metadata, members, queue_size, now):
    raise NotImplementedError


def join_nest(nest_id, email):
    raise NotImplementedError


def leave_nest(nest_id, email):
    raise NotImplementedError


class NestManager:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError

    def create_nest(self, creator_email, name=None):
        raise NotImplementedError

    def get_nest(self, nest_id):
        raise NotImplementedError

    def list_nests(self):
        raise NotImplementedError

    def delete_nest(self, nest_id):
        raise NotImplementedError

    def touch_nest(self, nest_id):
        raise NotImplementedError

    def join_nest(self, nest_id, email):
        raise NotImplementedError

    def leave_nest(self, nest_id, email):
        raise NotImplementedError

    def generate_code(self):
        raise NotImplementedError
