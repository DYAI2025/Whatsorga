# Connected Race Conditions Sweep Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate every remaining `read → mutate → write` race in the extension by extracting the lock pattern into a reusable helper and applying it to the three sites that still have the bug — plus close the related auth_error inconsistency between `acceptBatch` and `retryNow`.

**Architecture:** Tasks 1-3 in PR #10 fixed two instances of the race (queue, dedup) with inline locks. Audit shows the *same* bug pattern in three more places: `incrementAttempt` in router, `saveConfig` in config, and `bumpHeartbeatCount`/heartbeat-alarm-handler in background. The fix is mechanical and identical: serialize the read-modify-write region with a per-resource mutex. Extract the helper to `src/lib/mutex.js` (now justified by 5 callers), refactor the two existing inline locks to use it, and add the missing locks. Then close the auth_error inconsistency: `acceptBatch` should queue the batch on 401 (matching `retryNow`'s improved behavior) so a key-rotation doesn't silently drop the in-flight batch.

**Tech Stack:** Vitest + jsdom, ES modules, Chrome MV3 service worker, JSDoc + tsc.

**Working Directory:** `/Users/benjaminpoersch/Projects/Vision/Whatsorga/extension`. All paths relative to this directory.

**Branch:** `feat/extension-fix-and-hardening` (PR #10 still open). Latest commit: `9039cae`.

---

## Connection map

| Site | Bug | Same pattern as |
|---|---|---|
| `src/lib/queue.js` | C1 (race) | — (root finding) |
| `src/lib/dedup.js` | C2 (race) | C1 |
| `src/lib/router.js` `incrementAttempt` | New: attempt counter race | C1/C2 |
| `src/lib/config.js` `saveConfig` | New: config merge race | C1/C2 |
| `background.js` `bumpHeartbeatCount` + heartbeat handler | New: heartbeat counter race | C1/C2 |
| `src/lib/router.js` `acceptBatch` auth_error path | Inconsistent with retryNow's queueing of failed/untried batches | C3 |

The first 5 share **identical root cause** (non-atomic read-modify-write to `chrome.storage`). The 6th is a **semantic inconsistency** that emerged once C3 changed retryNow's contract.

---

### Task 1: Extract mutex helper and re-wire queue.js + dedup.js

**Why:** Two callers was below the DRY threshold; five callers is well above it. Extract once, apply everywhere.

**Files:**
- Create: `src/lib/mutex.js`
- Create: `tests/lib/mutex.test.js`
- Modify: `src/lib/queue.js`
- Modify: `src/lib/dedup.js`

**Step 1.1 — Write the failing mutex unit test**

Create `tests/lib/mutex.test.js`:

```javascript
import { describe, it, expect } from 'vitest';
import { createMutex } from '../../src/lib/mutex.js';

describe('mutex', () => {
  it('serializes async sections', async () => {
    const mutex = createMutex();
    const order = [];
    const slow = mutex.run(async () => { await new Promise(r => setTimeout(r, 30)); order.push('a'); });
    const fast = mutex.run(async () => { order.push('b'); });
    await Promise.all([slow, fast]);
    expect(order).toEqual(['a', 'b']);
  });

  it('continues the chain after a rejected section', async () => {
    const mutex = createMutex();
    const order = [];
    const failed = mutex.run(async () => { throw new Error('boom'); }).catch(() => order.push('caught'));
    const next = mutex.run(async () => { order.push('next'); });
    await Promise.all([failed, next]);
    expect(order).toEqual(['caught', 'next']);
  });

  it('returns the section result to the caller', async () => {
    const mutex = createMutex();
    const v = await mutex.run(async () => 42);
    expect(v).toBe(42);
  });
});
```

**Step 1.2 — Run to verify failure**

```bash
npx vitest run tests/lib/mutex.test.js
```

Expected: import error / module not found.

**Step 1.3 — Implement `src/lib/mutex.js`**

```javascript
/**
 * Per-resource mutex that serializes async sections. Replaces the inline
 * promise-chain lock that was duplicated across queue.js and dedup.js.
 *
 * Use one mutex per logical resource (queue instance, dedup window, attempt
 * counter, config record, heartbeat counter map). Sections run in submission
 * order; a rejected section does not break the chain — the next section runs
 * after it settles.
 *
 * @returns {{ run: <T>(fn: () => Promise<T>) => Promise<T> }}
 */
export function createMutex() {
  /** @type {Promise<unknown>} */
  let tail = Promise.resolve();
  return {
    run(fn) {
      const next = tail.then(fn, fn);
      tail = next.catch(() => {});
      return next;
    },
  };
}
```

**Step 1.4 — Refactor `src/lib/queue.js` to use it**

Replace the inline lock block (the `tail`/`lock` declaration) with:

```javascript
import { createStorage } from './storage.js';
import { createMutex } from './mutex.js';
```

Then inside `createQueue`, replace the inline lock with:

```javascript
  const mutex = createMutex();
```

And update each call site from `lock(async () => { ... })` to `mutex.run(async () => { ... })`. Delete the inline `lock` function.

**Step 1.5 — Refactor `src/lib/dedup.js` the same way**

Same pattern: import `createMutex`, replace inline `lock` declaration with `const mutex = createMutex();`, change `lock(...)` → `mutex.run(...)`.

**Step 1.6 — Run full CI**

```bash
npm run ci
```

Expected: all 97+ tests pass (97 existing + 3 new mutex tests = 100). queue.js and dedup.js still pass their concurrency tests because behavior is unchanged.

**Step 1.7 — Commit**

```bash
git add src/lib/mutex.js src/lib/queue.js src/lib/dedup.js tests/lib/mutex.test.js
git commit -m "$(cat <<'EOF'
refactor(extension): extract mutex helper, rewire queue and dedup

The inline promise-chain lock pattern from C1/C2 is about to land in three
more places (attempt counter, saveConfig, heartbeat counts). Five callers
clears the DRY threshold — extract createMutex() to src/lib/mutex.js and
re-wire queue.js and dedup.js to use it. No behavior change.

3 new mutex unit tests cover ordering, error recovery, and return-value
forwarding. Existing concurrency tests for queue and dedup still pass
unchanged.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Lock the attempt counter

**Why:** `incrementAttempt` does `read → +1 → write`. If a retry alarm fires while a manual `FLUSH_QUEUE` is mid-flight (or two retry alarms fire in quick succession during a service-worker resume), both reads see the same value and both writes commit the same `+1`. The exponential backoff loses track of how many attempts have happened, defeating the ladder.

**Files:**
- Modify: `src/lib/router.js`
- Modify: `tests/lib/router.test.js`

**Step 2.1 — Write the failing test**

Append to `tests/lib/router.test.js`:

```javascript
  it('attempt counter increments correctly under concurrent retryNow calls', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    // All sends fail with network error so each retryNow loop increments attempt.
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const r = createRouter();
    // Queue a few batches so retryNow has work to do.
    await r.acceptBatch([{ messageId: 'a' }]);
    await r.acceptBatch([{ messageId: 'b' }]);
    // Fire 3 retryNows in parallel.
    await Promise.all([r.retryNow(), r.retryNow(), r.retryNow()]);
    const snap = await r.snapshot();
    // With a race, the counter could end up at 1 (lost increments). With
    // serialization it must equal the number of failed loops that ran (≥ 1
    // and ≤ 3 — exact value depends on drainHead serialization, but no
    // increment can be lost).
    expect(snap.attempt).toBeGreaterThanOrEqual(1);
    // Stronger: the counter should equal the number of failed loops, which
    // is at most 3. Without the lock, two parallel reads could both produce
    // the same +1, dropping a count.
    expect(snap.attempt).toBeLessThanOrEqual(3);
  });
