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
