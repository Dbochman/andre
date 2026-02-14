# Apple Developer ID — Notarization Plan

## Step 1: Enroll ($99/year)

1. Go to https://developer.apple.com/programs/enroll/
2. Sign in with personal Apple ID
3. Enroll as **Individual** (not Organization)
4. Verify identity (phone call or ID scan, 1-2 business days)
5. Pay $99/year
6. Wait for approval (24-48 hours)

## Step 2: Create Certificates

1. Open **Keychain Access** → Certificate Assistant → Request a Certificate from a Certificate Authority
2. Go to https://developer.apple.com/account/resources/certificates
3. Create a **Developer ID Application** certificate (for signing .app bundles)
4. Download and install in Keychain

## Step 3: Create App-Specific Password

1. Go to https://appleid.apple.com/account/manage
2. Security → App-Specific Passwords → Generate
3. Label it "notarytool" and save the password

## Step 4: Store Credentials

```bash
xcrun notarytool store-credentials "echonest-notarize" \
  --apple-id you@email.com \
  --team-id XXXXXXXXXX \
  --password <app-specific-password>
```

## Step 5: Updated Build Flow

```bash
cd ~/repos/EchoNest/echonest-sync

# 1. Build the .app
sudo rm -rf "dist/EchoNest Sync.app"
/usr/local/bin/python3 build/macos/build_app.py

# 2. Sign with Developer ID (replaces ad-hoc signing)
codesign --force --deep --sign "Developer ID Application: Your Name (TEAM_ID)" "dist/EchoNest Sync.app"

# 3. Notarize
ditto -c -k --keepParent "dist/EchoNest Sync.app" "dist/EchoNest Sync.zip"
xcrun notarytool submit "dist/EchoNest Sync.zip" \
  --keychain-profile "echonest-notarize" \
  --wait

# 4. Staple the notarization ticket to the app
xcrun stapler staple "dist/EchoNest Sync.app"

# 5. Build DMG (with notarized app inside)
/usr/local/bin/python3 build/macos/build_dmg.py

# 6. (Optional) Notarize the DMG too
xcrun notarytool submit "dist/EchoNest-Sync.dmg" \
  --keychain-profile "echonest-notarize" \
  --wait
xcrun stapler staple "dist/EchoNest-Sync.dmg"
```

## Result

- Users double-click the DMG → drag to Applications → app opens with no Gatekeeper warning
- No need for `xattr -cr` or right-click → Open workaround
- TODO: Update `build_app.py` to accept a `--sign` flag for Developer ID signing + notarization
