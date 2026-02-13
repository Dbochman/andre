"""Tests for snooze/pause functionality in SyncAgent."""

import time
from unittest.mock import patch

from echonest_sync.ipc import SyncChannel
from echonest_sync.player import SpotifyPlayer
from echonest_sync.sync import SyncAgent


class MockPlayer(SpotifyPlayer):
    def __init__(self):
        self.calls = []

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
        return None

    def is_running(self):
        return True


class TestSnooze:
    def _agent(self):
        player = MockPlayer()
        channel = SyncChannel()
        agent = SyncAgent("https://test", "tok", player,
                          drift_threshold=3, channel=channel)
        return agent, player, channel

    def test_snooze_pauses_sync(self):
        agent, player, channel = self._agent()
        channel.send_command("snooze", duration=900)
        agent._process_commands()
        assert agent._sync_paused is True
        assert agent._snoozed_until > time.time()

    def test_snooze_skips_player_calls(self):
        agent, player, channel = self._agent()
        channel.send_command("snooze", duration=900)
        agent._process_commands()

        agent._handle_now_playing({
            "trackid": "abc123",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:00",
        })
        # Track URI should be updated (awareness) but no play_track call
        assert agent.current_track_uri == "spotify:track:abc123"
        play_calls = [c for c in player.calls if c[0] == "play_track"]
        assert len(play_calls) == 0

    def test_snooze_expiry_resumes(self):
        agent, player, channel = self._agent()
        # Set snooze to already expired
        agent._snoozed_until = time.time() - 1
        agent._sync_paused = True

        with patch.object(agent, "_initial_sync"):
            assert agent._is_sync_active() is True
        assert agent._sync_paused is False
        assert agent._snoozed_until == 0

    def test_resume_cancels_snooze(self):
        agent, player, channel = self._agent()
        channel.send_command("snooze", duration=900)
        agent._process_commands()
        assert agent._sync_paused is True

        with patch.object(agent, "_initial_sync"):
            channel.send_command("resume")
            agent._process_commands()
        assert agent._sync_paused is False
        assert agent._snoozed_until == 0

    def test_pause_and_resume(self):
        agent, player, channel = self._agent()
        channel.send_command("pause")
        agent._process_commands()
        assert agent._sync_paused is True

        with patch.object(agent, "_initial_sync"):
            channel.send_command("resume")
            agent._process_commands()
        assert agent._sync_paused is False

    def test_snooze_emits_events(self):
        agent, player, channel = self._agent()
        channel.send_command("snooze", duration=900)
        agent._process_commands()

        events = channel.get_events()
        assert any(e.type == "status_changed" and e.kwargs.get("status") == "snoozed"
                    for e in events)
