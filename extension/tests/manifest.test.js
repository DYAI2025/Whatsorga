import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const manifest = JSON.parse(
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../manifest.json'), 'utf8')
);

describe('manifest invariants', () => {
  it('uses Manifest V3', () => {
    expect(manifest.manifest_version).toBe(3);
  });

  it('service worker is an ES module', () => {
    expect(manifest.background.type).toBe('module');
    expect(manifest.background.service_worker).toBe('background.js');
  });

  it('content scripts are ES modules and target WhatsApp Web only', () => {
    expect(manifest.content_scripts[0].type).toBe('module');
    expect(manifest.content_scripts[0].matches).toEqual(['*://web.whatsapp.com/*']);
  });

  it('declares the minimum permissions only', () => {
    expect([...manifest.permissions].sort()).toEqual(['alarms', 'storage'].sort());
  });

  it('declares minimum_chrome_version >= 122 (content script modules)', () => {
    const min = parseInt(manifest.minimum_chrome_version || '0', 10);
    expect(min).toBeGreaterThanOrEqual(122);
  });

  it('host_permissions does not include the https wildcard', () => {
    expect(manifest.host_permissions).not.toContain('https://*/*');
    // No catch-all wildcards at all.
    for (const h of manifest.host_permissions) {
      expect(h).not.toMatch(/\*:\/\/\*\/\*/);
      expect(h).not.toMatch(/^https?:\/\/\*\/\*$/);
    }
  });

  it('does not request activeTab (auto-injected content script does not need it)', () => {
    expect(manifest.permissions).not.toContain('activeTab');
  });
});
