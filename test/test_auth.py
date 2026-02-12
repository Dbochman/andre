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

        from app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

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
