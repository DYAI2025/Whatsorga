# Extension Fix & Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the WhatsOrga Chrome extension reliably deliver every captured WhatsApp message to the radar-api server, with persisted queueing that survives MV3 service-worker suspension, comprehensive automated tests, and CI gates that prevent regressions.

**Architecture:** Replace the in-memory background retry queue with a single durable queue in `chrome.storage.session`. Make `background.js` a thin stateless dispatcher that wakes through `chrome.alarms` instead of `setTimeout`. Extract pure logic into `src/lib/*.js` ESM modules covered by Vitest. Add a GitHub Actions matrix that lints, type-checks JSDoc, runs all tests with coverage gating, validates the manifest, and uploads a packaged extension as a build artefact.

**Tech Stack:** Vanilla JavaScript (no build step) with JSDoc + `tsc --noEmit --checkJs --allowJs` as a static-type gate · Vitest (jsdom env) with a hand-rolled `chrome.*` test mock · ESLint flat config · `web-ext lint` for manifest validation · GitHub Actions on `node 20` · Chrome MV3 service worker with `"type": "module"`.

**Out of scope:** Backend changes (`radar-api/*`), the DOM-scraping logic in `content.js` (untouched except for replacing imports), UI redesign of the popup.

---

## Pre-flight

These steps run **once** before any task. They set up the worktree and confirm baseline reality.

```bash
cd /Users/benjaminpoersch/Projects/Vision/Whatsorga
git fetch origin
git checkout -b feat/extension-fix-and-hardening origin/main
node --version    # expect v20.x or v22.x
```

If node is older than 20, install via `brew install node@20 && brew link --force --overwrite node@20`.

Capture today's broken behaviour as a single recorded fact (this becomes the regression baseline that Phase 4 closes):

```bash
docker logs --since 24h deploy-radar-api-1 2>&1 \
  | grep -E "POST .*/api/(ingest|heartbeat)" \
  | wc -l
# expect 1 (only the synthetic test from before this plan)
```

Record the number in this file as a baseline marker:

> **Baseline (2026-04-30):** 1 successful `/api/ingest` POST in the previous 24 h despite ~2000 messages captured locally on the in-page side. The Phase 6 regression test must show this number rising in real time after a real WhatsApp Web message is sent.

---

## Phase 1 — Tooling foundation

Each task in this phase ends with a green CI run. Phase 1 does **not** change extension behaviour — it just adds scaffolding.

### Task 1.1 — Add `package.json` with dev dependencies

**Files:**
- Create: `extension/package.json`

**Step 1.1.1 — Write the failing test (manual: confirm tooling absent)**

```bash
cd extension && npx vitest --version 2>&1 | head -1
# expected: command not found OR network install attempt — meaning no package.json
```

**Step 1.1.2 — Create `extension/package.json`**

```json
{
  "name": "whatsorga-extension",
  "version": "0.4.0",
  "description": "WhatsApp Web capture extension for the WhatsOrga radar-api",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage",
    "lint": "eslint src tests *.js",
    "typecheck": "tsc --noEmit --allowJs --checkJs",
    "lint:manifest": "web-ext lint --source-dir=. --ignore-files='node_modules/**' 'tests/**' 'coverage/**' 'package*.json' 'tsconfig.json' 'eslint.config.js' 'vitest.config.js'",
    "package": "web-ext build --source-dir=. --artifacts-dir=./dist --overwrite-dest --ignore-files='node_modules/**' 'tests/**' 'coverage/**' 'package*.json' 'tsconfig.json' 'eslint.config.js' 'vitest.config.js' 'docs/**'",
    "ci": "npm run lint && npm run typecheck && npm run lint:manifest && npm run test:coverage"
  },
  "devDependencies": {
    "@eslint/js": "^9.10.0",
    "@types/chrome": "^0.0.270",
    "@types/node": "^20.16.0",
    "@vitest/coverage-v8": "^2.1.0",
    "eslint": "^9.10.0",
    "globals": "^15.9.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.6.0",
    "vitest": "^2.1.0",
    "web-ext": "^8.3.0"
  }
}
```

**Step 1.1.3 — Install and verify**

```bash
cd extension && npm install --no-fund --no-audit
npx vitest --version
# expected: vitest/2.x.x
```

**Step 1.1.4 — Commit**

```bash
git add extension/package.json extension/package-lock.json
git commit -m "build(extension): add npm tooling for tests, linting, and packaging"
```

---

### Task 1.2 — Add `tsconfig.json` for JSDoc type-checking

**Files:**
- Create: `extension/tsconfig.json`

**Step 1.2.1 — Write the failing test**

```bash
cd extension && npx tsc --noEmit --allowJs --checkJs 2>&1 | head -3
# expected: error TS5057: Cannot find a tsconfig.json file
```

**Step 1.2.2 — Create `extension/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": true,
    "checkJs": true,
    "noEmit": true,
    "strict": true,
    "noImplicitAny": false,
    "noUnusedLocals": true,
    "noUnusedParameters": false,
    "exactOptionalPropertyTypes": false,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "types": ["chrome", "node", "vitest/globals"]
  },
  "include": [
    "src/**/*.js",
    "tests/**/*.js",
    "background.js",
    "popup.js",
    "content.js",
    "queue-manager.js"
  ],
  "exclude": ["node_modules", "coverage", "dist"]
}
```

**Step 1.2.3 — Verify it passes (legacy code may have warnings; we set `strict` later)**

```bash
cd extension && npx tsc --noEmit --allowJs --checkJs 2>&1 | tail -5
# May report errors against legacy files; record them with: > docs/plans/baseline-typecheck.txt
```

If errors are found, append `// @ts-nocheck` to each legacy entry-point file so the gate passes today. The Phase 3 tasks remove these directives one at a time.

```bash
# Append directive (only if needed)
for f in background.js popup.js content.js queue-manager.js; do
  head -1 "$f" | grep -q "@ts-nocheck" || sed -i '' '1i\
// @ts-nocheck — to be removed in Phase 3 module migration
' "$f"
done
npx tsc --noEmit --allowJs --checkJs
# expected: no output, exit 0
```

**Step 1.2.4 — Commit**

```bash
git add extension/tsconfig.json extension/*.js
git commit -m "build(extension): add tsconfig.json for JSDoc type-gate"
```

---

### Task 1.3 — Add Vitest config + `chrome` mock

**Files:**
- Create: `extension/vitest.config.js`
- Create: `extension/tests/setup.js`
- Create: `extension/tests/mocks/chrome.js`

**Step 1.3.1 — Write a sentinel failing test**

```bash
mkdir -p extension/tests
cat > extension/tests/sentinel.test.js <<'EOF'
import { describe, it, expect } from 'vitest';

describe('sentinel', () => {
  it('chrome.storage.local is mocked', async () => {
    await chrome.storage.local.set({ foo: 'bar' });
    const got = await chrome.storage.local.get(['foo']);
    expect(got.foo).toBe('bar');
  });
});
EOF
cd extension && npx vitest run 2>&1 | tail -5
# expected: FAIL — chrome is not defined
```

**Step 1.3.2 — Create the chrome mock**

```javascript
// extension/tests/mocks/chrome.js
import { vi } from 'vitest';

/**
 * Minimal in-memory chrome.* mock covering: storage (local, session), runtime (onMessage,
 * sendMessage, lastError), tabs (query, sendMessage), alarms (create, onAlarm).
 * Returned object is mutated by tests (e.g., set lastError to simulate failure).
 */
export function createChromeMock() {
  const stores = { local: new Map(), session: new Map() };
  const listeners = { onMessage: [], onAlarm: [] };
  const alarms = new Map();

  const makeStorage = (key) => ({
    get: vi.fn(async (keys) => {
      const map = stores[key];
      if (keys === null || keys === undefined) {
        return Object.fromEntries(map);
      }
      const arr = Array.isArray(keys) ? keys : typeof keys === 'string' ? [keys] : Object.keys(keys);
      const out = {};
      for (const k of arr) {
        if (map.has(k)) out[k] = map.get(k);
        else if (typeof keys === 'object' && !Array.isArray(keys) && keys !== null) {
          out[k] = keys[k]; // default value
        }
      }
      return out;
    }),
    set: vi.fn(async (obj) => {
      for (const [k, v] of Object.entries(obj)) stores[key].set(k, v);
    }),
    remove: vi.fn(async (keys) => {
      const arr = Array.isArray(keys) ? keys : [keys];
      for (const k of arr) stores[key].delete(k);
    }),
    clear: vi.fn(async () => stores[key].clear()),
  });

  return {
    storage: { local: makeStorage('local'), session: makeStorage('session') },
    runtime: {
      lastError: undefined,
      sendMessage: vi.fn(async (msg) => {
        const responses = await Promise.all(
          listeners.onMessage.map(
            (l) => new Promise((resolve) => l(msg, { id: 'test' }, resolve))
          )
        );
        return responses.find((r) => r !== undefined);
      }),
      onMessage: {
        addListener: (fn) => listeners.onMessage.push(fn),
        removeListener: (fn) => {
          const i = listeners.onMessage.indexOf(fn);
          if (i >= 0) listeners.onMessage.splice(i, 1);
        },
      },
    },
    tabs: {
      query: vi.fn(async () => []),
      sendMessage: vi.fn(async () => undefined),
    },
    alarms: {
      create: vi.fn((name, opts) => {
        alarms.set(name, opts);
      }),
      clear: vi.fn(async (name) => alarms.delete(name)),
      onAlarm: {
        addListener: (fn) => listeners.onAlarm.push(fn),
      },
      _fire: (name) => {
        // test-only helper: fire an alarm tick
        for (const l of listeners.onAlarm) l({ name });
      },
      _scheduled: () => new Map(alarms),
    },
    _reset: () => {
      stores.local.clear();
      stores.session.clear();
      listeners.onMessage.length = 0;
      listeners.onAlarm.length = 0;
      alarms.clear();
    },
  };
}
```

**Step 1.3.3 — Create the test setup file that installs the mock globally**

```javascript
// extension/tests/setup.js
import { beforeEach, vi } from 'vitest';
import { createChromeMock } from './mocks/chrome.js';

beforeEach(() => {
  const chromeMock = createChromeMock();
  vi.stubGlobal('chrome', chromeMock);
  // Provide a fetch stub by default — tests override with vi.spyOn
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
});
```

**Step 1.3.4 — Create vitest.config.js**

