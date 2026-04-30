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
