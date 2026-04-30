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
