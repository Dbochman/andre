# Nests Implementation — Decision Log

Decisions made during overnight implementation of the Nests MVP (Phases 1-3).
Each entry documents what was decided, why, and any alternatives considered.

---

## D001: Migration uses DUMP+RESTORE+DEL, not RENAME
**Date:** 2026-02-11 (pre-implementation review)
**Context:** T3 migration script originally planned to use `RENAME` for each key.
**Decision:** Use `DUMP`+`RESTORE`+`DEL` (copy-then-delete) instead.
**Rationale:** `RENAME` clobbers if the destination key already exists, making partial re-runs unsafe. `DUMP`+`RESTORE` lets us check for destination existence first and skip with a warning, making the migration idempotent and safe for partial rollouts.
**Alternatives:** `RENAMENX` (fails silently on collision — harder to debug), `COPY` (Redis 6.2+ only, may not be available).

---

## D002: GET /api/nests requires authentication
**Date:** 2026-02-11 (pre-implementation review)
**Context:** T7 originally had `/api/nests` in `SAFE_PARAM_PATHS` with auth TBD.
**Decision:** All nest API routes require authentication (session auth or API token). Do NOT add to `SAFE_PARAM_PATHS`.
**Rationale:** Adding to `SAFE_PARAM_PATHS` bypasses the `before_request` session gate, making the endpoint fully public. This would leak the list of active nests (names, codes, creator emails) to anonymous users. Authenticated users can list/access nests; API clients use `@require_api_token`.

---

## D003: Migration covers all 9 Redis key prefix families
**Date:** 2026-02-11 (pre-implementation review)
**Context:** T3 originally listed only `MISC|*`, `QUEUE|*`, `FILTER|*`, `BENDER|*` for migration.
**Decision:** Expand SCAN to cover all 9 prefix families found in db.py: `MISC|*`, `QUEUE|*`, `FILTER|*`, `BENDER|*`, `QUEUEJAM|*`, `COMMENTS|*`, `FILL-INFO|*`, `AIRHORNS`, `FREEHORN_*`.
**Rationale:** Missing prefixes would leave orphaned data under old key names, invisible to the nest-scoped DB class. Users would lose jams, comments, airhorn history, and fill-info cache.

---

## D004: Membership heartbeat TTL for stale member cleanup
**Date:** 2026-02-11 (pre-implementation review)
**Context:** T9 originally only did join/leave on WebSocket connect/disconnect without liveness tracking.
**Decision:** Add per-member TTL keys (`NEST:{id}|MEMBER:{email}` with 90s TTL) refreshed every 30s in the WebSocket serve loop.
**Rationale:** Without heartbeat, a browser crash or network drop leaves a stale entry in the MEMBERS set forever. Stale members prevent cleanup (cleanup checks member count > 0 → won't delete). The TTL keys naturally expire, and cleanup can check for expired member keys to detect truly empty nests.

---

## D005: Spotify rate limit key stays global
**Date:** 2026-02-11 (pre-implementation review)
**Context:** T2 wraps all DB class Redis keys with `_key()` for nest-scoping.
**Decision:** `MISC|spotify-rate-limited` must NOT be wrapped. It's a global Spotify API concern, not per-nest.
**Rationale:** Rate limiting is per-Spotify-app, not per-nest. If one nest triggers a rate limit, all nests should back off. The key is already used in module-level functions (not DB class methods), so it naturally stays global — but T2 should explicitly verify it wasn't accidentally wrapped.

---

## D006: Vanity URL has no hold period on release
**Date:** 2026-02-11 (pre-implementation review)
**Context:** Vanity URL Policy section said "reserved for 30 days" but Open Questions confirmed "no hold period."
**Decision:** Immediate release on change. No hold period.
**Rationale:** Simplicity for MVP. Holding vanity codes requires a separate reservation system and TTL cleanup. If impersonation becomes a problem, can add hold periods later.

---

## D007: POST /api/nests returns 200, not 201
**Date:** 2026-02-11 (pre-implementation review)
**Context:** `docs/NESTS_TEST_SPEC.md` specified 201 for create, but Codex's actual tests (`test/test_nests.py:52`) assert 200.
**Decision:** Follow the actual tests — return 200 with nest metadata.
**Rationale:** The Codex contract tests are the source of truth for the overnight run. The test spec is superseded. 200 is acceptable for create endpoints that return the created resource (Flask convention), and changing the tests would be more disruptive.

---

## D008: Single test file with xfail contracts (not multi-file unit tests)
**Date:** 2026-02-11 (pre-implementation review)
**Context:** `docs/NESTS_TEST_SPEC.md` proposed 6+ test files with fakeredis injection. Codex produced a single `test/test_nests.py` with Flask-client contract tests.
**Decision:** Use Codex's approach as the primary test suite. Test spec marked as superseded reference. Implementation may add fakeredis-based unit tests if needed, but the overnight run targets passing the xfail contract tests.
**Rationale:** Contract tests are what Codex wrote and what the task breakdown maps to. Adding a parallel test suite would be confusing and time-consuming.

---

## D009: Admin access is creator-only (no admin role)
**Date:** 2026-02-11 (pre-implementation review)
**Context:** Admin UX section said "creators (and admins)" but decisions confirmed "creator-only."
**Decision:** Admin/settings access is strictly creator-only, defined by `created_by` email.
**Rationale:** No admin role system exists or is planned for MVP. Adding one would require a permissions model. Creator-only is simple and sufficient.

---

## D010: /nest/{code} pages require authentication (not public)
**Date:** 2026-02-11 (pre-implementation review)
**Context:** T8 originally said "Add `/nest/` to `SAFE_PARAM_PATHS`" which would bypass the Google auth gate and make nest pages publicly accessible.
**Decision:** Do NOT add `/nest/` to `SAFE_PARAM_PATHS`. Nest pages require Google auth like all other pages.
**Rationale:** The entire app requires Google OAuth login. Making nest pages public would be a major security model change — unauthenticated users could see queue contents, listener lists, etc. The flow is: `echone.st/X7K2P` → redirect → `/nest/X7K2P` → Google login → join nest. This is consistent and secure.

---

## D011: Plan key names corrected to match actual db.py
**Date:** 2026-02-11 (pre-implementation review)
**Context:** Plan listed `JAMS|{song_id}` and `AIRHORN|{user}` but db.py uses `QUEUEJAM|{song_id}`, `AIRHORNS`, and `FREEHORN_{userid}`.
**Decision:** Updated plan's Redis key reference to match actual db.py key names. Added missing keys: `FILL-INFO|{trackid}`, `MEMBER:{email}`.
**Rationale:** Migration and T2 refactor must use the real key names. Drift between plan and code causes silent data loss.
