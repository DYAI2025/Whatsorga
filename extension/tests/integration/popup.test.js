// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { applyServerForm } from '../../popup.js';
import { loadConfig } from '../../src/lib/config.js';
import { sendBatch } from '../../src/lib/transport.js';

describe('popup form handlers', () => {
  it('applyServerForm normalises and persists', async () => {
    await applyServerForm({ serverUrl: 'http://localhost:8900/api/  ', apiKey: ' k ' });
    const cfg = await loadConfig();
    expect(cfg.serverUrl).toBe('http://localhost:8900');
    expect(cfg.apiKey).toBe('k');
  });

  it('applyServerForm rejects invalid URL with thrown error', async () => {
    await expect(applyServerForm({ serverUrl: 'not a url', apiKey: 'k' })).rejects.toThrow();
  });

  it('outgoing payload contains eventVersion', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await sendBatch({ serverUrl: 'http://x', apiKey: 'k', messages: [{ id: 1 }], eventVersion: 1 });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.eventVersion).toBe(1);
  });
});
