// MV3 service worker — thin, stateless dispatcher backed by src/lib modules.
// All durability lives in chrome.storage.session (queue + attempt counter).
//
// Public message types (handled by createMessageHandler):
//   NEW_MESSAGES     - { data: object[] }       -> RouterResult
//   GET_STATUS       - {}                       -> Snapshot
//   CONFIG_UPDATED   - {}                       -> { ok: true } (after reload)
//   FLUSH_QUEUE      - {}                       -> RetryResult
//   CLEAR_QUEUE      - {}                       -> { ok: true }
//   MESSAGE_CAPTURED - { chatId: string }       -> { ok: true }

import { createRouter } from './src/lib/router.js';
import { ALARM_NAME } from './src/lib/retry.js';
import { runHeartbeat } from './src/lib/heartbeat.js';
import { loadConfig } from './src/lib/config.js';

const HEARTBEAT_ALARM = 'whatsorga_heartbeat';
const HEARTBEAT_COUNTS_KEY = 'heartbeatCounts';

console.log('[Radar] Background service worker started');

export function createMessageHandler() {
  const router = createRouter();
  return async function handle(msg) {
    switch (msg && msg.type) {
      case 'NEW_MESSAGES':
        return router.acceptBatch(msg.data || []);
      case 'GET_STATUS':
        return router.snapshot();
      case 'CONFIG_UPDATED':
        await forwardToContentScripts(msg);
        return { ok: true };
      case 'FLUSH_QUEUE':
        return router.retryNow();
      case 'CLEAR_QUEUE':
        await router.clear();
        return { ok: true };
      case 'MESSAGE_CAPTURED':
        await bumpHeartbeatCount(msg.chatId);
        return { ok: true };
      default:
        return { ok: false, error: 'unknown_message_type' };
    }
  };
}

async function forwardToContentScripts(msg) {
  const tabs = await chrome.tabs.query({ url: '*://web.whatsapp.com/*' });
  for (const tab of tabs) {
    if (tab.id === undefined || tab.id === null) continue;
    try { await chrome.tabs.sendMessage(tab.id, msg); } catch { /* tab may be closing */ }
  }
}

async function bumpHeartbeatCount(chatId) {
  if (!chatId) return;
  const out = await chrome.storage.local.get([HEARTBEAT_COUNTS_KEY]);
  const counts = out[HEARTBEAT_COUNTS_KEY] || {};
  counts[chatId] = (counts[chatId] || 0) + 1;
  await chrome.storage.local.set({ [HEARTBEAT_COUNTS_KEY]: counts });
}

// ---- runtime wiring (only in extension; guarded so tests can import this file safely) ----
// Tests import createMessageHandler() directly and never reach this block.
if (typeof chrome !== 'undefined' && chrome.runtime && chrome.alarms) {
  chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: 1 });

  const handler = createMessageHandler();

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    // Always return true so Chrome keeps the message channel open while we await.
    Promise.resolve(handler(msg)).then(sendResponse).catch((err) => {
      console.error('[Radar] handler error:', err);
      sendResponse({ ok: false, error: String(err) });
    });
    return true;
  });

  chrome.alarms.onAlarm.addListener(async (alarm) => {
    if (alarm.name === ALARM_NAME) {
      await handler({ type: 'FLUSH_QUEUE' });
    } else if (alarm.name === HEARTBEAT_ALARM) {
      const cfg = await loadConfig();
      const out = await chrome.storage.local.get([HEARTBEAT_COUNTS_KEY]);
      const counts = out[HEARTBEAT_COUNTS_KEY] || {};
      const router = createRouter();
      const snap = await router.snapshot();
      const result = await runHeartbeat({
        serverUrl: cfg.serverUrl, apiKey: cfg.apiKey, counts, queueSize: snap.queueSize,
      });
      await chrome.storage.local.set({ [HEARTBEAT_COUNTS_KEY]: result.remaining });
    }
  });
}
