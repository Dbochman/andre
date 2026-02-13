"""Tests for config directory, keyring, and config persistence."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from echonest_sync.config import (
    get_config_dir,
    get_token,
    load_config,
    save_config,
    set_token,
    delete_token,
)


class TestGetConfigDir:
    @patch("echonest_sync.config.platform.system", return_value="Darwin")
    def test_macos(self, _):
        d = get_config_dir()
        assert "Library/Application Support/echonest-sync" in str(d)

    @patch("echonest_sync.config.platform.system", return_value="Windows")
    @patch.dict(os.environ, {"APPDATA": "/Users/test/AppData/Roaming"})
    def test_windows(self, _):
        d = get_config_dir()
        assert "AppData/Roaming/echonest-sync" in str(d)

    @patch("echonest_sync.config.platform.system", return_value="Linux")
    def test_linux_default(self, _):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_CONFIG_HOME", None)
            d = get_config_dir()
        assert ".config/echonest-sync" in str(d)

    @patch("echonest_sync.config.platform.system", return_value="Linux")
    @patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom/config"})
    def test_linux_xdg(self, _):
        d = get_config_dir()
        assert str(d) == "/custom/config/echonest-sync"


class TestKeyring:
    def test_get_token_roundtrip(self):
        """get_token returns value set by set_token (mocked keyring)."""
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "mytoken"
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            # Force re-import of keyring inside the function
            result = get_token()
        assert result == "mytoken"

    def test_get_token_returns_none_on_error(self):
        """get_token returns None if keyring raises."""
        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = Exception("no keyring")
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            result = get_token()
        assert result is None

    def test_delete_token_no_crash(self):
        """delete_token should not crash even if keyring errors."""
        mock_kr = MagicMock()
        mock_kr.delete_password.side_effect = Exception("not found")
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            delete_token()  # Should not raise


class TestSaveConfig:
    def test_creates_config_file(self, tmp_path):
        with patch("echonest_sync.config.get_config_dir", return_value=tmp_path):
            save_config({"server": "https://test.com"})
            config_file = tmp_path / "config.yaml"
            assert config_file.exists()
            content = config_file.read_text()
            assert "https://test.com" in content

    def test_merges_existing_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("server: https://old.com\nautostart: true\n")
        with patch("echonest_sync.config.get_config_dir", return_value=tmp_path):
            save_config({"server": "https://new.com"})
            import yaml
            with open(config_file) as f:
                data = yaml.safe_load(f)
            assert data["server"] == "https://new.com"
            assert data["autostart"] is True  # Preserved

    def test_strips_secrets_from_disk(self, tmp_path):
        """Token should never be written to config file on disk."""
        config_file = tmp_path / "config.yaml"
        # Simulate a Phase 1 config that had token in the file
        config_file.write_text("server: https://old.com\ntoken: leaked-secret\n")
        with patch("echonest_sync.config.get_config_dir", return_value=tmp_path):
            save_config({"server": "https://new.com"})
            import yaml
            with open(config_file) as f:
                data = yaml.safe_load(f)
            assert "token" not in data
            assert data["server"] == "https://new.com"

    def test_strips_secrets_from_new_data(self, tmp_path):
        """Even if caller passes token in data dict, it gets stripped."""
        with patch("echonest_sync.config.get_config_dir", return_value=tmp_path):
            save_config({"server": "https://test.com", "token": "should-not-persist"})
            import yaml
            config_file = tmp_path / "config.yaml"
            with open(config_file) as f:
                data = yaml.safe_load(f)
            assert "token" not in data


class TestLoadConfigWithNewDir:
    def test_prefers_new_config_dir(self, tmp_path):
        """New config dir takes precedence over legacy path."""
        new_config = tmp_path / "config.yaml"
        new_config.write_text("server: https://new.com\ntoken: newtoken\n")

        with patch("echonest_sync.config.get_config_dir", return_value=tmp_path), \
             patch("echonest_sync.config.get_token", return_value=None):
            config = load_config()
        assert config["server"] == "https://new.com"
        assert config["token"] == "newtoken"

    def test_falls_back_to_legacy(self, tmp_path):
        """Falls back to ~/.echonest-sync.yaml if new dir doesn't exist."""
        legacy = tmp_path / "legacy.yaml"
        legacy.write_text("server: https://legacy.com\ntoken: legtoken\n")
        empty_dir = tmp_path / "empty"

        with patch("echonest_sync.config.get_config_dir", return_value=empty_dir), \
             patch("echonest_sync.config.DEFAULT_CONFIG_PATH", legacy), \
             patch("echonest_sync.config.get_token", return_value=None):
            config = load_config()
        assert config["server"] == "https://legacy.com"

    def test_keyring_fallback_for_token(self, tmp_path):
        """If no token in file/env/cli, fall back to keyring."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("server: https://test.com\n")

        with patch("echonest_sync.config.get_config_dir", return_value=tmp_path), \
             patch("echonest_sync.config.get_token", return_value="kr-token"):
            config = load_config()
        assert config["token"] == "kr-token"
