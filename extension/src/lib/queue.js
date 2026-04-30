import { createStorage } from './storage.js';
import { createMutex } from './mutex.js';

const STORAGE_AREA = 'session';
const DROPPED_KEY_SUFFIX = '__dropped';

/**
 * Durable FIFO queue backed by chrome.storage.session. Survives MV3
 * service-worker suspension within the same browser session.
 *
 * @param {string} key Unique storage key.
 * @param {{ maxSize: number, maxBytes?: number }} opts
 */
export function createQueue(key, opts) {
  const store = createStorage(STORAGE_AREA);
  const droppedKey = key + DROPPED_KEY_SUFFIX;
  const maxSize = opts.maxSize;
  const maxBytes = opts.maxBytes ?? 0; // 0 = no byte cap

  // Per-instance mutex: serializes all read-modify-write operations.
  const mutex = createMutex();

  async function read() {
    return (await store.get(key, [])) || [];
  }
  async function write(arr) {
    await store.set(key, arr);
  }

  return {
    /** @param {unknown} item */
    enqueue(item) {
      return mutex.run(async () => {
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
    async size() {
      return (await read()).length;
    },
    /** @param {number} n */
    async peek(n) {
      return (await read()).slice(0, n);
    },
    /** @param {number} n */
    drainHead(n) {
      return mutex.run(async () => {
        const arr = await read();
        const head = arr.splice(0, n);
        await write(arr);
        return head;
      });
    },
    /** @param {unknown[]} items */
    returnHead(items) {
      return mutex.run(async () => {
        const arr = await read();
        await write(items.concat(arr));
      });
    },
    clear() {
      return mutex.run(async () => write([]));
    },
    async droppedCount() {
      return (await store.get(droppedKey, 0)) || 0;
    },
    resetDroppedCount() {
      return mutex.run(async () => store.set(droppedKey, 0));
    },
  };
}
