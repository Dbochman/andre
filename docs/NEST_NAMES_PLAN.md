# Plan: Friendly Nest Names with Sonic Descriptors

## Context
When users create a nest without naming it, the default is "Nest A3KM7" — ugly and meaningless. The user wants auto-generated names that match the app's identity (like "EchoNest"), using sonic/audio descriptors as a theme. Examples: WaveyNest, VibesNest, BassNest, etc.

## Approach
Add a pre-populated list of `*Nest` names to `nests.py`. When no name is provided during creation, pick a random unused one. The 5-char code stays as the URL/ID — names are display-only.

## Files to Modify

### 1. `nests.py` — Add name list + random picker
- Add `NEST_NAMES` tuple (~50 entries) after `CODE_CHARS` (line 19). Pattern: `{SonicDescriptor}Nest`
  - Examples: WaveyNest, BassNest, VibesNest, FunkNest, GrooveNest, TrebleNest, ReverbNest, TempoNest, RiffNest, SynthNest, LoopNest, BeatNest, ChordNest, FaderNest, SubNest, DropNest, etc.
- Add `_pick_random_name(self)` method to `NestManager`:
  - Read active nest names from `NESTS|registry`
  - Filter `NEST_NAMES` to exclude names currently in use
  - Pick random from available; if all taken, append a number suffix
- Update `create_nest()` line 239: `name or f'Nest {code}'` → `name or self._pick_random_name()`

### 2. `static/js/app.js` — Update build prompt text
- Line ~1757: Change prompt text to hint that a fun name is auto-assigned if left blank

### 3. `test/test_nests.py` — Add test cases
- Test random name is from `NEST_NAMES` (not "Nest {code}")
- Test two nests get different random names
- Test explicit name still works

## What Stays the Same
- Join dialog — already renders `n.name`, will automatically show the new names
- Nest bar — already renders `{{ nest_name }}`
- Redis keys — still use 5-char code as `nest_id`
- URLs — still `/nest/{code}`
- API routes — no changes needed

## Verification
```bash
SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py -v
docker compose up --build -d echonest
# Click "Build a Nest" with no name → verify a *Nest name appears in the nest bar
# Click "Join a Nest" from another session → verify the friendly name shows in the list
```
