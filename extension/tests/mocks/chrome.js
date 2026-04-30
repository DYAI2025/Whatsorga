// @ts-nocheck — test infra; mock shape intentionally diverges from chrome.* types
import { vi } from 'vitest';

/**
 * Minimal in-memory chrome.* mock covering: storage (local, session), runtime (onMessage,
 * sendMessage, lastError), tabs (query, sendMessage), alarms (create, clear, onAlarm).
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
          out[k] = keys[k]; // default value from defaults object
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
