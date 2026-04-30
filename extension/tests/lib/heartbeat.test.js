import { describe, it, expect, vi } from 'vitest';
import { runHeartbeat } from '../../src/lib/heartbeat.js';

describe('heartbeat', () => {
  it('does nothing when no counts', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const r = await runHeartbeat({ serverUrl: 'x', apiKey: 'k', counts: {}, queueSize: 0 });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(r.sent).toEqual([]);
    expect(r.remaining).toEqual({});
  });

  it('sends one heartbeat per chat in parallel', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const r = await runHeartbeat({
      serverUrl: 'http://x', apiKey: 'k',
      counts: { chatA: 3, chatB: 5, chatC: 0 }, queueSize: 2,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2); // 0-count skipped
    expect(r.sent.sort()).toEqual(['chatA', 'chatB']);
    expect(r.remaining).toEqual({});
  });

  it('keeps counts that fail the network call', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))
      .mockRejectedValueOnce(new TypeError('boom'));
    vi.stubGlobal('fetch', fetchMock);
    const r = await runHeartbeat({
      serverUrl: 'http://x', apiKey: 'k',
      counts: { chatA: 3, chatB: 5 }, queueSize: 0,
    });
    // chatA succeeded (so reset to 0), chatB failed (so kept)
    expect(r.remaining).toEqual({ chatB: 5 });
  });

  it('refuses without configuration', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const r = await runHeartbeat({ serverUrl: '', apiKey: '', counts: { chatA: 1 }, queueSize: 0 });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(r.skipped).toBe('not_configured');
    expect(r.remaining).toEqual({ chatA: 1 });
  });
});