```javascript
// extension/vitest.config.js
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.test.js'],
    coverage: {
      provider: 'v8',
      include: ['src/lib/**/*.js'],
      exclude: ['tests/**'],
      thresholds: {
        lines: 90,
        functions: 90,
        branches: 85,
        statements: 90,
      },
      reporter: ['text', 'lcov', 'html'],
    },
  },
});
```

**Step 1.3.5 — Verify the sentinel test passes**

```bash
cd extension && npx vitest run
# expected: 1 passing
```

**Step 1.3.6 — Commit**

```bash
git add extension/vitest.config.js extension/tests/
git commit -m "test(extension): add vitest with chrome.* mock"
```

---

### Task 1.4 — Add ESLint flat config

**Files:**
- Create: `extension/eslint.config.js`

**Step 1.4.1 — Write the failing test**

```bash
cd extension && npx eslint . 2>&1 | head -3
# expected: ESLint couldn't find a configuration file
```

**Step 1.4.2 — Create `eslint.config.js`**

```javascript
// extension/eslint.config.js
import js from '@eslint/js';
import globals from 'globals';

export default [
  js.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.webextensions,
        chrome: 'readonly',
      },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-console': 'off',
      'prefer-const': 'error',
      'no-var': 'error',
      eqeqeq: ['error', 'always'],
      'no-throw-literal': 'error',
    },
  },
  {
    files: ['tests/**/*.js'],
    languageOptions: { globals: { ...globals.node, ...globals.vitest } },
  },
  {
    ignores: ['node_modules/**', 'coverage/**', 'dist/**'],
  },
];
```

`@eslint/js` was already added to `package.json` devDependencies in Task 1.1, so `npm ci` already installed it. Skip ahead.

**Step 1.4.3 — Run lint, fix legacy issues with auto-fix**

```bash
cd extension && npx eslint . --fix 2>&1 | tail -10
```

Manually resolve any remaining errors (likely `no-unused-vars`, `prefer-const`). Use `// eslint-disable-next-line ...` only on legacy DOM code where the fix is non-obvious.

**Step 1.4.4 — Commit**

```bash
git add extension/eslint.config.js extension/package.json extension/package-lock.json extension/*.js
git commit -m "build(extension): add ESLint flat config"
```

---

### Task 1.5 — Add CI workflow skeleton

**Files:**
- Create: `.github/workflows/extension-ci.yml`

**Step 1.5.1 — Write the failing test (CI trigger)**

```bash
cd /Users/benjaminpoersch/Projects/Vision/Whatsorga
ls .github/workflows/extension-ci.yml 2>&1
# expected: No such file
```

**Step 1.5.2 — Create the workflow**

```yaml
# .github/workflows/extension-ci.yml
name: extension-ci

on:
  push:
    branches: [main, "feat/**", "fix/**"]
    paths:
      - "extension/**"
      - ".github/workflows/extension-ci.yml"
  pull_request:
    paths:
      - "extension/**"
      - ".github/workflows/extension-ci.yml"

defaults:
  run:
    working-directory: extension

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: extension/package-lock.json
      - run: npm ci --no-fund --no-audit
      - run: npm run lint
      - run: npm run typecheck
      - run: npm run lint:manifest
      - run: npm run test:coverage
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: coverage-${{ github.run_id }}
          path: extension/coverage/
          retention-days: 14

  package:
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: extension/package-lock.json
      - run: npm ci --no-fund --no-audit
      - run: npm run package
      - uses: actions/upload-artifact@v4
        with:
          name: extension-build-${{ github.sha }}
          path: extension/dist/*.zip
          retention-days: 30
```

**Step 1.5.3 — Push and verify CI runs**

```bash
git add .github/workflows/extension-ci.yml
git commit -m "ci(extension): add lint, typecheck, manifest, and test workflow"
git push -u origin feat/extension-fix-and-hardening
gh run watch
# expected: workflow runs, all jobs green (with the sentinel test only)
```

---

## Phase 2 — Extract pure-logic modules with TDD

Every module in this phase lives under `extension/src/lib/` and is independently testable. The legacy entry-point files (`background.js`, `popup.js`, `content.js`, `queue-manager.js`) stay untouched until Phase 3.

### Task 2.1 — `src/lib/url.js` — URL normalisation and validation

**Files:**
- Create: `extension/src/lib/url.js`
- Create: `extension/tests/lib/url.test.js`

**Step 2.1.1 — Failing test**

```javascript
// extension/tests/lib/url.test.js
import { describe, it, expect } from 'vitest';
import { normalizeServerUrl, isValidServerUrl } from '../../src/lib/url.js';

describe('normalizeServerUrl', () => {
  it.each([
    ['http://localhost:8900',          'http://localhost:8900'],
    ['http://localhost:8900/',         'http://localhost:8900'],
    ['http://localhost:8900/api/',     'http://localhost:8900'],
    ['  https://example.com/api  ',    'https://example.com'],
    ['HTTPS://EXAMPLE.COM',            'https://example.com'],
  ])('%s -> %s', (input, expected) => {
    expect(normalizeServerUrl(input)).toBe(expected);
  });
});

describe('isValidServerUrl', () => {
  it('accepts http/https URLs with host', () => {
    expect(isValidServerUrl('http://localhost:8900')).toBe(true);
    expect(isValidServerUrl('https://radar.example.com')).toBe(true);
  });
  it('rejects empty, non-http schemes, and missing host', () => {
    expect(isValidServerUrl('')).toBe(false);
    expect(isValidServerUrl('ftp://example.com')).toBe(false);
    expect(isValidServerUrl('not a url')).toBe(false);
    expect(isValidServerUrl('http://')).toBe(false);
  });
});
```

**Step 2.1.2 — Run, verify failure**

```bash
cd extension && npx vitest run tests/lib/url.test.js
# expected: FAIL — module not found
```

**Step 2.1.3 — Implement**

```javascript
// extension/src/lib/url.js
/**
 * Normalise a server URL: trim, lowercase scheme/host, strip trailing slashes,
 * strip a trailing /api suffix. Returns the normalised origin (no path).
 *
 * @param {string} raw
 * @returns {string} normalised URL, or empty string if input is unparseable.
 */
export function normalizeServerUrl(raw) {
  if (!raw || typeof raw !== 'string') return '';
  let trimmed = raw.trim();
  if (!trimmed) return '';
  try {
    const url = new URL(trimmed);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return '';
    if (!url.host) return '';
    let path = url.pathname.replace(/\/+$/, '').replace(/\/api$/i, '');
    return `${url.protocol}//${url.host}${path}`.toLowerCase().replace(/\/$/, '');
  } catch {
    return '';
  }
}

/**
 * @param {string} raw
 * @returns {boolean}
 */
export function isValidServerUrl(raw) {
  return normalizeServerUrl(raw) !== '';
}
```

**Step 2.1.4 — Verify passes**

```bash
cd extension && npx vitest run tests/lib/url.test.js
# expected: 8 passing
```

**Step 2.1.5 — Commit**

```bash
git add extension/src/lib/url.js extension/tests/lib/url.test.js
git commit -m "feat(extension): add url normaliser with full test coverage"
```

---

### Task 2.2 — `src/lib/storage.js` — typed storage facade

**Files:**
- Create: `extension/src/lib/storage.js`
- Create: `extension/tests/lib/storage.test.js`

**Step 2.2.1 — Failing test**

```javascript
// extension/tests/lib/storage.test.js
import { describe, it, expect } from 'vitest';
import { createStorage } from '../../src/lib/storage.js';

describe('storage facade', () => {
  it('round-trips a value through local', async () => {
    const s = createStorage('local');
    await s.set('k', { x: 1 });
    expect(await s.get('k')).toEqual({ x: 1 });
  });

  it('returns the default when key absent', async () => {
    const s = createStorage('local');
    expect(await s.get('missing', 'default')).toBe('default');
  });

  it('removes keys', async () => {
    const s = createStorage('local');
    await s.set('k', 1);
    await s.remove('k');
    expect(await s.get('k', null)).toBe(null);
  });

  it('isolates local from session', async () => {
    const local = createStorage('local');
    const session = createStorage('session');
    await local.set('k', 'L');
    await session.set('k', 'S');
    expect(await local.get('k')).toBe('L');
    expect(await session.get('k')).toBe('S');
  });
});
```

**Step 2.2.2 — Run, verify failure**

```bash
cd extension && npx vitest run tests/lib/storage.test.js
# expected: FAIL — module not found
```

**Step 2.2.3 — Implement**

```javascript
// extension/src/lib/storage.js
/**
 * Thin async wrapper around chrome.storage.{local,session} with default values
 * and JSON-roundtrip safety.
 *
 * @param {'local'|'session'} area
 */
export function createStorage(area) {
  const backing = chrome.storage[area];
  if (!backing) throw new Error(`chrome.storage.${area} unavailable`);

  return {
    /**
     * @template T
     * @param {string} key
     * @param {T} [defaultValue]
     * @returns {Promise<T|undefined>}
     */
    async get(key, defaultValue) {
      const out = await backing.get([key]);
      return Object.prototype.hasOwnProperty.call(out, key) ? out[key] : defaultValue;
    },
    /** @param {string} key  @param {unknown} value */
    async set(key, value) {
      await backing.set({ [key]: value });
    },
    /** @param {string|string[]} keys */
    async remove(keys) {
      await backing.remove(keys);
    },
    async clear() {
      await backing.clear();
    },
  };
}
```

**Step 2.2.4 — Verify passes**

```bash
cd extension && npx vitest run tests/lib/storage.test.js
# expected: 4 passing
```

**Step 2.2.5 — Commit**

```bash
git add extension/src/lib/storage.js extension/tests/lib/storage.test.js
git commit -m "feat(extension): add typed storage facade for local + session areas"
```

---

### Task 2.3 — `src/lib/config.js` — config loader with schema validation

**Files:**
- Create: `extension/src/lib/config.js`
- Create: `extension/tests/lib/config.test.js`

**Step 2.3.1 — Failing test**

```javascript
// extension/tests/lib/config.test.js
import { describe, it, expect } from 'vitest';
import { loadConfig, saveConfig, isConfigured } from '../../src/lib/config.js';

