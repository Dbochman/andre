# Plan: Slim Homebrew Formula for echonest-sync CLI

## Context

The echonest-sync package bundles both a CLI (`echonest-sync`) and a desktop tray app (`echonest-sync-app`) in one `pip install`. Users who just want the CLI via `brew install echonest-sync` shouldn't need GUI deps like pystray, pillow, or rumps — and dropping them eliminates the native wheel workaround in the current formula.

The `homebrew-echonest` tap repo exists at `Dbochman/homebrew-echonest` with a working formula that installs everything (including native deps via a split-resource pattern). This plan simplifies it by splitting the Python package itself.

## Changes

### 1. Move GUI deps to optional extras in `pyproject.toml`

**File**: `echonest-sync/pyproject.toml`

Move `pystray` and `pillow` from base `dependencies` to a new `[app]` extra:

```toml
dependencies = [
    "requests",
    "sseclient-py",
    "click",
    "pyyaml",
    "keyring",
]

[project.optional-dependencies]
app = ["pystray", "pillow"]
mac = ["rumps"]
```

**Import trace verified** — CLI path (`cli.py → config.py, sync.py → audio.py, player.py`) only uses stdlib + requests/sseclient/click/pyyaml/keyring. No pillow/pystray/rumps anywhere in that chain.

### 2. Guard tray app imports

**File**: `echonest-sync/src/echonest_sync/app.py`

Add a graceful error at the top of `app.py` (the `echonest-sync-app` entry point) so it fails cleanly when GUI deps are missing:

```python
try:
    import pystray
    import PIL
except ImportError:
    import sys
    print("echonest-sync-app requires GUI dependencies.")
    print("Install with: pip install echonest-sync[app]")
    print("Or use the desktop .dmg from GitHub Releases.")
    sys.exit(1)
```

Also verify no top-level `__init__.py` import pulls in pystray/pillow unconditionally.

### 3. Simplify Homebrew formula

**File**: `homebrew-echonest/Formula/echonest-sync.rb`

Replace the current formula (which has 20+ resource blocks including native wheel workarounds) with a slim version:
- Depends on `python@3.12`
- Resources: only `requests, sseclient-py, click, pyyaml, keyring` + their transitive deps (`certifi, charset-normalizer, idna, urllib3, jaraco.classes, jaraco.context, jaraco.functools, more-itertools, six`)
- All pure-python sdists — no native wheels, no split-resource pattern needed
- Only symlinks `echonest-sync` (not `echonest-sync-app`)
- Drop `depends_on :macos` (pure-python CLI works cross-platform)
- Test block: `assert_match "Sync your local Spotify", shell_output("#{bin}/echonest-sync --help")`

### 4. Tag new release

Bump version to `0.6.0` in `pyproject.toml` (breaking change: base deps reduced), create tag `sync-v0.6.0`, update formula URL + sha256.

### 5. Push formula to tap repo

Commit the simplified formula to `Dbochman/homebrew-echonest`.

## Verification

1. `pip install echonest-sync` (base) — works without pystray/pillow:
   ```bash
   python -c "from echonest_sync.cli import main; main(['--help'])"
   ```
2. `pip install echonest-sync[app,mac]` — installs everything for the tray app
3. `echonest-sync-app` without `[app]` extras — prints friendly error and exits
4. `brew tap dbochman/echonest && brew install echonest-sync` — installs CLI only
5. `echonest-sync --help` and `echonest-sync login` — both work
6. `brew test echonest-sync` — passes
7. CI tests still pass: `SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest echonest-sync/tests/ -v`
8. Existing DMG / PyInstaller builds still work (they install `[app,mac]`)

## Files Modified

| File | Change |
|------|--------|
| `echonest-sync/pyproject.toml` | Move pystray+pillow to `[app]` extra |
| `echonest-sync/src/echonest_sync/app.py` | Guard missing GUI deps |
| `homebrew-echonest/Formula/echonest-sync.rb` | Slim formula, pure-python only |

## Files NOT Modified

- `cli.py`, `sync.py`, `config.py`, `audio.py`, `player.py` — no changes needed
- DMG/PyInstaller build scripts — they already install `[mac]`, just also need `[app]`
