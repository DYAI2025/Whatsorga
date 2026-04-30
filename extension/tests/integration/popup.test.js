import { describe, it, expect, vi } from 'vitest';
import { applyServerForm } from '../../popup.js';
import { loadConfig } from '../../src/lib/config.js';

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
});
