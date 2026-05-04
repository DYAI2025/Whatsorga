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



  it('applyServerForm requests host permission for non-default HTTPS origins', async () => {
    chrome.permissions.contains.mockResolvedValue(false);
    await applyServerForm({ serverUrl: 'https://radar.example.com', apiKey: 'k' });
    expect(chrome.permissions.request).toHaveBeenCalledWith({ origins: ['https://radar.example.com/*'] });
  });

  it('applyServerForm fails when host permission is denied', async () => {
    chrome.permissions.contains.mockResolvedValue(false);
    chrome.permissions.request.mockResolvedValue(false);
    await expect(applyServerForm({ serverUrl: 'https://radar.example.com', apiKey: 'k' }))
      .rejects.toThrow(/host permission/i);
  });

  it('outgoing payload contains eventVersion', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await sendBatch({ serverUrl: 'http://x', apiKey: 'k', messages: [{ id: 1 }], eventVersion: 1 });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.eventVersion).toBe(1);
  });
});