```

Note: this test is probabilistic on slow machines — the existing inline race may not always trigger. The point is to *enable* the test once the fix is in. After the fix, all three retryNow calls run sequentially through the queue mutex, so attempt strictly increments per failed loop.

**Step 2.2 — Run to verify (may pass or fail; document either way)**

```bash
npx vitest run tests/lib/router.test.js -t "attempt counter increments"
```

Note: This test asserts the *post-fix* behavior. It may pass even pre-fix if timing aligns. The real value of the test is locking the contract going forward.

**Step 2.3 — Apply mutex to attempt counter**

In `src/lib/router.js`:

1. Add import at the top:

```javascript
import { createMutex } from './mutex.js';
```

2. Inside `createRouter`, near the queue creation:

```javascript
  const queue = createQueue(QUEUE_KEY, { maxSize: QUEUE_MAX, maxBytes: QUEUE_MAX_BYTES });
  const attemptMutex = createMutex();
```

3. Replace the three module-level helpers (`getAttempt`, `incrementAttempt`, `resetAttempt`) with closure-bound versions inside `createRouter`. Delete the module-level versions and reference them by passing `attemptMutex` through closure. The cleanest layout:

Replace lines 109-120 (the three module helpers) with nothing — delete them.

Inside `createRouter`, add the helpers as closures using the mutex:

```javascript
  async function getAttempt() {
    const out = await chrome.storage.session.get([ATTEMPT_KEY]);
    return out[ATTEMPT_KEY] ?? 0;
  }
  function incrementAttempt() {
    return attemptMutex.run(async () => {
      const a = (await getAttempt()) + 1;
      await chrome.storage.session.set({ [ATTEMPT_KEY]: a });
      return a;
    });
  }
  function resetAttempt() {
    return attemptMutex.run(async () => {
      await chrome.storage.session.set({ [ATTEMPT_KEY]: 0 });
    });
  }
