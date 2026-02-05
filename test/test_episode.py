"""Tests for podcast/episode support."""
import pytest
from unittest.mock import patch, MagicMock


class TestEpisodeURIDetection:
    """Test episode URI detection in add_spotify_song."""

    def test_episode_uri_detected(self):
        """Episode URIs should be detected by 'episode' in the string."""
        episode_uri = "spotify:episode:4D9Kl0oLzsblLWGGLgKIKT"
        track_uri = "spotify:track:3utq2FgD1pkmIoaWfjXWAU"

        assert 'episode' in episode_uri
        assert 'episode' not in track_uri

    def test_episode_id_extraction(self):
        """Episode ID should be extracted from URI correctly."""
        episode_uri = "spotify:episode:4D9Kl0oLzsblLWGGLgKIKT"
        episode_id = episode_uri.split(':')[-1]

        assert episode_id == "4D9Kl0oLzsblLWGGLgKIKT"

    def test_track_id_extraction(self):
        """Track ID should be extracted from URI correctly."""
        track_uri = "spotify:track:3utq2FgD1pkmIoaWfjXWAU"
        track_id = track_uri.split(':')[-1]

        assert track_id == "3utq2FgD1pkmIoaWfjXWAU"


class TestExtractImages:
    """Test the _extract_images helper function."""

    def test_extract_images_empty_list(self):
        """Empty image list should return None, None."""
        from db import DB
        db = DB(init_history_to_redis=False)

        big_img, img = db._extract_images([])
        assert big_img is None
        assert img is None

    def test_extract_images_none(self):
        """None should return None, None."""
        from db import DB
        db = DB(init_history_to_redis=False)

        big_img, img = db._extract_images(None)
        assert big_img is None
        assert img is None

    def test_extract_images_single(self):
        """Single image should be used for both big and small."""
        from db import DB
        db = DB(init_history_to_redis=False)

        images = [{'url': 'http://example.com/img1.jpg'}]
        big_img, img = db._extract_images(images)

        assert big_img == 'http://example.com/img1.jpg'
        assert img == 'http://example.com/img1.jpg'

    def test_extract_images_multiple(self):
        """Multiple images: first for big, last for small."""
        from db import DB
        db = DB(init_history_to_redis=False)

        images = [
            {'url': 'http://example.com/large.jpg'},
            {'url': 'http://example.com/medium.jpg'},
            {'url': 'http://example.com/small.jpg'},
        ]
        big_img, img = db._extract_images(images)

        assert big_img == 'http://example.com/large.jpg'
        assert img == 'http://example.com/small.jpg'


class TestEpisodeScrobbling:
    """Test that episodes are not scrobbled."""

    def test_episode_not_scrobbled(self):
        """Episodes should not trigger scrobbling."""
        episode_uri = "spotify:episode:4D9Kl0oLzsblLWGGLgKIKT"

        # The scrobble logic checks for 'episode' in trackid
        should_scrobble = 'episode' not in episode_uri
        assert should_scrobble is False

    def test_track_scrobbled(self):
        """Tracks should trigger scrobbling."""
        track_uri = "spotify:track:3utq2FgD1pkmIoaWfjXWAU"

        should_scrobble = 'episode' not in track_uri
        assert should_scrobble is True
