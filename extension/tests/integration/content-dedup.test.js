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
