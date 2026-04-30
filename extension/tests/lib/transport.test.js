// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { sendBatch } from '../../src/lib/transport.js';

describe('transport.sendBatch', () => {
  it('returns ok on 2xx', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
    const r = await sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k',
      messages: [{ messageId: 'm1' }],
    });
    expect(r).toEqual({ outcome: 'ok' });
  });

  it('classifies 401 as auth_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = await sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k', messages: [{}],
    });
    expect(r.outcome).toBe('auth_error');
    expect(r.status).toBe(401);
  });

  it('classifies 5xx as server_error (retriable)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 503 })));
    const r = await sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k', messages: [{}],
    });
    expect(r.outcome).toBe('server_error');
  });

  it('classifies network failure as network_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const r = await sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k', messages: [{}],
    });
    expect(r.outcome).toBe('network_error');
  });

  it('aborts a slow request after the configured timeout', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_, init) =>
          new Promise((_resolve, reject) => {
            init.signal.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError'))
            );
          })
      )
    );
    const promise = sendBatch({
      serverUrl: 'http://localhost:8900', apiKey: 'k', messages: [{}], timeoutMs: 1000,
    });
    await vi.advanceTimersByTimeAsync(1100);
    const r = await promise;
    expect(r.outcome).toBe('timeout');
    vi.useRealTimers();
  });

  it('refuses to send when serverUrl or apiKey is missing', async () => {
    const r1 = await sendBatch({ serverUrl: '', apiKey: 'k', messages: [{}] });
    expect(r1.outcome).toBe('not_configured');
    const r2 = await sendBatch({ serverUrl: 'http://localhost:8900', apiKey: '', messages: [{}] });
    expect(r2.outcome).toBe('not_configured');
  });
});
