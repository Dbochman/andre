.PHONY: test-nests test-all test-quick

# Run nest contract tests + regression suite
test-nests:
	./scripts/test_nests.sh

# Run full test suite (all tests including nests)
test-all:
	SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/ -v

# Quick: just nest tests, no regression
test-quick:
	SKIP_SPOTIFY_PREFETCH=1 python3 -m pytest test/test_nests.py -v -rx
