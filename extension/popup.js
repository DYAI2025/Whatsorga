// @ts-nocheck — DOM null-checks deferred to Task 3.6
import { loadConfig, saveConfig } from './src/lib/config.js';

/**
 * Pure handler used by the Save button. Exposed for testing.
 * @param {{ serverUrl:string, apiKey:string }} input
 */
export async function applyServerForm(input) {
  await saveConfig({ serverUrl: input.serverUrl, apiKey: input.apiKey });
  await chrome.runtime.sendMessage({ type: 'CONFIG_UPDATED' }).catch(() => {});
}

/**
 * Probe /health to confirm the saved config actually reaches the server.
 * @param {{ serverUrl:string, apiKey:string }} cfg
 * @returns {Promise<{ ok:boolean, status?:number, error?:string }>}
 */
export async function probeHealth(cfg) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 5000);
  try {
    const r = await fetch(`${cfg.serverUrl}/health`, {
      headers: { Authorization: `Bearer ${cfg.apiKey}` },
      signal: ctrl.signal,
    });
    return { ok: r.ok, status: r.status };
  } catch (err) {
    return { ok: false, error: err.message || String(err) };
  } finally {
    clearTimeout(t);
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  const serverUrlInput = document.getElementById('serverUrl');
  const apiKeyInput = document.getElementById('apiKey');
  const saveServerBtn = document.getElementById('saveServerBtn');
  const newContactInput = document.getElementById('newContact');
  const addContactBtn = document.getElementById('addContactBtn');
  const whitelistItems = document.getElementById('whitelistItems');
  const enabledToggle = document.getElementById('enabledToggle');

  // Load saved config
  const cfg = await loadConfig();
  serverUrlInput.value = cfg.serverUrl || '';
  apiKeyInput.value = cfg.apiKey || '';
  enabledToggle.checked = cfg.enabled !== false;
  renderWhitelist(cfg.whitelist || []);

  // Save server config
  saveServerBtn.addEventListener('click', async () => {
    try {
      await applyServerForm({ serverUrl: serverUrlInput.value, apiKey: apiKeyInput.value });
      showSaved(saveServerBtn);
    } catch (err) {
      setStatus('error', err.message || 'Invalid URL');
    }
  });

  // Add contact to whitelist
  async function addContact() {
    const name = newContactInput.value.trim();
    if (!name) return;
    const current = await loadConfig();
    const list = current.whitelist || [];
    if (!list.some((w) => w.toLowerCase() === name.toLowerCase())) {
      await saveConfig({ whitelist: [...list, name] });
      notifyConfigUpdated();
    }
    newContactInput.value = '';
    const updated = await loadConfig();
    renderWhitelist(updated.whitelist || []);
  }

  addContactBtn.addEventListener('click', addContact);
  newContactInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') addContact();
  });

  // Toggle enabled
  enabledToggle.addEventListener('change', async () => {
    await saveConfig({ enabled: enabledToggle.checked });
    notifyConfigUpdated();
  });

  // Refresh status
  refreshStatus();
  setInterval(refreshStatus, 3000);

  // --- Functions ---

  function renderWhitelist(list) {
    whitelistItems.innerHTML = '';
    if (list.length === 0) {
      whitelistItems.innerHTML = '<li class="empty">No contacts added yet</li>';
      return;
    }
    list.forEach((name) => {
      const li = document.createElement('li');
      li.className = 'whitelist-entry';

      const span = document.createElement('span');
      span.textContent = name;

      const removeBtn = document.createElement('button');
      removeBtn.textContent = 'x';
      removeBtn.className = 'btn-remove';
      removeBtn.addEventListener('click', async () => {
        const current = await loadConfig();
        const updated = (current.whitelist || []).filter((w) => w !== name);
        await saveConfig({ whitelist: updated });
        notifyConfigUpdated();
        renderWhitelist(updated);
      });

      li.appendChild(span);
      li.appendChild(removeBtn);
      whitelistItems.appendChild(li);
    });
  }

  async function refreshStatus() {
    // Content script status
    try {
      const tabs = await chrome.tabs.query({ url: '*://web.whatsapp.com/*' });
      if (tabs.length > 0) {
        const response = await chrome.tabs.sendMessage(tabs[0].id, { type: 'GET_STATUS' });
        if (response) {
          document.getElementById('extEnabled').textContent = response.enabled ? 'Active' : 'Paused';
          document.getElementById('currentChat').textContent = response.currentChat?.name || '--';
          document.getElementById('isWhitelisted').textContent = response.isWhitelisted ? 'Yes' : 'No';
          document.getElementById('sentCount').textContent = response.sentCount || 0;

          const obsEl = document.getElementById('observerStatus');
          if (response.observerActive) {
            const reconLabel = response.reconnectCount > 0 ? ` (${response.reconnectCount}x)` : '';
            obsEl.textContent = `Active${reconLabel}`;
            obsEl.style.color = '#4caf50';
          } else if (response.lastScanAge !== null) {
            obsEl.textContent = 'Reconnecting';
            obsEl.style.color = '#ff9800';
          } else {
            obsEl.textContent = 'Waiting';
            obsEl.style.color = '#9e9e9e';
          }

          setStatus(response.enabled ? 'success' : 'warning',
            response.enabled ? 'Capturing' : 'Paused');
        }
      } else {
        setStatus('warning', 'Open WhatsApp Web');
        document.getElementById('extEnabled').textContent = '--';
        document.getElementById('currentChat').textContent = '--';
        document.getElementById('isWhitelisted').textContent = '--';
      }
    } catch {
      setStatus('warning', 'Connecting...');
    }

    // Background status
    try {
      const bgStatus = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });
      if (bgStatus) {
        document.getElementById('queueSize').textContent = bgStatus.queueSize || 0;
        if (!bgStatus.configured) {
          setStatus('error', 'Server not configured');
        }
      }
    } catch { /* ignore */ }
  }

  function setStatus(type, text) {
    document.getElementById('statusDot').className = `status-dot ${type}`;
    document.getElementById('statusText').textContent = text;
  }

  function notifyConfigUpdated() {
    chrome.runtime.sendMessage({ type: 'CONFIG_UPDATED' }).catch(() => {});
  }

  function showSaved(btn) {
    const original = btn.textContent;
    btn.textContent = 'Saved!';
    btn.classList.add('saved');
    setTimeout(() => {
      btn.textContent = original;
      btn.classList.remove('saved');
    }, 1500);
  }
});
