/**
 * Thin async wrapper around chrome.storage.{local,session} with default values.
 *
 * Real chrome.storage is IPC-bridged and structured-clones values across the
 * boundary; the test mock matches that fidelity. Callers can therefore mutate
 * returned values without aliasing the stored copy.
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
    /**
     * @param {string} key
     * @param {unknown} value
     */
    async set(key, value) {
      await backing.set({ [key]: value });
    },
    /**
     * @param {string|string[]} keys
     */
    async remove(keys) {
      await backing.remove(keys);
    },
    async clear() {
      await backing.clear();
    },
  };
}
