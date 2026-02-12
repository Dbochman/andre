"""
Tests for authentication behavior.
"""
import pytest
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAuthGate:
    """Test authentication behavior."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        # Skip if Spotify prefetch would fail
        if os.environ.get('SKIP_SPOTIFY_PREFETCH'):
            pytest.skip('Skipping due to SKIP_SPOTIFY_PREFETCH')

        from app import app, CONF

        app.config['TESTING'] = True

        class _DummyDB:
            def get_now_playing(self):
                return {}

            def get_queued(self):
                return []

        original_hostname = getattr(CONF, 'HOSTNAME', None)
        original_dev_email = getattr(CONF, 'DEV_AUTH_EMAIL', None)
        original_db = getattr(app, 'd', None)
        try:
            setattr(CONF, 'HOSTNAME', '')
            setattr(CONF, 'DEV_AUTH_EMAIL', None)
            setattr(app, 'd', _DummyDB())
            with app.test_client() as client:
                yield client
        finally:
            setattr(CONF, 'HOSTNAME', original_hostname)
            setattr(CONF, 'DEV_AUTH_EMAIL', original_dev_email)
            if original_db is not None:
                setattr(app, 'd', original_db)

    def test_health_endpoint_public(self, client):
        """Health endpoint should be accessible without auth."""
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'

    def test_root_requires_auth(self, client):
        """Root endpoint should redirect to login when not authenticated."""
        response = client.get('/', follow_redirects=False)
        assert response.status_code == 302
        assert '/login/' in response.location

    def test_playing_endpoint_public(self, client):
        """Playing endpoint should be accessible without auth."""
        response = client.get('/playing/')
        # May return empty or error if no song playing, but should not redirect
        assert response.status_code == 200

    def test_queue_endpoint_public(self, client):
        """Queue endpoint should be accessible without auth."""
        response = client.get('/queue/')
        assert response.status_code == 200

    def test_static_files_public(self, client):
        """Static files should be accessible without auth."""
        # Just check that it doesn't redirect to login
        response = client.get('/static/favicon.png', follow_redirects=False)
        # 200 if exists, 404 if not, but not 302 redirect
        assert response.status_code != 302 or '/login/' not in response.location

    def test_auth_callback_rejects_unapproved_domain(self, monkeypatch):
        """OAuth callback returns 403 with a helpful message when domain is not allowed."""
        if os.environ.get('SKIP_SPOTIFY_PREFETCH'):
            pytest.skip('Skipping due to SKIP_SPOTIFY_PREFETCH')

        from app import app, CONF

        class DummyResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        monkeypatch.setattr('app.requests.post',
                            lambda *args, **kwargs: DummyResponse({'access_token': 'fake-token'}))
        monkeypatch.setattr('app.requests.get',
                            lambda *args, **kwargs: DummyResponse({'email': 'user@blocked.com', 'name': 'Blocked User'}))
        monkeypatch.setattr(CONF, 'ALLOWED_EMAIL_DOMAINS', ['allowed.com'], raising=False)

        app.config['TESTING'] = True
        base_url = f'http://{CONF.HOSTNAME}' if CONF.HOSTNAME else 'http://127.0.0.1:5000'
        with app.test_client() as client:
            response = client.get(
                '/authentication/callback',
                query_string={'code': 'dummy'},
                base_url=base_url,
            )

        assert response.status_code == 403
        assert b'not on the guest list' in response.data
        assert b'Sign in with Google' in response.data

    def test_auth_callback_allows_permitted_domain(self, monkeypatch):
        """OAuth callback succeeds when the email domain is allowed."""
        if os.environ.get('SKIP_SPOTIFY_PREFETCH'):
            pytest.skip('Skipping due to SKIP_SPOTIFY_PREFETCH')

        from app import app, CONF

        class DummyResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        monkeypatch.setattr('app.requests.post',
                            lambda *args, **kwargs: DummyResponse({'access_token': 'fake-token'}))
        monkeypatch.setattr('app.requests.get',
                            lambda *args, **kwargs: DummyResponse({'email': 'user@allowed.com', 'name': 'Allowed User'}))
        monkeypatch.setattr(CONF, 'ALLOWED_EMAIL_DOMAINS', ['allowed.com'], raising=False)

        app.config['TESTING'] = True
        base_url = f'http://{CONF.HOSTNAME}' if CONF.HOSTNAME else 'http://127.0.0.1:5000'
        with app.test_client() as client:
            response = client.get(
                '/authentication/callback',
                query_string={'code': 'dummy'},
                follow_redirects=False,
                base_url=base_url,
            )

        assert response.status_code == 302
        assert response.location.endswith('/')


class TestAuthGateWithoutSpotify:
    """Tests that don't require Spotify connection."""

    def test_safe_paths_defined(self):
        """Verify safe paths are properly defined."""
        # Skip if we can't import the app (missing dependencies)
        try:
            from app import SAFE_PATHS, SAFE_PARAM_PATHS
        except Exception as e:
            pytest.skip(f'Cannot import app: {e}')

        assert '/login/' in SAFE_PATHS
        assert '/logout/' in SAFE_PATHS
        assert '/health' in SAFE_PATHS
        assert '/playing/' in SAFE_PATHS
        assert '/queue/' in SAFE_PATHS

        assert '/history' in SAFE_PARAM_PATHS
        assert '/search/v2' in SAFE_PARAM_PATHS
