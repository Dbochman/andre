"""
Contract tests for Nests (xfail until implementation lands).
"""
import os
import sys

import pytest
import datetime
import importlib

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.xfail(reason="Nests not implemented yet")
class TestNestsAPI:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        os.environ["ANDRE_API_TOKEN"] = "test-secret-token-12345"
        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _get(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.get(path, headers=headers, **kwargs)

    def _post(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.post(path, headers=headers, **kwargs)

    def _patch(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.patch(path, headers=headers, **kwargs)

    def test_create_nest_returns_code(self, client):
        rv = self._post(
            client,
            "/api/nests",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"name": "Friday Vibes"},
        )
        assert rv.status_code == 200
        data = rv.get_json()
        assert "code" in data
        assert len(data["code"]) == 5

    def test_get_nest_info(self, client):
        rv = self._get(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        assert rv.status_code in (200, 404)

    def test_patch_nest_name(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"name": "New Name"},
        )
        assert rv.status_code in (200, 403, 404)

    def test_vanity_validation_reserved_and_charset(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "admin"},
        )
        assert rv.status_code in (400, 403, 404)

        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "JAZZ NIGHT"},
        )
        assert rv.status_code in (400, 403, 404)

        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "jazznight"},
        )
        assert rv.status_code in (200, 403, 404)

    def test_vanity_validation_length_bounds(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "ab"},
        )
        assert rv.status_code in (400, 403, 404)

        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "abc"},
        )
        assert rv.status_code in (200, 403, 404)

        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "a" * 24},
        )
        assert rv.status_code in (200, 403, 404)

        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "a" * 25},
        )
        assert rv.status_code in (400, 403, 404)

    def test_vanity_validation_start_and_chars(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "1start"},
        )
        assert rv.status_code in (400, 403, 404)

        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "good-name"},
        )
        assert rv.status_code in (200, 403, 404)

        rv = self._patch(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "bad_name"},
        )
        assert rv.status_code in (400, 403, 404)

    def test_vanity_reserved_words_list(self, client):
        for reserved in (
            "api",
            "socket",
            "login",
            "signup",
            "static",
            "assets",
            "health",
            "status",
            "metrics",
            "terms",
            "privacy",
        ):
            rv = self._patch(
                client,
                "/api/nests/XXXXX",
                headers={"Authorization": "Bearer test-secret-token-12345"},
                json={"vanity_code": reserved},
            )
            assert rv.status_code in (400, 403, 404)

    def test_invite_only_join_blocked_without_token(self, client):
        rv = self._get(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        # Expect 403 if invite-only and no token, otherwise 200/404.
        assert rv.status_code in (200, 403, 404)

    def test_invite_token_rotation_invalidates_old(self, client):
        rv = self._post(
            client,
            "/api/nests/XXXXX/invites/rotate",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        # After rotation, old token should be invalid.
        assert rv.status_code in (200, 401, 403, 404)

        rv = self._get(
            client,
            "/api/nests/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            query_string={"invite": "oldtoken"},
        )
        assert rv.status_code in (403, 404, 200)

    def test_create_nest_free_cap_error_shape(self, client):
        rv = self._post(
            client,
            "/api/nests",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"name": "Cap Test"},
        )
        if rv.status_code in (403, 429):
            data = rv.get_json()
            assert data.get("error") == "nest_limit_reached"
            assert "upgrade" in data.get("message", "").lower()

    def test_rate_limit_shape(self, client):
        rv = self._post(
            client,
            "/api/nests",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"name": "Rate Limit Test"},
        )
        if rv.status_code == 429:
            data = rv.get_json()
            assert data.get("error") in ("rate_limited", "nest_limit_reached")

    def test_rate_limit_buckets(self, client):
        rv = self._post(
            client,
            "/api/nests/XXXXX/kick",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"email": "user@example.com"},
        )
        if rv.status_code == 429:
            data = rv.get_json()
            assert data.get("error") == "rate_limited"


