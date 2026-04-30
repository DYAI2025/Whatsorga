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
    expect([...manifest.permissions].sort()).toEqual(['activeTab', 'alarms', 'storage'].sort());
  });

  it('declares minimum_chrome_version >= 122 (content script modules)', () => {
    const min = parseInt(manifest.minimum_chrome_version || '0', 10);
    expect(min).toBeGreaterThanOrEqual(122);
  });
});
