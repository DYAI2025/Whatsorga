import { describe, it, expect, vi } from 'vitest';
import { createRouter } from '../../src/lib/router.js';
import { saveConfig } from '../../src/lib/config.js';

describe('router', () => {
  it('queues + sends when configured (happy path)', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'm1' }]);
    expect(result.outcome).toBe('ok');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('returns queued and schedules a retry when network fails', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'm2' }]);
    expect(result.outcome).toBe('queued');
    expect(chrome.alarms.create).toHaveBeenCalledWith(
      'whatsorga_retry', expect.objectContaining({ delayInMinutes: 0.5 })
    );
  });

  it('returns queued (not_configured) when no config', async () => {
    // saveConfig defaults — no server set
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'm3' }]);
    expect(result.outcome).toBe('queued');
    expect(result.reason).toBe('not_configured');
  });

  it('retryNow drains queue head and sends', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls++;
      return calls === 1
        ? new Response('', { status: 503 })
        : new Response('{}', { status: 200 });
    }));
    const r = createRouter();
    await r.acceptBatch([{ messageId: 'a' }]);
    await r.retryNow();
    expect(calls).toBe(2);
  });

  it('drops a batch on auth_error and clears retry', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'wrong' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    const r = createRouter();
    const result = await r.acceptBatch([{ messageId: 'a' }]);
    expect(result.outcome).toBe('rejected');
    expect(result.reason).toBe('auth_error');
    expect(chrome.alarms.clear).toHaveBeenCalledWith('whatsorga_retry');
  });

  it('retryNow returns auth_error when server returns 401 during drain', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    // First call (acceptBatch) fails with network error, queuing the batch
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls++;
      if (calls === 1) throw new TypeError('net');
      return new Response('', { status: 401 });
    }));
    const r = createRouter();
    await r.acceptBatch([{ messageId: 'x' }]);
    const result = await r.retryNow();
    expect(result.outcome).toBe('auth_error');
  });

  it('retryNow returns partial when some batches fail', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls++;
      // First: queue the batch (network error during acceptBatch)
      if (calls === 1) throw new TypeError('net');
      // Second: queue another batch
      if (calls === 2) throw new TypeError('net');
      // retryNow: first batch ok, second batch server_error
      if (calls === 3) return new Response('{}', { status: 200 });
      return new Response('', { status: 503 });
    }));
    const r = createRouter();
    await r.acceptBatch([{ messageId: 'b1' }]);
    await r.acceptBatch([{ messageId: 'b2' }]);
    const result = await r.retryNow();
    expect(result.outcome).toBe('partial');
    expect(result.sent).toBe(1);
    expect(result.failed).toBe(1);
  });

  it('retryNow returns idle when queue is empty', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    vi.stubGlobal('fetch', vi.fn());
    const r = createRouter();
    const result = await r.retryNow();
    expect(result.outcome).toBe('idle');
  });

  it('snapshot returns queue stats and config info', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k', whitelist: ['Alice', 'Bob'] });
    const r = createRouter();
    const snap = await r.snapshot();
    expect(snap.configured).toBe(true);
    expect(snap.serverUrl).toBe('http://localhost:8900');
    expect(snap.whitelistSize).toBe(2);
    expect(typeof snap.queueSize).toBe('number');
  });

  it('clear empties the queue', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('net'); }));
    const r = createRouter();
    await r.acceptBatch([{ messageId: 'z' }]);
    await r.clear();
    const snap = await r.snapshot();
    expect(snap.queueSize).toBe(0);
  });
});
