# Plan: Master Player Follow-Up Cleanup

> **Status:** Draft
> **Author:** Codex
> **Date:** 2026-03-10
> **Depends on:** `docs/remove-queue-ttl-plan.md` is related but not required to start this work

## Purpose

Capture adjacent `master_player()` bugs and cleanup work that should be handled separately from queue-TTL removal.

This plan is written for async execution by another agent. It assumes no prior context beyond the codebase.

## Scope

This follow-up covers:

- stale player-state keys that are not consistently cleared
- recovery/cleanup behavior for short tracks
- unbounded retry behavior when Bender fill fails
- clarifying or removing `MISC|now-playing-done`
- nest cleanup counting raw queue members instead of real playable songs

This follow-up does not change:

- queue scoring
- Bender recommendation strategy selection
- playback semantics for skip/pause/unpause beyond cleanup correctness
- client-facing queue UI structure

## Background

The current `DB.master_player()` loop in [`db.py`](/Users/dylanbochman/repos/EchoNest/db.py) has a few correctness and state-hygiene issues adjacent to the queue TTL work:

1. Player-state keys are written in multiple places but only partially cleared.
2. Very short tracks take a special path that skips normal timer setup.
3. Empty-queue Bender fill retries forever with no backoff on persistent failure.
4. `MISC|now-playing-done` is written but appears unused.
5. The nest cleanup worker uses `ZCARD` on the queue sorted set, which can miscount if the set contains stale members.

## Current Issues

### 1. Incomplete player-state cleanup

Relevant code paths:

- `pop_next()` sets:
  - `MISC|now-playing`
  - `MISC|now-playing-done`
- `master_player()` sets:
  - `MISC|current-done`
  - `MISC|started-on`
- `master_player()` normal cleanup currently deletes:
  - `MISC|current-done`
  - queue-song keys only
- `pop_next()` empty-queue path currently deletes:
  - `MISC|now-playing` only

Consequences:

- `MISC|started-on` can survive after playback finishes or after queue-empty transitions.
- `MISC|now-playing-done` can survive indefinitely if it is not naturally expired or if its semantics drift from the rest of the loop.
- cleanup logic is fragmented and easy to miss when new recovery paths are added.

### 2. Short tracks rely on implicit stale recovery

Relevant code path:

- after `song = self.pop_next()`, `master_player()` does `if song['duration'] < 5: continue`

Consequences:

- no `MISC|current-done` is set for these tracks
- no normal end-of-track cleanup runs for that loop iteration
- next loop iteration treats the track as effectively stale/finished
- correctness depends on whichever stale-recovery cleanup exists at that time

This is brittle even if it mostly works in practice.

### 3. Bender fill loop has no backoff

Relevant code path:

- when `pop_next()` returns no song and Bender is allowed, `master_player()` loops until `get_fill_song()` + `add_spotify_song()` succeeds
- on exception, it logs and immediately retries

Consequences:

- log spam on persistent Spotify or recommendation failures
- unnecessary CPU churn
- noisy failure mode during outages

### 4. `MISC|now-playing-done` lacks a clear owner

Relevant code path:

- `pop_next()` writes `MISC|now-playing-done`
- current readers appear to use `MISC|current-done` instead

Consequences:

- likely dead state
- if not dead, semantics are unclear and split across two end-time markers
- makes future recovery behavior harder to reason about

### 5. Nest cleanup uses raw queue cardinality

Relevant code path:

- `nest_cleanup_loop()` in [`master_player.py`](/Users/dylanbochman/repos/EchoNest/master_player.py) uses `zcard(queue_key)` to determine whether a nest still has queued songs

Consequences:

- stale sorted-set members can block cleanup of otherwise empty nests
- queue TTL removal reduces but does not eliminate the value of using a “real songs” count

## Desired Outcome

After this work:

- all player-state keys are cleared through one shared helper
- short-track behavior is explicit, not an accidental side effect
- Bender fill failure paths back off instead of hot-looping
- `MISC|now-playing-done` is either removed or made the single intentional source of truth
- nest cleanup counts playable songs, not just sorted-set members

## Proposed Changes

### Phase 1: Centralize player-state cleanup

Add a helper in `db.py`:

```python
def _clear_now_playing_state(self):
    self._r.delete(self._key('MISC|now-playing'))
    self._r.delete(self._key('MISC|current-done'))
    self._r.delete(self._key('MISC|started-on'))
    self._r.delete(self._key('MISC|now-playing-done'))
```

Use this helper in all relevant paths:

- normal song completion in `master_player()`
- stale `now-playing` reconciliation path in `master_player()`
- empty queue path in `pop_next()`
- any recovery branch that abandons the previous active song

Implementation note:

- if the queue-TTL plan introduces its own helper for song-state deletion, keep player-state cleanup separate from per-song queue-state cleanup
- call both helpers where needed rather than mixing concerns

### Phase 2: Make short-track handling explicit

Replace the current `if song['duration'] < 5: continue` behavior with one of these explicit approaches:

Preferred approach:

1. treat sub-5-second items as immediately completed
2. log them as finished if appropriate
3. delete per-song state
4. clear player-state keys
5. continue the loop

Alternative approach:

- set a minimum 1-second `current-done` marker and let the normal cleanup path run

Recommendation:

- use the preferred approach because it makes the edge case obvious and keeps the loop simple

Acceptance requirement:

- short tracks must not rely on the stale-recovery branch for cleanup

### Phase 3: Add bounded retry/backoff to empty-queue Bender fill

Current behavior retries forever with no delay beyond the work itself.

Change the empty-queue fill section so that:

- repeated failures back off with a small sleep
- warnings remain visible but do not spam every CPU tick
- the loop can recover automatically once Spotify/Bender starts working again

Recommended behavior:

```python
failures = 0
while not got_song:
    try:
        ...
        failures = 0
    except Exception:
        failures += 1
        sleep_seconds = min(30, max(1, failures * 2))
        logger.warning(...)
        time.sleep(sleep_seconds)
```

Requirements:

- do not stop trying permanently
- cap backoff so the queue can still recover reasonably quickly
- include enough context in logs to distinguish transient vs repeated failure

### Phase 4: Resolve `MISC|now-playing-done`

Choose one of these and document it in code comments and docs:

Option A: remove it

- stop writing `MISC|now-playing-done`
- remove any dead references if found
- use `MISC|current-done` as the only active end marker

Option B: standardize on it

- define its semantics clearly
- update readers to use it consistently
- remove duplicate use of `MISC|current-done` where appropriate

Recommendation:

- choose Option A unless a real consumer is found during implementation

Reason:

- current code already appears to use `MISC|current-done` for user-visible timing
- removing duplicate state is lower risk than re-plumbing timing reads

### Phase 5: Make nest cleanup count real songs

In `master_player.py`, replace raw `ZCARD` usage with a count that reflects playable entries.

Possible implementations:

Option A:

- instantiate `DB(nest_id=nest_id)` and call a helper that purges/filters stale entries, then returns the effective queue size

Option B:

- add a lightweight DB helper such as `_queue_size_after_purge()` and call that from `nest_cleanup_loop()`

Recommendation:

- add a small DB helper and keep the cleanup worker thin

Requirements:

- avoid duplicating purge logic in `master_player.py`
- do not accidentally count the Bender preview row as a queue item
- behavior must remain correct for main and temporary nests

## Execution Plan

### Task 1: Audit and choose the now-playing marker model

Files:

- [`db.py`](/Users/dylanbochman/repos/EchoNest/db.py)
- [`master_player.py`](/Users/dylanbochman/repos/EchoNest/master_player.py)
- docs and tests if references exist

Steps:

1. confirm whether `MISC|now-playing-done` has any real readers
2. if not, mark it for removal in this change
3. note the chosen direction in the PR summary and docs

Done when:

- one end-marker model is selected and reflected in the implementation plan

### Task 2: Add shared player-state cleanup helper

Files:

- [`db.py`](/Users/dylanbochman/repos/EchoNest/db.py)

Steps:

1. add `_clear_now_playing_state()`
2. replace ad hoc deletes in completion and recovery paths with the helper
3. ensure helper usage does not clear state prematurely while a song is still active

Done when:

- all known “song is no longer active” paths use the helper

### Task 3: Fix short-track cleanup path

Files:

- [`db.py`](/Users/dylanbochman/repos/EchoNest/db.py)

Steps:

1. replace the bare `continue` branch for `duration < 5`
2. ensure short-track completion performs the same cleanup guarantees as normal tracks
3. verify no duplicate “finished song” logging occurs

Done when:

- short tracks exit through an explicit, tested cleanup path

### Task 4: Add retry backoff to Bender empty-queue fill

Files:

- [`db.py`](/Users/dylanbochman/repos/EchoNest/db.py)

Steps:

1. add bounded backoff around repeated fill failures
2. update logging to include retry count or next delay
3. confirm successful fill resets the backoff state

Done when:

- repeated failures do not tight-loop

### Task 5: Fix nest cleanup queue counting

Files:

- [`db.py`](/Users/dylanbochman/repos/EchoNest/db.py)
- [`master_player.py`](/Users/dylanbochman/repos/EchoNest/master_player.py)

Steps:

1. add a helper that returns effective queue size after stale-entry cleanup or filtering
2. use that helper from `nest_cleanup_loop()`
3. confirm temp nests with no playable songs can still be deleted

Done when:

- cleanup worker decisions are based on real queue occupancy

### Task 6: Add tests

Files:

- `test/` files as appropriate

Required coverage:

1. player-state helper clears the intended keys
2. normal song completion clears player state
3. stale recovery clears player state and does not leave prior markers behind
4. short tracks do not leak player state or per-song state
5. repeated Bender fill failures back off instead of hammering the loop
6. nest cleanup does not treat stale queue members as active songs

Done when:

- targeted tests exist for each bug class above

## Implementation Notes

- Keep helper boundaries clear:
  - one helper for now-playing/player-loop state
  - one helper for per-song queue state
- Do not mix queue preview state with active playback state.
- Preserve current skip behavior: skipping should still advance promptly, but cleanup should be explicit.
- Be careful not to clear `MISC|paused` as part of generic player-state cleanup.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Clearing player-state keys too aggressively breaks `get_now_playing()` timing | Medium | Medium | Use one helper only on terminal/recovery paths and add tests |
| Short-track explicit cleanup double-logs songs | Medium | Low | Add targeted tests for `log_finished_song()` call count |
| Backoff slows recovery too much after transient failures | Low | Low | Cap delay and reset on first success |
| Nest cleanup helper introduces extra Redis work | Low | Low | Reuse existing purge/filter logic instead of re-scanning multiple ways |

## Validation Checklist

- `get_now_playing()` returns sensible `starttime`, `endtime`, and `paused` fields during active playback
- after a song finishes, no stale `started-on` or end-marker keys remain
- after the queue becomes empty, no stale active-song keys remain
- skipping a song leaves the system ready for the next track with clean state
- repeated recommendation failures do not spam logs every loop tick
- inactive temporary nests with ghost queue entries no longer survive cleanup incorrectly

## Suggested Commit Shape

If implemented incrementally, split into:

1. `fix(player): centralize master player state cleanup`
2. `fix(player): make short-track and fill-retry behavior explicit`
3. `fix(nests): base cleanup on effective queue occupancy`

If done in one PR, keep the PR description grouped by:

- player-state cleanup
- failure/backoff behavior
- nest cleanup correctness

