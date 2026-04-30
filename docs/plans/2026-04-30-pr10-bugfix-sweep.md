# PR #10 Bug Fix Sweep Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close out the seven bugs surfaced by code review of PR #10 (`feat/extension-fix-and-hardening`) before merging to main.

**Architecture:** All fixes target files already touched by PR #10. Race conditions in `queue.js` and `dedup.js` are resolved by per-instance promise-chain serialization (no external dep). The `retryNow` queue-loss bug is a 2-line correction. Manifest hardening drops two unused/overscoped permissions. The byte-cap on queue is a new option on the existing `createQueue` factory. Each fix lands as its own commit on the same branch (`feat/extension-fix-and-hardening`) so PR #10 absorbs them.

**Tech Stack:** Vitest + jsdom, ES modules, Chrome MV3 service worker (`chrome.storage.session`, `chrome.alarms`), JSDoc + tsc.

**Working Directory:** `/Users/benjaminpoersch/Projects/Vision/Whatsorga/extension`. All paths below are relative to this directory unless prefixed.

**Branch:** `feat/extension-fix-and-hardening` (already checked out, PR #10 open).

---

## Severity legend

| ID | Severity | Bug | File |
|----|----------|-----|------|
| C1 | Critical | Race in `queue.enqueue`/`drainHead` loses messages | `src/lib/queue.js` |
| C2 | Critical | Race in `dedup.isFresh` allows duplicates | `src/lib/dedup.js` |
| C3 | Critical | `retryNow` auth_error drops unprocessed queue head | `src/lib/router.js` |
| H1 | High | `host_permissions: "https://*/*"` is wildcard | `manifest.json` |
| M1 | Medium | Queue byte-budget unrealistic for audio | `src/lib/queue.js` |
| M2 | Medium | `activeTab` permission unused | `manifest.json` |
| L1 | Low | Diagnostic export click handler missing try/catch | `popup.js` |

H1 + M2 share one task (both manifest edits with one new test).

---

### Task 1 (C1): Serialize queue operations

**Why:** `enqueue`, `drainHead`, `returnHead` all do `read → mutate → write`. Two concurrent calls can read the same array, both write, second clobbers first → message loss. The whole queue exists to *prevent* loss. Fix is a per-instance promise chain so every operation runs to completion before the next starts.

**Files:**
- Modify: `src/lib/queue.js`
- Modify: `tests/lib/queue.test.js`

**Step 1.1 — Write the failing concurrency test**

Append to `tests/lib/queue.test.js`:

```javascript
it('enqueues concurrently without losing items', async () => {
  const q = createQueue('q_concurrent', { maxSize: 1000 });
  const N = 100;
  const promises = [];
  for (let i = 0; i < N; i++) promises.push(q.enqueue({ id: i }));
  await Promise.all(promises);
  expect(await q.size()).toBe(N);
});

it('drains and returns concurrently without item loss', async () => {
  const q = createQueue('q_drain_concurrent', { maxSize: 1000 });
  for (let i = 0; i < 10; i++) await q.enqueue({ id: i });
  const [a, b] = await Promise.all([q.drainHead(5), q.drainHead(5)]);
  expect(a.length + b.length).toBe(10);
  expect(await q.size()).toBe(0);
});
```

**Step 1.2 — Run tests to verify they fail**

```bash
npx vitest run tests/lib/queue.test.js -t "concurrent" 2>&1 | tail -20
```

Expected: at least one of the two new tests fails (size < N, or `a` and `b` overlap).

**Step 1.3 — Add the lock to `createQueue`**

In `src/lib/queue.js`, add the lock helper at the top of `createQueue` and wrap every method that does read-then-write:

```javascript
export function createQueue(key, opts) {
  const store = createStorage(STORAGE_AREA);
  const droppedKey = key + DROPPED_KEY_SUFFIX;
  const maxSize = opts.maxSize;

  // Per-instance mutex: serializes all read-modify-write operations.
  let tail = Promise.resolve();
  /** @template T @param {() => Promise<T>} fn @returns {Promise<T>} */
  function lock(fn) {
    const next = tail.then(fn, fn);
    tail = next.catch(() => {});
    return next;
  }

  async function read() {
    return (await store.get(key, [])) || [];
  }
  async function write(arr) {
    await store.set(key, arr);
  }

  return {
    /** @param {unknown} item */
    enqueue(item) {
      return lock(async () => {
        const arr = await read();
        arr.push(item);
        let dropped = 0;
        while (arr.length > maxSize) { arr.shift(); dropped++; }
        if (dropped > 0) {
          const prev = (await store.get(droppedKey, 0)) || 0;
          await store.set(droppedKey, prev + dropped);
        }
        await write(arr);
      });
    },
    async size() {
      return (await read()).length;
    },
    /** @param {number} n */
    async peek(n) {
      return (await read()).slice(0, n);
    },
    /** @param {number} n */
    drainHead(n) {
      return lock(async () => {
        const arr = await read();
        const head = arr.splice(0, n);
        await write(arr);
        return head;
      });
    },
    /** @param {unknown[]} items */
    returnHead(items) {
      return lock(async () => {
        const arr = await read();
        await write(items.concat(arr));
      });
    },
    clear() {
      return lock(async () => write([]));
    },
    async droppedCount() {
      return (await store.get(droppedKey, 0)) || 0;
    },
    resetDroppedCount() {
      return lock(async () => store.set(droppedKey, 0));
    },
  };
}
```

Note: `size()` and `peek()` are read-only and don't need the lock. `droppedCount()` is also read-only.

**Step 1.4 — Run tests to verify they pass**

```bash
npx vitest run tests/lib/queue.test.js
```

Expected: all queue tests pass (5 original + 2 new = 7).

**Step 1.5 — Commit**

```bash
git add src/lib/queue.js tests/lib/queue.test.js
git commit -m "$(cat <<'EOF'
fix(extension): serialize queue read-modify-write operations (C1)

Two concurrent enqueue or drainHead calls could race on the
`read → mutate → write` pattern and lose messages — the exact failure
mode the durable queue exists to prevent. Add a per-instance promise-chain
lock so every mutating op runs to completion before the next starts.

Two new concurrency tests assert no item loss under 100 parallel enqueues
and overlapping drainHead calls.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2 (C2): Serialize dedup operations

**Why:** Same race pattern. Two simultaneous `isFresh(id)` calls can both pass the `arr.includes(id)` check before either writes, both return `true`, message gets sent twice. Same fix.

**Files:**
- Modify: `src/lib/dedup.js`
- Modify: `tests/lib/dedup.test.js`

**Step 2.1 — Write the failing test**

Append to `tests/lib/dedup.test.js`:

```javascript
it('returns true for the same id exactly once under concurrency', async () => {
  const dedup = createDedup({ key: 'concurrent_id', windowSize: 100 });
  const id = 'msg-race';
  const promises = [];
  for (let i = 0; i < 10; i++) promises.push(dedup.isFresh(id));
  const results = await Promise.all(promises);
  expect(results.filter(Boolean).length).toBe(1);
});
```

**Step 2.2 — Run to verify failure**

```bash
npx vitest run tests/lib/dedup.test.js -t "concurrency"
```

Expected: trueCount > 1 (likely all 10 return true).

**Step 2.3 — Add lock to `createDedup`**

Replace `src/lib/dedup.js` with:

```javascript
import { createStorage } from './storage.js';

/**
 * Rolling-window message deduplicator backed by chrome.storage. Caller
 * uses isFresh(id) — first call returns true and marks the id seen,
 * subsequent calls return false until eviction by the window.
 *
 * @param {{ key:string, windowSize:number, area?:'local'|'session' }} opts
 */
export function createDedup({ key, windowSize, area = 'local' }) {
  const store = createStorage(area);

  let tail = Promise.resolve();
  /** @template T @param {() => Promise<T>} fn @returns {Promise<T>} */
  function lock(fn) {
    const next = tail.then(fn, fn);
    tail = next.catch(() => {});
    return next;
  }

  return {
    /** @param {string} id */
    isFresh(id) {
      return lock(async () => {
        const arr = (await store.get(key, [])) || [];
        if (arr.includes(id)) return false;
        arr.push(id);
        while (arr.length > windowSize) arr.shift();
        await store.set(key, arr);
        return true;
      });
    },
    async size() {
      return ((await store.get(key, [])) || []).length;
    },
    clear() {
      return lock(async () => store.set(key, []));
    },
  };
}
```

**Step 2.4 — Run to verify pass**

```bash
npx vitest run tests/lib/dedup.test.js
```

Expected: all 6 dedup tests pass (5 original + 1 new).

**Step 2.5 — Commit**

```bash
git add src/lib/dedup.js tests/lib/dedup.test.js
git commit -m "$(cat <<'EOF'
fix(extension): serialize dedup isFresh under concurrency (C2)

Two simultaneous isFresh(id) calls could both pass the includes() check
before either wrote, returning true twice for the same id. Same lock
pattern as queue.js.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3 (C3): Preserve unprocessed batches on auth_error

**Why:** `retryNow` calls `drainHead(10)` which removes up to 10 batches from the queue. If batch 0 hits 401, the loop returns early without putting batches 1..9 back. They are silently lost. Fix: on auth_error, return the not-yet-tried tail to the queue head before bailing.

**Files:**
- Modify: `src/lib/router.js`
- Modify: `tests/lib/router.test.js`

**Step 3.1 — Write the failing test**

Append to `tests/lib/router.test.js`:

```javascript
it('retryNow preserves unprocessed batches in queue on auth_error', async () => {
  await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
  let calls = 0;
  vi.stubGlobal('fetch', vi.fn(async () => {
    calls++;
    // calls 1+2: queue both batches via network error
    if (calls <= 2) throw new TypeError('net');
    // call 3 (retryNow's first send): 401, halts the drain
    return new Response('', { status: 401 });
  }));
  const r = createRouter();
  await r.acceptBatch([{ messageId: 'a' }]);
  await r.acceptBatch([{ messageId: 'b' }]);
  // Both batches now queued. retryNow drains both, first one hits 401.
  const result = await r.retryNow();
  expect(result.outcome).toBe('auth_error');
  // The second batch was never even tried — must remain in the queue.
  const snap = await r.snapshot();
  expect(snap.queueSize).toBeGreaterThanOrEqual(1);
});
```

**Step 3.2 — Run to verify failure**

```bash
npx vitest run tests/lib/router.test.js -t "preserves unprocessed"
```

Expected: `snap.queueSize` is 0, test fails.

**Step 3.3 — Patch `retryNow`**

In `src/lib/router.js`, replace the `retryNow` function (currently lines 49-80) with:

```javascript
    async retryNow() {
      const cfg = await loadConfig();
      if (!isConfigured(cfg)) return { outcome: 'skipped', reason: 'not_configured' };
      const head = await queue.drainHead(10);
      if (head.length === 0) {
        await clearRetry();
        await resetAttempt();
        return { outcome: 'idle' };
      }
      const failed = [];
      for (let i = 0; i < head.length; i++) {
        const batch = head[i];
        const r = await sendBatch({
          serverUrl: cfg.serverUrl, apiKey: cfg.apiKey, messages: batch, eventVersion: cfg.eventVersion,
        });
        if (r.outcome === 'auth_error') {
          // The current batch is rejected (auth is non-retriable). Put back
          // anything we hadn't tried yet so it isn't silently lost.
          const untried = head.slice(i + 1);
          if (untried.length > 0) await queue.returnHead(untried);
          await clearRetry();
          await resetAttempt();
          return { outcome: 'auth_error' };
        }
        if (r.outcome !== 'ok') failed.push(batch);
      }
      if (failed.length > 0) {
        await queue.returnHead(failed);
        const attempt = await incrementAttempt();
        scheduleRetry(backoffMinutes(attempt));
        return { outcome: 'partial', sent: head.length - failed.length, failed: failed.length };
      }
      await resetAttempt();
      if ((await queue.size()) > 0) scheduleRetry(0.1);
      else await clearRetry();
      return { outcome: 'ok', sent: head.length };
    },
```

Note the loop is now indexed so we know exactly which batches were unprocessed. The `failed.push` lives after the auth check so a 401 isn't double-counted.

**Step 3.4 — Run to verify pass**

```bash
npx vitest run tests/lib/router.test.js
```

Expected: all 11 router tests pass (10 original + 1 new). The pre-existing single-batch auth_error test still passes (no untried batches when auth_error hits the only batch).

**Step 3.5 — Commit**

```bash
git add src/lib/router.js tests/lib/router.test.js
git commit -m "$(cat <<'EOF'
fix(extension): retryNow returns untried batches to queue on auth_error (C3)

drainHead(10) removed up to 10 batches; if the first hit 401 the rest
were silently dropped. Now we slice the unprocessed tail back into the
queue head before returning auth_error.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4 (H1 + M2): Manifest permission hardening

**Why:**
- H1: `host_permissions: "https://*/*"` lets the extension fetch any https origin. Real targets are localhost (dev) and one user-configured server. Drop the wildcard.
- M2: `activeTab` is unused — content script auto-injects via `content_scripts` matches; no `chrome.tabs.executeScript` or click-to-activate flow exists. Drop it.

**Files:**
- Modify: `manifest.json`
- Modify: `tests/manifest.test.js`

**Step 4.1 — Write the failing test additions**

Append two `it()` blocks to `tests/manifest.test.js` inside the existing `describe`:

```javascript
  it('host_permissions does not include the https wildcard', () => {
    expect(manifest.host_permissions).not.toContain('https://*/*');
    // No catch-all wildcards at all.
    for (const h of manifest.host_permissions) {
      expect(h).not.toMatch(/\*:\/\/\*\/\*/);
      expect(h).not.toMatch(/^https?:\/\/\*\/\*$/);
    }
  });

  it('does not request activeTab (auto-injected content script does not need it)', () => {
    expect(manifest.permissions).not.toContain('activeTab');
  });
```

Also update the existing minimum-permissions test (currently asserts `['activeTab', 'alarms', 'storage']`) to drop `activeTab`:

```javascript
  it('declares the minimum permissions only', () => {
    expect([...manifest.permissions].sort()).toEqual(['alarms', 'storage'].sort());
  });
```

**Step 4.2 — Run to verify failure**

```bash
npx vitest run tests/manifest.test.js
```

Expected: at least 2 of the 3 modified/new tests fail.

**Step 4.3 — Edit `manifest.json`**

Remove `"activeTab"` from `permissions` and remove `"https://*/*"` from `host_permissions`. The manifest should look like:

```json
{
  "manifest_version": 3,
  "name": "WhatsOrga",
  "version": "0.3.0",
  "minimum_chrome_version": "122",
  "description": "Captures WhatsApp messages from whitelisted contacts, analyzes them with AI, and syncs appointments to your calendar",
  "permissions": [
    "storage",
    "alarms"
  ],
  "host_permissions": [
    "https://web.whatsapp.com/*",
    "http://localhost/*",
    "http://127.0.0.1/*"
  ],
  ...
}
```

(Leave the rest of the manifest unchanged.)

**Step 4.4 — Run full CI to verify**

```bash
npm run ci
```

Expected: all tests pass, including manifest invariants. If the popup or background still uses `activeTab` indirectly the smoke test would surface it — none does.

**Step 4.5 — Commit**

```bash
git add manifest.json tests/manifest.test.js
git commit -m "$(cat <<'EOF'
fix(extension): drop wildcard host_permission and unused activeTab (H1 + M2)

H1: https://*/* granted blanket access to every https origin. The
extension only needs the user-configured server (localhost is preserved
for dev; users with a remote server must add their host explicitly or
grant via a future optional_host_permissions flow).

M2: activeTab was unused — the content script auto-injects via
content_scripts matches and the popup makes no use of executeScript.

Both invariants now pinned in tests/manifest.test.js.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5 (M1): Byte-cap on queue

**Why:** `chrome.storage.session` is capped at 10 MB. With audio messages (~100 KB base64 each), the existing count-based cap of 200 batches can blow past quota. Add a `maxBytes` option that drops oldest items until total serialized size fits.

**Files:**
- Modify: `src/lib/queue.js`
- Modify: `src/lib/router.js` (pass `maxBytes`)
- Modify: `tests/lib/queue.test.js`

**Step 5.1 — Write the failing test**

Append to `tests/lib/queue.test.js`:

```javascript
it('drops oldest items when serialized total exceeds maxBytes', async () => {
  const q = createQueue('q_bytes', { maxSize: 1000, maxBytes: 1000 });
  const big = 'x'.repeat(400); // ~430 bytes once serialized
  for (let i = 0; i < 5; i++) await q.enqueue({ id: i, data: big });
  // 5 × ~430 = ~2150 bytes; budget is 1000 bytes
  const remaining = await q.peek(100);
  const totalBytes = JSON.stringify(remaining).length;
  expect(totalBytes).toBeLessThanOrEqual(1000);
  expect(await q.droppedCount()).toBeGreaterThan(0);
  // Most recent item must be retained
  expect(remaining[remaining.length - 1].id).toBe(4);
});
```

**Step 5.2 — Run to verify failure**

```bash
npx vitest run tests/lib/queue.test.js -t "maxBytes"
```

Expected: fails because `maxBytes` is currently ignored.

**Step 5.3 — Add `maxBytes` to enqueue**

In `src/lib/queue.js`, update the `enqueue` body inside the `lock(...)` call to also evict by bytes:

```javascript
    enqueue(item) {
      return lock(async () => {
        const arr = await read();
        arr.push(item);
        let dropped = 0;
        while (arr.length > maxSize) { arr.shift(); dropped++; }
        if (maxBytes) {
          while (arr.length > 1 && JSON.stringify(arr).length > maxBytes) {
            arr.shift();
            dropped++;
          }
        }
        if (dropped > 0) {
          const prev = (await store.get(droppedKey, 0)) || 0;
          await store.set(droppedKey, prev + dropped);
        }
        await write(arr);
      });
    },
```

And destructure `maxBytes` near `maxSize` at the top of `createQueue`:

```javascript
  const maxSize = opts.maxSize;
  const maxBytes = opts.maxBytes ?? 0; // 0 = no byte cap
```

Update the JSDoc:

```javascript
/**
 * @param {string} key Unique storage key.
 * @param {{ maxSize: number, maxBytes?: number }} opts
 */
```

`while (arr.length > 1 && ...)` keeps at least one item — even if a single batch exceeds the cap, dropping it loses everything; better to keep it and let the storage write fail loudly.

**Step 5.4 — Set the cap in router.js**

In `src/lib/router.js`, replace the queue creation line (currently line 18):

```javascript
  const queue = createQueue(QUEUE_KEY, { maxSize: QUEUE_MAX, maxBytes: QUEUE_MAX_BYTES });
```

And add a constant near the top of the file (alongside `QUEUE_MAX`):

```javascript
const QUEUE_MAX_BYTES = 8 * 1024 * 1024; // 8 MB — leaves 2 MB headroom under chrome.storage.session's 10 MB quota
```

**Step 5.5 — Run full test suite**

```bash
npm run ci
```

Expected: all tests pass; the new maxBytes test passes.

**Step 5.6 — Update `extension/README.md` storage map**

In the Storage map table, change the explanation paragraph below the table from:

> `chrome.storage.session` is capped at 10 MB. With `QUEUE_MAX = 200` batches × ~50 messages/batch × ~500 bytes/message ≈ 5 MB, leaving headroom. Going above this requires raising the storage quota with `"unlimitedStorage"` permission.

to:

> `chrome.storage.session` is capped at 10 MB. The router enforces both `QUEUE_MAX = 200` batches and `QUEUE_MAX_BYTES = 8 MB` of serialized payload — whichever evicts first. Audio messages (~100 KB each) hit the byte cap before the count cap, so dropped messages always reflect a real storage-pressure event surfaced via `droppedCount`.

**Step 5.7 — Commit**

```bash
git add src/lib/queue.js src/lib/router.js tests/lib/queue.test.js README.md
git commit -m "$(cat <<'EOF'
fix(extension): byte-cap on queue prevents storage.session overflow (M1)

The 200-batch count cap was sized for text-only messages (~500 B each);
audio messages are ~100 KB base64. Adds a maxBytes option (8 MB in
production) that evicts oldest batches when the serialized total exceeds
budget, alongside the count cap. Whichever cap triggers first wins.

README storage map updated to describe the dual cap.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6 (L1): Wrap diagnostic export in try/catch

**Why:** The click handler in `popup.js` calls `collectDiagnostics()` and then `URL.createObjectURL`/`a.click()`. If any step throws (storage corruption, blob API rejection), the rejection is unhandled and the user sees nothing. Defensive wrap with a status-line message.

**Files:**
- Modify: `popup.js`

**Step 6.1 — Patch the click handler**

In `popup.js`, replace the existing `el('diagBtn').addEventListener('click', ...)` block (look for it near the other event listeners) with:

```javascript
  el('diagBtn').addEventListener('click', async () => {
    try {
      const diag = await collectDiagnostics();
      const blob = new Blob([JSON.stringify(diag, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `whatsorga-diag-${diag.timestamp}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (/** @type {any} */ err) {
      setStatus('error', `Diagnostic export failed: ${err.message || err}`);
    }
  });
```

No new test — `collectDiagnostics` is already covered, and the wrapper is purely defensive UI plumbing.

**Step 6.2 — Run full CI**

```bash
npm run ci
```

Expected: all 90+ tests still pass.

**Step 6.3 — Commit**

```bash
git add popup.js
git commit -m "$(cat <<'EOF'
fix(extension): wrap diagnostic export click handler in try/catch (L1)

If collectDiagnostics or the Blob/URL APIs throw, the rejection was
unhandled and the user saw nothing happen. Now surfaces the failure via
the status line.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Push to update PR #10

**Step 7.1 — Confirm CI is green locally**

```bash
npm run ci
```

Expected: lint clean, typecheck clean, manifest lint clean, all tests pass (90 + new ones), coverage above 90%.

**Step 7.2 — Push**

```bash
git push
```

**Step 7.3 — Comment on the PR with the fix summary**

```bash
gh pr comment 10 --body "$(cat <<'EOF'
Bug-fix sweep applied — addresses all 7 review findings:

- **C1** queue race: per-instance promise-chain serialization
- **C2** dedup race: same lock pattern
- **C3** retryNow auth_error: untried batches now returned to queue head
- **H1** manifest: dropped `https://*/*` wildcard host permission
- **M1** queue: 8 MB byte-cap added, README updated
- **M2** manifest: dropped unused `activeTab` permission
- **L1** popup: diagnostic export click handler wrapped in try/catch

3 new concurrency tests + 2 new manifest invariant tests + 1 new queue byte-cap test + 1 new router auth_error queue-state test. All 96+ tests pass.
EOF
)"
```

---

## Verification checklist

After all tasks complete:

- [ ] `npm run ci` exits 0
- [ ] Coverage on `src/lib/**` still ≥ 90% lines / 85% branches
- [ ] No new ESLint warnings
- [ ] Manifest test asserts no wildcard host_permissions and no activeTab
- [ ] PR #10 page shows the new commits
- [ ] PR comment posted

## Notes

- **Lock helper not extracted:** Two callers (`queue.js`, `dedup.js`) is below the DRY threshold; inline is clearer than a `src/lib/mutex.js` for two consumers. Revisit if a third caller appears.
- **Byte cap is conservative:** 8 MB on a 10 MB quota leaves room for the dropped counter, attempt counter, and any future session keys. Tune up only if drop telemetry shows premature evictions.
- **`activeTab` removal is safe:** content script injection uses `content_scripts` manifest matching, not `chrome.tabs.executeScript`. Verified by grepping `executeScript` and finding zero hits.
