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
