"""Build a macOS .pkg installer from the .app bundle.

The .pkg installer copies the app to /Applications and runs a postinstall
script that strips the quarantine attribute, so unsigned apps open without
Gatekeeper blocking them.

Usage:
    cd echonest-sync
    python build/macos/build_app.py   # build the .app first
    python build/macos/build_pkg.py   # then wrap it in a .pkg

Produces: dist/EchoNest-Sync.pkg
"""

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(ROOT, "dist")
APP_PATH = os.path.join(DIST_DIR, "EchoNest Sync.app")
PKG_PATH = os.path.join(DIST_DIR, "EchoNest-Sync.pkg")
IDENTIFIER = "st.echone.sync"
VERSION = "0.2.0"


def build_pkg():
    if not os.path.isdir(APP_PATH):
        print(f"Error: {APP_PATH} not found. Run build_app.py first.", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        # 1. Create payload root: the app goes into Applications/
        payload = os.path.join(tmp, "payload")
        apps_dir = os.path.join(payload, "Applications")
        os.makedirs(apps_dir)
        shutil.copytree(APP_PATH, os.path.join(apps_dir, "EchoNest Sync.app"),
                        symlinks=True)

        # 2. Create scripts directory with postinstall
        scripts_dir = os.path.join(tmp, "scripts")
        os.makedirs(scripts_dir)
        postinstall_src = os.path.join(BUILD_DIR, "postinstall")
        postinstall_dst = os.path.join(scripts_dir, "postinstall")
        shutil.copy2(postinstall_src, postinstall_dst)
        os.chmod(postinstall_dst, 0o755)

        # 3. Build the component .pkg
        component_pkg = os.path.join(tmp, "component.pkg")
        subprocess.check_call([
            "pkgbuild",
            "--root", payload,
            "--scripts", scripts_dir,
            "--identifier", IDENTIFIER,
            "--version", VERSION,
            "--install-location", "/",
            component_pkg,
        ])

        # 4. Build the distribution .pkg (adds the installer UI)
        dist_xml = os.path.join(tmp, "distribution.xml")
        subprocess.check_call([
            "productbuild",
            "--synthesize",
            "--package", component_pkg,
            dist_xml,
        ])

        # Patch distribution.xml to add title and welcome
        _patch_distribution(dist_xml)

        subprocess.check_call([
            "productbuild",
            "--distribution", dist_xml,
            "--package-path", tmp,
            PKG_PATH,
        ])

    print(f"\nInstaller built: {PKG_PATH}")
    print(f"Size: {os.path.getsize(PKG_PATH) / 1024 / 1024:.1f} MB")


def _patch_distribution(dist_xml):
    """Add a title to the distribution XML so the installer shows a name."""
    with open(dist_xml, "r") as f:
        content = f.read()

    # Add title after the opening <installer-gui-script> tag
    content = content.replace(
        '<installer-gui-script',
        '<installer-gui-script',
        1,
    )
    # Insert title element
    content = content.replace(
        '</installer-gui-script>',
        '    <title>EchoNest Sync</title>\n</installer-gui-script>',
    )

    with open(dist_xml, "w") as f:
        f.write(content)


if __name__ == "__main__":
    build_pkg()
