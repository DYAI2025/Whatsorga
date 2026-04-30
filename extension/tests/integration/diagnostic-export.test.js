import { describe, it, expect } from 'vitest';
import { collectDiagnostics } from '../../popup.js';
import { saveConfig } from '../../src/lib/config.js';

describe('collectDiagnostics', () => {
  it('redacts apiKey', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'secret123' });
    const diag = await collectDiagnostics();
    expect(diag.config.apiKey).toBe('***');
    expect(JSON.stringify(diag)).not.toContain('secret123');
  });

  it('includes router snapshot and timestamp', async () => {
    await saveConfig({ serverUrl: 'http://x', apiKey: 'k' });
    const diag = await collectDiagnostics();
    expect(diag.snapshot).toBeDefined();
    expect(diag.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});
