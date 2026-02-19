"""Build a styled DMG installer for EchoNest Sync.

Usage:
    cd echonest-sync
    python build/macos/build_dmg.py [--adhoc]

Requires: dist/EchoNest Sync.app (run build_app.py first)
Produces: dist/EchoNest-Sync.dmg

By default, signs the DMG with Developer ID and submits for notarization.
Pass --adhoc to skip signing/notarization (local dev).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

NOTARIZE_PROFILE = "EchoNest-Notarize"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST = os.path.join(ROOT, "dist")
APP_NAME = "EchoNest Sync"
APP_PATH = os.path.join(DIST, f"{APP_NAME}.app")
DMG_NAME = "EchoNest-Sync"
DMG_PATH = os.path.join(DIST, f"{DMG_NAME}.dmg")
VOL_NAME = "EchoNest Sync"
ICON_PATH = os.path.join(ROOT, "resources", "icon.icns")

# DMG window dimensions
WIN_W, WIN_H = 600, 400
ICON_SIZE = 128
APP_X, APP_Y = 170, 190
APPS_X, APPS_Y = 430, 190


def _make_background(path, width=WIN_W, height=WIN_H):
    """Generate a simple background image with an arrow using Quartz (CoreGraphics)."""
    try:
        import Quartz
        from Quartz import (
            CGColorSpaceCreateDeviceRGB,
            CGBitmapContextCreate,
            CGContextSetRGBFillColor,
            CGContextFillRect,
            CGContextSetRGBStrokeColor,
            CGContextSetLineWidth,
            CGContextMoveToPoint,
            CGContextAddLineToPoint,
            CGContextStrokePath,
            CGImageDestinationCreateWithURL,
            CGBitmapContextCreateImage,
            CGImageDestinationAddImage,
            CGImageDestinationFinalize,
            kCGImageAlphaPremultipliedLast,
        )
        from CoreFoundation import CFURLCreateWithFileSystemPath, kCFURLPOSIXPathStyle

        cs = CGColorSpaceCreateDeviceRGB()
        ctx = CGBitmapContextCreate(None, width, height, 8, 0, cs, kCGImageAlphaPremultipliedLast)

        # Light background (#f0f0f0)
        CGContextSetRGBFillColor(ctx, 0xf0 / 255, 0xf0 / 255, 0xf0 / 255, 1.0)
        CGContextFillRect(ctx, ((0, 0), (width, height)))

        # Arrow from app icon to Applications folder
        arrow_y = height - (APP_Y + ICON_SIZE // 2)  # flip y (CG origin is bottom-left)
        ax1 = APP_X + ICON_SIZE // 2 + 30
        ax2 = APPS_X - ICON_SIZE // 2 - 30
        CGContextSetRGBStrokeColor(ctx, 0.45, 0.45, 0.45, 0.8)
        CGContextSetLineWidth(ctx, 3.0)
        CGContextMoveToPoint(ctx, ax1, arrow_y)
        CGContextAddLineToPoint(ctx, ax2, arrow_y)
        # Arrowhead
        CGContextMoveToPoint(ctx, ax2 - 12, arrow_y + 10)
        CGContextAddLineToPoint(ctx, ax2, arrow_y)
        CGContextAddLineToPoint(ctx, ax2 - 12, arrow_y - 10)
        CGContextStrokePath(ctx)

        # Save as PNG
        image = CGBitmapContextCreateImage(ctx)
        url = CFURLCreateWithFileSystemPath(None, path, kCFURLPOSIXPathStyle, False)
        dest = CGImageDestinationCreateWithURL(url, "public.png", 1, None)
        CGImageDestinationAddImage(dest, image, None)
        CGImageDestinationFinalize(dest)
        return True
    except Exception as e:
        print(f"  Could not generate background image: {e}")
        return False


def build_dmg():
    if not os.path.isdir(APP_PATH):
        print(f"ERROR: {APP_PATH} not found. Run build_app.py first.")
        sys.exit(1)

    # Clean previous DMG
    if os.path.exists(DMG_PATH):
        os.remove(DMG_PATH)

    # Work in a temp directory
    with tempfile.TemporaryDirectory() as tmp:
        staging = os.path.join(tmp, VOL_NAME)
        os.makedirs(staging)

        # Copy .app into staging
        print(f"Copying {APP_NAME}.app ...")
        shutil.copytree(APP_PATH, os.path.join(staging, f"{APP_NAME}.app"), symlinks=True)

        # Create Applications symlink
        os.symlink("/Applications", os.path.join(staging, "Applications"))

        # Prevent Spotlight from indexing the volume (avoids stuck eject)
        open(os.path.join(staging, ".metadata_never_index"), "w").close()

        # Generate background image
        bg_dir = os.path.join(staging, ".background")
        os.makedirs(bg_dir)
        bg_path = os.path.join(bg_dir, "bg.png")
        has_bg = _make_background(bg_path)

        # Set volume icon
        vol_icon = os.path.join(staging, ".VolumeIcon.icns")
        if os.path.exists(ICON_PATH):
            shutil.copy2(ICON_PATH, vol_icon)

        # Create read-write DMG
        rw_dmg = os.path.join(tmp, "rw.dmg")
        print("Creating read-write DMG ...")
        subprocess.check_call([
            "hdiutil", "create",
            "-volname", VOL_NAME,
            "-srcfolder", staging,
            "-format", "UDRW",
            "-fs", "HFS+",
            rw_dmg,
        ])

        # Mount it
        print("Mounting DMG for styling ...")
        result = subprocess.check_output([
            "hdiutil", "attach", rw_dmg,
            "-mountpoint", f"/Volumes/{VOL_NAME}",
            "-noverify", "-noautoopen", "-nobrowse",
        ], text=True)
        print(f"  Mounted at /Volumes/{VOL_NAME}")

        try:
            # Apply Finder window settings via AppleScript
            bg_clause = ""
            if has_bg:
                bg_clause = f'''
                    set background picture of viewOptions to file ".background:bg.png"'''

            applescript = f'''
                tell application "Finder"
                    tell disk "{VOL_NAME}"
                        open
                        set current view of container window to icon view
                        set toolbar visible of container window to false
                        set statusbar visible of container window to false
                        set bounds of container window to {{100, 100, {100 + WIN_W}, {100 + WIN_H}}}
                        set viewOptions to the icon view options of container window
                        set arrangement of viewOptions to not arranged
                        set icon size of viewOptions to {ICON_SIZE}{bg_clause}
                        set position of item "{APP_NAME}.app" of container window to {{{APP_X}, {APP_Y}}}
                        set position of item "Applications" of container window to {{{APPS_X}, {APPS_Y}}}
                        close
                        open
                        update without registering applications
                        delay 1
                        close
                    end tell
                end tell
            '''
            print("Applying Finder window layout ...")
            subprocess.run(["osascript", "-e", applescript], check=False, timeout=30)

            # Set volume icon flag
            subprocess.run(["SetFile", "-a", "C", f"/Volumes/{VOL_NAME}"], check=False)

        finally:
            # Tell Finder to eject (it holds the volume after AppleScript styling)
            print("Unmounting ...")
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "Finder" to eject disk "{VOL_NAME}"'],
                check=False, timeout=10,
            )
            time.sleep(2)
            # Retry hdiutil detach in case Finder didn't fully release
            for attempt in range(5):
                if not os.path.exists(f"/Volumes/{VOL_NAME}"):
                    break
                result = subprocess.run(
                    ["hdiutil", "detach", f"/Volumes/{VOL_NAME}", "-force"],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    break
                print(f"  Retry {attempt + 1}/5 (volume busy) ...")
                time.sleep(2)

        # Small delay to ensure the volume is fully released
        time.sleep(1)

        # Remove old DMG if it exists (hdiutil won't overwrite)
        if os.path.exists(DMG_PATH):
            os.remove(DMG_PATH)

        # Convert to compressed read-only DMG
        print("Compressing to final DMG ...")
        subprocess.check_call([
            "hdiutil", "convert", rw_dmg,
            "-format", "UDZO",
            "-imagekey", "zlib-level=9",
            "-o", DMG_PATH,
        ])

    adhoc = "--adhoc" in sys.argv

    if not adhoc:
        # Notarize the DMG
        print("\nSubmitting DMG for notarization...")
        result = subprocess.run([
            "xcrun", "notarytool", "submit", DMG_PATH,
            "--keychain-profile", NOTARIZE_PROFILE,
            "--wait",
        ], capture_output=True, text=True, timeout=600)
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode != 0:
            print("Notarization FAILED.")
            sys.exit(1)
        print("Notarization succeeded.")

        # Staple the ticket to the DMG
        print("Stapling notarization ticket to DMG...")
        subprocess.check_call(["xcrun", "stapler", "staple", DMG_PATH])

    print(f"\nDMG created: {DMG_PATH}")
    # Show size
    size_mb = os.path.getsize(DMG_PATH) / (1024 * 1024)
    print(f"Size: {size_mb:.1f} MB")
    if not adhoc:
        print("(Signed + Notarized)")


if __name__ == "__main__":
    build_dmg()
