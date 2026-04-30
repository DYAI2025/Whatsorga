// @ts-nocheck
import { describe, it, expect } from 'vitest';

describe('chrome.storage mock — structured clone fidelity', () => {
  it('set does not retain a reference to the input object', async () => {
    const queue = [{ id: 1, attempts: 0 }];
    await chrome.storage.session.set({ queue });
    queue[0].attempts = 999; // mutate caller's array after set
    const { queue: stored } = await chrome.storage.session.get('queue');
    expect(stored[0].attempts).toBe(0);
  });

  it('get returns a fresh clone, not the stored reference', async () => {
    await chrome.storage.session.set({ obj: { count: 1 } });
    const a = await chrome.storage.session.get('obj');
    a.obj.count = 999; // mutate the returned object
    const b = await chrome.storage.session.get('obj');
    expect(b.obj.count).toBe(1);
  });

  it('get with default-value object also clones the default', async () => {
    const defaults = { settings: { theme: 'light' } };
    const a = await chrome.storage.local.get(defaults);
    a.settings.theme = 'dark'; // mutate the returned default
    const b = await chrome.storage.local.get(defaults);
    expect(b.settings.theme).toBe('light');
  });
});