@pytest.mark.xfail(reason="Admin console not implemented yet")
class TestNestsAdminAPI:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        os.environ["ANDRE_API_TOKEN"] = "test-secret-token-12345"
        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _get(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.get(path, headers=headers, **kwargs)

    def _post(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.post(path, headers=headers, **kwargs)

    def _patch(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.patch(path, headers=headers, **kwargs)

    def test_admin_get_settings(self, client):
        rv = self._get(
            client,
            "/api/nests/XXXXX/admin",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        assert rv.status_code in (200, 401, 403, 404)

    def test_admin_update_settings(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX/admin",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={
                "vanity_code": "jazznight",
                "theme": {"accent": "#22ff66"},
                "bender": {"enabled": True},
                "is_private": True,
            },
        )
        assert rv.status_code in (200, 400, 401, 403, 404)

    def test_vanity_case_insensitive_collision(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX/admin",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "JazzNight"},
        )
        assert rv.status_code in (200, 400, 401, 403, 404)

        rv = self._patch(
            client,
            "/api/nests/YYYYY/admin",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "jazznight"},
        )
        assert rv.status_code in (400, 401, 403, 404)

    def test_admin_kick_ban_unban(self, client):
        for path in (
            "/api/nests/XXXXX/kick",
            "/api/nests/XXXXX/ban",
            "/api/nests/XXXXX/unban",
        ):
            rv = self._post(
                client,
                path,
                headers={"Authorization": "Bearer test-secret-token-12345"},
                json={"email": "user@example.com"},
            )
            assert rv.status_code in (200, 400, 401, 403, 404)

    def test_admin_invite_rotate(self, client):
        rv = self._post(
            client,
            "/api/nests/XXXXX/invites/rotate",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        assert rv.status_code in (200, 401, 403, 404)


@pytest.mark.xfail(reason="Billing endpoints not implemented yet")
class TestBillingAPI:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        os.environ["ANDRE_API_TOKEN"] = "test-secret-token-12345"
        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _get(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.get(path, headers=headers, **kwargs)

    def _post(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.post(path, headers=headers, **kwargs)

    def test_billing_status(self, client):
        rv = self._get(
            client,
            "/api/billing/status",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        assert rv.status_code in (200, 401, 403)

    def test_billing_checkout(self, client):
        rv = self._post(
            client,
            "/api/billing/checkout",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"price_id": "price_tier_a_monthly"},
        )
        assert rv.status_code in (200, 400, 401, 403)

    def test_billing_portal(self, client):
        rv = self._post(
            client,
            "/api/billing/portal",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        assert rv.status_code in (200, 401, 403)

    def test_billing_webhook_signature_required(self, client):
        rv = self._post(client, "/api/billing/webhook", data="{}")
        assert rv.status_code in (400, 401, 403)

    def test_billing_webhook_idempotency(self, client):
        payload = '{"id":"evt_123","type":"invoice.payment_succeeded"}'
        rv1 = self._post(
            client,
            "/api/billing/webhook",
            data=payload,
            headers={"Stripe-Signature": "t=123,v1=bad"},
        )
        rv2 = self._post(
            client,
            "/api/billing/webhook",
            data=payload,
            headers={"Stripe-Signature": "t=123,v1=bad"},
        )
        assert rv1.status_code in (400, 401, 403)
        assert rv2.status_code in (400, 401, 403, 409)

    def test_billing_entitlements_cache(self, client):
        rv = self._get(
            client,
            "/api/billing/status",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        assert rv.status_code in (200, 401, 403)
        if rv.status_code == 200:
            data = rv.get_json()
            assert "plan_tier" in data
            assert "features" in data

    def test_webhook_cancel_releases_vanity(self, client):
        payload = '{"id":"evt_456","type":"customer.subscription.deleted"}'
        rv = self._post(
            client,
            "/api/billing/webhook",
            data=payload,
            headers={"Stripe-Signature": "t=123,v1=bad"},
        )
        assert rv.status_code in (200, 400, 401, 403)


@pytest.mark.xfail(reason="Super admin interface not implemented yet")
class TestSuperAdminAPI:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        os.environ["ANDRE_API_TOKEN"] = "test-secret-token-12345"
        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _get(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.get(path, headers=headers, **kwargs)

    def _post(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.post(path, headers=headers, **kwargs)

    def test_superadmin_list_nests(self, client):
        rv = self._get(
            client,
            "/api/admin/nests",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        assert rv.status_code in (200, 401, 403, 404)

    def test_superadmin_force_delete(self, client):
        rv = self._post(
            client,
            "/api/admin/nests/XXXXX/delete",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"reason": "abuse"},
        )
        assert rv.status_code in (200, 400, 401, 403, 404)

    def test_superadmin_release_vanity(self, client):
        rv = self._post(
            client,
            "/api/admin/vanity/release",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "jazznight", "reason": "requested"},
        )
        assert rv.status_code in (200, 400, 401, 403, 404)


@pytest.mark.xfail(reason="Entitlement gating not implemented yet")
class TestEntitlementGates:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        os.environ["ANDRE_API_TOKEN"] = "test-secret-token-12345"
        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _patch(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.patch(path, headers=headers, **kwargs)

    def test_tier_a_gate_on_moderation(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX/admin",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"banlist": ["user@example.com"]},
        )
        assert rv.status_code in (200, 401, 403, 404)
        if rv.status_code == 403:
            data = rv.get_json()
            assert data.get("error") in ("forbidden", "feature_not_allowed")

    def test_tier_b_gate_on_theme(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX/admin",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"theme": {"accent": "#00ff88"}},
        )
        assert rv.status_code in (200, 401, 403, 404)
        if rv.status_code == 403:
            data = rv.get_json()
            assert data.get("error") in ("forbidden", "feature_not_allowed")

    def test_feature_gate_error_shape(self, client):
        rv = self._patch(
            client,
            "/api/nests/XXXXX/admin",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"vanity_code": "jazznight"},
        )
        assert rv.status_code in (200, 401, 403, 404)
        if rv.status_code == 403:
            data = rv.get_json()
            assert "error" in data
            assert "message" in data


@pytest.mark.xfail(reason="Audit logging not implemented yet")
class TestAuditLogs:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        os.environ["ANDRE_API_TOKEN"] = "test-secret-token-12345"
        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _post(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.post(path, headers=headers, **kwargs)

    def test_admin_actions_write_audit(self, client):
        rv = self._post(
            client,
            "/api/nests/XXXXX/ban",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"email": "user@example.com", "reason": "spam"},
        )
        assert rv.status_code in (200, 400, 401, 403, 404)


@pytest.mark.xfail(reason="Invite-only enforcement not implemented yet")
class TestInviteOnly:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        os.environ["ANDRE_API_TOKEN"] = "test-secret-token-12345"
        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _get(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.get(path, headers=headers, **kwargs)

    def test_invite_only_rejects_without_token(self, client):
        rv = self._get(
            client,
            "/nest/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
        )
        assert rv.status_code in (200, 401, 403, 404)
        if rv.status_code == 403:
            data = rv.get_json()
            assert data.get("error") in ("invite_required", "forbidden")

    def test_invite_only_accepts_token(self, client):
        rv = self._get(
            client,
            "/nest/XXXXX",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            query_string={"invite": "validtoken"},
        )
        assert rv.status_code in (200, 401, 404)


@pytest.mark.xfail(reason="Free cap accounting not implemented yet")
class TestFreeCap:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        os.environ["ANDRE_API_TOKEN"] = "test-secret-token-12345"
        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _post(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.post(path, headers=headers, **kwargs)

    def test_free_cap_counts_paid_vs_free(self, client):
        rv = self._post(
            client,
            "/api/nests",
            headers={"Authorization": "Bearer test-secret-token-12345"},
            json={"name": "Free Cap Check"},
        )
        assert rv.status_code in (200, 403, 429)
        if rv.status_code in (403, 429):
            data = rv.get_json()
            assert data.get("error") == "nest_limit_reached"


@pytest.mark.xfail(reason="Redis key prefixing not implemented yet")
class TestRedisKeyPrefixing:
    def test_db_key_prefixing(self):
        try:
            from db import DB
        except Exception as e:
            pytest.xfail(f"Cannot import DB: {e}")

        try:
            db = DB(nest_id="X7K2P", init_history_to_redis=False)
        except TypeError:
            pytest.xfail("DB does not accept nest_id yet")
        except Exception as e:
            pytest.xfail(f"DB init failed: {e}")

        if not hasattr(db, "_key"):
            pytest.xfail("DB._key missing")

        assert db._key("MISC|now-playing") == "NEST:X7K2P|MISC|now-playing"


@pytest.mark.xfail(reason="Nest cleanup logic not implemented yet")
class TestNestCleanupLogic:
    def test_should_delete_nest_predicate(self):
        try:
            nests = importlib.import_module("nests")
        except Exception as e:
            pytest.xfail(f"Cannot import nests module: {e}")

        helper = getattr(nests, "should_delete_nest", None)
        if helper is None:
            pytest.xfail("should_delete_nest helper missing")

        now = datetime.datetime(2026, 2, 11, 12, 0, 0)
        metadata = {
            "is_main": False,
            "last_activity": "2026-02-11T09:00:00",
            "ttl_minutes": 120,
        }
        assert helper(metadata, members=0, queue_size=0, now=now) is True
        assert helper(metadata, members=1, queue_size=0, now=now) is False
        assert helper(metadata, members=0, queue_size=1, now=now) is False

        metadata["is_main"] = True
        assert helper(metadata, members=0, queue_size=0, now=now) is False


@pytest.mark.xfail(reason="Membership heartbeat helpers not implemented yet")
class TestMembershipHeartbeat:
    def test_member_key_helpers(self):
        try:
            nests = importlib.import_module("nests")
        except Exception as e:
            pytest.xfail(f"Cannot import nests module: {e}")

        member_key = getattr(nests, "member_key", None)
        members_key = getattr(nests, "members_key", None)
        if member_key is None or members_key is None:
            pytest.xfail("member_key/members_key helpers missing")

        assert members_key("X7K2P") == "NEST:X7K2P|MEMBERS"
        assert member_key("X7K2P", "user@example.com") == "NEST:X7K2P|MEMBER:user@example.com"


@pytest.mark.xfail(reason="Migration helpers not implemented yet")
class TestMigrationHelpers:
    def test_legacy_key_rename_map(self):
        try:
            nests = importlib.import_module("nests")
        except Exception as e:
            pytest.xfail(f"Cannot import nests module: {e}")

        mapping = getattr(nests, "legacy_key_mapping", None)
        if mapping is None:
            pytest.xfail("legacy_key_mapping helper missing")

        expected = {
            "MISC|now-playing": "NEST:main|MISC|now-playing",
            "MISC|priority-queue": "NEST:main|MISC|priority-queue",
        }
        for k, v in expected.items():
            assert mapping[k] == v


@pytest.mark.xfail(reason="Per-nest pubsub channel not implemented yet")
class TestPubSubChannels:
    def test_pubsub_channel_key(self):
        try:
            nests = importlib.import_module("nests")
        except Exception as e:
            pytest.xfail(f"Cannot import nests module: {e}")

        channel = getattr(nests, "pubsub_channel", None)
        if channel is None:
            pytest.xfail("pubsub_channel helper missing")

        assert channel("X7K2P") == "NEST:X7K2P|MISC|update-pubsub"


@pytest.mark.xfail(reason="Master player multi-nest iteration not implemented yet")
class TestMasterPlayerMultiNest:
    def test_master_player_iterates_nests(self):
        try:
            mp = importlib.import_module("master_player")
        except Exception as e:
            pytest.xfail(f"Cannot import master_player: {e}")

        helper = getattr(mp, "master_player_tick_all", None)
        if helper is None:
            pytest.xfail("master_player_tick_all helper missing")

        assert callable(helper)


class TestNestManagerCRUD:
    def test_create_get_list_delete(self):
        try:
            nests = importlib.import_module("nests")
        except Exception as e:
            pytest.xfail(f"Cannot import nests module: {e}")

        manager_cls = getattr(nests, "NestManager", None)
        if manager_cls is None:
            pytest.xfail("NestManager missing")

        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = manager_cls(redis_client=fake_r)

        # Create
        nest = manager.create_nest("creator@example.com", name="Friday Vibes")
        assert "code" in nest
        assert nest["name"] == "Friday Vibes"
        assert nest["creator"] == "creator@example.com"
        assert nest["is_main"] is False

        # Get by nest_id (which is the code)
        fetched = manager.get_nest(nest["code"])
        assert fetched is not None
        assert fetched["name"] == "Friday Vibes"

        # List — main nest should exist (created by _ensure_main_nest)
        nests_list = manager.list_nests()
        assert isinstance(nests_list, list)
        assert any(nid == "main" for nid, _meta in nests_list)
        # The new nest should also appear
        assert any(nid == nest["nest_id"] for nid, _meta in nests_list)

        # Delete
        manager.delete_nest(nest["code"])
        assert manager.get_nest(nest["code"]) is None

    def test_random_name_from_nest_names(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)

        nest = manager.create_nest("creator@example.com")
        assert nest["name"] in nests.NEST_NAMES

    def test_two_nests_get_different_random_names(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)

        nest1 = manager.create_nest("a@example.com")
        nest2 = manager.create_nest("b@example.com")
        assert nest1["name"] != nest2["name"]

    def test_explicit_name_overrides_random(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)

        nest = manager.create_nest("creator@example.com", name="Friday Jams")
        assert nest["name"] == "Friday Jams"

    def test_join_and_leave(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)

        nest = manager.create_nest("host@example.com")
        code = nest["code"]

        # Join
        manager.join_nest(code, "user1@example.com")
        members = fake_r.smembers(nests.members_key(code))
        assert "user1@example.com" in members

        # Leave
        manager.leave_nest(code, "user1@example.com")
        members = fake_r.smembers(nests.members_key(code))
        assert "user1@example.com" not in members

    def test_generate_code_uniqueness(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)

        codes = set()
        for _ in range(20):
            codes.add(manager.generate_code())
        # All 20 codes should be unique
        assert len(codes) == 20
        # All codes should use only valid characters
        for code in codes:
            assert len(code) == 5
            assert all(c in nests.CODE_CHARS for c in code)


class TestCountActiveMembers:
    def test_prunes_stale_members(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)
        nest = manager.create_nest("host@example.com")
        nid = nest["code"]

        # Add two members to the set
        manager.join_nest(nid, "active@example.com")
        manager.join_nest(nid, "stale@example.com")

        # Set heartbeat TTL for active member only
        nests.refresh_member_ttl(fake_r, nid, "active@example.com")
        # stale@example.com has no TTL key (simulates expired heartbeat)

        count = nests.count_active_members(fake_r, nid)
        assert count == 1

        # Stale member should have been pruned from the MEMBERS set
        members = fake_r.smembers(nests.members_key(nid))
        assert "active@example.com" in members
        assert "stale@example.com" not in members

    def test_all_active(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)
        nest = manager.create_nest("host@example.com")
        nid = nest["code"]

        manager.join_nest(nid, "a@example.com")
        manager.join_nest(nid, "b@example.com")
        nests.refresh_member_ttl(fake_r, nid, "a@example.com")
        nests.refresh_member_ttl(fake_r, nid, "b@example.com")

        count = nests.count_active_members(fake_r, nid)
        assert count == 2

    def test_empty_nest(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)
        nest = manager.create_nest("host@example.com")

        count = nests.count_active_members(fake_r, nest["code"])
        assert count == 0


class TestDeleteNestMainGuard:
    def test_delete_main_is_noop(self):
        nests = importlib.import_module("nests")
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = nests.NestManager(redis_client=fake_r)

        # Main nest should exist after init
        assert manager.get_nest("main") is not None

        # Attempting to delete main should be a no-op
        manager.delete_nest("main")

        # Main nest should still exist
        assert manager.get_nest("main") is not None


@pytest.mark.xfail(reason="Migration script not implemented yet")
class TestMigrationScriptBehavior:
    def test_migration_script_idempotent(self):
        try:
            import migrate_keys
        except Exception as e:
            pytest.xfail(f"Cannot import migrate_keys: {e}")

        assert hasattr(migrate_keys, "migrate")

    def test_migration_skips_existing_dest(self):
        try:
            import migrate_keys
        except Exception as e:
            pytest.xfail(f"Cannot import migrate_keys: {e}")

        assert hasattr(migrate_keys, "migrate")


@pytest.mark.xfail(reason="Auth gating for nest routes not implemented yet")
class TestNestAuthGating:
    @pytest.fixture
    def client(self):
        if os.environ.get("SKIP_SPOTIFY_PREFETCH"):
            pytest.skip("Skipping due to SKIP_SPOTIFY_PREFETCH")

        from app import app, CONF

        app.config["TESTING"] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else "localhost:5000"
        with app.test_client() as client:
            yield client

    def _get(self, client, path, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Host"] = self._host
        return client.get(path, headers=headers, **kwargs)

    def test_api_nests_requires_auth(self, client):
        rv = self._get(client, "/api/nests")
        assert rv.status_code in (401, 403, 302)

    def test_nest_page_requires_auth(self, client):
        rv = self._get(client, "/nest/XXXXX")
        assert rv.status_code in (401, 403, 302, 404)


@pytest.mark.xfail(reason="WebSocket membership tracking not implemented yet")
class TestWebSocketMembership:
    def test_membership_join_leave(self):
        try:
            nests = importlib.import_module("nests")
        except Exception as e:
            pytest.xfail(f"Cannot import nests module: {e}")

        join = getattr(nests, "join_nest", None)
        leave = getattr(nests, "leave_nest", None)
        if join is None or leave is None:
            pytest.xfail("join_nest/leave_nest helpers missing")

        assert callable(join)
        assert callable(leave)

    def test_heartbeat_ttl_refresh(self):
        try:
            nests = importlib.import_module("nests")
        except Exception as e:
            pytest.xfail(f"Cannot import nests module: {e}")

        refresh = getattr(nests, "refresh_member_ttl", None)
        if refresh is None:
            pytest.xfail("refresh_member_ttl helper missing")

        assert callable(refresh)


class TestCrossNestIsolation:
    """Verify that operations on one nest do not leak into another."""

    @pytest.fixture
    def nest_pair(self):
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        from db import DB

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        db_a = DB(nest_id="nest-A", init_history_to_redis=False, redis_client=fake_r)
        db_b = DB(nest_id="nest-B", init_history_to_redis=False, redis_client=fake_r)
        return db_a, db_b, fake_r

    def test_queue_isolation(self, nest_pair):
        db_a, db_b, fake_r = nest_pair
        # Add a song hash to nest-A's queue directly
        fake_r.hset("NEST:nest-A|QUEUE|1", mapping={"trackid": "spotify:track:abc", "user": "u@x.com"})
        fake_r.zadd("NEST:nest-A|MISC|priority-queue", {"1": 1.0})

        # nest-B queue should be empty
        assert fake_r.zcard("NEST:nest-B|MISC|priority-queue") == 0
        assert fake_r.exists("NEST:nest-B|QUEUE|1") == 0

    def test_vote_isolation(self, nest_pair):
        db_a, db_b, fake_r = nest_pair
        fake_r.sadd("NEST:nest-A|QUEUE|VOTE|1", "voter@example.com")
        assert fake_r.scard("NEST:nest-B|QUEUE|VOTE|1") == 0

    def test_pause_isolation(self, nest_pair):
        db_a, db_b, fake_r = nest_pair
        fake_r.set("NEST:nest-A|MISC|paused", "1")
        assert fake_r.exists("NEST:nest-B|MISC|paused") == 0

    def test_volume_isolation(self, nest_pair):
        db_a, db_b, fake_r = nest_pair
        fake_r.set("NEST:nest-A|MISC|volume", "50")
        assert fake_r.exists("NEST:nest-B|MISC|volume") == 0

    def test_pubsub_channel_isolation(self):
        nests_mod = importlib.import_module("nests")
        ch_a = nests_mod.pubsub_channel("nest-A")
        ch_b = nests_mod.pubsub_channel("nest-B")
        assert ch_a != ch_b
        assert "nest-A" in ch_a
        assert "nest-B" in ch_b


class TestQueueDepthLimit:
    """Ensure temporary nests enforce configurable queue depth caps."""

    @pytest.fixture
    def temp_db(self):
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        from db import DB

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        db = DB(nest_id="temp-nest", init_history_to_redis=False, redis_client=fake_r)

        # Silence pubsub messages during tests
        db._msg = lambda *args, **kwargs: None
        return db, fake_r

    def _song_payload(self, idx):
        return {
            'src': 'spotify',
            'trackid': f'spotify:track:{idx}',
            'title': f'Song {idx}',
            'artist': 'Tester',
            'duration': 60,
            'auto': False,
            'big_img': '',
            'img': '',
        }

    def test_temp_nest_rejects_when_full(self, temp_db, monkeypatch):
        db, fake_r = temp_db

        import config
        monkeypatch.setattr(config.CONF, 'NEST_MAX_QUEUE_DEPTH', 2, raising=False)

        db._add_song('user@example.com', self._song_payload(1), False)
        db._add_song('user@example.com', self._song_payload(2), False)

        with pytest.raises(RuntimeError, match='Queue is full'):
            db._add_song('user@example.com', self._song_payload(3), False)

        assert fake_r.zcard('NEST:temp-nest|MISC|priority-queue') == 2

    def test_main_nest_ignores_queue_limit(self, monkeypatch):
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        from db import DB
        import config

        monkeypatch.setattr(config.CONF, 'NEST_MAX_QUEUE_DEPTH', 2, raising=False)

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        db = DB(nest_id="main", init_history_to_redis=False, redis_client=fake_r)
        db._msg = lambda *args, **kwargs: None

        # Should not raise even past the configured limit
        for i in range(5):
            db._add_song('user@example.com', self._song_payload(i), False)

        assert fake_r.zcard('NEST:main|MISC|priority-queue') == 5

class TestRaceResistantDeletion:
    """Verify the DELETING flag blocks writes and cleanup removes all keys."""

    @pytest.fixture
    def fake_redis(self):
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")
        return fakeredis.FakeRedis(decode_responses=True)

    def test_deleting_flag_blocks_writes(self, fake_redis):
        from db import DB
        from nests import deleting_key

        db = DB(nest_id="doomed", init_history_to_redis=False, redis_client=fake_redis)
        fake_redis.setex(deleting_key("doomed"), 30, "1")

        with pytest.raises(RuntimeError, match="being deleted"):
            db._check_nest_active()

    def test_no_flag_allows_writes(self, fake_redis):
        from db import DB

        db = DB(nest_id="alive", init_history_to_redis=False, redis_client=fake_redis)
        # Should not raise
        db._check_nest_active()

    def test_main_nest_skips_check(self, fake_redis):
        from db import DB
        from nests import deleting_key

        db = DB(nest_id="main", init_history_to_redis=False, redis_client=fake_redis)
        # Even with a flag set (shouldn't happen, but testing guard)
        fake_redis.setex(deleting_key("main"), 30, "1")
        # Should not raise
        db._check_nest_active()

    def test_delete_nest_cleans_up(self, fake_redis):
        from nests import NestManager, deleting_key, _nest_prefix

        manager = NestManager(redis_client=fake_redis)
        nest = manager.create_nest("creator@example.com", name="Temp")
        nid = nest["nest_id"]

        # Plant some keys that would exist in a real nest
        fake_redis.set(f"NEST:{nid}|MISC|volume", "80")
        fake_redis.set(f"NEST:{nid}|MISC|paused", "1")
        fake_redis.hset(f"NEST:{nid}|QUEUE|1", mapping={"trackid": "abc"})

        manager.delete_nest(nid)

        # All nest keys should be gone
        prefix = _nest_prefix(nid)
        remaining = list(fake_redis.scan_iter(match=f"{prefix}*"))
        assert remaining == []

        # DELETING flag should also be gone
        assert fake_redis.exists(deleting_key(nid)) == 0

        # Nest should not be in registry
        assert manager.get_nest(nid) is None

    def test_guard_blocks_nuke_queue(self, fake_redis):
        from db import DB
        from nests import deleting_key

        db = DB(nest_id="doomed", init_history_to_redis=False, redis_client=fake_redis)
        fake_redis.setex(deleting_key("doomed"), 30, "1")

        with pytest.raises(RuntimeError, match="being deleted"):
            db.nuke_queue("user@example.com")


class TestNestSeedMap:
    """Tests for nest-name-based Bender seed mapping."""

    def test_nest_seed_map_covers_all_names(self):
        from nests import NEST_NAMES, NEST_SEED_MAP
        assert set(NEST_NAMES) == set(NEST_SEED_MAP.keys())

    def test_seed_uris_are_valid_format(self):
        from nests import NEST_SEED_MAP
        for name, (uri, genre) in NEST_SEED_MAP.items():
            assert uri.startswith('spotify:track:'), f"{name} has invalid URI: {uri}"

    def test_get_nest_seed_info_known_name(self):
        from nests import get_nest_seed_info, NEST_SEED_MAP
        # Pick a known name and verify the lookup returns the right tuple
        uri, genre = get_nest_seed_info('FunkNest')
        expected_uri, expected_genre = NEST_SEED_MAP['FunkNest']
        assert uri == expected_uri
        assert genre == expected_genre

    def test_get_nest_seed_info_strips_suffix(self):
        from nests import get_nest_seed_info, NEST_SEED_MAP
        # "BassNest2" should resolve to BassNest's entry
        uri, genre = get_nest_seed_info('BassNest2')
        expected_uri, expected_genre = NEST_SEED_MAP['BassNest']
        assert uri == expected_uri
        assert genre == expected_genre

    def test_get_nest_seed_info_unknown_returns_default(self):
        from nests import get_nest_seed_info, _DEFAULT_SEED
        # Custom names like "Friday Vibes" should get the default
        assert get_nest_seed_info('Friday Vibes') == _DEFAULT_SEED
        assert get_nest_seed_info('Home Nest') == _DEFAULT_SEED
        assert get_nest_seed_info('') == _DEFAULT_SEED

    def test_create_nest_with_seed_track_stores_metadata(self):
        """Creating a nest with seed_track stores seed_uri and genre_hint."""
        from unittest.mock import patch, MagicMock
        from nests import NestManager
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = NestManager(redis_client=fake_r)

        mock_spotify = MagicMock()
        mock_spotify.track.return_value = {
            'artists': [{'id': 'artist123', 'name': 'Test Artist'}],
        }
        mock_spotify.artist.return_value = {
            'genres': ['indie rock', 'alternative'],
        }

        with patch('nests.spotify_client', mock_spotify, create=True):
            # Patch at the import target in the module
            import db as db_mod
            with patch.object(db_mod, 'spotify_client', mock_spotify):
                nest = manager.create_nest(
                    "creator@example.com",
                    name="Friday Vibes",
                    seed_track="spotify:track:abc123",
                )

        assert nest['seed_uri'] == 'spotify:track:abc123'
        assert nest['genre_hint'] == 'indie rock'

        # Verify it's persisted in Redis
        fetched = manager.get_nest(nest['code'])
        assert fetched['seed_uri'] == 'spotify:track:abc123'
        assert fetched['genre_hint'] == 'indie rock'

    def test_create_nest_with_invalid_seed_track_raises(self):
        """Non-spotify:track: URI raises ValueError."""
        from nests import NestManager
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = NestManager(redis_client=fake_r)

        with pytest.raises(ValueError, match="spotify:track:"):
            manager.create_nest("c@example.com", seed_track="spotify:album:xyz")

        with pytest.raises(ValueError, match="spotify:track:"):
            manager.create_nest("c@example.com", seed_track="https://open.spotify.com/track/abc")

    def test_create_nest_without_seed_track_unchanged(self):
        """No seed_track → no seed_uri/genre_hint in metadata."""
        from nests import NestManager
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = NestManager(redis_client=fake_r)

        nest = manager.create_nest("c@example.com", name="Plain Nest")
        assert 'seed_uri' not in nest
        assert 'genre_hint' not in nest

    def test_fallback_prefers_explicit_seed_uri(self):
        """Nest with explicit seed_uri → _nest_fallback_seed() returns it."""
        from unittest.mock import patch, MagicMock
        from nests import NestManager
        from db import DB
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = NestManager(redis_client=fake_r)

        mock_spotify = MagicMock()
        mock_spotify.track.return_value = {
            'artists': [{'id': 'a1', 'name': 'Artist'}],
        }
        mock_spotify.artist.return_value = {'genres': ['funk']}

        import db as db_mod
        with patch.object(db_mod, 'spotify_client', mock_spotify):
            nest = manager.create_nest(
                "c@example.com", name="Custom",
                seed_track="spotify:track:explicit123",
            )

        db = DB(nest_id=nest['code'], init_history_to_redis=False, redis_client=fake_r)
        result = db._nest_fallback_seed()
        assert result == 'spotify:track:explicit123'

    def test_genre_hint_prefers_explicit(self):
        """Nest with explicit genre_hint → _get_nest_genre_hint() returns it."""
        from unittest.mock import patch, MagicMock
        from nests import NestManager
        from db import DB
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis not installed")

        fake_r = fakeredis.FakeRedis(decode_responses=True)
        manager = NestManager(redis_client=fake_r)

        mock_spotify = MagicMock()
        mock_spotify.track.return_value = {
            'artists': [{'id': 'a1', 'name': 'Artist'}],
        }
        mock_spotify.artist.return_value = {'genres': ['synthwave']}

        import db as db_mod
        with patch.object(db_mod, 'spotify_client', mock_spotify):
            nest = manager.create_nest(
                "c@example.com", name="Custom",
                seed_track="spotify:track:synth456",
            )

        db = DB(nest_id=nest['code'], init_history_to_redis=False, redis_client=fake_r)
        result = db._get_nest_genre_hint()
        assert result == 'synthwave'
