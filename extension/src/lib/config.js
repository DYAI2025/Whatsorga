import { createStorage } from './storage.js';
import { isValidServerUrl, normalizeServerUrl } from './url.js';

const KEY = 'whatsorga_config_v1';

/**
 * @typedef {object} Config
 * @property {string} serverUrl   Origin of the radar-api, no path.
 * @property {string} apiKey      Bearer token.
 * @property {string[]} whitelist Contact display names that pass capture.
 * @property {boolean} enabled    Whether the content script is active.
 * @property {number} eventVersion Schema version sent with each ingest payload.
 */

/** @returns {Config} */
function defaults() {
  return { serverUrl: '', apiKey: '', whitelist: [], enabled: true, eventVersion: 1 };
}

/** @returns {Promise<Config>} */
export async function loadConfig() {
  const store = createStorage('local');
  const stored = await store.get(KEY, {});
  return { ...defaults(), ...stored };
}

/**
 * @param {Partial<Config>} patch
 * @returns {Promise<Config>}
 */
export async function saveConfig(patch) {
  const store = createStorage('local');
  const current = await loadConfig();
  const next = { ...current, ...patch };

  if (patch.serverUrl !== undefined) {
    const trimmed = String(patch.serverUrl).trim();
    if (trimmed && !isValidServerUrl(trimmed)) {
      throw new Error(`Invalid server URL: ${trimmed}`);
    }
    next.serverUrl = normalizeServerUrl(trimmed);
  }
  if (patch.apiKey !== undefined) {
    next.apiKey = String(patch.apiKey).trim();
  }
  if (patch.whitelist !== undefined) {
    const seen = new Set();
    next.whitelist = (patch.whitelist || [])
      .map((s) => String(s).trim())
      .filter((s) => {
        if (!s) return false;
        const lower = s.toLowerCase();
        if (seen.has(lower)) return false;
        seen.add(lower);
        return true;
      });
  }
  if (patch.enabled !== undefined) next.enabled = Boolean(patch.enabled);

  await store.set(KEY, next);
  return next;
}

/**
 * @param {Config} cfg
 * @returns {boolean}
 */
export function isConfigured(cfg) {
  return Boolean(cfg.serverUrl) && Boolean(cfg.apiKey);
}
