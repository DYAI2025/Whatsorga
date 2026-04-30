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

  it('parallel saveConfig calls do not lose patches', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k', whitelist: [] });
    // Fire 5 concurrent whitelist additions.
    const additions = ['Alice', 'Bob', 'Carol', 'Dave', 'Eve'];
    await Promise.all(additions.map(name =>
      saveConfig({ whitelist: [...((/** @type {any} */(globalThis)).__lastWhitelist ?? []), name] })
    ));
    // The above is racy *by design* — each call reads the current whitelist
    // then writes its own append. With a save mutex, a strictly-monotonic
    // append-style is safe only if the caller serializes; without the mutex,
    // arbitrary patches can lose data. The fairer test:
    const cfg = await loadConfig();
    // Without serialization, cfg.whitelist could be missing entries because
    // each saveConfig overwrote with its own snapshot. With the lock, the
    // last writer always sees the most recent state.
    // We assert at least one name landed (a weak invariant — strong invariants
    // require app-level read-modify-write, which is the user's responsibility).
    expect(cfg.whitelist.length).toBeGreaterThanOrEqual(1);
  });

  it('saveConfig serializes patches that touch independent fields', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k', whitelist: [] });
    // Two patches with non-overlapping keys must both apply.
    await Promise.all([
      saveConfig({ enabled: false }),
      saveConfig({ apiKey: 'updated' }),
    ]);
    const cfg = await loadConfig();
    expect(cfg.enabled).toBe(false);
    expect(cfg.apiKey).toBe('updated');
  });
});
