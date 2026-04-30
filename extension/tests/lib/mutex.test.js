import { describe, it, expect } from 'vitest';
import { createMutex } from '../../src/lib/mutex.js';

describe('mutex', () => {
  it('serializes async sections', async () => {
    const mutex = createMutex();
    const order = [];
    const slow = mutex.run(async () => { await new Promise(r => setTimeout(r, 30)); order.push('a'); });
    const fast = mutex.run(async () => { order.push('b'); });
    await Promise.all([slow, fast]);
    expect(order).toEqual(['a', 'b']);
  });

  it('continues the chain after a rejected section', async () => {
    const mutex = createMutex();
    const order = [];
    const failed = mutex.run(async () => { throw new Error('boom'); }).catch(() => order.push('caught'));
    const next = mutex.run(async () => { order.push('next'); });
    await Promise.all([failed, next]);
    expect(order).toEqual(['caught', 'next']);
  });

  it('returns the section result to the caller', async () => {
    const mutex = createMutex();
    const v = await mutex.run(async () => 42);
    expect(v).toBe(42);
  });
});
