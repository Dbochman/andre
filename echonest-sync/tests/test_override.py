"""Tests for manual playback (user override) detection."""

import time

from echonest_sync.ipc import SyncChannel
from echonest_sync.player import SpotifyPlayer
from echonest_sync.sync import SyncAgent


class MockPlayer(SpotifyPlayer):
    def __init__(self, current_track=None):
        self.calls = []
        self._current_track = current_track

    def play_track(self, uri):
        self.calls.append(("play_track", uri))

    def pause(self):
        self.calls.append(("pause",))

    def resume(self):
        self.calls.append(("resume",))

    def seek_to(self, seconds):
        self.calls.append(("seek_to", seconds))

    def get_position(self):
        return 0.0

    def get_current_track(self):
        return self._current_track

    def is_running(self):
        return True


class TestUserOverride:
    def _agent(self, current_track=None):
        player = MockPlayer(current_track=current_track)
        channel = SyncChannel()
        agent = SyncAgent("https://test", "tok", player,
                          drift_threshold=3, channel=channel)
        return agent, player, channel

    def test_override_after_two_checks(self):
        """Override detected after 2 consecutive mismatches (10s)."""
        agent, player, channel = self._agent(current_track="spotify:track:local")
        agent.current_track_uri = "spotify:track:server"

        # First check — count goes to 1
        agent._last_override_check = 0
        agent._check_user_override()
        assert agent._override_count == 1
        assert agent._sync_paused is False

        # Second check — count goes to 2, override fires
        agent._last_override_check = 0
        agent._check_user_override()
        assert agent._override_count == 2
        assert agent._sync_paused is True

        events = channel.get_events()
        assert any(e.type == "user_override" for e in events)
        assert any(e.type == "status_changed" and e.kwargs.get("status") == "override"
                    for e in events)

    def test_reset_on_match(self):
        """Override count resets when tracks match again."""
        agent, player, channel = self._agent(current_track="spotify:track:local")
        agent.current_track_uri = "spotify:track:server"
        agent._override_count = 1
        agent._last_override_check = 0

        # Change player to match server
        player._current_track = "spotify:track:server"
        agent._check_user_override()
        assert agent._override_count == 0

    def test_skipped_when_get_current_track_returns_none(self):
        """Override detection silently disabled on Windows (returns None)."""
        agent, player, channel = self._agent(current_track=None)
        agent.current_track_uri = "spotify:track:server"
        agent._last_override_check = 0

        agent._check_user_override()
        assert agent._override_count == 0
        assert agent._sync_paused is False

    def test_skipped_without_channel(self):
        """No override detection in CLI mode (no channel)."""
        player = MockPlayer(current_track="spotify:track:local")
        agent = SyncAgent("https://test", "tok", player, drift_threshold=3, channel=None)
        agent.current_track_uri = "spotify:track:server"
        agent._last_override_check = 0

        agent._check_user_override()
        assert agent._override_count == 0

    def test_skipped_without_current_track(self):
        """No override check when no server track is known."""
        agent, player, channel = self._agent(current_track="spotify:track:local")
        agent.current_track_uri = None
        agent._last_override_check = 0

        agent._check_user_override()
        assert agent._override_count == 0

    def test_respects_5s_interval(self):
        """Checks are throttled to every 5 seconds."""
        agent, player, channel = self._agent(current_track="spotify:track:local")
        agent.current_track_uri = "spotify:track:server"

        agent._last_override_check = time.time()  # Just checked
        agent._check_user_override()
        assert agent._override_count == 0  # Skipped due to throttle
