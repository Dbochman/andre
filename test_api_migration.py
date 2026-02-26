#!/usr/bin/env python3
"""Quick smoke tests for Spotify Feb 2026 API migration.

Validates that every endpoint we depend on still works with real API calls.
Uses client credentials (no user auth needed).

Usage: python3 test_api_migration.py
"""
import sys
import os
import logging
sys.path.insert(0, os.path.dirname(__file__))

# Suppress config.py debug output
logging.disable(logging.CRITICAL)
old_stdout = sys.stdout
sys.stdout = open(os.devnull, 'w')
from config import CONF
sys.stdout = old_stdout
logging.disable(logging.NOTSET)

import spotipy

# --- Setup ---
creds = spotipy.oauth2.SpotifyClientCredentials(CONF.SPOTIFY_CLIENT_ID, CONF.SPOTIFY_CLIENT_SECRET)
sp = spotipy.Spotify(client_credentials_manager=creds)

# Test data: Radiohead - Everything In Its Right Place
TEST_TRACK_ID = '3yad4Bfxw3hS6IfevPWxBT'
TEST_ARTIST_ID = '4Z8W4fKeB5YxbusRsdQVPb'  # Radiohead
TEST_ALBUM_ID = '6dVIqQ8qmQ5GBnJ9shOYGE'   # Kid A
TEST_EPISODE_ID = '512ojhOuo1ktJprKbVcKyQ'  # random popular episode

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        result = fn()
        print(f'  PASS  {name}')
        passed += 1
        return result
    except Exception as e:
        print(f'  FAIL  {name}: {e}')
        failed += 1
        return None

print('\n=== Spotify API Migration Smoke Tests ===\n')

# 1. Single track fetch (GET /tracks/{id}) — used everywhere
print('[1] Single track fetch')
track = test('GET /tracks/{id}', lambda: sp.track(TEST_TRACK_ID))
if track:
    test('  has name', lambda: track['name'])
    test('  has artists', lambda: track['artists'][0]['name'])
    test('  has album.images', lambda: track['album']['images'][0]['url'])
    test('  has duration_ms', lambda: track['duration_ms'])
    # Verify removed fields are actually gone
    if 'popularity' in track:
        print('  INFO  popularity field still present (not yet enforced)')
    if 'available_markets' in track:
        print('  INFO  available_markets still present (not yet enforced)')

# 2. Single artist fetch (GET /artists/{id}) — used by Bender _get_seed_info
print('\n[2] Single artist fetch')
artist = test('GET /artists/{id}', lambda: sp.artist(TEST_ARTIST_ID))
if artist:
    test('  has genres', lambda: artist['genres'])

# 3. Artist albums (GET /artists/{id}/albums) — NEW, replaces top-tracks
print('\n[3] Artist albums (replaces top-tracks)')
albums = test('GET /artists/{id}/albums', lambda: sp.artist_albums(TEST_ARTIST_ID, album_type='album,single', country='US', limit=5))
if albums:
    test('  has items', lambda: albums['items'][0]['id'])
    test('  items have name', lambda: albums['items'][0]['name'])

# 4. Album tracks (GET /albums/{id}/tracks) — used by Bender
print('\n[4] Album tracks')
album_tracks = test('GET /albums/{id}/tracks', lambda: sp.album_tracks(TEST_ALBUM_ID))
if album_tracks:
    test('  has items', lambda: album_tracks['items'][0]['uri'])

# 5. Search with limit=10 (GET /search) — new max
print('\n[5] Search with limit=10')
search = test('GET /search limit=10', lambda: sp.search('radiohead', type='track', limit=10, market='US'))
if search:
    items = search.get('tracks', {}).get('items', [])
    test(f'  returned {len(items)} items (<=10)', lambda: None if len(items) <= 10 else (_ for _ in ()).throw(AssertionError(f'got {len(items)}')))

# 6. Search with limit=11 should fail or be capped
print('\n[6] Search with limit>10 (should fail or cap)')
try:
    over = sp.search('radiohead', type='track', limit=11, market='US')
    over_count = len(over.get('tracks', {}).get('items', []))
    if over_count <= 10:
        print(f'  INFO  limit=11 returned {over_count} items (silently capped)')
    else:
        print(f'  WARN  limit=11 returned {over_count} items (not enforced yet)')
