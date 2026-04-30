// @ts-nocheck
// Drives the public message-handler API (NEW_MESSAGES, GET_STATUS, CONFIG_UPDATED,
// FLUSH_QUEUE) without depending on chrome.runtime wiring details.
import { describe, it, expect, vi } from 'vitest';
import { createMessageHandler } from '../../background.js';
import { saveConfig } from '../../src/lib/config.js';

describe('background message handler', () => {
  it('NEW_MESSAGES with valid config → ok', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k' });
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
    const handler = createMessageHandler();
    const r = await handler({ type: 'NEW_MESSAGES', data: [{ messageId: 'm1' }] });
    expect(r.outcome).toBe('ok');
  });

  it('NEW_MESSAGES without config → queued (not_configured)', async () => {
    const handler = createMessageHandler();
    const r = await handler({ type: 'NEW_MESSAGES', data: [{ messageId: 'm2' }] });
    expect(r.outcome).toBe('queued');
    expect(r.reason).toBe('not_configured');
  });

  it('GET_STATUS returns a snapshot', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k', whitelist: ['a', 'b'] });
    const handler = createMessageHandler();
    const r = await handler({ type: 'GET_STATUS' });
    expect(r.configured).toBe(true);
    expect(r.serverUrl).toBe('http://x');
    expect(r.whitelistSize).toBe(2);
  });

  it('CONFIG_UPDATED awaits the reload before responding', async () => {
    const handler = createMessageHandler();
    // First, GET_STATUS shows not configured
    expect((await handler({ type: 'GET_STATUS' })).configured).toBe(false);
    // Save config externally, dispatch CONFIG_UPDATED
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k' });
    await handler({ type: 'CONFIG_UPDATED' });
    expect((await handler({ type: 'GET_STATUS' })).configured).toBe(true);
  });
});
