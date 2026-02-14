"""Desktop launcher: keyring check -> onboarding -> tray app."""

import logging
import os
import platform
import sys
import threading

from .config import get_token, load_config, setup_logging
from .ipc import SyncChannel
from .player import create_player
from .sync import SyncAgent

log = logging.getLogger(__name__)


def _run_onboarding(server=None):
    """Run onboarding dialog. Returns True on success."""
    from .onboarding import OnboardingDialog, DEFAULT_SERVER
    dialog = OnboardingDialog(server=server or DEFAULT_SERVER)
    return dialog.run()


def main():
    setup_logging(verbose=os.environ.get("ECHONEST_VERBOSE", "").lower() in ("1", "true"))

    # Handle --search subprocess invocation (frozen builds re-invoke the
    # binary with this flag to show the search dialog in its own process,
    # avoiding the tkinter + rumps segfault on macOS).
    if "--search" in sys.argv:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--search", action="store_true")
        parser.add_argument("--server", required=True)
        parser.add_argument("--token", required=True)
        args = parser.parse_args()
        from .search import SearchDialog
        SearchDialog(args.server, args.token).show()
        return

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

    # Check for linked account email
    linked_email = config.get("email")
    if linked_email:
        log.info("Account linked as %s", linked_email)

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
        # Hide dock icon (agent/accessory app) and set app icon for dialogs
        try:
            from AppKit import NSApplication, NSImage
            from AppKit import NSApplicationActivationPolicyAccessory
            ns_app = NSApplication.sharedApplication()
            ns_app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            from .tray_mac import _resource_path
            icon_path = _resource_path("icon_app.png")
            ns_image = NSImage.alloc().initWithContentsOfFile_(icon_path)
            if ns_image:
                ns_app.setApplicationIconImage_(ns_image)
        except Exception:
            pass
        from .tray_mac import EchoNestSync
        app = EchoNestSync(channel, server=server, token=token, email=linked_email)
        app.run()
    else:
        # Windows and Linux both use pystray
        from .tray_win import EchoNestSyncTray
        app = EchoNestSyncTray(channel, server=server, token=token, email=linked_email)
        app.run()


if __name__ == "__main__":
    main()
