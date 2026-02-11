// Beziehungs-Radar Background Service Worker
// Receives messages from content.js, forwards to server with retry queue
console.log('[Radar] Background service worker started');

const RETRY_DELAYS = [5000, 15000, 60000, 300000]; // 5s, 15s, 1m, 5m
const MAX_QUEUE_SIZE = 500;

let serverUrl = '';
let apiKey = '';
let retryQueue = [];
let retryTimer = null;

// Heartbeat tracking
let heartbeatState = {
  chatCounts: {}, // { chatId: messageCount }
  lastBeat: null,
  timer: null
};

// Load config on startup
loadServerConfig();

// Initialize heartbeat on extension load
startHeartbeat();

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case 'NEW_MESSAGES':
      handleNewMessages(msg.data);
      sendResponse({ ok: true });
      break;

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
      // Track messages for heartbeat
      const { chatId } = msg;
      heartbeatState.chatCounts[chatId] = (heartbeatState.chatCounts[chatId] || 0) + 1;
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
  if (!Array.isArray(messages) || messages.length === 0) return;

  console.log(`[Radar] Received ${messages.length} new messages`);

  if (!serverUrl || !apiKey) {
    console.warn('[Radar] Server not configured, queuing messages');
    enqueue(messages);
    return;
  }

  const success = await sendToServer(messages);
  if (!success) {
    enqueue(messages);
  }
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
      return true;
    }

    console.warn(`[Radar] Server responded ${response.status}`);
    return false;
  } catch (err) {
    console.warn('[Radar] Network error:', err.message);
    return false;
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
    const success = await sendToServer(item.messages);
    if (!success) {
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

function startHeartbeat() {
  // Send heartbeat every 60 seconds
  heartbeatState.timer = setInterval(async () => {
    await sendHeartbeat();
  }, 60000);
}

async function sendHeartbeat() {
  if (!serverUrl || !apiKey) return;

  try {
    // Send heartbeat for each tracked chat
    for (const [chatId, count] of Object.entries(heartbeatState.chatCounts)) {
      if (count === 0) continue;

      await fetch(`${serverUrl}/api/heartbeat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`
        },
        body: JSON.stringify({
          chatId,
          messageCount: count,
          queueSize: retryQueue.length,
          timestamp: new Date().toISOString()
        })
      });

      console.log(`[Radar Heartbeat] Sent for ${chatId}: ${count} messages`);
      heartbeatState.chatCounts[chatId] = 0; // Reset counter
    }

    heartbeatState.lastBeat = new Date().toISOString();
  } catch (error) {
    console.error('[Radar Heartbeat] Error:', error);
  }
}
