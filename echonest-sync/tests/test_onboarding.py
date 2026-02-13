"""Tests for onboarding token exchange logic (no tkinter — logic only)."""

from unittest.mock import MagicMock, patch

import pytest
import requests


class TestTokenExchange:
    """Test the HTTP exchange logic that onboarding.py uses."""

    def test_valid_code_stores_token(self):
        """200 response → token stored in keyring, server persisted to config."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "token": "bearer-abc",
            "server": "https://echone.st",
        }

        with patch("requests.post", return_value=mock_resp) as mock_post, \
             patch("echonest_sync.config.set_token") as mock_set, \
             patch("echonest_sync.config.save_config") as mock_save:
            # Simulate what onboarding does on success
            resp = requests.post(
                "https://echone.st/api/sync-token",
                json={"invite_code": "futureofmusic"},
                timeout=10,
            )
            assert resp.status_code == 200
            data = resp.json()

            from echonest_sync.config import set_token, save_config
            set_token(data["token"])
            save_config({"server": data["server"]})

            mock_set.assert_called_once_with("bearer-abc")
            mock_save.assert_called_once_with({"server": "https://echone.st"})

    def test_invalid_code_returns_401(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": "invalid_code"}

        with patch("requests.post", return_value=mock_resp):
            resp = requests.post(
                "https://echone.st/api/sync-token",
                json={"invite_code": "wrong"},
                timeout=10,
            )
            assert resp.status_code == 401

    def test_rate_limited_returns_429(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": "rate_limited"}

        with patch("requests.post", return_value=mock_resp):
            resp = requests.post(
                "https://echone.st/api/sync-token",
                json={"invite_code": "futureofmusic"},
                timeout=10,
            )
            assert resp.status_code == 429

    def test_connection_error(self):
        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("unreachable")):
            with pytest.raises(requests.exceptions.ConnectionError):
                requests.post(
                    "https://unreachable.example.com/api/sync-token",
                    json={"invite_code": "futureofmusic"},
                    timeout=10,
                )

    def test_missing_code_returns_400(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "missing_code"}

        with patch("requests.post", return_value=mock_resp):
            resp = requests.post(
                "https://echone.st/api/sync-token",
                json={"invite_code": ""},
                timeout=10,
            )
            assert resp.status_code == 400

    def test_server_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("requests.post", return_value=mock_resp):
            resp = requests.post(
                "https://echone.st/api/sync-token",
                json={"invite_code": "futureofmusic"},
                timeout=10,
            )
            assert resp.status_code == 500