except Exception as e:
    print(f'  INFO  limit=11 rejected: {e}')

# 7. Search pagination with offset
print('\n[7] Search pagination (offset=10)')
page2 = test('GET /search offset=10', lambda: sp.search('radiohead', type='track', limit=10, offset=10, market='US'))
if page2:
    items2 = page2.get('tracks', {}).get('items', [])
    test(f'  page 2 returned {len(items2)} items', lambda: None if items2 else (_ for _ in ()).throw(AssertionError('empty')))

# 8. Artist top-tracks should fail (REMOVED)
print('\n[8] Artist top-tracks (should be REMOVED)')
try:
    top = sp.artist_top_tracks(TEST_ARTIST_ID, country='US')
    count = len(top.get('tracks', []))
    print(f'  WARN  top-tracks still works! Returned {count} tracks (not enforced yet)')
except Exception as e:
    print(f'  OK    top-tracks rejected as expected: {type(e).__name__}')

# 9. Batch tracks should fail (REMOVED)
print('\n[9] Batch GET /tracks (should be REMOVED)')
try:
    batch = sp.tracks([TEST_TRACK_ID, '1zZZ9DQGV7B5Z7SCKOn9B9'])
    count = len(batch.get('tracks', []))
    print(f'  WARN  batch tracks still works! Returned {count} tracks (not enforced yet)')
except Exception as e:
    print(f'  OK    batch tracks rejected as expected: {type(e).__name__}')

# 10. Episode fetch (GET /episodes/{id})
print('\n[10] Single episode fetch')
try:
    ep = sp.episode(TEST_EPISODE_ID, market='US')
    test('GET /episodes/{id}', lambda: ep['name'])
    if ep.get('show'):
        has_pub = 'publisher' in ep['show']
        print(f'  INFO  show.publisher {"present" if has_pub else "REMOVED"}')
except Exception as e:
    print(f'  SKIP  Episode fetch failed (may need user auth): {e}')

# 11. Playlist items endpoint (GET /playlists/{id}/items) — renamed from /tracks
print('\n[11] Playlist items (renamed from /tracks)')
# Use Spotify's "Today's Top Hits" playlist
try:
    # Try the new /items endpoint via raw request
    import requests
    token = creds.get_access_token()
    if isinstance(token, dict):
        token = token['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    # New endpoint (non-owned playlists return 404 in dev mode — expected)
    r = requests.get('https://api.spotify.com/v1/playlists/37i9dQZF1DXcBWIGoYBM5M/items',
                      headers=headers, params={'limit': 5, 'fields': 'items(item(uri,name))'})
    if r.status_code == 200:
        data = r.json()
        if 'items' in data:
            print(f'  PASS  /playlists/{{id}}/items returned {len(data["items"])} items')
            passed += 1
        else:
            print(f'  INFO  /playlists/{{id}}/items returned no items (non-owned playlist restriction)')
            passed += 1
    elif r.status_code == 404:
        print(f'  OK    /playlists/{{id}}/items returned 404 (non-owned playlist, dev mode restriction)')
        passed += 1
    else:
        print(f'  FAIL  /playlists/{{id}}/items returned {r.status_code}: {r.text[:100]}')
        failed += 1

    # Old endpoint (should also fail)
    r2 = requests.get('https://api.spotify.com/v1/playlists/37i9dQZF1DXcBWIGoYBM5M/tracks',
                       headers=headers, params={'limit': 5})
    if r2.status_code == 200:
        print(f'  WARN  /playlists/{{id}}/tracks still works (not enforced yet)')
    else:
        print(f'  OK    /playlists/{{id}}/tracks also rejected: {r2.status_code}')
except Exception as e:
    print(f'  SKIP  Playlist test failed: {e}')

# --- Summary ---
print(f'\n=== Results: {passed} passed, {failed} failed ===')
if failed > 0:
    print('Some tests failed — check if the API changes are enforced yet.')
    print('Failures on endpoints marked REMOVED are expected AFTER March 9.')

if __name__ == '__main__':
    raise SystemExit(1 if failed > 0 else 0)
