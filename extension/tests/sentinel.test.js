import { describe, it, expect } from 'vitest';

describe('sentinel', () => {
  it('chrome.storage.local is mocked', async () => {
    await chrome.storage.local.set({ foo: 'bar' });
    const got = await chrome.storage.local.get(['foo']);
    expect(got.foo).toBe('bar');
  });

  it('chrome.storage.session is mocked', async () => {
    await chrome.storage.session.set({ queue: [1, 2, 3] });
    const got = await chrome.storage.session.get(['queue']);
    expect(got.queue).toEqual([1, 2, 3]);
  });

  it('chrome.alarms.create is tracked', () => {
    chrome.alarms.create('retry', { periodInMinutes: 1 });
    expect(chrome.alarms._scheduled().has('retry')).toBe(true);
  });

  it('fetch is mocked', async () => {
    const res = await fetch('https://example.com/api');
    expect(res.status).toBe(200);
  });
});
