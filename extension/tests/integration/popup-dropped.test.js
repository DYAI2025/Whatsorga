import { describe, it, expect, vi } from 'vitest';
import { createRouter } from '../../src/lib/router.js';
import { saveConfig } from '../../src/lib/config.js';

describe('snapshot exposes drop count', () => {
  it('counts dropped batches when queue is saturated', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k' });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const router = createRouter();
    // QUEUE_MAX is 200 in router.js — fill with 201 to provoke a drop
    for (let i = 0; i < 201; i++) {
      await router.acceptBatch([{ messageId: `m${i}` }]);
    }
    const snap = await router.snapshot();
    expect(snap.droppedCount).toBeGreaterThanOrEqual(1);
  });
});