describe('config', () => {
  it('returns sensible defaults when storage is empty', async () => {
    const cfg = await loadConfig();
    expect(cfg).toEqual({
      serverUrl: '',
      apiKey: '',
      whitelist: [],
      enabled: true,
      eventVersion: 1,
    });
    expect(isConfigured(cfg)).toBe(false);
  });

  it('round-trips and normalises serverUrl on save', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900/api/  ', apiKey: 'k' });
    const cfg = await loadConfig();
    expect(cfg.serverUrl).toBe('http://localhost:8900');
    expect(cfg.apiKey).toBe('k');
    expect(isConfigured(cfg)).toBe(true);
  });

  it('rejects an invalid serverUrl with a thrown error', async () => {
    await expect(saveConfig({ serverUrl: 'not a url' })).rejects.toThrow(/server url/i);
  });

  it('deduplicates whitelist case-insensitively', async () => {
    await saveConfig({ whitelist: ['Vincent', 'vincent', 'Ben'] });
    const cfg = await loadConfig();
    expect(cfg.whitelist).toEqual(['Vincent', 'Ben']);
  });
});
```

**Step 2.3.2 — Verify failure**

```bash
cd extension && npx vitest run tests/lib/config.test.js
# expected: FAIL — module not found
```

**Step 2.3.3 — Implement**

```javascript
// extension/src/lib/config.js
import { createStorage } from './storage.js';
import { isValidServerUrl, normalizeServerUrl } from './url.js';

const KEY = 'whatsorga_config_v1';

/**
 * @typedef {object} Config
 * @property {string} serverUrl   Origin of the radar-api, no path.
 * @property {string} apiKey      Bearer token.
 * @property {string[]} whitelist Contact display names that pass capture.
 * @property {boolean} enabled    Whether the content script is active.
 * @property {number} eventVersion Schema version sent with each ingest payload.
 */

/** @returns {Config} */
function defaults() {
  return { serverUrl: '', apiKey: '', whitelist: [], enabled: true, eventVersion: 1 };
}

/** @returns {Promise<Config>} */
export async function loadConfig() {
  const store = createStorage('local');
  const stored = await store.get(KEY, {});
  return { ...defaults(), ...stored };
}

/**
 * @param {Partial<Config>} patch
 * @returns {Promise<Config>}
 */
export async function saveConfig(patch) {
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
      .filter((s) => s && !seen.has(s.toLowerCase()) && (seen.add(s.toLowerCase()), true));
  }
  if (patch.enabled !== undefined) next.enabled = !!patch.enabled;

  await store.set(KEY, next);
  return next;
}

/** @param {Config} cfg @returns {boolean} */
export function isConfigured(cfg) {
  return Boolean(cfg.serverUrl) && Boolean(cfg.apiKey);
}
```

**Step 2.3.4 — Verify passes**

```bash
cd extension && npx vitest run tests/lib/config.test.js
# expected: 4 passing
```

**Step 2.3.5 — Commit**

```bash
git add extension/src/lib/config.js extension/tests/lib/config.test.js
git commit -m "feat(extension): add config module with schema validation"
```

---

### Task 2.4 — `src/lib/queue.js` — durable FIFO queue

**Why this is critical:** The current `background.js` retry queue is in-memory only. MV3 service workers suspend after ~30 s idle and **all queued messages are lost**. This task replaces it with a queue persisted to `chrome.storage.session` (in-memory across the browser session, fast, survives service-worker suspension).

**Files:**
- Create: `extension/src/lib/queue.js`
- Create: `extension/tests/lib/queue.test.js`

**Step 2.4.1 — Failing test**

```javascript
// extension/tests/lib/queue.test.js
import { describe, it, expect } from 'vitest';
import { createQueue } from '../../src/lib/queue.js';

describe('queue', () => {
  it('enqueues and drains FIFO', async () => {
    const q = createQueue('test_q', { maxSize: 10 });
    await q.enqueue({ id: 1 });
    await q.enqueue({ id: 2 });
    expect(await q.size()).toBe(2);
    expect(await q.peek(2)).toEqual([{ id: 1 }, { id: 2 }]);
    expect(await q.drainHead(1)).toEqual([{ id: 1 }]);
    expect(await q.size()).toBe(1);
  });

  it('drops the oldest when maxSize exceeded', async () => {
    const q = createQueue('test_q', { maxSize: 3 });
    await q.enqueue({ id: 1 });
    await q.enqueue({ id: 2 });
    await q.enqueue({ id: 3 });
    await q.enqueue({ id: 4 });
    expect(await q.peek(10)).toEqual([{ id: 2 }, { id: 3 }, { id: 4 }]);
    expect(await q.droppedCount()).toBe(1);
  });

  it('persists across new instances (simulates worker resume)', async () => {
    const q1 = createQueue('test_q', { maxSize: 10 });
    await q1.enqueue({ id: 'survive' });
    const q2 = createQueue('test_q', { maxSize: 10 });
    expect(await q2.peek(1)).toEqual([{ id: 'survive' }]);
  });

  it('returnHead puts items back in original order', async () => {
    const q = createQueue('test_q', { maxSize: 10 });
    await q.enqueue({ id: 1 });
    await q.enqueue({ id: 2 });
    await q.enqueue({ id: 3 });
    const head = await q.drainHead(2);
    await q.returnHead(head);
    expect(await q.peek(3)).toEqual([{ id: 1 }, { id: 2 }, { id: 3 }]);
  });

  it('clear empties the queue but keeps droppedCount', async () => {
    const q = createQueue('test_q', { maxSize: 1 });
    await q.enqueue({ id: 1 });
    await q.enqueue({ id: 2 }); // drops 1
    await q.clear();
    expect(await q.size()).toBe(0);
    expect(await q.droppedCount()).toBe(1);
  });
});
```

**Step 2.4.2 — Verify failure**

```bash
cd extension && npx vitest run tests/lib/queue.test.js
# expected: FAIL
```

**Step 2.4.3 — Implement**

```javascript
// extension/src/lib/queue.js
import { createStorage } from './storage.js';

const STORAGE_AREA = 'session';
const DROPPED_KEY_SUFFIX = '__dropped';

/**
 * Durable FIFO queue backed by chrome.storage.session. Survives MV3
 * service-worker suspension within the same browser session.
 *
 * @param {string} key Unique storage key.
 * @param {{ maxSize: number }} opts
 */
export function createQueue(key, opts) {
  const store = createStorage(STORAGE_AREA);
  const droppedKey = key + DROPPED_KEY_SUFFIX;
  const maxSize = opts.maxSize;

  async function read() {
    return (await store.get(key, [])) || [];
  }
  async function write(arr) {
    await store.set(key, arr);
  }

  return {
    /** @param {unknown} item */
    async enqueue(item) {
      const arr = await read();
      arr.push(item);
      let dropped = 0;
      while (arr.length > maxSize) {
        arr.shift();
        dropped++;
      }
      if (dropped > 0) {
        const prev = (await store.get(droppedKey, 0)) || 0;
        await store.set(droppedKey, prev + dropped);
      }
      await write(arr);
    },
    async size() {
      return (await read()).length;
    },
    /** @param {number} n */
    async peek(n) {
      return (await read()).slice(0, n);
    },
    /** @param {number} n */
    async drainHead(n) {
      const arr = await read();
      const head = arr.splice(0, n);
      await write(arr);
      return head;
    },
    /** @param {unknown[]} items */
    async returnHead(items) {
      const arr = await read();
      await write(items.concat(arr));
    },
    async clear() {
      await write([]);
    },
    async droppedCount() {
      return (await store.get(droppedKey, 0)) || 0;
    },
    async resetDroppedCount() {
      await store.set(droppedKey, 0);
    },
  };
}
```

**Step 2.4.4 — Verify passes**

```bash
cd extension && npx vitest run tests/lib/queue.test.js
# expected: 5 passing
```

**Step 2.4.5 — Commit**

```bash
git add extension/src/lib/queue.js extension/tests/lib/queue.test.js
git commit -m "feat(extension): add durable storage-backed FIFO queue"
```

---

### Task 2.5 — `src/lib/transport.js` — fetch with timeout + classified errors

**Files:**
- Create: `extension/src/lib/transport.js`
- Create: `extension/tests/lib/transport.test.js`

**Step 2.5.1 — Failing test**

```javascript
// extension/tests/lib/transport.test.js
import { describe, it, expect, vi } from 'vitest';
import { sendBatch } from '../../src/lib/transport.js';

describe('transport.sendBatch', () => {
  it('returns ok on 2xx', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
    const r = await sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k',
      messages: [{ messageId: 'm1' }],
    });
    expect(r).toEqual({ outcome: 'ok' });
  });

  it('classifies 401 as auth_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = await sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k', messages: [{}],
    });
    expect(r.outcome).toBe('auth_error');
    expect(r.status).toBe(401);
  });

  it('classifies 5xx as server_error (retriable)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 503 })));
    const r = await sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k', messages: [{}],
    });
    expect(r.outcome).toBe('server_error');
  });

  it('classifies network failure as network_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const r = await sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k', messages: [{}],
    });
    expect(r.outcome).toBe('network_error');
  });

  it('aborts a slow request after the configured timeout', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_, init) =>
          new Promise((_resolve, reject) => {
            init.signal.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError'))
            );
          })
      )
    );
    const promise = sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k', messages: [{}], timeoutMs: 1000,
    });
    // advanceTimersByTimeAsync flushes pending microtasks (the abort -> reject path)
    // before resolving — advanceTimersByTime alone is racy here.
    await vi.advanceTimersByTimeAsync(1100);
    const r = await promise;
    expect(r.outcome).toBe('timeout');
    vi.useRealTimers();
  });

  it('refuses to send when serverUrl or apiKey is missing', async () => {
    const r1 = await sendBatch({ serverUrl: '', apiKey: 'k', messages: [{}] });
    expect(r1.outcome).toBe('not_configured');
    const r2 = await sendBatch({ serverUrl: 'http://localhost:8900', apiKey: '', messages: [{}] });
    expect(r2.outcome).toBe('not_configured');
  });
});
```

**Step 2.5.2 — Failure check**

```bash
cd extension && npx vitest run tests/lib/transport.test.js
# expected: FAIL
```

**Step 2.5.3 — Implement**

```javascript
// extension/src/lib/transport.js
const DEFAULT_TIMEOUT_MS = 10_000;

/**
 * @typedef {{ outcome:'ok' }
 *   | { outcome:'auth_error', status:number }
 *   | { outcome:'server_error', status:number }
 *   | { outcome:'client_error', status:number }
 *   | { outcome:'network_error', error:string }
 *   | { outcome:'timeout' }
 *   | { outcome:'not_configured' }
 * } SendResult
 */

/**
 * @param {{ serverUrl:string, apiKey:string, messages:object[], timeoutMs?:number, eventVersion?:number }} params
 * @returns {Promise<SendResult>}
 */