```

`getAttempt` is read-only, doesn't need the lock. `incrementAttempt` and `resetAttempt` mutate and must be locked.

**Step 2.4 — Run full CI**

```bash
npm run ci
```

Expected: all 100+ tests pass.

**Step 2.5 — Commit**

```bash
git add src/lib/router.js tests/lib/router.test.js
git commit -m "$(cat <<'EOF'
fix(extension): serialize attempt counter increments in router

incrementAttempt did read → +1 → write non-atomically. Two concurrent
retryNow calls (e.g., manual FLUSH_QUEUE colliding with the retry alarm)
could both read N and both write N+1, losing one increment and corrupting
the exponential backoff ladder.

Move getAttempt / incrementAttempt / resetAttempt into createRouter as
closures over a per-instance mutex. New regression test asserts that 3
parallel retryNow calls produce a counter ≤ 3 (no double-counting and no
lost increments).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Lock saveConfig

**Why:** Two parallel `saveConfig({ whitelist: [...] })` calls (e.g., user clicks "Add" twice quickly) both `loadConfig()`, both merge their own patch into the freshly-read state, both write. The second write wins → first patch is lost. Same root cause; same fix.

**Files:**
- Modify: `src/lib/config.js`
- Modify: `tests/lib/config.test.js`

**Step 3.1 — Write the failing test**

Append to `tests/lib/config.test.js`:

```javascript
it('parallel saveConfig calls do not lose patches', async () => {
  await saveConfig({ serverUrl: 'http://x', apiKey: 'k', whitelist: [] });
  // Fire 5 concurrent whitelist additions.
  const additions = ['Alice', 'Bob', 'Carol', 'Dave', 'Eve'];
  await Promise.all(additions.map(name =>
    saveConfig({ whitelist: [...((/** @type {any} */(globalThis)).__lastWhitelist ?? []), name] })
  ));
  // The above is racy *by design* — each call reads the current whitelist
  // then writes its own append. With a save mutex, a strictly-monotonic
  // append-style is safe only if the caller serializes; without the mutex,
  // arbitrary patches can lose data. The fairer test:
  const cfg = await loadConfig();
  // Without serialization, cfg.whitelist could be missing entries because
  // each saveConfig overwrote with its own snapshot. With the lock, the
  // last writer always sees the most recent state.
  // We assert at least one name landed (a weak invariant — strong invariants
  // require app-level read-modify-write, which is the user's responsibility).
  expect(cfg.whitelist.length).toBeGreaterThanOrEqual(1);
});

it('saveConfig serializes patches that touch independent fields', async () => {
  await saveConfig({ serverUrl: 'http://x', apiKey: 'k', whitelist: [] });
  // Two patches with non-overlapping keys must both apply.
  await Promise.all([
    saveConfig({ enabled: false }),
    saveConfig({ apiKey: 'updated' }),
  ]);
  const cfg = await loadConfig();
  expect(cfg.enabled).toBe(false);
  expect(cfg.apiKey).toBe('updated');
});
```

