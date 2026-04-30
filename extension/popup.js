import { loadConfig, saveConfig } from './src/lib/config.js';
import { createRouter } from './src/lib/router.js';

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
 * @returns {Promise<{ ok:boolean, status?:number, error?:string, skipped?:string }>}
 */
export async function probeHealth(cfg) {
  const serverUrl = (cfg.serverUrl || '').trim();
  const apiKey = (cfg.apiKey || '').trim();
  if (!serverUrl || !apiKey) {
    return { ok: false, error: 'not_configured', skipped: 'not_configured' };
  }

  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 5000);
  try {
    const r = await fetch(`${serverUrl}/health`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: ctrl.signal,
    });
    return { ok: r.ok, status: r.status };
  } catch (/** @type {any} */ err) {
    return { ok: false, error: err.message || String(err) };
  } finally {
    clearTimeout(t);
  }
}

/**
 * Collect a redacted diagnostic snapshot for bug reports.
 * @returns {Promise<object>}
 */
export async function collectDiagnostics() {
  const cfg = await loadConfig();
  const snap = await createRouter().snapshot();
  return {
    timestamp: new Date().toISOString(),
    config: { ...cfg, apiKey: cfg.apiKey ? '***' : '' },
    snapshot: snap,
    userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : 'n/a',
  };
}

document.addEventListener('DOMContentLoaded', async () => {
  const serverUrlInput = /** @type {HTMLInputElement} */ (document.getElementById('serverUrl'));
  const apiKeyInput = /** @type {HTMLInputElement} */ (document.getElementById('apiKey'));
  const saveServerBtn = /** @type {HTMLButtonElement} */ (document.getElementById('saveServerBtn'));
  const newContactInput = /** @type {HTMLInputElement} */ (document.getElementById('newContact'));
  const addContactBtn = /** @type {HTMLButtonElement} */ (document.getElementById('addContactBtn'));
  const whitelistItems = /** @type {HTMLElement} */ (document.getElementById('whitelistItems'));
  const enabledToggle = /** @type {HTMLInputElement} */ (document.getElementById('enabledToggle'));

  // Load saved config
  const cfg = await loadConfig();
  serverUrlInput.value = cfg.serverUrl || '';
  apiKeyInput.value = cfg.apiKey || '';
  enabledToggle.checked = cfg.enabled !== false;
  el('eventVersion').textContent = String(cfg.eventVersion ?? 1);
  renderWhitelist(cfg.whitelist || []);

  // Save server config + health probe
  saveServerBtn.addEventListener('click', async () => {
    try {
      await applyServerForm({ serverUrl: serverUrlInput.value, apiKey: apiKeyInput.value });
      showSaved(saveServerBtn);
      const savedCfg = await loadConfig();
      const probe = await probeHealth(savedCfg);
      el('healthDot').className = `status-dot ${probe.ok ? 'success' : 'error'}`;
      el('healthText').textContent = probe.ok
        ? 'OK (200)'
        : (probe.status ? `Server ${probe.status}` : 'Network error');
    } catch (/** @type {any} */ err) {
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

  // Diagnostic export
  el('diagBtn').addEventListener('click', async () => {
    const diag = await collectDiagnostics();
    const blob = new Blob([JSON.stringify(diag, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `whatsorga-diag-${diag.timestamp}.json`;
    a.click();
    URL.revokeObjectURL(url);
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
      if (tabs.length > 0 && tabs[0].id !== undefined && tabs[0].id !== null) {
        const response = /** @type {any} */ (
          await chrome.tabs.sendMessage(tabs[0].id, { type: 'GET_STATUS' })
        );
        if (response) {
          el('extEnabled').textContent = response.enabled ? 'Active' : 'Paused';
          el('currentChat').textContent = response.currentChat?.name || '--';
          el('isWhitelisted').textContent = response.isWhitelisted ? 'Yes' : 'No';
          el('sentCount').textContent = response.sentCount || 0;

          const obsEl = el('observerStatus');
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
        el('extEnabled').textContent = '--';
        el('currentChat').textContent = '--';
        el('isWhitelisted').textContent = '--';
      }
    } catch {
      setStatus('warning', 'Connecting...');
    }

    // Background status
    try {
      const bgStatus = /** @type {any} */ (
        await chrome.runtime.sendMessage({ type: 'GET_STATUS' })
      );
      if (bgStatus) {
        el('queueSize').textContent = bgStatus.queueSize || 0;
        if (bgStatus.droppedCount !== undefined) {
          el('droppedCount').textContent = String(bgStatus.droppedCount);
        }
        if (!bgStatus.configured) {
          setStatus('error', 'Server not configured');
        }
      }
    } catch { /* ignore */ }
  }

  /** @param {string} id @returns {HTMLElement} */
  function el(id) {
    return /** @type {HTMLElement} */ (document.getElementById(id));
  }

  /** @param {string} type @param {string|number} text */
  function setStatus(type, text) {
    el('statusDot').className = `status-dot ${type}`;
    el('statusText').textContent = String(text);
  }

  function notifyConfigUpdated() {
    chrome.runtime.sendMessage({ type: 'CONFIG_UPDATED' }).catch(() => {});
  }

  /** @param {HTMLElement} btn */
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
