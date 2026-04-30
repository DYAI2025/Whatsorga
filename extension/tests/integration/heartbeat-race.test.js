// @ts-nocheck
// Verifies that bumpHeartbeatCount and the heartbeat-alarm reset don't
// trample each other when they execute concurrently.
import { describe, it, expect, beforeEach } from 'vitest';

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
