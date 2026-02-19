// WhatsOrga Background Service Worker
// Receives messages from content.js, forwards to server with retry queue
console.log('[Radar] Background service worker started');

const RETRY_DELAYS = [5000, 15000, 60000, 300000]; // 5s, 15s, 1m, 5m
const MAX_QUEUE_SIZE = 500;

let serverUrl = '';
let apiKey = '';
let retryQueue = [];
let retryTimer = null;

// Load config on startup
loadServerConfig();

// Use chrome.alarms for heartbeat (survives MV3 service worker suspension)
chrome.alarms.create('heartbeat', { periodInMinutes: 1 });

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case 'NEW_MESSAGES':
      handleNewMessages(msg.data).then(result => sendResponse(result));
      return true; // keep channel open for async response

    case 'GET_STATUS':
      sendResponse({
        serverUrl: serverUrl || '',
        queueSize: retryQueue.length,
        configured: !!(serverUrl && apiKey)
      });
      break;

    case 'CONFIG_UPDATED':
      loadServerConfig();
      sendResponse({ ok: true });
      // Also forward to content script
      forwardToContentScript(msg);
      break;

    case 'FLUSH_QUEUE':
      processRetryQueue();
      sendResponse({ ok: true });
      break;

    case 'CLEAR_QUEUE':
      retryQueue = [];
      sendResponse({ ok: true });
      break;

    case 'MESSAGE_CAPTURED':
      // Track messages for heartbeat (persisted to survive worker restarts)
      chrome.storage.local.get(['heartbeatCounts'], (data) => {
        const counts = data.heartbeatCounts || {};
        counts[msg.chatId] = (counts[msg.chatId] || 0) + 1;
        chrome.storage.local.set({ heartbeatCounts: counts });
      });
      sendResponse({ ok: true });
      break;
  }
  return true;
});

async function loadServerConfig() {
  const data = await chrome.storage.local.get(['serverUrl', 'apiKey']);
  serverUrl = data.serverUrl || '';
  apiKey = data.apiKey || '';
  console.log(`[Radar] Config loaded: server=${serverUrl ? 'set' : 'empty'}`);
}

function forwardToContentScript(msg) {
  chrome.tabs.query({ url: '*://web.whatsapp.com/*' }, (tabs) => {
    for (const tab of tabs) {
      chrome.tabs.sendMessage(tab.id, msg).catch(() => {});
    }
  });
}

async function handleNewMessages(messages) {
  if (!Array.isArray(messages) || messages.length === 0) return { ok: false };

  console.log(`[Radar] Received ${messages.length} new messages`);

  if (!serverUrl || !apiKey) {
    console.warn('[Radar] Server not configured, queuing messages');
    enqueue(messages);
    return { ok: false };
  }

  const result = await sendToServer(messages);
  if (!result.ok) {
    enqueue(messages);
  }
  return result;
}

async function sendToServer(messages) {
  try {
    const response = await fetch(`${serverUrl}/api/ingest`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body: JSON.stringify({ messages })
    });

    if (response.ok) {
      console.log(`[Radar] Sent ${messages.length} messages to server`);
      return { ok: true };
    }

    if (response.status === 401 || response.status === 403) {
      console.error(`[Radar] Auth error ${response.status} - check API key`);
      return { ok: false, authError: true };
    }

    console.warn(`[Radar] Server responded ${response.status}`);
    return { ok: false };
  } catch (err) {
    console.warn('[Radar] Network error:', err.message);
    return { ok: false };
  }
}

function enqueue(messages) {
  retryQueue.push({ messages, attempts: 0, addedAt: Date.now() });

  // Trim queue if too large (drop oldest)
  while (retryQueue.length > MAX_QUEUE_SIZE) {
    retryQueue.shift();
  }

  scheduleRetry();
}

function scheduleRetry() {
  if (retryTimer) return;
  if (retryQueue.length === 0) return;

  const nextItem = retryQueue[0];
  const delay = RETRY_DELAYS[Math.min(nextItem.attempts, RETRY_DELAYS.length - 1)];

  retryTimer = setTimeout(() => {
    retryTimer = null;
    processRetryQueue();
  }, delay);
}

async function processRetryQueue() {
  if (retryQueue.length === 0) return;
  if (!serverUrl || !apiKey) return;

  // Process up to 10 batches per cycle
  const toProcess = retryQueue.splice(0, 10);
  const failed = [];

  for (const item of toProcess) {
    const result = await sendToServer(item.messages);
    if (!result.ok) {
      item.attempts++;
      if (item.attempts < RETRY_DELAYS.length + 2) {
        failed.push(item);
      } else {
        console.warn(`[Radar] Dropping ${item.messages.length} messages after ${item.attempts} retries`);
      }
    }
  }

  // Put failed items back at the front
  retryQueue.unshift(...failed);

  if (retryQueue.length > 0) {
    scheduleRetry();
  }
}

// Handle alarms (survives service worker suspension)
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'heartbeat') {
    await sendHeartbeat();
  }
});

async function sendHeartbeat() {
  // Always reload config fresh — worker may have been suspended and lost state
  const config = await chrome.storage.local.get(['serverUrl', 'apiKey', 'heartbeatCounts']);
  const url = config.serverUrl || '';
  const key = config.apiKey || '';
  const counts = config.heartbeatCounts || {};

  if (!url || !key) return;

  const chatIds = Object.keys(counts).filter(id => counts[id] > 0);
  if (chatIds.length === 0) return;

  try {
    for (const chatId of chatIds) {
      await fetch(`${url}/api/heartbeat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${key}`
        },
        body: JSON.stringify({
          chatId,
          messageCount: counts[chatId],
          queueSize: retryQueue.length,
          timestamp: new Date().toISOString()
        })
      });

      console.log(`[Radar Heartbeat] Sent for ${chatId}: ${counts[chatId]} messages`);
      counts[chatId] = 0;
    }

    await chrome.storage.local.set({ heartbeatCounts: counts });
  } catch (error) {
    console.error('[Radar Heartbeat] Error:', error);
  }
}
