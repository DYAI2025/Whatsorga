import { describe, it, expect } from 'vitest';
import { createStorage } from '../../src/lib/storage.js';

describe('storage facade', () => {
  it('round-trips a value through local', async () => {
    const s = createStorage('local');
    await s.set('k', { x: 1 });
    expect(await s.get('k')).toEqual({ x: 1 });
  });

  it('returns the default when key absent', async () => {
    const s = createStorage('local');
    expect(await s.get('missing', 'default')).toBe('default');
  });

  it('returns undefined when key absent and no default given', async () => {
    const s = createStorage('local');
    expect(await s.get('missing')).toBeUndefined();
  });

  it('removes keys', async () => {
    const s = createStorage('local');
    await s.set('k', 1);
    await s.remove('k');
    expect(await s.get('k', null)).toBe(null);
  });

  it('removes multiple keys', async () => {
    const s = createStorage('local');
    await s.set('a', 1);
    await s.set('b', 2);
    await s.remove(['a', 'b']);
    expect(await s.get('a', 'gone')).toBe('gone');
    expect(await s.get('b', 'gone')).toBe('gone');
  });

  it('clear() empties the area', async () => {
    const s = createStorage('local');
    await s.set('a', 1);
    await s.set('b', 2);
    await s.clear();
    expect(await s.get('a', 'gone')).toBe('gone');
    expect(await s.get('b', 'gone')).toBe('gone');
  });

  it('isolates local from session', async () => {
    const local = createStorage('local');
    const session = createStorage('session');
    await local.set('k', 'L');
    await session.set('k', 'S');
    expect(await local.get('k')).toBe('L');
    expect(await session.get('k')).toBe('S');
  });

  it('throws on unknown storage area', () => {
    // @ts-expect-error — intentionally invalid area to verify the runtime guard
    expect(() => createStorage('bogus')).toThrow(/chrome\.storage\.bogus unavailable/);
  });
});
