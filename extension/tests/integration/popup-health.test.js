import { describe, it, expect, vi } from 'vitest';
import { probeHealth } from '../../popup.js';

describe('probeHealth', () => {
  it('reports ok on 200', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
    expect(await probeHealth({ serverUrl: 'http://x', apiKey: 'k' })).toEqual({ ok: true, status: 200 });
  });

  it('reports failure on 401', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = await probeHealth({ serverUrl: 'http://x', apiKey: 'wrong' });
    expect(r.ok).toBe(false);
    expect(r.status).toBe(401);
  });

  it('reports network error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const r = await probeHealth({ serverUrl: 'http://x', apiKey: 'k' });
    expect(r.ok).toBe(false);
    expect(r.error).toBeTruthy();
  });
});