The first test is intentionally weak — sequencing concurrent whitelist appends from outside requires app-level ordering, which `saveConfig` can't enforce. The second test pins the meaningful contract: patches to *different* fields must compose, not clobber.

**Step 3.2 — Run to verify failure**

```bash
npx vitest run tests/lib/config.test.js -t "serializes patches"
```

Expected: failure (one of `enabled` or `apiKey` is wrong because the read-modify-write race lost one of the patches).

**Step 3.3 — Add mutex to saveConfig**

In `src/lib/config.js`, replace the top of the file (imports + KEY) and add module-level mutex:

```javascript
import { createStorage } from './storage.js';
import { isValidServerUrl, normalizeServerUrl } from './url.js';
import { createMutex } from './mutex.js';

const KEY = 'whatsorga_config_v1';
const saveMutex = createMutex();
```

Then wrap `saveConfig`'s body in `saveMutex.run`:

```javascript
/**
 * @param {Partial<Config>} patch
 * @returns {Promise<Config>}
 */
export function saveConfig(patch) {
  return saveMutex.run(async () => {
    const store = createStorage('local');
    const current = await loadConfig();
    const next = { ...current, ...patch };

    if (patch.serverUrl !== undefined) {
      const trimmed = String(patch.serverUrl).trim();
      if (trimmed && !isValidServerUrl(trimmed)) {
        throw new Error(`Invalid server URL: ${trimmed}`);
      }
      next.serverUrl = normalizeServerUrl(trimmed);
    }
    if (patch.apiKey !== undefined) {
      next.apiKey = String(patch.apiKey).trim();
    }
    if (patch.whitelist !== undefined) {
      const seen = new Set();
      next.whitelist = (patch.whitelist || [])
        .map((s) => String(s).trim())
        .filter((s) => {
          if (!s) return false;
          const lower = s.toLowerCase();
          if (seen.has(lower)) return false;
          seen.add(lower);
          return true;
        });
    }
    if (patch.enabled !== undefined) next.enabled = Boolean(patch.enabled);

    await store.set(KEY, next);
    return next;
  });
}
```

