"""Tests for autostart (LaunchAgent / Startup folder)."""

import sys
from pathlib import Path
from unittest.mock import patch

from echonest_sync.autostart import (
    LABEL,
    _plist_path,
    disable_autostart,
    enable_autostart,
    is_autostart_enabled,
)


class TestMacOSAutostart:
    def test_plist_written(self, tmp_path):
        plist = tmp_path / f"{LABEL}.plist"
        with patch("echonest_sync.autostart._plist_path", return_value=plist), \
             patch("echonest_sync.autostart.platform.system", return_value="Darwin"):
            enable_autostart()
            assert plist.exists()
            content = plist.read_text()
            assert LABEL in content
            assert "RunAtLoad" in content
            assert sys.executable in content

    def test_plist_removed(self, tmp_path):
        plist = tmp_path / f"{LABEL}.plist"
        plist.write_text("<plist>test</plist>")
        with patch("echonest_sync.autostart._plist_path", return_value=plist), \
             patch("echonest_sync.autostart.platform.system", return_value="Darwin"):
            disable_autostart()
            assert not plist.exists()

    def test_is_enabled(self, tmp_path):
        plist = tmp_path / f"{LABEL}.plist"
        with patch("echonest_sync.autostart._plist_path", return_value=plist), \
             patch("echonest_sync.autostart.platform.system", return_value="Darwin"):
            assert is_autostart_enabled() is False
            plist.write_text("<plist>test</plist>")
            assert is_autostart_enabled() is True

    def test_disable_noop_when_not_exists(self, tmp_path):
        plist = tmp_path / f"{LABEL}.plist"
        with patch("echonest_sync.autostart._plist_path", return_value=plist), \
             patch("echonest_sync.autostart.platform.system", return_value="Darwin"):
            # Should not raise
            disable_autostart()


class TestUnsupportedPlatform:
    def test_enable_noop_on_linux(self):
        with patch("echonest_sync.autostart.platform.system", return_value="Linux"):
            # Should not raise, just log warning
            enable_autostart()

    def test_is_enabled_false_on_linux(self):
        with patch("echonest_sync.autostart.platform.system", return_value="Linux"):
            assert is_autostart_enabled() is False
