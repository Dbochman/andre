#!/usr/bin/env bash
set -euo pipefail

export SKIP_SPOTIFY_PREFETCH=1
python3 -m pytest test/test_nests.py -v -rx
