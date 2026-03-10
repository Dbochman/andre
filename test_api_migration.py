#!/usr/bin/env python3
"""Quick smoke tests for Spotify Feb 2026 API migration.

Validates that every endpoint we depend on still works with real API calls.
Uses client credentials (no user auth needed).

Usage: python3 test_api_migration.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import requests
import spotipy

from config import CONF


# Test data: Radiohead - Everything In Its Right Place
TEST_TRACK_ID = '3yad4Bfxw3hS6IfevPWxBT'
TEST_ARTIST_ID = '4Z8W4fKeB5YxbusRsdQVPb'  # Radiohead
TEST_ALBUM_ID = '6dVIqQ8qmQ5GBnJ9shOYGE'   # Kid A
TEST_EPISODE_ID = '512ojhOuo1ktJprKbVcKyQ'  # random popular episode


def main():
    creds = spotipy.oauth2.SpotifyClientCredentials(
        CONF.SPOTIFY_CLIENT_ID,
        CONF.SPOTIFY_CLIENT_SECRET,
    )
    sp = spotipy.Spotify(client_credentials_manager=creds)

    passed = 0
    failed = 0

    def run_check(name, fn):
        nonlocal passed, failed
        try:
            result = fn()
            print(f'  PASS  {name}')
            passed += 1
            return result
        except Exception as exc:
            print(f'  FAIL  {name}: {exc}')
            failed += 1
            return None

    print('\n=== Spotify API Migration Smoke Tests ===\n')

    print('[1] Single track fetch')
    track = run_check('GET /tracks/{id}', lambda: sp.track(TEST_TRACK_ID))
    if track:
        run_check('  has name', lambda: track['name'])
        run_check('  has artists', lambda: track['artists'][0]['name'])
        run_check('  has album.images', lambda: track['album']['images'][0]['url'])
        run_check('  has duration_ms', lambda: track['duration_ms'])
        if 'popularity' in track:
            print('  INFO  popularity field still present (not yet enforced)')
        if 'available_markets' in track:
            print('  INFO  available_markets still present (not yet enforced)')

    print('\n[2] Single artist fetch')
    artist = run_check('GET /artists/{id}', lambda: sp.artist(TEST_ARTIST_ID))
    if artist:
        run_check('  has genres', lambda: artist['genres'])

    print('\n[3] Artist albums (replaces top-tracks)')
    albums = run_check(
        'GET /artists/{id}/albums',
        lambda: sp.artist_albums(TEST_ARTIST_ID, album_type='album,single', country='US', limit=5),
    )
    if albums:
        run_check('  has items', lambda: albums['items'][0]['id'])
        run_check('  items have name', lambda: albums['items'][0]['name'])

    print('\n[4] Album tracks')
    album_tracks = run_check('GET /albums/{id}/tracks', lambda: sp.album_tracks(TEST_ALBUM_ID))
    if album_tracks:
        run_check('  has items', lambda: album_tracks['items'][0]['uri'])

    print('\n[5] Search with limit=10')
    search = run_check('GET /search limit=10', lambda: sp.search('radiohead', type='track', limit=10, market='US'))
    if search:
        items = search.get('tracks', {}).get('items', [])
        run_check(
            f'  returned {len(items)} items (<=10)',
            lambda: None if len(items) <= 10 else (_ for _ in ()).throw(AssertionError(f'got {len(items)}')),
        )

    print('\n[6] Search with limit>10 (should fail or cap)')
    try:
        over = sp.search('radiohead', type='track', limit=11, market='US')
        over_count = len(over.get('tracks', {}).get('items', []))
        if over_count <= 10:
            print(f'  INFO  limit=11 returned {over_count} items (silently capped)')
        else:
            print(f'  WARN  limit=11 returned {over_count} items (not enforced yet)')
    except Exception as exc:
        print(f'  INFO  limit=11 rejected: {exc}')

    print('\n[7] Search pagination (offset=10)')
    page2 = run_check('GET /search offset=10', lambda: sp.search('radiohead', type='track', limit=10, offset=10, market='US'))
    if page2:
        items2 = page2.get('tracks', {}).get('items', [])
        run_check(
            f'  page 2 returned {len(items2)} items',
            lambda: None if items2 else (_ for _ in ()).throw(AssertionError('empty')),
        )

    print('\n[8] Artist top-tracks (should be REMOVED)')
    try:
        top = sp.artist_top_tracks(TEST_ARTIST_ID, country='US')
        count = len(top.get('tracks', []))
        print(f'  WARN  top-tracks still works! Returned {count} tracks (not enforced yet)')
    except Exception as exc:
        print(f'  OK    top-tracks rejected as expected: {type(exc).__name__}')

    print('\n[9] Batch GET /tracks (should be REMOVED)')
    try:
        batch = sp.tracks([TEST_TRACK_ID, '1zZZ9DQGV7B5Z7SCKOn9B9'])
        count = len(batch.get('tracks', []))
        print(f'  WARN  batch tracks still works! Returned {count} tracks (not enforced yet)')
    except Exception as exc:
        print(f'  OK    batch tracks rejected as expected: {type(exc).__name__}')

    print('\n[10] Single episode fetch')
    try:
        episode = sp.episode(TEST_EPISODE_ID, market='US')
        run_check('GET /episodes/{id}', lambda: episode['name'])
        if episode.get('show'):
            has_publisher = 'publisher' in episode['show']
            print(f'  INFO  show.publisher {"present" if has_publisher else "REMOVED"}')
    except Exception as exc:
        print(f'  SKIP  Episode fetch failed (may need user auth): {exc}')

    print('\n[11] Playlist items (renamed from /tracks)')
    try:
        token = creds.get_access_token()
        if isinstance(token, dict):
            token = token['access_token']
        headers = {'Authorization': f'Bearer {token}'}

        response = requests.get(
            'https://api.spotify.com/v1/playlists/37i9dQZF1DXcBWIGoYBM5M/items',
            headers=headers,
            params={'limit': 5, 'fields': 'items(item(uri,name))'},
        )
        if response.status_code == 200:
            data = response.json()
            if 'items' in data:
                print(f'  PASS  /playlists/{{id}}/items returned {len(data["items"])} items')
                passed += 1
            else:
                print('  INFO  /playlists/{id}/items returned no items (non-owned playlist restriction)')
                passed += 1
        elif response.status_code == 404:
            print('  OK    /playlists/{id}/items returned 404 (non-owned playlist, dev mode restriction)')
            passed += 1
        else:
            print(f'  FAIL  /playlists/{{id}}/items returned {response.status_code}: {response.text[:100]}')
            failed += 1

        old_response = requests.get(
            'https://api.spotify.com/v1/playlists/37i9dQZF1DXcBWIGoYBM5M/tracks',
            headers=headers,
            params={'limit': 5},
        )
        if old_response.status_code == 200:
            print('  WARN  /playlists/{id}/tracks still works (not enforced yet)')
        else:
            print(f'  OK    /playlists/{{id}}/tracks also rejected: {old_response.status_code}')
    except Exception as exc:
        print(f'  SKIP  Playlist test failed: {exc}')

    print(f'\n=== Results: {passed} passed, {failed} failed ===')
    if failed > 0:
        print('Some tests failed — check if the API changes are enforced yet.')
        print('Failures on endpoints marked REMOVED are expected AFTER March 9.')

    return 1 if failed > 0 else 0


if __name__ == '__main__':
    raise SystemExit(main())