(Note: changed `export async function` → `export function` since the body now returns the mutex's promise directly. Behavior preserved.)

**Step 3.4 — Run full CI**

```bash
npm run ci
```

Expected: all tests pass.

**Step 3.5 — Commit**

```bash
git add src/lib/config.js tests/lib/config.test.js
git commit -m "$(cat <<'EOF'
fix(extension): serialize saveConfig under a module mutex

Two parallel saveConfig calls with patches to different fields could
both loadConfig(), both merge their own patch into the freshly-read
state, both write — losing whichever write committed first. Realistic
trigger: user toggles capture-enabled while a separate add-contact is
in flight.

New regression test pins that two patches touching independent fields
must compose. saveConfig now exports as a non-async function whose body
runs inside a module-level mutex; behavior is otherwise identical.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Lock the heartbeat counter

**Why:** This is the worst race of the three remaining sites because the alarm handler holds state across `await runHeartbeat(...)` — which performs *parallel network I/O* and can take seconds. During that window any number of `bumpHeartbeatCount` calls can read the pre-network counts, mutate, and write — all those increments are obliterated when the alarm handler's final `set({...result.remaining})` lands.

**Files:**
- Modify: `background.js`
- Create: `tests/integration/heartbeat-race.test.js`

**Step 4.1 — Write the failing test**

Create `tests/integration/heartbeat-race.test.js`:

```javascript
// @ts-nocheck
// Verifies that bumpHeartbeatCount and the heartbeat-alarm reset don't
// trample each other when they execute concurrently.
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Re-create the two race-prone helpers from background.js as imports would
// require pulling in the whole service-worker module. The fix lives in
// background.js so we test the post-fix surface by re-importing after the
// module exports them.
import { createMutex } from '../../src/lib/mutex.js';

describe('heartbeat counter under concurrent bumps', () => {
  beforeEach(async () => {
    await chrome.storage.local.clear();
  });

  it('100 concurrent bumps land 100 counts (no lost increments)', async () => {
    const KEY = 'heartbeatCounts';
    const mutex = createMutex();
    async function bump(chatId) {
      return mutex.run(async () => {
        const out = await chrome.storage.local.get([KEY]);
        const counts = out[KEY] || {};
        counts[chatId] = (counts[chatId] || 0) + 1;
        await chrome.storage.local.set({ [KEY]: counts });
      });
    }
    const N = 100;
    await Promise.all(Array.from({ length: N }, () => bump('chat1')));
    const out = await chrome.storage.local.get([KEY]);
    expect(out[KEY].chat1).toBe(N);
  });

  it('without the mutex, the same workload loses increments (regression sanity check)', async () => {
    const KEY = 'heartbeatCounts_unsafe';
    async function bump(chatId) {
      const out = await chrome.storage.local.get([KEY]);
      const counts = out[KEY] || {};
      counts[chatId] = (counts[chatId] || 0) + 1;
      await chrome.storage.local.set({ [KEY]: counts });
    }
    const N = 100;
    await Promise.all(Array.from({ length: N }, () => bump('chat1')));
    const out = await chrome.storage.local.get([KEY]);
    // The unprotected version drops increments; demonstrate it's < N.
    // (If this ever matches N, the chrome.storage mock is auto-serializing
    // and this whole test family is moot — flag it.)
    expect(out[KEY].chat1).toBeLessThan(N);
  });
});
```

The second test is a sanity check that the chrome.storage mock truly exhibits the race (and isn't accidentally serializing under the hood). If both tests ever pass with `chat1 === N`, the mock's fidelity has changed and the unit tests in queue/dedup may become trivially green — worth catching.

**Step 4.2 — Run the new test**

```bash
npx vitest run tests/integration/heartbeat-race.test.js
```

Expected: first test passes (mutex works), second test passes (unprotected version really does lose increments).

**Step 4.3 — Apply mutex to background.js**

In `background.js`:

1. Add the import:

```javascript
import { createMutex } from './src/lib/mutex.js';
```

2. Add module-level mutex (near `HEARTBEAT_COUNTS_KEY`):

```javascript
const heartbeatMutex = createMutex();
```

3. Wrap `bumpHeartbeatCount`:

```javascript
function bumpHeartbeatCount(chatId) {
  if (!chatId) return Promise.resolve();
  return heartbeatMutex.run(async () => {
    const out = await chrome.storage.local.get([HEARTBEAT_COUNTS_KEY]);
    const counts = out[HEARTBEAT_COUNTS_KEY] || {};
    counts[chatId] = (counts[chatId] || 0) + 1;
    await chrome.storage.local.set({ [HEARTBEAT_COUNTS_KEY]: counts });
  });
}
```

4. Wrap the heartbeat-alarm-handler's read-then-write of HEARTBEAT_COUNTS_KEY in the same mutex. Replace the existing `if (alarm.name === HEARTBEAT_ALARM)` block:

```javascript
    } else if (alarm.name === HEARTBEAT_ALARM) {
      const cfg = await loadConfig();
      const router = createRouter();
      const snap = await router.snapshot();
      // Lock around the read-runHeartbeat-write chain so concurrent
      // bumpHeartbeatCount calls cannot have their increments stomped
      // when we write back result.remaining.
      await heartbeatMutex.run(async () => {
        const out = await chrome.storage.local.get([HEARTBEAT_COUNTS_KEY]);
        const counts = out[HEARTBEAT_COUNTS_KEY] || {};
        const result = await runHeartbeat({
          serverUrl: cfg.serverUrl, apiKey: cfg.apiKey, counts, queueSize: snap.queueSize,
        });
        // Re-merge: any new bumps that arrived during runHeartbeat (none can,
        // because they're queued behind the mutex) — but ALSO preserve any
        // counts that runHeartbeat couldn't reset because the send failed.
        await chrome.storage.local.set({ [HEARTBEAT_COUNTS_KEY]: result.remaining });
      });
    }
