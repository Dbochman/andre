"""Tests for echonest-sync: config, elapsed math, state machine, drift, CLI."""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from echonest_sync.cli import main
from echonest_sync.config import load_config
from echonest_sync.player import SpotifyPlayer
from echonest_sync.sync import SyncAgent, _elapsed_seconds


# ---------------------------------------------------------------------------
# Mock player — records all calls for assertion
# ---------------------------------------------------------------------------

class MockPlayer(SpotifyPlayer):
    def __init__(self, position=0.0, running=True):
        self.calls = []
        self._position = position
        self._running = running

    def play_track(self, uri):
        self.calls.append(("play_track", uri))

    def pause(self):
        self.calls.append(("pause",))

    def resume(self):
        self.calls.append(("resume",))

    def seek_to(self, seconds):
        self.calls.append(("seek_to", seconds))
        self._position = seconds

    def get_position(self):
        self.calls.append(("get_position",))
        return self._position

    def get_current_track(self):
        return None

    def is_running(self):
        return self._running


# ---------------------------------------------------------------------------
# _elapsed_seconds
# ---------------------------------------------------------------------------

class TestElapsedSeconds:
    def test_basic(self):
        assert _elapsed_seconds("2026-02-13T10:00:00", "2026-02-13T10:00:05") == 5.0

    def test_zero(self):
        assert _elapsed_seconds("2026-02-13T10:00:00", "2026-02-13T10:00:00") == 0.0

    def test_negative_clamped(self):
        """If starttime is after now (clock skew?), clamp to 0."""
        assert _elapsed_seconds("2026-02-13T10:00:10", "2026-02-13T10:00:05") == 0

    def test_subsecond(self):
        elapsed = _elapsed_seconds("2026-02-13T10:00:00.000000", "2026-02-13T10:00:00.500000")
        assert abs(elapsed - 0.5) < 0.001

    def test_large_gap(self):
        elapsed = _elapsed_seconds("2026-02-13T10:00:00", "2026-02-13T10:05:00")
        assert elapsed == 300.0


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestConfig:
    @patch("echonest_sync.config.get_token", return_value=None)
    def test_defaults(self, _mock_kr):
        config = load_config(config_path="/nonexistent/path.yaml")
        assert config["server"] is None
        assert config["token"] is None
        assert config["drift_threshold"] == 3

    def test_cli_overrides(self):
        config = load_config(
            config_path="/nonexistent/path.yaml",
            cli_overrides={"server": "https://example.com", "token": "abc", "drift_threshold": 10},
        )
        assert config["server"] == "https://example.com"
        assert config["token"] == "abc"
        assert config["drift_threshold"] == 10

    def test_cli_none_doesnt_override(self):
        """CLI args that are None should not clobber env/file values."""
        with patch.dict(os.environ, {"ECHONEST_SERVER": "https://env.com"}):
            config = load_config(
                config_path="/nonexistent/path.yaml",
                cli_overrides={"server": None, "token": None, "drift_threshold": None},
            )
        assert config["server"] == "https://env.com"

    def test_env_overrides(self):
        env = {
            "ECHONEST_SERVER": "https://env.example.com",
            "ECHONEST_TOKEN": "envtoken",
            "ECHONEST_DRIFT_THRESHOLD": "7",
        }
        with patch.dict(os.environ, env, clear=False):
            config = load_config(config_path="/nonexistent/path.yaml")
        assert config["server"] == "https://env.example.com"
        assert config["token"] == "envtoken"
        assert config["drift_threshold"] == 7

    def test_file_loading(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("server: https://file.com\ntoken: filetoken\ndrift_threshold: 5\n")
        config = load_config(config_path=str(cfg_file))
        assert config["server"] == "https://file.com"
        assert config["token"] == "filetoken"
        assert config["drift_threshold"] == 5

    def test_precedence_cli_over_env(self):
        with patch.dict(os.environ, {"ECHONEST_SERVER": "https://env.com"}):
            config = load_config(
                config_path="/nonexistent/path.yaml",
                cli_overrides={"server": "https://cli.com", "token": None, "drift_threshold": None},
            )
        assert config["server"] == "https://cli.com"

    def test_precedence_env_over_file(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("server: https://file.com\ntoken: filetoken\n")
        with patch.dict(os.environ, {"ECHONEST_SERVER": "https://env.com"}):
            config = load_config(config_path=str(cfg_file))
        assert config["server"] == "https://env.com"
        assert config["token"] == "filetoken"  # file value kept when no env override

    def test_bad_config_file_doesnt_crash(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(": bad: yaml: [[")
        config = load_config(config_path=str(cfg_file))
        assert config["server"] is None  # falls back to defaults


# ---------------------------------------------------------------------------
# SyncAgent state machine — now_playing
# ---------------------------------------------------------------------------

class TestHandleNowPlaying:
    def _agent(self, **kw):
        player = kw.pop("player", MockPlayer())
        return SyncAgent("https://test", "tok", player, drift_threshold=3), player

    def test_new_spotify_track(self):
        agent, player = self._agent()
        agent._handle_now_playing({
            "trackid": "abc123",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:00",
        })
        assert agent.current_track_uri == "spotify:track:abc123"
        assert ("play_track", "spotify:track:abc123") in player.calls

    @patch("echonest_sync.sync.time.sleep")  # skip the 0.5s delay
    def test_new_track_seeks_when_elapsed(self, mock_sleep):
        agent, player = self._agent()
        agent._handle_now_playing({
            "trackid": "abc123",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:30",
        })
        assert ("play_track", "spotify:track:abc123") in player.calls
        assert ("seek_to", 30.0) in player.calls

    def test_no_seek_when_elapsed_under_1s(self):
        agent, player = self._agent()
        agent._handle_now_playing({
            "trackid": "abc123",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:00.500000",
        })
        assert ("play_track", "spotify:track:abc123") in player.calls
        seek_calls = [c for c in player.calls if c[0] == "seek_to"]
        assert len(seek_calls) == 0

    def test_same_track_no_replay(self):
        agent, player = self._agent()
        data = {
            "trackid": "abc123",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:00",
        }
        agent._handle_now_playing(data)
        player.calls.clear()
        agent._handle_now_playing(data)
        play_calls = [c for c in player.calls if c[0] == "play_track"]
        assert len(play_calls) == 0

    def test_non_spotify_track_skipped(self):
        agent, player = self._agent()
        agent._handle_now_playing({
            "trackid": "sc123",
            "src": "soundcloud",
            "starttime": "",
            "now": "",
        })
        assert agent.current_track_uri is None
        assert agent.current_src == "soundcloud"
        assert len(player.calls) == 0

    def test_empty_trackid(self):
        agent, player = self._agent()
        agent._handle_now_playing({"trackid": "", "src": "spotify"})
        assert agent.current_track_uri is None
        assert len(player.calls) == 0

    def test_pause(self):
        agent, player = self._agent()
        # New track arriving paused should NOT start playback
        agent._handle_now_playing({
            "trackid": "abc123",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:00",
            "paused": True,
        })
        assert agent.paused is True
        # Should not play or pause — just record state
        play_calls = [c for c in player.calls if c[0] == "play_track"]
        pause_calls = [c for c in player.calls if c[0] == "pause"]
        assert len(play_calls) == 0
        assert len(pause_calls) == 0

    def test_resume(self):
        agent, player = self._agent()
        agent.current_track_uri = "spotify:track:abc123"
        agent.paused = True
        agent._handle_now_playing({
            "trackid": "abc123",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:30",
            "paused": False,
        })
        assert agent.paused is False
        assert ("resume",) in player.calls
        assert ("seek_to", 30.0) in player.calls

    def test_already_paused_no_double_pause(self):
        agent, player = self._agent()
        agent.current_track_uri = "spotify:track:abc123"
        agent.paused = True
        agent._handle_now_playing({
            "trackid": "abc123",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:00",
            "paused": True,
        })
        pause_calls = [c for c in player.calls if c[0] == "pause"]
        assert len(pause_calls) == 0

    def test_track_change_clears_pause_state(self):
        """When a new track starts (not paused), paused state should be False."""
        agent, player = self._agent()
        agent.paused = True
        agent.current_track_uri = "spotify:track:old"
        agent._handle_now_playing({
            "trackid": "new",
            "src": "spotify",
            "starttime": "2026-02-13T10:00:00",
            "now": "2026-02-13T10:00:00",
            "paused": False,
        })
        assert agent.current_track_uri == "spotify:track:new"
        assert ("play_track", "spotify:track:new") in player.calls
        assert agent.paused is False


# ---------------------------------------------------------------------------
# SyncAgent state machine — player_position (drift correction)
# ---------------------------------------------------------------------------

class TestHandlePlayerPosition:
    def test_drift_correction(self):
        player = MockPlayer(position=10.0)
        agent = SyncAgent("https://test", "tok", player, drift_threshold=3)
        agent.current_track_uri = "spotify:track:abc123"
        agent.current_src = "spotify"

        agent._handle_player_position({"src": "spotify", "trackid": "abc123", "pos": 20})
        assert ("seek_to", 20) in player.calls

    def test_no_correction_within_threshold(self):
        player = MockPlayer(position=18.0)
        agent = SyncAgent("https://test", "tok", player, drift_threshold=3)
        agent.current_track_uri = "spotify:track:abc123"
        agent.current_src = "spotify"

        agent._handle_player_position({"src": "spotify", "trackid": "abc123", "pos": 20})
        seek_calls = [c for c in player.calls if c[0] == "seek_to"]
        assert len(seek_calls) == 0

    def test_no_correction_without_current_track(self):
        player = MockPlayer(position=10.0)
        agent = SyncAgent("https://test", "tok", player, drift_threshold=3)

        agent._handle_player_position({"src": "spotify", "trackid": "abc123", "pos": 20})
        seek_calls = [c for c in player.calls if c[0] == "seek_to"]
        assert len(seek_calls) == 0

    def test_non_spotify_ignored(self):
        player = MockPlayer(position=10.0)
        agent = SyncAgent("https://test", "tok", player, drift_threshold=3)
        agent.current_track_uri = "spotify:track:abc123"

        agent._handle_player_position({"src": "soundcloud", "trackid": "sc1", "pos": 20})
        seek_calls = [c for c in player.calls if c[0] == "seek_to"]
        assert len(seek_calls) == 0

    def test_get_position_returns_none(self):
        """If player can't report position (e.g. Windows), skip correction."""
        player = MockPlayer(position=10.0)
        player.get_position = lambda: None  # override
        agent = SyncAgent("https://test", "tok", player, drift_threshold=3)
        agent.current_track_uri = "spotify:track:abc123"

        agent._handle_player_position({"src": "spotify", "trackid": "abc123", "pos": 20})
        # No crash, no seek

    def test_exact_threshold_boundary(self):
        """Drift exactly equal to threshold should NOT trigger correction."""
        player = MockPlayer(position=17.0)
        agent = SyncAgent("https://test", "tok", player, drift_threshold=3)
        agent.current_track_uri = "spotify:track:abc123"

        agent._handle_player_position({"src": "spotify", "trackid": "abc123", "pos": 20})
        seek_calls = [c for c in player.calls if c[0] == "seek_to"]
        assert len(seek_calls) == 0

    def test_just_over_threshold(self):
        """Drift just over threshold should trigger correction."""
        player = MockPlayer(position=16.9)
        agent = SyncAgent("https://test", "tok", player, drift_threshold=3)
        agent.current_track_uri = "spotify:track:abc123"

        agent._handle_player_position({"src": "spotify", "trackid": "abc123", "pos": 20})
        assert ("seek_to", 20) in player.calls


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Sync your local Spotify" in result.output

    @patch("echonest_sync.config.get_token", return_value=None)
    @patch("echonest_sync.config.get_config_dir", return_value=Path("/nonexistent"))
    def test_missing_server(self, _d, _t):
        runner = CliRunner()
        result = runner.invoke(main, ["--token", "abc"])
        assert result.exit_code == 1

    @patch("echonest_sync.config.get_token", return_value=None)
    @patch("echonest_sync.config.get_config_dir", return_value=Path("/nonexistent"))
    def test_missing_token(self, _d, _t):
        runner = CliRunner()
        result = runner.invoke(main, ["--server", "https://example.com"])
        assert result.exit_code == 1

    def test_config_file_loading(self, tmp_path):
        cfg = tmp_path / "test.yaml"
        cfg.write_text("server: https://test.com\ntoken: testtoken\n")
        runner = CliRunner()
        # Patch create_player and SyncAgent.run to avoid actual execution
        with patch("echonest_sync.cli.create_player") as mock_cp, \
             patch("echonest_sync.cli.SyncAgent") as mock_sa:
            mock_player = MockPlayer()
            mock_cp.return_value = mock_player
            mock_sa.return_value.run.return_value = None
            result = runner.invoke(main, ["-c", str(cfg)])
        assert result.exit_code == 0
        mock_sa.assert_called_once()
        call_kwargs = mock_sa.call_args
        assert call_kwargs.kwargs["server"] == "https://test.com"
        assert call_kwargs.kwargs["token"] == "testtoken"
