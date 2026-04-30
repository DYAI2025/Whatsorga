# Phase 1 Review-Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve the five Important findings from the Phase 1 code review before Phase 2 lands real source modules — close test-fidelity gaps, kill a hidden ESLint blind spot, and add CI hygiene.

**Architecture:** Five surgical edits across `tests/mocks/chrome.js`, `scripts/validate-manifest.mjs`, `eslint.config.js`, `package.json`, and `.github/workflows/extension-ci.yml`. Each fix has a sentinel test or runtime check that fails before the change and passes after. One commit per fix.

**Tech Stack:** Same as Phase 1 — Vitest + jsdom, ESLint flat config, GitHub Actions, Node 20.

**Findings being closed:**
1. Chrome storage mock leaks references (no `structuredClone` on `set`/`get`) — would mask aliasing bugs in queue persistence.
2. `function require(...)` in `validate-manifest.mjs` shadows the conventional CJS `require` name.
3. `scripts/**/*.mjs` is not linted (Node globals missing from ESLint flat config; lint script doesn't include the directory).
4. `extension-ci.yml` has no `concurrency` group — wastes Actions minutes on rapid pushes.
5. `_reset()` helper in the chrome mock is dead code — either remove or annotate.

---

## Pre-flight

```bash
cd /Users/benjaminpoersch/Projects/Vision/Whatsorga
git status --short                          # ensure clean working tree
git rev-parse --abbrev-ref HEAD             # expect feat/extension-fix-and-hardening
cd extension && npm run ci 2>&1 | tail -5   # baseline: all green
```

---

### Task A — Deep-clone in chrome.storage mock (Finding #1)

**Files:**
- Modify: `extension/tests/mocks/chrome.js`
- Add test: `extension/tests/mocks/chrome.test.js`

**Step A.1 — Failing test**

Create `extension/tests/mocks/chrome.test.js`:

```javascript
// @ts-nocheck
import { describe, it, expect } from 'vitest';

describe('chrome.storage mock — structured clone fidelity', () => {
  it('set does not retain a reference to the input object', async () => {
    const queue = [{ id: 1, attempts: 0 }];
    await chrome.storage.session.set({ queue });
    queue[0].attempts = 999; // mutate after set
    const { queue: stored } = await chrome.storage.session.get('queue');
    expect(stored[0].attempts).toBe(0);
  });

  it('get returns a fresh clone, not the stored reference', async () => {
    await chrome.storage.session.set({ obj: { count: 1 } });
    const a = await chrome.storage.session.get('obj');
    a.obj.count = 999;
    const b = await chrome.storage.session.get('obj');
    expect(b.obj.count).toBe(1);
  });
});
```

**Step A.2 — Run, expect FAIL**

```bash
cd extension && npx vitest run tests/mocks/chrome.test.js 2>&1 | tail -15
# expected: 2 failed (mutation leaks through)
```

**Step A.3 — Patch mock**

Replace lines 14–38 of `extension/tests/mocks/chrome.js` with the deep-cloning version:

```javascript
const makeStorage = (key) => ({
  get: vi.fn(async (keys) => {
    const map = stores[key];
    const cloneIfPresent = (k) => (map.has(k) ? structuredClone(map.get(k)) : undefined);
    if (keys === null || keys === undefined) {
      return Object.fromEntries(
        Array.from(map.entries()).map(([k, v]) => [k, structuredClone(v)])
      );
    }
    const arr = Array.isArray(keys) ? keys : typeof keys === 'string' ? [keys] : Object.keys(keys);
    const out = {};
    for (const k of arr) {
      const v = cloneIfPresent(k);
      if (v !== undefined) out[k] = v;
      else if (typeof keys === 'object' && !Array.isArray(keys) && keys !== null) {
        out[k] = structuredClone(keys[k]); // default value
      }
    }
    return out;
  }),
  set: vi.fn(async (obj) => {
    for (const [k, v] of Object.entries(obj)) stores[key].set(k, structuredClone(v));
  }),
  remove: vi.fn(async (keys) => {
    const arr = Array.isArray(keys) ? keys : [keys];
    for (const k of arr) stores[key].delete(k);
  }),
  clear: vi.fn(async () => stores[key].clear()),
});
```

**Step A.4 — Run, expect PASS**

```bash
npx vitest run 2>&1 | tail -10
# expected: 6 passed (4 sentinel + 2 new clone tests)
```

**Step A.5 — Commit**

```bash
git add extension/tests/mocks/chrome.js extension/tests/mocks/chrome.test.js
git commit -m "test(extension): structuredClone in chrome.storage mock — fidelity with real Chrome"
```

---

### Task B — Rename `require` in manifest validator (Finding #2)

**Files:**
- Modify: `extension/scripts/validate-manifest.mjs`
- Modify: `extension/eslint.config.js` (add `no-shadow-restricted-names`)

**Step B.1 — Add the lint rule first (will FAIL on current code)**

In `extension/eslint.config.js`, add to the `rules` block:

```javascript
'no-shadow-restricted-names': 'error',
```

**Step B.2 — Run lint on the script, expect FAIL**

The script isn't yet covered by lint (Finding #3 fixes that), so this step is implicit until Task C lands. Skip ahead, but verify by hand:

```bash
cd extension && npx eslint scripts/validate-manifest.mjs --no-config-lookup --rule '{"no-shadow-restricted-names":"error"}' --parser-options=ecmaVersion:2022,sourceType:module 2>&1 | tail -5
```

Note: `require` is not in ESLint's restricted-names list (those are `NaN`, `Infinity`, `undefined`, etc.), so this rule won't fire on `require`. The rename is therefore a **readability fix, not a lint fix**. Skip the lint rule from Step B.1 — it's overkill — and just rename.

**Step B.3 — Rename `require` → `must` in `extension/scripts/validate-manifest.mjs`**

Replace every `require(...)` call with `must(...)` and the function definition `function require(...)` with `function must(...)`. Total: 1 definition + 14 call sites.

**Step B.4 — Run validator, expect PASS**

```bash
npm run lint:manifest 2>&1
# expected: manifest.json OK (WhatsOrga v0.3.0, MV3)
```

**Step B.5 — Commit**

```bash
git add extension/scripts/validate-manifest.mjs
git commit -m "refactor(extension): rename require->must in manifest validator to avoid CJS name shadow"
```

---

### Task C — Lint `scripts/**/*.mjs` with Node globals (Finding #3)

**Files:**
- Modify: `extension/eslint.config.js`
- Modify: `extension/package.json`

**Step C.1 — Failing test**

```bash
cd extension && npx eslint scripts/validate-manifest.mjs 2>&1
# expected: 'process' is not defined (no-undef errors)
```

**Step C.2 — Add Node globals block to `extension/eslint.config.js`**

Insert after the `tests/**/*.js` block, before `ignores`:

```javascript
{
  files: ['scripts/**/*.{js,mjs}'],
  languageOptions: { globals: { ...globals.node } },
},
```

**Step C.3 — Extend the lint npm script in `extension/package.json`**

Change line 11 from:
```json
"lint": "eslint --no-error-on-unmatched-pattern src tests *.js",
```
to:
```json
"lint": "eslint --no-error-on-unmatched-pattern src tests scripts *.js",
```

**Step C.4 — Run lint, expect PASS**

```bash
npm run lint 2>&1
# expected: clean exit, no output
```

**Step C.5 — Commit**

```bash
git add extension/eslint.config.js extension/package.json
git commit -m "build(extension): lint scripts/ with node globals"
```

---

### Task D — CI concurrency guard (Finding #4)

**Files:**
- Modify: `.github/workflows/extension-ci.yml`

**Step D.1 — Add `concurrency` block**

Insert after the top-level `on:` block (before `defaults:`):

```yaml
concurrency:
  group: extension-ci-${{ github.ref }}
  cancel-in-progress: true
```

**Step D.2 — Verify YAML is valid**

```bash
cd /Users/benjaminpoersch/Projects/Vision/Whatsorga && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/extension-ci.yml'))" && echo OK
# expected: OK
```

**Step D.3 — Commit**

```bash
git add .github/workflows/extension-ci.yml
git commit -m "ci(extension): cancel in-progress runs on the same ref"
```

---

### Task E — Document or remove `_reset()` (Finding #5)

**Files:**
- Modify: `extension/tests/mocks/chrome.js`

**Decision:** keep `_reset()` — Phase 2/3 tests may need to clear state mid-test (e.g., simulating "user re-installs extension"). Add a docstring annotating intended use.

**Step E.1 — Annotate the helper**

Replace the `_reset` block in `extension/tests/mocks/chrome.js` with:

```javascript
/**
 * Clear all in-memory state. NOT called automatically — `tests/setup.js` creates
 * a fresh mock per `beforeEach`. Use this only when a single test needs to wipe
 * state mid-flow (e.g., simulating extension re-install or browser restart).
 */
_reset: () => {
  stores.local.clear();
  stores.session.clear();
  listeners.onMessage.length = 0;
  listeners.onAlarm.length = 0;
  alarms.clear();
},
```

**Step E.2 — Run the full test suite to confirm no regressions**

```bash
npm run ci 2>&1 | tail -10
# expected: 6 tests passing, lint clean, typecheck clean, manifest OK
```

**Step E.3 — Commit**

```bash
git add extension/tests/mocks/chrome.js
git commit -m "docs(extension): annotate chrome mock _reset as opt-in mid-test escape hatch"
```

---

## Wrap-up

```bash
git log --oneline 238a7a0..HEAD
# expected: 5 commits (one per task)
cd extension && npm run ci 2>&1 | tail -10
# expected: green
```

**Estimated total time:** 25 minutes
**Risk:** none — all changes are test-infra or config; no production-code paths touched.
