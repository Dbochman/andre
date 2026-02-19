"""PyInstaller build script for macOS .app bundle.

Usage:
    cd echonest-sync
    pip install pyinstaller
    python build/macos/build_app.py [--adhoc]

Produces: dist/EchoNest Sync.app

By default, signs with Developer ID and submits for notarization.
Pass --adhoc to skip notarization and use ad-hoc signing (local dev).

Notarization requires stored credentials:
    xcrun notarytool store-credentials "EchoNest-Notarize" \\
        --apple-id "dylanbochman@gmail.com" --team-id "D5VFBW83BT"
"""

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_DIR = os.path.dirname(os.path.abspath(__file__))

DEVELOPER_ID = "Developer ID Application: Dylan Bochman (D5VFBW83BT)"
NOTARIZE_PROFILE = "EchoNest-Notarize"


def _is_macho_binary(path):
    """Check if a file is a Mach-O binary (executable, dylib, or bundle)."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        # Mach-O magic numbers (32/64-bit, both endians) and fat binaries
        return magic in (
            b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",  # MH_MAGIC, MH_MAGIC_64
            b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",  # MH_CIGAM, MH_CIGAM_64
            b"\xca\xfe\xba\xbe",                         # FAT_MAGIC
        )
    except (IOError, OSError):
        return False


def _codesign(path, identity, entitlements=None):
    """Sign a path with the given identity."""
    cmd = [
        "codesign", "--force", "--options", "runtime",
        "--sign", identity,
        "--timestamp",
    ]
    if entitlements:
        cmd += ["--entitlements", entitlements]
    cmd.append(path)
    # Show path relative to the .app for readability
    rel = path
    idx = path.find(".app/")
    if idx >= 0:
        rel = path[idx:]
    print(f"  Signing: {rel}")
    subprocess.check_call(cmd)


def _sign_app(app_path, identity):
    """Sign the .app bundle with hardened runtime.

    Recursively finds and signs ALL Mach-O binaries (dylibs, .so, .framework,
    executables) inside the bundle — deepest first so nested code is signed
    before its parent container.
    """
    entitlements = os.path.join(BUILD_DIR, "entitlements.plist")
    ent_arg = entitlements if os.path.exists(entitlements) else None

    contents_dir = os.path.join(app_path, "Contents")

    # Collect all signable paths: Mach-O files + .framework bundles
    signable = []
    for dirpath, dirnames, filenames in os.walk(contents_dir):
        # Collect .framework directories (sign as bundles, don't descend)
        frameworks_to_remove = []
        for d in dirnames:
            if d.endswith(".framework"):
                signable.append(os.path.join(dirpath, d))
                frameworks_to_remove.append(d)
        # Don't descend into .framework dirs (they get signed as a unit)
        for fw in frameworks_to_remove:
            dirnames.remove(fw)

        for f in filenames:
            fpath = os.path.join(dirpath, f)
            if os.path.islink(fpath):
                continue
            if f.endswith((".dylib", ".so")):
                signable.append(fpath)
            elif _is_macho_binary(fpath):
                signable.append(fpath)

    # Sort deepest paths first so inner binaries are signed before outer ones
    signable.sort(key=lambda p: p.count(os.sep), reverse=True)

    print(f"  Found {len(signable)} binaries to sign")
    for path in signable:
        _codesign(path, identity, ent_arg)

    # Finally sign the .app bundle itself
    _codesign(app_path, identity, ent_arg)


def _notarize(path):
    """Submit a file for notarization and wait for completion."""
    print(f"\nSubmitting for notarization: {os.path.basename(path)}")
    result = subprocess.run([
        "xcrun", "notarytool", "submit", path,
        "--keychain-profile", NOTARIZE_PROFILE,
        "--wait",
    ], capture_output=True, text=True, timeout=600)

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    # Extract submission ID for log retrieval
    sub_id = None
    for line in result.stdout.splitlines():
        if line.strip().startswith("id:"):
            sub_id = line.split(":", 1)[-1].strip()
            break

    # Check both return code AND status text (notarytool returns 0 for Invalid)
    failed = result.returncode != 0 or "status: Invalid" in result.stdout
    if failed:
        print("\nNotarization FAILED.")
        if sub_id:
            print("View detailed log with:")
            print(f"  xcrun notarytool log {sub_id} "
                  f"--keychain-profile {NOTARIZE_PROFILE}")
        sys.exit(1)

    print("Notarization succeeded.")


def _staple(path):
    """Staple the notarization ticket to the artifact."""
    print(f"Stapling ticket to: {os.path.basename(path)}")
    subprocess.check_call(["xcrun", "stapler", "staple", path])


def build():
    adhoc = "--adhoc" in sys.argv

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "EchoNest Sync",
        "--windowed",                    # .app bundle, no console
        "--onedir",                      # directory bundle (smaller, faster startup)
        "--noconfirm",                   # overwrite without asking

        # macOS-specific
        "--osx-bundle-identifier", "st.echone.sync",

        # App icon
        "--icon", os.path.join(ROOT, "resources", "icon.icns"),

        # Resources
        "--add-data", os.path.join(ROOT, "resources") + ":resources",

        # Hidden imports that PyInstaller may miss
        "--hidden-import", "rumps",
        "--hidden-import", "keyring.backends.macOS",
        "--hidden-import", "keyring.backends.SecretService",

        # Hidden imports for the app modules (relative imports in the package)
        "--hidden-import", "echonest_sync.config",
        "--hidden-import", "echonest_sync.ipc",
        "--hidden-import", "echonest_sync.player",
        "--hidden-import", "echonest_sync.sync",
        "--hidden-import", "echonest_sync.app",
        "--hidden-import", "echonest_sync.tray_mac",
        "--hidden-import", "echonest_sync.onboarding",
        "--hidden-import", "echonest_sync.autostart",
        "--hidden-import", "echonest_sync.link",
        "--hidden-import", "echonest_sync.search",
        "--hidden-import", "echonest_sync.audio",
        "--hidden-import", "echonest_sync.miniplayer",
        "--hidden-import", "echonest_sync.updater",
        "--hidden-import", "echonest_sync.cli",

        # Entry point (uses absolute imports, not relative)
        os.path.join(ROOT, "src", "echonest_sync", "__main__.py"),
    ]

    print("Building macOS .app bundle...")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    # Replace PyInstaller's generated Info.plist with our custom one
    app_path = os.path.join(ROOT, "dist", "EchoNest Sync.app")
    app_plist = os.path.join(app_path, "Contents", "Info.plist")
    custom_plist = os.path.join(BUILD_DIR, "Info.plist")
    if os.path.exists(custom_plist):
        print(f"Replacing Info.plist with {custom_plist}")
        shutil.copy2(custom_plist, app_plist)

    if adhoc:
        # Ad-hoc signing for local dev/testing
        print("\nAd-hoc signing .app bundle...")
        subprocess.check_call([
            "codesign", "--force", "--deep", "--sign", "-", app_path,
        ])
        print("\nBuild complete (ad-hoc signed): dist/EchoNest Sync.app")
    else:
        # Developer ID signing with hardened runtime
        print(f"\nSigning with: {DEVELOPER_ID}")
        _sign_app(app_path, DEVELOPER_ID)

        # Verify signature
        print("\nVerifying signature...")
        subprocess.check_call([
            "codesign", "--verify", "--deep", "--strict", "--verbose=2",
            app_path,
        ])

        # Notarize
        # Create a zip for notarization (notarytool requires zip or dmg)
        zip_path = os.path.join(ROOT, "dist", "EchoNest-Sync-notarize.zip")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        print("\nCreating zip for notarization...")
        subprocess.check_call([
            "ditto", "-c", "-k", "--keepParent", app_path, zip_path,
        ])

        _notarize(zip_path)
        _staple(app_path)

        # Clean up the notarization zip
        os.remove(zip_path)

        print(f"\nBuild complete (signed + notarized): dist/EchoNest Sync.app")

    print("\nTo create a DMG:")
    print("  python build/macos/build_dmg.py")


if __name__ == "__main__":
    build()
