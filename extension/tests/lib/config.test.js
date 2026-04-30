import { describe, it, expect } from 'vitest';
import { loadConfig, saveConfig, isConfigured } from '../../src/lib/config.js';

describe('config', () => {
  it('returns sensible defaults when storage is empty', async () => {
    const cfg = await loadConfig();
    expect(cfg).toEqual({
      serverUrl: '',
      apiKey: '',
      whitelist: [],
      enabled: true,
      eventVersion: 1,
    });
    expect(isConfigured(cfg)).toBe(false);
  });

  it('round-trips and normalises serverUrl on save', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900/api/  ', apiKey: 'k' });
    const cfg = await loadConfig();
    expect(cfg.serverUrl).toBe('http://localhost:8900');
    expect(cfg.apiKey).toBe('k');
    expect(isConfigured(cfg)).toBe(true);
  });

  it('rejects an invalid serverUrl with a thrown error', async () => {
    await expect(saveConfig({ serverUrl: 'not a url' })).rejects.toThrow(/server url/i);
  });

  it('accepts an empty string serverUrl as "not configured"', async () => {
    const cfg = await saveConfig({ serverUrl: '' });
    expect(cfg.serverUrl).toBe('');
  });

  it('deduplicates whitelist case-insensitively, keeping first form', async () => {
    await saveConfig({ whitelist: ['Vincent', 'vincent', 'Ben'] });
    const cfg = await loadConfig();
    expect(cfg.whitelist).toEqual(['Vincent', 'Ben']);
  });

  it('strips empty entries from the whitelist', async () => {
    await saveConfig({ whitelist: ['Alice', '', '  ', 'Bob'] });
    const cfg = await loadConfig();
    expect(cfg.whitelist).toEqual(['Alice', 'Bob']);
  });

  it('partial saves merge with existing config', async () => {
    await saveConfig({ serverUrl: 'http://localhost:8900', apiKey: 'k1', enabled: true });
    await saveConfig({ apiKey: 'k2' });
    const cfg = await loadConfig();
    expect(cfg.serverUrl).toBe('http://localhost:8900');
    expect(cfg.apiKey).toBe('k2');
    expect(cfg.enabled).toBe(true);
  });

  it('coerces enabled to boolean', async () => {
    // @ts-expect-error — intentionally pass 0 to verify Boolean() coercion
    await saveConfig({ enabled: 0 });
    const cfg = await loadConfig();
    expect(cfg.enabled).toBe(false);
  });
});
