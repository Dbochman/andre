"""
Tests for the REST API token-authentication and endpoints.
"""
import pytest
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAPIAuth:
    """Test API authentication behavior."""

    @pytest.fixture
    def client(self):
        """Create a test client with API token configured."""
        if os.environ.get('SKIP_SPOTIFY_PREFETCH'):
            pytest.skip('Skipping due to SKIP_SPOTIFY_PREFETCH')

        os.environ['ANDRE_API_TOKEN'] = 'test-secret-token-12345'
        from app import app, CONF
        app.config['TESTING'] = True
        # Use CONF.HOSTNAME so the host check in before_request passes
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else 'localhost:5000'
        with app.test_client() as client:
            yield client

    def _post(self, client, path, **kwargs):
        """POST with correct Host header to pass the hostname check."""
        headers = kwargs.pop('headers', {})
        headers['Host'] = self._host
        return client.post(path, headers=headers, **kwargs)

    def test_401_without_auth_header(self, client):
        """API should return 401 without Authorization header."""
        rv = self._post(client, '/api/queue/skip')
        assert rv.status_code == 401
        assert 'WWW-Authenticate' in rv.headers
        assert rv.headers['WWW-Authenticate'] == 'Bearer'

    def test_403_with_invalid_token(self, client):
        """API should return 403 with wrong Bearer token."""
        rv = self._post(client, '/api/queue/skip',
                         headers={'Authorization': 'Bearer wrong-token'})
        assert rv.status_code == 403

    def test_no_redirect_on_api_paths(self, client):
        """API paths should return JSON errors, never 302 to /login/."""
        rv = self._post(client, '/api/queue/skip')
        assert rv.status_code != 302

    def test_401_includes_json_error(self, client):
        """401 response should include a JSON error body."""
        rv = self._post(client, '/api/queue/skip')
        data = rv.get_json()
        assert 'error' in data


class TestSpotifyAPI:
    """Test Spotify Connect API endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client with API token configured but NO Spotify email."""
        if os.environ.get('SKIP_SPOTIFY_PREFETCH'):
            pytest.skip('Skipping due to SKIP_SPOTIFY_PREFETCH')

        os.environ['ANDRE_API_TOKEN'] = 'test-secret-token-12345'
        # Ensure ANDRE_SPOTIFY_EMAIL is NOT set so we get 503
        os.environ.pop('ANDRE_SPOTIFY_EMAIL', None)
        from app import app, CONF
        CONF.ANDRE_SPOTIFY_EMAIL = None
        app.config['TESTING'] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else 'localhost:5000'
        with app.test_client() as client:
            yield client

    def _get(self, client, path, **kwargs):
        headers = kwargs.pop('headers', {})
        headers['Host'] = self._host
        return client.get(path, headers=headers, **kwargs)

    def test_401_without_auth_header(self, client):
        """Spotify API should return 401 without Authorization header."""
        rv = self._get(client, '/api/spotify/devices')
        assert rv.status_code == 401

    def test_403_with_invalid_token(self, client):
        """Spotify API should return 403 with wrong Bearer token."""
        rv = self._get(client, '/api/spotify/devices',
                       headers={'Authorization': 'Bearer wrong-token'})
        assert rv.status_code == 403

    def test_503_when_spotify_email_not_set(self, client):
        """Spotify API should return 503 when ANDRE_SPOTIFY_EMAIL is not configured."""
        rv = self._get(client, '/api/spotify/devices',
                       headers={'Authorization': 'Bearer test-secret-token-12345'})
        assert rv.status_code == 503
        data = rv.get_json()
        assert 'ANDRE_SPOTIFY_EMAIL' in data.get('error', '')


class TestReadEndpoints:
    """Test /api/queue, /api/playing, and /api/events auth."""

    @pytest.fixture
    def client(self):
        if os.environ.get('SKIP_SPOTIFY_PREFETCH'):
            pytest.skip('Skipping due to SKIP_SPOTIFY_PREFETCH')

        os.environ['ANDRE_API_TOKEN'] = 'test-secret-token-12345'
        from app import app, CONF
        app.config['TESTING'] = True
        self._host = str(CONF.HOSTNAME) if CONF.HOSTNAME else 'localhost:5000'
        with app.test_client() as client:
            yield client

    def _get(self, client, path, **kwargs):
        headers = kwargs.pop('headers', {})
        headers['Host'] = self._host
        return client.get(path, headers=headers, **kwargs)

    # --- /api/queue ---

    def test_api_queue_401(self, client):
        rv = self._get(client, '/api/queue')
        assert rv.status_code == 401

    def test_api_queue_403(self, client):
        rv = self._get(client, '/api/queue',
                       headers={'Authorization': 'Bearer wrong'})
        assert rv.status_code == 403

    # --- /api/playing ---

    def test_api_playing_401(self, client):
        rv = self._get(client, '/api/playing')
        assert rv.status_code == 401

    def test_api_playing_403(self, client):
        rv = self._get(client, '/api/playing',
                       headers={'Authorization': 'Bearer wrong'})
        assert rv.status_code == 403

    # --- /api/events ---

    def test_api_events_401(self, client):
        rv = self._get(client, '/api/events')
        assert rv.status_code == 401

    def test_api_events_403(self, client):
        rv = self._get(client, '/api/events',
                       headers={'Authorization': 'Bearer wrong'})
        assert rv.status_code == 403


class TestAPIWithoutSpotify:
    """Tests that don't require Spotify connection."""

    def test_api_prefix_in_safe_param_paths(self):
        """Verify /api/ is in SAFE_PARAM_PATHS so it bypasses session auth."""
        try:
            from app import SAFE_PARAM_PATHS
        except Exception as e:
            pytest.skip(f'Cannot import app: {e}')

        assert '/api/' in SAFE_PARAM_PATHS

    def test_config_env_override_includes_token(self):
        """Verify ANDRE_API_TOKEN is in the ENV_OVERRIDES list."""
        try:
            from config import ENV_OVERRIDES
        except (ImportError, ModuleNotFoundError) as e:
            pytest.skip(f'Cannot import config: {e}')

        assert 'ANDRE_API_TOKEN' in ENV_OVERRIDES

    def test_config_env_override_includes_spotify_email(self):
        """Verify ANDRE_SPOTIFY_EMAIL is in the ENV_OVERRIDES list."""
        try:
            from config import ENV_OVERRIDES
        except (ImportError, ModuleNotFoundError) as e:
            pytest.skip(f'Cannot import config: {e}')

        assert 'ANDRE_SPOTIFY_EMAIL' in ENV_OVERRIDES