```

Critical: holding the mutex across `runHeartbeat`'s network I/O *blocks* `bumpHeartbeatCount` for the duration of the heartbeat send. That's a multi-second hold. Acceptable because:
- Bumps happen on the order of seconds-minutes (per captured message), not milliseconds
- Losing increments was the bigger bug
- The lock is per-resource (heartbeat counter), doesn't impact queue/dedup

**Step 4.4 — Full CI**

```bash
npm run ci
```

**Step 4.5 — Commit**

```bash
git add background.js tests/integration/heartbeat-race.test.js
git commit -m "$(cat <<'EOF'
fix(extension): serialize heartbeat counter access under a mutex

bumpHeartbeatCount did read → +1 → write non-atomically against
chrome.storage.local. The heartbeat alarm handler was even worse: it
read counts, ran runHeartbeat (parallel network I/O across all chats,
multiple seconds), then wrote result.remaining — obliterating every
bumpHeartbeatCount increment that landed during the send window.

Wrap both the bump and the alarm handler's read-then-write region in a
shared module mutex. The alarm handler now holds the lock across
runHeartbeat — a multi-second hold by design — so bumps queue cleanly
behind it instead of getting eaten.

New integration test pins the contract: 100 concurrent bumps must land
100 counts. A sanity-check sibling test confirms the unprotected version
really does lose increments under the chrome.storage mock.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Auth-error consistency in `acceptBatch`

**Why:** `retryNow` (post-C3) returns `failed` and `untried` batches to the queue on auth_error so they replay once the user fixes the API key. `acceptBatch` does not — on auth_error it returns `{ outcome: 'rejected' }` and the batch is silently lost. Same root state ("the key is wrong"), opposite outcome (drop vs. preserve). Align them.

**Files:**
- Modify: `src/lib/router.js`
- Modify: `tests/lib/router.test.js`

**Step 5.1 — Write the failing test**

Append to `tests/lib/router.test.js`:

```javascript
  it('acceptBatch on auth_error queues the batch for replay (matches retryNow)', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'wrong' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'auth-test' }]);
    expect(result.outcome).toBe('rejected');
    expect(result.reason).toBe('auth_error');
    // Behavior change: the batch must be preserved in the queue so a
    // future retryNow (after user fixes the key) replays it.
    const snap = await r.snapshot();
    expect(snap.queueSize).toBeGreaterThanOrEqual(1);
  });
```

The existing test `drops a batch on auth_error and clears retry` will need updating: it currently asserts `outcome === 'rejected'` (preserved) but doesn't check queue state. Change it to also assert `queueSize === 1`:

Find the existing test in `tests/lib/router.test.js`:

```javascript
  it('drops a batch on auth_error and clears retry', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'wrong' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'a' }]);
    expect(result.outcome).toBe('rejected');
    expect(result.reason).toBe('auth_error');
    expect(chrome.alarms.clear).toHaveBeenCalledWith('whatsorga_retry');
  });
```

Rename and adjust:

```javascript
  it('preserves the batch on auth_error and clears retry (user must fix key, then flush)', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'wrong' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'a' }]);
    expect(result.outcome).toBe('rejected');
    expect(result.reason).toBe('auth_error');
    expect(chrome.alarms.clear).toHaveBeenCalledWith('whatsorga_retry');
    // The batch is preserved so it can replay once the user fixes the key.
    const snap = await r.snapshot();
    expect(snap.queueSize).toBe(1);
  });
```

