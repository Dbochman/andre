# Contributing

## Nests TDD Workflow (xfail-first)

- The canonical contract tests are in `test/test_nests.py` and are marked `xfail` until implemented.
- When implementing a feature, remove the `xfail` marker for the relevant test class *only after* it passes.
- Run tests via `make test-quick` (fast) during a task, and `make test-nests` before finishing a task to catch regressions.
- Keep API error payloads aligned with `docs/NESTS_API_ERRORS.md`.

## Test Commands

```bash
make test-quick
make test-nests
make test-all
```
