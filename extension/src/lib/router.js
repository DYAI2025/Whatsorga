import { loadConfig, isConfigured } from './config.js';
import { createQueue } from './queue.js';
import { sendBatch } from './transport.js';
import { backoffMinutes, scheduleRetry, clearRetry } from './retry.js';

const QUEUE_KEY = 'whatsorga_send_queue';
const QUEUE_MAX = 200;
const ATTEMPT_KEY = 'whatsorga_retry_attempt';

/**
 * @typedef {{ outcome:'ok' }
 *   | { outcome:'queued', reason:string }
 *   | { outcome:'rejected', reason:string }
 * } RouterResult
 */

export function createRouter() {
  const queue = createQueue(QUEUE_KEY, { maxSize: QUEUE_MAX });

  return {
    /**
     * @param {object[]} messages
     * @returns {Promise<RouterResult>}
     */
    async acceptBatch(messages) {
      if (!Array.isArray(messages) || messages.length === 0) {
        return { outcome: 'rejected', reason: 'empty' };
      }
      const cfg = await loadConfig();
      if (!isConfigured(cfg)) {
        await queue.enqueue(messages);
        return { outcome: 'queued', reason: 'not_configured' };
      }
      const result = await sendBatch({
        serverUrl: cfg.serverUrl, apiKey: cfg.apiKey, messages, eventVersion: cfg.eventVersion,
      });
      if (result.outcome === 'ok') return { outcome: 'ok' };
      if (result.outcome === 'auth_error') {
        await clearRetry();
        return { outcome: 'rejected', reason: 'auth_error' };
      }
      // server_error, network_error, timeout, client_error — queue + retry
      await queue.enqueue(messages);
      const attempt = await getAttempt();
      scheduleRetry(backoffMinutes(attempt));
      return { outcome: 'queued', reason: result.outcome };
    },

    async retryNow() {
      const cfg = await loadConfig();
      if (!isConfigured(cfg)) return { outcome: 'skipped', reason: 'not_configured' };
      const head = await queue.drainHead(10);
      if (head.length === 0) {
        await clearRetry();
        await resetAttempt();
        return { outcome: 'idle' };
      }
      const failed = [];
      for (let i = 0; i < head.length; i++) {
        const batch = head[i];
        const r = await sendBatch({
          serverUrl: cfg.serverUrl, apiKey: cfg.apiKey, messages: batch, eventVersion: cfg.eventVersion,
        });
        if (r.outcome === 'auth_error') {
          // The current batch is rejected (auth is non-retriable). Put back
          // anything we hadn't tried yet so it isn't silently lost.
          const untried = head.slice(i + 1);
          if (untried.length > 0) await queue.returnHead(untried);
          await clearRetry();
          await resetAttempt();
          return { outcome: 'auth_error' };
        }
        if (r.outcome !== 'ok') failed.push(batch);
      }
      if (failed.length > 0) {
        await queue.returnHead(failed);
        const attempt = await incrementAttempt();
        scheduleRetry(backoffMinutes(attempt));
        return { outcome: 'partial', sent: head.length - failed.length, failed: failed.length };
      }
      await resetAttempt();
      if ((await queue.size()) > 0) scheduleRetry(0.1);
      else await clearRetry();
      return { outcome: 'ok', sent: head.length };
    },

    async snapshot() {
      const cfg = await loadConfig();
      return {
        configured: isConfigured(cfg),
        serverUrl: cfg.serverUrl,
        whitelistSize: cfg.whitelist.length,
        queueSize: await queue.size(),
        droppedCount: await queue.droppedCount(),
        attempt: await getAttempt(),
      };
    },

    async clear() {
      await queue.clear();
      await resetAttempt();
      await clearRetry();
    },
  };
}

async function getAttempt() {
  const out = await chrome.storage.session.get([ATTEMPT_KEY]);
  return out[ATTEMPT_KEY] ?? 0;
}
async function incrementAttempt() {
  const a = (await getAttempt()) + 1;
  await chrome.storage.session.set({ [ATTEMPT_KEY]: a });
  return a;
}
async function resetAttempt() {
  await chrome.storage.session.set({ [ATTEMPT_KEY]: 0 });
}
