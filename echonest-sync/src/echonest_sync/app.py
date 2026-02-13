"""Desktop launcher: keyring check -> onboarding -> tray app."""

import logging
import os
import platform
import subprocess
import sys
import threading

from .config import get_token, load_config, setup_logging
from .ipc import SyncChannel
from .player import create_player
from .sync import SyncAgent

log = logging.getLogger(__name__)


def _run_onboarding(server=None):
    """Spawn onboarding dialog as subprocess. Returns True on success."""
    cmd = [sys.executable, "-m", "echonest_sync.onboarding"]
    if server:
        cmd.extend(["--server", server])
    result = subprocess.run(cmd)
    return result.returncode == 0


def _restart():
    """Re-launch this process (used by 'Forget Server')."""
    os.execv(sys.executable, [sys.executable, "-m", "echonest_sync.app"])


def main():
    setup_logging(verbose=os.environ.get("ECHONEST_VERBOSE", "").lower() in ("1", "true"))
    log.info("echonest-sync desktop app starting")

    # Load config early so we can pick up a non-default server URL
    # (from config file or ECHONEST_SERVER env var) before onboarding.
    # This lets dev/staging installs point at the right server.
    config = load_config()
    server_hint = config.get("server")

    # Check for token
    token = get_token()
    if not token:
        log.info("No token found — launching onboarding")
        if not _run_onboarding(server=server_hint):
            log.info("Onboarding cancelled")
            sys.exit(0)
        token = get_token()
        if not token:
            log.error("No token after onboarding — exiting")
            sys.exit(1)

    # Reload config (onboarding may have persisted server URL)
    config = load_config()
    server = config.get("server")
    if not server:
        log.error("No server URL configured — re-run onboarding")
        if not _run_onboarding(server=server_hint):
            sys.exit(0)
        config = load_config()
        server = config.get("server")
        if not server:
            log.error("Still no server URL — exiting")
            sys.exit(1)
        token = get_token() or token

    # Create IPC channel
    channel = SyncChannel()

    # Create player
    player = create_player()

    # Start sync engine in background thread
    agent = SyncAgent(
        server=server,
        token=token,
        player=player,
        drift_threshold=config.get("drift_threshold", 3),
        channel=channel,
    )
    engine_thread = threading.Thread(target=agent.run, daemon=True, name="sync-engine")
    engine_thread.start()
    log.info("Sync engine started (server=%s)", server)

    # Start tray app on main thread
    system = platform.system()
    if system == "Darwin":
        from .tray_mac import EchoNestSync
        app = EchoNestSync(channel, restart_callback=_restart)
        app.run()
    elif system == "Windows":
        from .tray_win import EchoNestSyncTray
        app = EchoNestSyncTray(channel, restart_callback=_restart)
        app.run()
    else:
        log.warning("No tray app for %s — running engine only (Ctrl+C to stop)", system)
        try:
            engine_thread.join()
        except KeyboardInterrupt:
            channel.send_command("quit")
            log.info("Stopped")


if __name__ == "__main__":
    main()
