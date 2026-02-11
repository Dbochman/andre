#!/usr/bin/env bash
set -euo pipefail

export SKIP_SPOTIFY_PREFETCH=1

echo "=== Nest contract tests ==="
python3 -m pytest test/test_nests.py -v -rx

echo ""
echo "=== Regression tests (existing suite) ==="
python3 -m pytest test/ --ignore=test/test_nests.py -v --tb=short 2>&1 || {
    echo "WARNING: Existing tests failed — check for regressions"
    exit 1
}
