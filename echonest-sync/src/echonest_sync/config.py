"""Config loading with OS-appropriate config dir, keyring integration, and logging setup."""

import logging
import os
import platform
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import yaml


# Legacy config path (Phase 1)
DEFAULT_CONFIG_PATH = Path.home() / ".echonest-sync.yaml"

DEFAULTS = {
    "server": None,
    "token": None,
    "drift_threshold": 3,
    "autostart": False,
    "notifications": True,
}

SERVICE_NAME = "echonest-sync"
KEYRING_USERNAME = "api-token"


# ---------------------------------------------------------------------------
# Config directory
# ---------------------------------------------------------------------------

def get_config_dir() -> Path:
    """OS-appropriate config directory."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:  # Linux / other
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / SERVICE_NAME


# ---------------------------------------------------------------------------
# Keyring (secure token storage)
# ---------------------------------------------------------------------------

def get_token() -> Optional[str]:
    """Read API token from OS keychain. Returns None if not set."""
    try:
        import keyring
        return keyring.get_password(SERVICE_NAME, KEYRING_USERNAME)
    except Exception:
        return None


def set_token(token: str) -> None:
    """Store API token in OS keychain."""
    import keyring
    keyring.set_password(SERVICE_NAME, KEYRING_USERNAME, token)


def delete_token() -> None:
    """Remove API token from OS keychain."""
    try:
        import keyring
        keyring.delete_password(SERVICE_NAME, KEYRING_USERNAME)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config file persistence
# ---------------------------------------------------------------------------

# Keys that must never be written to the config file on disk.
# token lives in the OS keychain; keeping it out of YAML prevents
# Phase 1 → Phase 2 upgrades from leaving credentials in plain text.
_SECRET_KEYS = {"token"}


def save_config(data: dict) -> None:
    """Write/update config.yaml in the config directory.

    Merges *data* into existing config (if any) so callers can
    persist a single key without clobbering the rest.  Secret keys
    (e.g. ``token``) are stripped before writing to ensure credentials
    never persist on disk.
    """
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"

    existing = {}
    if config_file.exists():
        try:
            with open(config_file) as f:
                existing = yaml.safe_load(f) or {}
        except Exception:
            pass

    existing.update(data)

    # Scrub secrets so they never end up on disk
    for key in _SECRET_KEYS:
        existing.pop(key, None)

    with open(config_file, "w") as f:
        yaml.safe_dump(existing, f, default_flow_style=False)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool = False) -> None:
    """Configure rotating file log + console output."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    log_file = config_dir / "sync.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # Rotating file handler (1MB, 3 backups)
    fh = RotatingFileHandler(str(log_file), maxBytes=1_000_000, backupCount=3)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                       datefmt="%H:%M:%S"))
    root.addHandler(ch)


# ---------------------------------------------------------------------------
# Config loading (backward compatible with Phase 1)
# ---------------------------------------------------------------------------

def load_config(config_path=None, cli_overrides=None):
    """Load config with precedence: CLI args > env vars > config file > defaults.

    Config file resolution:
    1. Explicit *config_path* argument
    2. New config dir: ``get_config_dir() / config.yaml``
    3. Legacy path: ``~/.echonest-sync.yaml``
    """
    config = dict(DEFAULTS)

    # Determine config file path
    if config_path:
        path = Path(config_path)
    else:
        new_path = get_config_dir() / "config.yaml"
        if new_path.exists():
            path = new_path
        else:
            path = DEFAULT_CONFIG_PATH

    # 1. Config file
    if path.exists():
        try:
            with open(path) as f:
                file_config = yaml.safe_load(f) or {}
            for key in DEFAULTS:
                if key in file_config:
                    config[key] = file_config[key]
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Failed to read config file %s: %s", path, e)

    # 2. Env var overrides
    env_map = {
        "server": "ECHONEST_SERVER",
        "token": "ECHONEST_TOKEN",
        "drift_threshold": "ECHONEST_DRIFT_THRESHOLD",
    }
    for key, env_var in env_map.items():
        val = os.environ.get(env_var)
        if val is not None:
            if key == "drift_threshold":
                config[key] = int(val)
            else:
                config[key] = val

    # 3. CLI arg overrides
    if cli_overrides:
        for key, val in cli_overrides.items():
            if val is not None:
                config[key] = val

    # 4. If no token from file/env/cli, try keyring
    if not config.get("token"):
        kr_token = get_token()
        if kr_token:
            config["token"] = kr_token

    return config