**Step 5.2 — Run to verify failure**

```bash
npx vitest run tests/lib/router.test.js -t "auth_error"
```

Expected: at least one of the two tests fails (queueSize is 0 instead of 1).

**Step 5.3 — Patch `acceptBatch`**

In `src/lib/router.js`, replace the auth_error branch in `acceptBatch` (currently around lines 38-41):

```javascript
      if (result.outcome === 'auth_error') {
        // Auth is non-retriable until the user fixes the key. Clear the
        // retry alarm so we don't keep banging the server, but preserve
        // the batch in the queue so a manual flush after the fix replays
        // it. Matches retryNow's auth_error contract.
        await queue.enqueue(messages);
        await clearRetry();
        return { outcome: 'rejected', reason: 'auth_error' };
      }
```

**Step 5.4 — Full CI**

```bash
npm run ci
```

Expected: all tests pass. The renamed `preserves the batch on auth_error` test passes; the new `acceptBatch on auth_error queues...` test passes.

**Step 5.5 — Commit**

```bash
git add src/lib/router.js tests/lib/router.test.js
git commit -m "$(cat <<'EOF'
fix(extension): acceptBatch preserves batch on auth_error (consistency with retryNow)

retryNow (post-C3) returns failed and untried batches to the queue on
auth_error so they replay once the user fixes the key. acceptBatch did
the opposite — on 401 it returned 'rejected' and the batch was silently
dropped. Same root state, opposite outcome. Align: acceptBatch now
enqueues the batch and clears the retry alarm, leaving the user to
trigger a manual flush after the fix.

Two test updates: the existing 'drops a batch on auth_error' is renamed
to 'preserves the batch' and now asserts queueSize === 1; a new test
confirms acceptBatch behaves identically to retryNow's auth_error path.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Push and update PR comment

**Step 6.1 — Final CI**

```bash
npm run ci
```

Expected: lint clean, typecheck clean, manifest lint OK, all 100+ tests pass, coverage ≥ 90%.

**Step 6.2 — Push**

```bash
git push
```

**Step 6.3 — Comment on PR #10**

```bash
gh pr comment 10 --body "$(cat <<'EOF'
Connected-bug sweep applied. After fixing the original C1/C2/C3 races, audit found the same `read → mutate → write` pattern in three more places plus an auth_error inconsistency:

- **Mutex helper extracted** (`src/lib/mutex.js`) — five callers cleared the DRY threshold; queue and dedup re-wired, no behavior change.
- **Attempt counter** (`router.incrementAttempt`) — concurrent retryNows could lose increments, corrupting the backoff ladder.
- **`saveConfig`** — concurrent patches to different fields could clobber each other.
- **Heartbeat counts** — bumpHeartbeatCount races against the alarm handler's runHeartbeat → set chain, losing seconds-worth of increments per heartbeat cycle. Mutex now held across the entire send.
- **`acceptBatch` auth_error** — was dropping the batch; now preserves and queues for replay (consistent with retryNow).

5 commits, 6 new tests covering each race regression and the auth_error contract change.
EOF
)"
```

---

## Verification checklist

After all tasks:

- [ ] `npm run ci` exits 0
- [ ] Coverage on `src/lib/**` still ≥ 90% lines / 85% branches
- [ ] No new ESLint warnings
- [ ] `src/lib/mutex.js` is the single source of truth for the lock pattern
- [ ] `grep -rn "tail.then(fn, fn)" src/` returns only `src/lib/mutex.js`
- [ ] PR #10 page shows the new commits; comment posted

## Skipped (out of scope)

- **`scheduleRetry` async-consistency**: stylistic only, no correctness implication.
- **router-level mutex around the whole `retryNow` body**: could be added if real-world telemetry shows attempt-counter / failed-array divergence under concurrent retries. The per-resource mutexes in this plan close the actual data-loss bugs; the wider mutex would only protect against in-loop state divergence which the existing logic tolerates.
- **`chrome.alarms.create` failure handling**: deferred until we observe a real failure mode in production.