export async function sendBatch({
  serverUrl, apiKey, messages, timeoutMs = DEFAULT_TIMEOUT_MS, eventVersion = 1,
}) {
  if (!serverUrl || !apiKey) return { outcome: 'not_configured' };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${serverUrl}/api/ingest`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({ messages, eventVersion }),
      signal: controller.signal,
    });
    if (response.ok) return { outcome: 'ok' };
    if (response.status === 401 || response.status === 403)
      return { outcome: 'auth_error', status: response.status };
    if (response.status >= 500) return { outcome: 'server_error', status: response.status };
    return { outcome: 'client_error', status: response.status };
  } catch (err) {
    if (err && err.name === 'AbortError') return { outcome: 'timeout' };
    return { outcome: 'network_error', error: err && err.message ? err.message : String(err) };
  } finally {
    clearTimeout(timer);
  }
}
```

**Step 2.5.4 — Verify passes**

```bash
cd extension && npx vitest run tests/lib/transport.test.js
# expected: 6 passing
```

**Step 2.5.5 — Commit**

```bash
git add extension/src/lib/transport.js extension/tests/lib/transport.test.js
git commit -m "feat(extension): add transport with timeout + classified outcomes"
```

---

### Task 2.6 — `src/lib/retry.js` — alarm-driven exponential backoff

**Files:**
- Create: `extension/src/lib/retry.js`
- Create: `extension/tests/lib/retry.test.js`

**Step 2.6.1 — Failing test**

```javascript
// extension/tests/lib/retry.test.js
import { describe, it, expect } from 'vitest';
import { backoffMinutes, scheduleRetry, clearRetry } from '../../src/lib/retry.js';

describe('retry', () => {
  it('uses exponential backoff capped at 5 min', () => {
    expect(backoffMinutes(0)).toBe(0.5);   // 30s
    expect(backoffMinutes(1)).toBe(1);     // 1min
    expect(backoffMinutes(2)).toBe(2);
    expect(backoffMinutes(3)).toBe(5);     // cap
    expect(backoffMinutes(4)).toBe(5);
  });

  it('schedules a chrome alarm with the right delay', () => {
    scheduleRetry(2);
    expect(chrome.alarms.create).toHaveBeenCalledWith(
      'whatsorga_retry',
      { delayInMinutes: 2 }
    );
  });

  it('clearRetry removes the alarm', async () => {
    scheduleRetry(1);
    await clearRetry();
    expect(chrome.alarms.clear).toHaveBeenCalledWith('whatsorga_retry');
  });
});
```

**Step 2.6.2 — Failure**

```bash
cd extension && npx vitest run tests/lib/retry.test.js
```

**Step 2.6.3 — Implement**

```javascript
// extension/src/lib/retry.js
export const ALARM_NAME = 'whatsorga_retry';

/**
 * @param {number} attempt 0-indexed attempt counter
 * @returns {number} minutes to wait before the next attempt
 */
export function backoffMinutes(attempt) {
  // 0.5, 1, 2, 5, 5, 5 ...
  const ladder = [0.5, 1, 2, 5];
  return ladder[Math.min(attempt, ladder.length - 1)];
}

/** @param {number} minutes */
export function scheduleRetry(minutes) {
  chrome.alarms.create(ALARM_NAME, { delayInMinutes: minutes });
}

export async function clearRetry() {
  await chrome.alarms.clear(ALARM_NAME);
}
```

**Step 2.6.4 — Verify**

```bash
cd extension && npx vitest run tests/lib/retry.test.js
# expected: 3 passing
```

**Step 2.6.5 — Commit**

```bash
git add extension/src/lib/retry.js extension/tests/lib/retry.test.js
git commit -m "feat(extension): add alarm-based retry scheduler"
```

---

### Task 2.7 — `src/lib/heartbeat.js` — parallel sends with timeout, atomic counter reset

**Files:**
- Create: `extension/src/lib/heartbeat.js`
- Create: `extension/tests/lib/heartbeat.test.js`

The current heartbeat in `background.js:184-220` has two bugs:
- Sequential sends — if 50 chats are tracked, 50 sequential `fetch` calls in a single alarm cycle.
- Counter reset is not atomic with the network call — a mid-loop crash leaves earlier chats zeroed in memory but not persisted, while later chats keep their old counters.

**Step 2.7.1 — Failing test**

```javascript
// extension/tests/lib/heartbeat.test.js
import { describe, it, expect, vi } from 'vitest';
import { runHeartbeat } from '../../src/lib/heartbeat.js';

describe('heartbeat', () => {
  it('does nothing when no counts', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const r = await runHeartbeat({ serverUrl: 'x', apiKey: 'k', counts: {}, queueSize: 0 });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(r.sent).toEqual([]);
    expect(r.remaining).toEqual({});
  });

  it('sends one heartbeat per chat in parallel', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const r = await runHeartbeat({
      serverUrl: 'http://x', apiKey: 'k',
      counts: { chatA: 3, chatB: 5, chatC: 0 }, queueSize: 2,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2); // 0-count skipped
    expect(r.sent.sort()).toEqual(['chatA', 'chatB']);
    expect(r.remaining).toEqual({});
  });

  it('keeps counts that fail the network call', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))
      .mockRejectedValueOnce(new TypeError('boom'));
    vi.stubGlobal('fetch', fetchMock);
    const r = await runHeartbeat({
      serverUrl: 'http://x', apiKey: 'k',
      counts: { chatA: 3, chatB: 5 }, queueSize: 0,
    });
    // chatA succeeded (so reset to 0), chatB failed (so kept)
    expect(r.remaining).toEqual({ chatB: 5 });
  });

  it('refuses without configuration', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const r = await runHeartbeat({ serverUrl: '', apiKey: '', counts: { chatA: 1 }, queueSize: 0 });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(r.skipped).toBe('not_configured');
    expect(r.remaining).toEqual({ chatA: 1 });
  });
});
```

**Step 2.7.2 — Failure**

```bash
cd extension && npx vitest run tests/lib/heartbeat.test.js
```

**Step 2.7.3 — Implement**

```javascript
// extension/src/lib/heartbeat.js
const TIMEOUT_MS = 8_000;

/**
 * @param {{ serverUrl:string, apiKey:string, counts:Record<string,number>, queueSize:number, timeoutMs?:number }} params
 * @returns {Promise<{ sent:string[], remaining:Record<string,number>, skipped?:string }>}
 */
export async function runHeartbeat({
  serverUrl, apiKey, counts, queueSize, timeoutMs = TIMEOUT_MS,
}) {
  if (!serverUrl || !apiKey) return { sent: [], remaining: { ...counts }, skipped: 'not_configured' };

  const entries = Object.entries(counts).filter(([, n]) => n > 0);
  const remaining = { ...counts };
  for (const [chatId] of entries) remaining[chatId] = counts[chatId];

  const sent = [];

  const tasks = entries.map(async ([chatId, n]) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${serverUrl}/api/heartbeat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({
          chatId, messageCount: n, queueSize, timestamp: new Date().toISOString(),
        }),
        signal: ctrl.signal,
      });
      if (res.ok) {
        sent.push(chatId);
        delete remaining[chatId];
      }
    } catch {
      // keep remaining[chatId] as-is
    } finally {
      clearTimeout(timer);
    }
  });

  await Promise.all(tasks);

  // Strip zero counters that came in already at 0
  for (const k of Object.keys(remaining)) {
    if (remaining[k] === 0) delete remaining[k];
  }
  return { sent, remaining };
}
```

**Step 2.7.4 — Verify**

```bash
cd extension && npx vitest run tests/lib/heartbeat.test.js
# expected: 4 passing
```

**Step 2.7.5 — Commit**

```bash
git add extension/src/lib/heartbeat.js extension/tests/lib/heartbeat.test.js
git commit -m "feat(extension): add parallel heartbeat with atomic counter reset"
```

---

### Task 2.8 — `src/lib/dedup.js` — rolling-window message deduplicator

**Files:**
- Create: `extension/src/lib/dedup.js`
- Create: `extension/tests/lib/dedup.test.js`

**Step 2.8.1 — Failing test**

```javascript
// extension/tests/lib/dedup.test.js
import { describe, it, expect } from 'vitest';
import { createDedup } from '../../src/lib/dedup.js';

describe('dedup', () => {
  it('marks unseen ids fresh, then duplicates', async () => {
    const d = createDedup({ key: 'd1', windowSize: 100 });
    expect(await d.isFresh('a')).toBe(true);
    expect(await d.isFresh('a')).toBe(false);
  });

  it('survives a new instance (storage persisted)', async () => {
    const d1 = createDedup({ key: 'd1', windowSize: 100 });
    await d1.isFresh('x');
    const d2 = createDedup({ key: 'd1', windowSize: 100 });
    expect(await d2.isFresh('x')).toBe(false);
  });

  it('drops oldest entries when window overflows', async () => {
    const d = createDedup({ key: 'd1', windowSize: 3 });
    await d.isFresh('a');
    await d.isFresh('b');
    await d.isFresh('c');
    await d.isFresh('d'); // evicts 'a'
    expect(await d.isFresh('a')).toBe(true);
    expect(await d.isFresh('d')).toBe(false);
  });
});
```

**Step 2.8.2 — Failure**

```bash
cd extension && npx vitest run tests/lib/dedup.test.js
```

**Step 2.8.3 — Implement**

```javascript
// extension/src/lib/dedup.js
import { createStorage } from './storage.js';

/**
 * Rolling-window message deduplicator backed by chrome.storage.local. Caller
 * uses isFresh(id) — first call returns true and marks the id seen, subsequent
 * calls return false until the id is evicted by the window.
 *
 * @param {{ key:string, windowSize:number, area?:'local'|'session' }} opts
 */
export function createDedup({ key, windowSize, area = 'local' }) {
  const store = createStorage(area);
  return {
    /** @param {string} id */
    async isFresh(id) {
      const arr = (await store.get(key, [])) || [];
      if (arr.includes(id)) return false;
      arr.push(id);
      while (arr.length > windowSize) arr.shift();
      await store.set(key, arr);
      return true;
    },
    async size() {
      return ((await store.get(key, [])) || []).length;
    },
    async clear() {
      await store.set(key, []);
    },
  };
}
```

**Step 2.8.4 — Verify**

```bash
cd extension && npx vitest run tests/lib/dedup.test.js
# expected: 3 passing
```

**Step 2.8.5 — Commit**

```bash
git add extension/src/lib/dedup.js extension/tests/lib/dedup.test.js
git commit -m "feat(extension): add rolling-window dedup module"
```

---

### Task 2.9 — `src/lib/router.js` — orchestrator: queue + transport + retry

**Files:**
- Create: `extension/src/lib/router.js`
- Create: `extension/tests/lib/router.test.js`

The router is the single entry point that the service worker calls when new messages arrive. It consumes config + queue + transport + retry.

**Step 2.9.1 — Failing test**

```javascript
// extension/tests/lib/router.test.js
import { describe, it, expect, vi } from 'vitest';
import { createRouter } from '../../src/lib/router.js';
import { saveConfig } from '../../src/lib/config.js';

describe('router', () => {
  it('queues + sends when configured (happy path)', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'm1' }]);
    expect(result.outcome).toBe('ok');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('returns queued and schedules a retry when network fails', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'm2' }]);
    expect(result.outcome).toBe('queued');
    expect(chrome.alarms.create).toHaveBeenCalledWith(
      'whatsorga_retry', expect.objectContaining({ delayInMinutes: 0.5 })
    );
  });

  it('returns queued (not_configured) when no config', async () => {
    // saveConfig defaults — no server set
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'm3' }]);
    expect(result.outcome).toBe('queued');
    expect(result.reason).toBe('not_configured');
  });

  it('retryNow drains queue head and sends', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls++;
      return calls === 1
        ? new Response('', { status: 503 })
        : new Response('{}', { status: 200 });
    }));
    const r = createRouter();
    await r.acceptBatch([{ messageId: 'a' }]);
    await r.retryNow();
    expect(calls).toBe(2);
  });

  it('drops a batch on auth_error and clears retry', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'wrong' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'a' }]);
    expect(result.outcome).toBe('rejected');
    expect(result.reason).toBe('auth_error');
    expect(chrome.alarms.clear).toHaveBeenCalledWith('whatsorga_retry');
  });
});
```

**Step 2.9.2 — Failure**

```bash
cd extension && npx vitest run tests/lib/router.test.js
```

**Step 2.9.3 — Implement**

```javascript
// extension/src/lib/router.js
import { loadConfig, isConfigured } from './config.js';
import { createQueue } from './queue.js';
import { sendBatch } from './transport.js';
import { backoffMinutes, scheduleRetry, clearRetry } from './retry.js';

const QUEUE_KEY = 'whatsorga_send_queue';
const QUEUE_MAX = 200;            // batches in queue (each batch is up to ~50 messages)
const ATTEMPT_KEY = 'whatsorga_retry_attempt';

/**
 * @typedef {{ outcome:'ok' }
 *   | { outcome:'queued', reason:string }
 *   | { outcome:'rejected', reason:string }
 * } RouterResult
 */

export function createRouter() {
  const queue = createQueue(QUEUE_KEY, { maxSize: QUEUE_MAX });

  return {
    /**
     * @param {object[]} messages
     * @returns {Promise<RouterResult>}
     */
    async acceptBatch(messages) {
      if (!Array.isArray(messages) || messages.length === 0) {
        return { outcome: 'rejected', reason: 'empty' };
      }
      const cfg = await loadConfig();
      if (!isConfigured(cfg)) {
        await queue.enqueue(messages);
        return { outcome: 'queued', reason: 'not_configured' };
      }
      const result = await sendBatch({
        serverUrl: cfg.serverUrl, apiKey: cfg.apiKey, messages, eventVersion: cfg.eventVersion,
      });
      if (result.outcome === 'ok') return { outcome: 'ok' };
      if (result.outcome === 'auth_error') {
        await clearRetry();
        return { outcome: 'rejected', reason: 'auth_error' };
      }
      // server_error, network_error, timeout, client_error — queue + retry
      await queue.enqueue(messages);
      const attempt = (await queue.peek(0), await getAttempt());
      scheduleRetry(backoffMinutes(attempt));
      return { outcome: 'queued', reason: result.outcome };
    },

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
      for (const batch of head) {
        const r = await sendBatch({
          serverUrl: cfg.serverUrl, apiKey: cfg.apiKey, messages: batch, eventVersion: cfg.eventVersion,
        });
        if (r.outcome !== 'ok') failed.push(batch);
        if (r.outcome === 'auth_error') {
          await clearRetry();
          await resetAttempt();
          // Drop the rest — auth needs user attention.
          return { outcome: 'auth_error' };
        }
      }
      if (failed.length > 0) {
        await queue.returnHead(failed);
        const attempt = await incrementAttempt();
        scheduleRetry(backoffMinutes(attempt));
        return { outcome: 'partial', sent: head.length - failed.length, failed: failed.length };
      }
      await resetAttempt();
      // More items remaining? schedule another tick.
      if ((await queue.size()) > 0) scheduleRetry(0.1);
      else await clearRetry();
      return { outcome: 'ok', sent: head.length };
    },

    async snapshot() {
      const cfg = await loadConfig();
      return {
        configured: isConfigured(cfg),
        serverUrl: cfg.serverUrl,
        whitelistSize: cfg.whitelist.length,
        queueSize: await queue.size(),
        droppedCount: await queue.droppedCount(),
        attempt: await getAttempt(),
      };
    },

    async clear() {
      await queue.clear();
      await resetAttempt();
      await clearRetry();
    },
  };
}

async function getAttempt() {
  const out = await chrome.storage.session.get([ATTEMPT_KEY]);
  return out[ATTEMPT_KEY] ?? 0;
}
async function incrementAttempt() {
  const a = (await getAttempt()) + 1;
  await chrome.storage.session.set({ [ATTEMPT_KEY]: a });
  return a;
}
async function resetAttempt() {
  await chrome.storage.session.set({ [ATTEMPT_KEY]: 0 });
}
```

**Step 2.9.4 — Verify**

```bash
cd extension && npx vitest run tests/lib/router.test.js
# expected: 5 passing
```

**Step 2.9.5 — Commit**

```bash
git add extension/src/lib/router.js extension/tests/lib/router.test.js
git commit -m "feat(extension): add router orchestrating queue + transport + retry"
```

---

### Task 2.10 — Phase-2 final verification

All Phase-2 modules together must hit the coverage threshold.

**Step 2.10.1 — Run full coverage**

```bash
cd extension && npm run test:coverage
# expected: all suites green; coverage on src/lib >= 90% lines
```

If a metric is below threshold, add tests for the missing branch in the appropriate file before continuing.

**Step 2.10.2 — Push and watch CI**

```bash
git push
gh run watch
# expected: extension-ci/test job green
```

---

## Phase 3 — Wire modules into entry points

Each task in this phase removes legacy code and replaces it with module imports. We update one entry-point at a time and run CI between them.

### Task 3.1 — Convert `manifest.json` service worker to module type

**Files:**
- Modify: `extension/manifest.json`

**Step 3.1.1 — Failing test (manifest currently classic)**

```bash
grep -A2 '"background"' extension/manifest.json
# expected: shows "service_worker": "background.js" with no "type" key
```

**Step 3.1.2 — Update**

```bash
# Edit extension/manifest.json — change the "background" block to:
#   "background": {
#     "service_worker": "background.js",
#     "type": "module"
#   }
```

Use the Edit tool, not sed, to preserve formatting. After editing:

```bash
cd extension && npm run lint:manifest
# expected: web-ext lint passes
```

**Step 3.1.3 — Commit**

```bash
git add extension/manifest.json
git commit -m "build(extension): switch service_worker to ES module type"
```

---

### Task 3.2 — Refactor `background.js` to use modules

**Files:**
- Modify: `extension/background.js` (replace contents)
- Create: `extension/tests/integration/background-flow.test.js`

**Step 3.2.1 — Write the integration regression test FIRST**

```javascript
// extension/tests/integration/background-flow.test.js
// Drives the public message-handler API (NEW_MESSAGES, GET_STATUS, CONFIG_UPDATED,
// FLUSH_QUEUE) without depending on chrome.runtime wiring details.
import { describe, it, expect, vi } from 'vitest';
import { createMessageHandler } from '../../background.js';
import { saveConfig } from '../../src/lib/config.js';

describe('background message handler', () => {
  it('NEW_MESSAGES with valid config → ok', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
    const handler = createMessageHandler();
    const r = await handler({ type: 'NEW_MESSAGES', data: [{ messageId: 'm1' }] });
    expect(r.outcome).toBe('ok');
  });

  it('NEW_MESSAGES without config → queued (not_configured)', async () => {
    const handler = createMessageHandler();
    const r = await handler({ type: 'NEW_MESSAGES', data: [{ messageId: 'm2' }] });
    expect(r.outcome).toBe('queued');
    expect(r.reason).toBe('not_configured');
  });

  it('GET_STATUS returns a snapshot', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k', whitelist: ['a','b'] });
    const handler = createMessageHandler();
    const r = await handler({ type: 'GET_STATUS' });
    expect(r.configured).toBe(true);
    expect(r.serverUrl).toBe('http://x');
    expect(r.whitelistSize).toBe(2);
  });

  it('CONFIG_UPDATED awaits the reload before responding', async () => {
    const handler = createMessageHandler();
    // First, GET_STATUS shows not configured
    expect((await handler({ type: 'GET_STATUS' })).configured).toBe(false);
    // Save config externally, dispatch CONFIG_UPDATED
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k' });
    await handler({ type: 'CONFIG_UPDATED' });
    expect((await handler({ type: 'GET_STATUS' })).configured).toBe(true);
  });
});
```

**Step 3.2.2 — Run, verify failure (createMessageHandler not exported)**

```bash
cd extension && npx vitest run tests/integration/background-flow.test.js
```

**Step 3.2.3 — Replace `extension/background.js`**

```javascript
// extension/background.js
// MV3 service worker — thin, stateless dispatcher backed by src/lib modules.
// All durability lives in chrome.storage.session (queue + attempt counter).
//
// Public message types (handled by createMessageHandler):
//   NEW_MESSAGES     - { data: object[] }       -> RouterResult
//   GET_STATUS       - {}                       -> Snapshot
//   CONFIG_UPDATED   - {}                       -> { ok: true } (after reload)
//   FLUSH_QUEUE      - {}                       -> RetryResult
//   CLEAR_QUEUE      - {}                       -> { ok: true }

import { createRouter } from './src/lib/router.js';
import { ALARM_NAME } from './src/lib/retry.js';
import { runHeartbeat } from './src/lib/heartbeat.js';
import { loadConfig } from './src/lib/config.js';

const HEARTBEAT_ALARM = 'whatsorga_heartbeat';
const HEARTBEAT_COUNTS_KEY = 'heartbeatCounts';

console.log('[Radar] Background service worker started');

chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: 1 });

export function createMessageHandler() {
  const router = createRouter();
  return async function handle(msg) {
    switch (msg && msg.type) {
      case 'NEW_MESSAGES':
        return router.acceptBatch(msg.data || []);
      case 'GET_STATUS':
        return router.snapshot();
      case 'CONFIG_UPDATED':
        // No router state to reload — config is read on every call. Forward to content scripts.
        await forwardToContentScripts(msg);
        return { ok: true };
      case 'FLUSH_QUEUE':
        return router.retryNow();
      case 'CLEAR_QUEUE':
        await router.clear();
        return { ok: true };
      case 'MESSAGE_CAPTURED':
        await bumpHeartbeatCount(msg.chatId);
        return { ok: true };
      default:
        return { ok: false, error: 'unknown_message_type' };
    }
  };
}

async function forwardToContentScripts(msg) {
  const tabs = await chrome.tabs.query({ url: '*://web.whatsapp.com/*' });
  for (const tab of tabs) {
    try { await chrome.tabs.sendMessage(tab.id, msg); } catch { /* tab may be closing */ }
  }
}

async function bumpHeartbeatCount(chatId) {
  if (!chatId) return;
  const out = await chrome.storage.local.get([HEARTBEAT_COUNTS_KEY]);
  const counts = out[HEARTBEAT_COUNTS_KEY] || {};
  counts[chatId] = (counts[chatId] || 0) + 1;
  await chrome.storage.local.set({ [HEARTBEAT_COUNTS_KEY]: counts });
}

// ---- runtime wiring (skipped during unit tests, executed only in extension) ----

const handler = createMessageHandler();

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  // Always return true so Chrome keeps the message channel open while we await.
  Promise.resolve(handler(msg)).then(sendResponse).catch((err) => {
    console.error('[Radar] handler error:', err);
    sendResponse({ ok: false, error: String(err) });
  });
  return true;
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === ALARM_NAME) {
    await handler({ type: 'FLUSH_QUEUE' });
  } else if (alarm.name === HEARTBEAT_ALARM) {
    const cfg = await loadConfig();
    const out = await chrome.storage.local.get([HEARTBEAT_COUNTS_KEY]);
    const counts = out[HEARTBEAT_COUNTS_KEY] || {};
    const router = createRouter();
    const snap = await router.snapshot();
    const result = await runHeartbeat({
      serverUrl: cfg.serverUrl, apiKey: cfg.apiKey, counts, queueSize: snap.queueSize,
    });
    await chrome.storage.local.set({ [HEARTBEAT_COUNTS_KEY]: result.remaining });
  }
});
```

**Step 3.2.4 — Verify integration test passes**

```bash
cd extension && npx vitest run tests/integration/background-flow.test.js
# expected: 4 passing
```

**Step 3.2.5 — Manual smoke test (load extension)**

```bash
# Reload extension in chrome://extensions/
# Open the WhatsOrga service worker DevTools and run:
#   await chrome.runtime.sendMessage({type:'GET_STATUS'})
# expected: { configured: bool, serverUrl, whitelistSize, queueSize, droppedCount, attempt }
```

**Step 3.2.6 — Commit**

```bash
git add extension/background.js extension/tests/integration/background-flow.test.js
git commit -m "refactor(extension): replace background.js with module-based dispatcher"
```

---

### Task 3.3 — Refactor `popup.js` to use config module

**Files:**
- Modify: `extension/popup.js`
- Create: `extension/tests/integration/popup.test.js`

**Step 3.3.1 — Failing test**

```javascript
// extension/tests/integration/popup.test.js
import { describe, it, expect, vi } from 'vitest';
import { applyServerForm } from '../../popup.js';
import { loadConfig } from '../../src/lib/config.js';

describe('popup form handlers', () => {
  it('applyServerForm normalises and persists', async () => {
    await applyServerForm({ serverUrl: 'http://localhost:8900/api/  ', apiKey: ' k ' });
    const cfg = await loadConfig();
    expect(cfg.serverUrl).toBe('http://localhost:8900');
    expect(cfg.apiKey).toBe('k');
  });

  it('applyServerForm rejects invalid URL with thrown error', async () => {
    await expect(applyServerForm({ serverUrl: 'not a url', apiKey: 'k' })).rejects.toThrow();
  });
});
```

**Step 3.3.2 — Failure**

```bash
cd extension && npx vitest run tests/integration/popup.test.js
```

**Step 3.3.3 — Refactor `popup.js` (extract pure handlers from DOM event handlers)**

Add at top of `popup.js`:

```javascript
// extension/popup.js  (top of file)
import { loadConfig, saveConfig, isConfigured } from './src/lib/config.js';

/**
 * Pure handler used by the Save button. Exposed for testing.
 * @param {{ serverUrl:string, apiKey:string }} input
 */
export async function applyServerForm(input) {
  await saveConfig({ serverUrl: input.serverUrl, apiKey: input.apiKey });
  await chrome.runtime.sendMessage({ type: 'CONFIG_UPDATED' }).catch(() => {});
}

/**
 * Probe /health to confirm the saved config actually reaches the server.
 * @param {{ serverUrl:string, apiKey:string }} cfg
 * @returns {Promise<{ ok:boolean, status?:number, error?:string }>}
 */
export async function probeHealth(cfg) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 5000);
  try {
    const r = await fetch(`${cfg.serverUrl}/health`, {
      headers: { Authorization: `Bearer ${cfg.apiKey}` },
      signal: ctrl.signal,
    });
    return { ok: r.ok, status: r.status };
  } catch (err) {
    return { ok: false, error: err.message || String(err) };
  } finally {
    clearTimeout(t);
  }
}
```

Then update the existing `saveServerBtn` click handler in `popup.js` to call `applyServerForm` instead of doing storage writes inline. Update the existing "load saved config" block to use `loadConfig`.

**Step 3.3.4 — Verify all popup tests pass**

```bash
cd extension && npx vitest run tests/integration/popup.test.js
# expected: 2 passing
```

**Step 3.3.5 — Commit**

```bash
git add extension/popup.js extension/tests/integration/popup.test.js
git commit -m "refactor(extension): popup uses config module + adds health-probe helper"
```

---

### Task 3.4 — Refactor `content.js` dedup to use module

**Files:**
- Modify: `extension/content.js` (replace `_loadSentMessageIds` / `_saveSentMessageIds` / `sentMessageIds.has` calls with `dedup.isFresh`)

**Step 3.4.1 — Add a regression test**

```javascript
// extension/tests/integration/content-dedup.test.js
// Verifies that a content-script-style flow uses the dedup module's window
// behaviour (deduplication + persistence + eviction).
import { describe, it, expect } from 'vitest';
import { createDedup } from '../../src/lib/dedup.js';

describe('content script dedup integration', () => {
  it('dedups across two scans, evicts oldest', async () => {
    const d = createDedup({ key: 'sentMessageIds_v2', windowSize: 3, area: 'local' });
    expect(await d.isFresh('m1')).toBe(true);
    expect(await d.isFresh('m1')).toBe(false);
    expect(await d.isFresh('m2')).toBe(true);
    expect(await d.isFresh('m3')).toBe(true);
    expect(await d.isFresh('m4')).toBe(true); // evicts m1
    expect(await d.isFresh('m1')).toBe(true);
  });
});
```

**Step 3.4.2 — In `content.js`, replace the persistence helpers**

At the top of `content.js`, after the existing `console.log`:

```javascript
import { createDedup } from './src/lib/dedup.js';

const messageDedup = createDedup({
  key: 'sentMessageIds_v2', // new key — old `sentMessageIds` becomes orphan, will be cleared on next migration step
  windowSize: 5000,
  area: 'local',
});
```

Replace `_loadSentMessageIds` and `_saveSentMessageIds` with calls into `messageDedup`. Replace the `if (this.sentMessageIds.has(messageId)) continue;` check with `if (!(await messageDedup.isFresh(messageId))) continue;`. Drop the `_saveSentMessageIds` call after the loop.

Manifest content_script entry must add `"type": "module"`:

```json
"content_scripts": [
  {
    "matches": ["*://web.whatsapp.com/*"],
    "js": ["queue-manager.js", "content.js"],
    "run_at": "document_idle",
    "all_frames": false,
    "type": "module"
  }
]
```

> **Note:** Chrome supports content-script ES modules from version 122 (Feb 2024). Older Chrome will reject the load. CI manifest validation must include this constraint as a documented requirement in `extension/README.md` (Phase 6).

**Step 3.4.3 — Verify**

```bash
cd extension && npx vitest run
# expected: full suite green
```

**Step 3.4.4 — Manual smoke test**

```bash
# Reload extension. Open WhatsApp Web. Capture some messages.
# Service worker DevTools console:
#   await chrome.runtime.sendMessage({type:'GET_STATUS'})
# expected: queueSize fluctuates as messages flow through
```

**Step 3.4.5 — Commit**

```bash
git add extension/content.js extension/manifest.json extension/tests/integration/content-dedup.test.js
git commit -m "refactor(extension): content.js uses shared dedup module"
```

---

### Task 3.5 — Remove obsolete `queue-manager.js`

The legacy `queue-manager.js` is now dead — the dedup is handled by `src/lib/dedup.js` and the queue by the router. Remove the file and its manifest entry.

**Files:**
- Delete: `extension/queue-manager.js`
- Modify: `extension/manifest.json` (remove from content_scripts.js)

**Step 3.5.1 — Verify nothing else references it**

```bash
cd extension && grep -rn "MessageQueue\|queue-manager" . --include='*.js' --include='*.json' \
  --exclude-dir=node_modules --exclude-dir=coverage
# expected: only the line in manifest.json (to remove) and possibly a stale reference in content.js (already replaced in Task 3.4)
```

If content.js still references `MessageQueue`, remove those lines (no replacement — the module-based dedup covers it).

**Step 3.5.2 — Delete and update manifest**

```bash
git rm extension/queue-manager.js
```

Edit manifest.json — change `"js": ["queue-manager.js", "content.js"]` to `"js": ["content.js"]`.

**Step 3.5.3 — Verify**

```bash
cd extension && npm run ci
# expected: all green
```

**Step 3.5.4 — Commit**

```bash
git add extension/manifest.json
git commit -m "refactor(extension): remove obsolete queue-manager.js"
```

---

### Task 3.6 — Remove `// @ts-nocheck` directives

The legacy entry-point files no longer need them.

**Files:**
- Modify: `extension/background.js`, `extension/popup.js`, `extension/content.js`

**Step 3.6.1 — Remove directives**

```bash
cd extension
for f in background.js popup.js content.js; do
  sed -i '' '/^\/\/ @ts-nocheck/d' "$f"
done
npm run typecheck
```

If type errors surface, fix them (most will be JSDoc additions to function signatures). Iterate until clean.

**Step 3.6.2 — Commit**

```bash
git add extension/*.js
git commit -m "refactor(extension): remove @ts-nocheck — JSDoc types now complete"
```

---

## Phase 4 — Targeted bug fixes with regression tests

Phase 3 already eliminates the worst structural bugs (in-memory queue, race condition). Phase 4 closes the remaining narrow ones.

### Task 4.1 — Health probe in popup

The user has no proof the saved config actually reaches the server. Add a "Test connection" indicator that runs `probeHealth()` after Save.

**Files:**
- Modify: `extension/popup.html`
- Modify: `extension/popup.js`
- Create: `extension/tests/integration/popup-health.test.js`

**Step 4.1.1 — Failing test**

```javascript
// extension/tests/integration/popup-health.test.js
import { describe, it, expect, vi } from 'vitest';
import { probeHealth } from '../../popup.js';

describe('probeHealth', () => {
  it('reports ok on 200', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
    expect(await probeHealth({ serverUrl: 'http://x', apiKey: 'k' })).toEqual({ ok: true, status: 200 });
  });
  it('reports failure on 401', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = await probeHealth({ serverUrl: 'http://x', apiKey: 'wrong' });
    expect(r.ok).toBe(false);
    expect(r.status).toBe(401);
  });
  it('reports network error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const r = await probeHealth({ serverUrl: 'http://x', apiKey: 'k' });
    expect(r.ok).toBe(false);
    expect(r.error).toBeTruthy();
  });
});
```

**Step 4.1.2 — Verify failure**

```bash
cd extension && npx vitest run tests/integration/popup-health.test.js
```

**Step 4.1.3 — Add a probe indicator to `popup.html`**

Insert this after the existing `<button id="saveServerBtn">` line:

```html
<div id="healthRow" class="health-row">
  <span class="status-dot" id="healthDot"></span>
  <span id="healthText">Not tested</span>
</div>
```

**Step 4.1.4 — Wire it in `popup.js`**

Inside the existing `saveServerBtn.addEventListener('click', async () => { ... })` block, after the existing save:

```javascript
const cfg = await loadConfig();
const probe = await probeHealth(cfg);
const dot = document.getElementById('healthDot');
const txt = document.getElementById('healthText');
dot.className = `status-dot ${probe.ok ? 'success' : 'error'}`;
txt.textContent = probe.ok
  ? `OK (200)`
  : (probe.status ? `Server ${probe.status}` : `Network error`);
```

**Step 4.1.5 — Verify and commit**

```bash
cd extension && npm test
git add extension/popup.html extension/popup.js extension/tests/integration/popup-health.test.js
git commit -m "feat(extension): add health-probe indicator after save"
```

---

### Task 4.2 — Schema versioning of payloads

The router already passes `eventVersion` in `sendBatch`. Surface it in the popup as a read-only field for diagnostic purposes and make sure the server-side handler tolerates missing version (server change is out of scope, but document the expectation).

**Files:**
- Modify: `extension/popup.html` (add read-only `eventVersion` display)
- Modify: `extension/popup.js`
- Modify: `extension/tests/integration/popup.test.js` (assert version is sent)

**Step 4.2.1 — Add a test that asserts payload includes version**

```javascript
// Append to extension/tests/integration/popup.test.js
import { sendBatch } from '../../src/lib/transport.js';
it('outgoing payload contains eventVersion', async () => {
  const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  await sendBatch({ serverUrl: 'http://x', apiKey: 'k', messages: [{ id: 1 }], eventVersion: 1 });
  const body = JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(body.eventVersion).toBe(1);
});
```

**Step 4.2.2 — Surface version in popup**

Add to `popup.html`:

```html
<div class="meta">Schema v<span id="eventVersion">?</span></div>
```

In popup.js' `loadConfig` block:

```javascript
document.getElementById('eventVersion').textContent = String((data.eventVersion ?? 1));
```

**Step 4.2.3 — Verify and commit**

```bash
cd extension && npm test
git add extension/popup.html extension/popup.js extension/tests/integration/popup.test.js
git commit -m "feat(extension): surface ingest schema version in popup"
```

---

### Task 4.3 — Drop telemetry visible in popup

The router queue tracks `droppedCount`. Show it in the popup so silent loss becomes visible.

**Files:**
- Modify: `extension/popup.html`
- Modify: `extension/popup.js`

**Step 4.3.1 — Add a visible row**

In `popup.html`, in the `<div class="status-grid">`, add:

```html
<div class="status-item">
  <span class="status-label">Dropped</span>
  <span class="status-value" id="droppedCount">0</span>
</div>
```

**Step 4.3.2 — Wire in `refreshStatus`**

In `popup.js`'s `refreshStatus` function, after the existing `bgStatus` handling:

```javascript
if (bgStatus && bgStatus.droppedCount !== undefined) {
  document.getElementById('droppedCount').textContent = String(bgStatus.droppedCount);
}
```

**Step 4.3.3 — Add a behaviour test**

```javascript
// extension/tests/integration/popup-dropped.test.js
import { describe, it, expect, vi } from 'vitest';
import { createRouter } from '../../src/lib/router.js';
import { saveConfig } from '../../src/lib/config.js';

describe('snapshot exposes drop count', () => {
  it('counts dropped batches when queue is saturated', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k' });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const router = createRouter();
    // QUEUE_MAX is 200 in router.js — fill with 201 to provoke a drop.
    for (let i = 0; i < 201; i++) {
      await router.acceptBatch([{ messageId: `m${i}` }]);
    }
    const snap = await router.snapshot();
    expect(snap.droppedCount).toBeGreaterThanOrEqual(1);
  });
});
```

**Step 4.3.4 — Verify**

```bash
cd extension && npm test
```

**Step 4.3.5 — Commit**

```bash
git add extension/popup.html extension/popup.js extension/tests/integration/popup-dropped.test.js
git commit -m "feat(extension): surface drop telemetry in popup"
```

---

### Task 4.4 — Diagnostic export button

A single button in the popup that downloads a JSON dump of state for bug reports.

**Files:**
- Modify: `extension/popup.html`
- Modify: `extension/popup.js`
- Create: `extension/tests/integration/diagnostic-export.test.js`

**Step 4.4.1 — Failing test**

```javascript
// extension/tests/integration/diagnostic-export.test.js
import { describe, it, expect, vi } from 'vitest';
import { collectDiagnostics } from '../../popup.js';
import { saveConfig } from '../../src/lib/config.js';

describe('collectDiagnostics', () => {
  it('redacts apiKey', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'secret123' });
    const diag = await collectDiagnostics();
    expect(diag.config.apiKey).toBe('***');
    expect(JSON.stringify(diag)).not.toContain('secret123');
  });

  it('includes router snapshot and timestamp', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k' });
    const diag = await collectDiagnostics();
    expect(diag.snapshot).toBeDefined();
    expect(diag.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});
```

**Step 4.4.2 — Implement in `popup.js`**

```javascript
// Add to popup.js (exported)
import { createRouter } from './src/lib/router.js';

export async function collectDiagnostics() {
  const cfg = await loadConfig();
  const snap = await createRouter().snapshot();
  return {
    timestamp: new Date().toISOString(),
    config: { ...cfg, apiKey: cfg.apiKey ? '***' : '' },
    snapshot: snap,
    userAgent: navigator.userAgent,
  };
}
```

Add a button in `popup.html`:

```html
<button id="diagBtn" class="btn btn-small">Export diagnostics</button>
```

Wire it (inside the existing DOMContentLoaded handler):

```javascript
document.getElementById('diagBtn').addEventListener('click', async () => {
  const diag = await collectDiagnostics();
  const blob = new Blob([JSON.stringify(diag, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `whatsorga-diag-${diag.timestamp}.json`;
  a.click();
  URL.revokeObjectURL(url);
});
```

**Step 4.4.3 — Verify and commit**

```bash
cd extension && npm test
git add extension/popup.html extension/popup.js extension/tests/integration/diagnostic-export.test.js
git commit -m "feat(extension): add diagnostic export button (apiKey redacted)"
```

---

## Phase 5 — Documentation

### Task 5.1 — Write `extension/README.md`

**Files:**
- Create or replace: `extension/README.md`

**Step 5.1.1 — Write the file with this exact content**

````markdown
# WhatsOrga Extension

Captures messages from whitelisted contacts on WhatsApp Web and forwards them to a
self-hosted radar-api server. Designed to never lose a captured message.

## Requirements

- Chrome 122 or later (content-script ES modules + `chrome.storage.session`).
- A reachable radar-api with a valid `RADAR_API_KEY`.

## Install (developer)

1. Clone the repo, then `cd extension && npm install`.
2. In Chrome, open `chrome://extensions/`, enable Developer mode, click **Load unpacked**, pick this directory.
3. Click the WhatsOrga icon, paste the server URL (e.g. `http://localhost:8900`) and the API key. The dot under the Save button turns green when `/health` responds.
4. Add the WhatsApp display name(s) you want captured to the whitelist.

## Architecture

```text
content.js (WhatsApp Web tab)
   │  scrape DOM, dedup via src/lib/dedup
   ▼
chrome.runtime.sendMessage({type:'NEW_MESSAGES', data:[...]})
   ▼
background.js (MV3 service worker, type:"module")
   │  createRouter() — composes config + queue + transport + retry
   ▼
fetch POST /api/ingest        ↘   on failure  → enqueue to chrome.storage.session
   │                              schedule chrome.alarms.create('whatsorga_retry')
   ▼
radar-api → Postgres → GBrain bridge → Obsidian vault
```

Heartbeat: a 1-minute `chrome.alarms` tick flushes per-chat counters via parallel `POST /api/heartbeat`.

## Module map

| Module                   | Public API                                      | Owns               |
|--------------------------|-------------------------------------------------|--------------------|
| `src/lib/url.js`         | `normalizeServerUrl`, `isValidServerUrl`        | URL hygiene        |
| `src/lib/storage.js`     | `createStorage(area)`                           | typed storage      |
| `src/lib/config.js`      | `loadConfig`, `saveConfig`, `isConfigured`      | config schema      |
| `src/lib/queue.js`       | `createQueue(key,{maxSize})`                    | durable FIFO       |
| `src/lib/transport.js`   | `sendBatch`                                     | HTTP + timeouts    |
| `src/lib/retry.js`       | `backoffMinutes`, `scheduleRetry`, `clearRetry` | alarm-based timer  |
| `src/lib/heartbeat.js`   | `runHeartbeat`                                  | periodic flush     |
| `src/lib/dedup.js`       | `createDedup`                                   | rolling window     |
| `src/lib/router.js`      | `createRouter`                                  | orchestration      |

## Storage map

| Area      | Key                              | Owner       | Purpose                                | Survives  |
|-----------|----------------------------------|-------------|----------------------------------------|-----------|
| `local`   | `whatsorga_config_v1`            | popup       | serverUrl, apiKey, whitelist, enabled  | restart   |
| `local`   | `sentMessageIds_v2`              | content.js  | rolling 5000-id dedup window           | restart   |
| `local`   | `heartbeatCounts`                | background  | per-chat counters                      | restart   |
| `session` | `whatsorga_send_queue`           | router      | FIFO queue of failed batches           | session   |
| `session` | `whatsorga_send_queue__dropped`  | router      | counter of evicted batches             | session   |
| `session` | `whatsorga_retry_attempt`        | router      | exponential backoff index              | session   |

`chrome.storage.session` is capped at 10 MB. With `QUEUE_MAX = 200` batches × ~50 messages/batch × ~500 bytes/message ≈ 5 MB, leaving headroom. Going above this requires raising the storage quota with `"unlimitedStorage"` permission.

## Schema versioning

Every payload includes `eventVersion` (currently `1`). Increment when changing the message shape so the server can tolerate or reject specific extension versions.

## Tests

```bash
npm run ci       # full gate (lint + typecheck + manifest + tests + coverage)
npm run test:watch
```

Coverage threshold for `src/lib/**`: 90 % lines, 85 % branches.

## Known limitations

- **In-page send-failure**: if `chrome.runtime.sendMessage` from `content.js` fails (e.g., during extension reload), the message is lost. Mitigation: WhatsApp Web's DOM scan picks the same message up on the next sweep, dedup re-allows it because the `sentMessageIds_v2` window did not get the prior write. This means duplicate-send is more likely than message loss in this edge case.
- **`chrome.storage.session` is per-Chrome-session**: closing Chrome empties the queue. Long network outages spanning a Chrome restart will drop queued messages. The dedup window in `local` storage persists, so a re-scan will re-emit recent messages.
- **WhatsApp Web layout changes**: the DOM scraper in `content.js` is brittle by definition. If WhatsApp ships a redesign, the scraper needs an update; the rest of the extension is decoupled.
````

**Step 5.1.2 — Commit**

```bash
git add extension/README.md
git commit -m "docs(extension): document module architecture, storage map, and limits"
```

---

### Task 5.2 — Update root `CLAUDE.md` extension section

**Files:**
- Modify: `CLAUDE.md` (the section under "Extension Architecture")

Replace the old description with the new module-based one. Keep the watchdog/observer discussion — that did not change.

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md to reflect new extension architecture"
```

---

## Phase 6 — Final CI hardening + PR

### Task 6.1 — Add a manifest schema test

The current `web-ext lint` catches MV3 schema issues but does not assert specific invariants this codebase needs (e.g., service_worker is a module).

**Files:**
- Create: `extension/tests/manifest.test.js`

**Step 6.1.1 — Write tests**

```javascript
// extension/tests/manifest.test.js
import { describe, it, expect } from 'vitest';
import manifest from '../manifest.json' with { type: 'json' };

describe('manifest invariants', () => {
  it('uses Manifest V3', () => {
    expect(manifest.manifest_version).toBe(3);
  });

  it('service worker is an ES module', () => {
    expect(manifest.background.type).toBe('module');
    expect(manifest.background.service_worker).toBe('background.js');
  });

  it('content scripts are ES modules and target WhatsApp Web only', () => {
    expect(manifest.content_scripts[0].type).toBe('module');
    expect(manifest.content_scripts[0].matches).toEqual(['*://web.whatsapp.com/*']);
  });

  it('declares the minimum permissions only', () => {
    // Spread to avoid mutating the imported (potentially frozen) manifest.
    expect([...manifest.permissions].sort()).toEqual(['activeTab', 'alarms', 'storage'].sort());
  });

  it('declares minimum_chrome_version >= 122 (content script modules)', () => {
    const min = parseInt(manifest.minimum_chrome_version || '0', 10);
    expect(min).toBeGreaterThanOrEqual(122);
  });
});
```

**Step 6.1.2 — Set `minimum_chrome_version` in the manifest**

Add to `manifest.json`:

```json
"minimum_chrome_version": "122"
```

**Step 6.1.3 — Verify and commit**

```bash
cd extension && npm test
git add extension/manifest.json extension/tests/manifest.test.js
git commit -m "test(extension): add manifest invariants and pin minimum_chrome_version"
```

---

### Task 6.2 — Add CI status badge to README

**Files:**
- Modify: `extension/README.md`

```bash
# Add at the top of extension/README.md:
# ![extension-ci](https://github.com/DYAI2025/Whatsorga/actions/workflows/extension-ci.yml/badge.svg?branch=main)
git add extension/README.md
git commit -m "docs(extension): add CI status badge"
```

---

### Task 6.3 — Final integration smoke test

Run an end-to-end live capture against the running radar-api stack.

**Step 6.3.1 — Setup**

```bash
# 1. Reload extension (fully — remove + load unpacked)
# 2. Configure popup: http://localhost:8900 + the API key from deploy/.env
# 3. Verify the green health dot appears
# 4. Open WhatsApp Web, send a message in a whitelisted chat
```

**Step 6.3.2 — Verify server-side**

```bash
docker exec deploy-postgres-1 psql -U radar -d radar \
  -c "SELECT COUNT(*) FROM messages WHERE timestamp > NOW() - INTERVAL '1 hour';"
# expected: > 0 within seconds of sending
```

**Step 6.3.3 — Verify GBrain bridge picks it up**

```bash
ls -la /Users/benjaminpoersch/Projects/Vision/gbrain-vault/chats/*/messages/ | wc -l
# expected: increases as messages flow
```

**Step 6.3.4 — Worker-suspend regression check**

The single most important smoke test:

```bash
# 1. In WhatsApp Web, send a message in a whitelisted chat
# 2. Immediately stop the radar-api: docker compose -f deploy/docker-compose.yml stop radar-api
# 3. Send 5 more messages
# 4. Wait 60s — Chrome will suspend the service worker during this idle window
# 5. Restart radar-api: docker compose -f deploy/docker-compose.yml start radar-api
# 6. Within 5 minutes (max retry backoff), all 5 messages must arrive in Postgres
docker exec deploy-postgres-1 psql -U radar -d radar \
  -c "SELECT chat_name, COUNT(*) FROM messages WHERE timestamp > NOW() - INTERVAL '15 minutes' GROUP BY chat_name;"
```

If the count is 6, the durable queue + alarms-driven retry passed the most stringent regression that motivated this whole plan.

---

### Task 6.4 — Open PR

```bash
git push
gh pr create --title "feat(extension): durable queue, modular ESM, and CI hardening" \
  --body "$(cat <<'EOF'
## Summary

- Durable send queue (chrome.storage.session) — survives MV3 service-worker suspension.
- Replaced setTimeout-based retry with chrome.alarms (also survives suspension).
- Extracted pure logic into ESM modules under `src/lib/*.js` with 90%+ Vitest coverage.
- Manifest invariants enforced in CI (web-ext lint + custom assertions).
- Health probe + drop telemetry + diagnostic export visible in popup.
- Schema-versioned ingest payloads.

## Test plan

- [ ] CI green (lint, typecheck, web-ext lint, vitest with coverage).
- [ ] Local `npm run ci` passes against a clean checkout.
- [ ] Manual: extension reloads cleanly; health-probe shows green after Save.
- [ ] Worker-suspend regression: 5 messages sent during a 60 s outage all arrive.
- [ ] Postgres reflects every captured message within 30 s of WhatsApp scrape.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Storage map (canonical reference)

| Area    | Key                     | Owner       | Purpose                                      | Survives... |
|---------|-------------------------|-------------|----------------------------------------------|-------------|
| `local` | `whatsorga_config_v1`   | popup       | serverUrl, apiKey, whitelist, enabled        | restart     |
| `local` | `sentMessageIds_v2`     | content.js  | rolling 5000-id dedup window                 | restart     |
| `local` | `heartbeatCounts`       | background  | per-chat counters                            | restart     |
| `session` | `whatsorga_send_queue`  | router      | FIFO queue of failed batches                 | session     |
| `session` | `whatsorga_send_queue__dropped` | router | counter of evicted batches                | session     |
| `session` | `whatsorga_retry_attempt` | router    | exponential backoff index                    | session     |

## Module map (canonical reference)

| Module                   | Public API                                      | Owns               |
|--------------------------|-------------------------------------------------|--------------------|
| `src/lib/url.js`         | `normalizeServerUrl`, `isValidServerUrl`        | URL hygiene        |
| `src/lib/storage.js`     | `createStorage(area)`                           | typed storage      |
| `src/lib/config.js`      | `loadConfig`, `saveConfig`, `isConfigured`      | config schema      |
| `src/lib/queue.js`       | `createQueue(key,{maxSize})`                    | durable FIFO       |
| `src/lib/transport.js`   | `sendBatch`                                     | HTTP + timeouts    |
| `src/lib/retry.js`       | `backoffMinutes`, `scheduleRetry`, `clearRetry` | alarm-based timer  |
| `src/lib/heartbeat.js`   | `runHeartbeat`                                  | periodic flush     |
| `src/lib/dedup.js`       | `createDedup`                                   | rolling window     |
| `src/lib/router.js`      | `createRouter`                                  | orchestration      |

## Bugs closed by this plan (with line numbers in the original `background.js`)

| Bug | Original location | Fix |
|---|---|---|
| In-memory queue lost on worker suspend | `background.js:10, 125-134` | Phase 2.4 + 2.9 + 3.2 (storage.session) |
| `setTimeout` does not survive suspend  | `background.js:143-147`     | Phase 2.6 (chrome.alarms) |
| `CONFIG_UPDATED` race                  | `background.js:33-38`       | Phase 3.2 (await + then sendResponse) |
| `fetch` no timeout                     | `background.js:96-123`      | Phase 2.5 (AbortController) |
| Heartbeat sequential + non-atomic counters | `background.js:184-220` | Phase 2.7 (Promise.all + per-chat reset) |
| Unclear ok/queued/rejected return      | `background.js:78-94`       | Phase 2.9 (router result types) |
| Silent batch drop                      | `background.js:128-131`     | Phase 4.3 (dropped count + popup) |
| URL not normalised                     | `popup.js:19-26`            | Phase 2.1 + 2.3 |
| No proof config reaches server         | n/a                         | Phase 4.1 (health probe) |
