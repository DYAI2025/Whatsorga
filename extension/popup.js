// Beziehungs-Radar Popup Script
document.addEventListener('DOMContentLoaded', async () => {
  const serverUrlInput = document.getElementById('serverUrl');
  const apiKeyInput = document.getElementById('apiKey');
  const saveServerBtn = document.getElementById('saveServerBtn');
  const newContactInput = document.getElementById('newContact');
  const addContactBtn = document.getElementById('addContactBtn');
  const whitelistItems = document.getElementById('whitelistItems');
  const enabledToggle = document.getElementById('enabledToggle');

  // Load saved config
  const data = await chrome.storage.local.get(['serverUrl', 'apiKey', 'whitelist', 'enabled']);
  serverUrlInput.value = data.serverUrl || '';
  apiKeyInput.value = data.apiKey || '';
  enabledToggle.checked = data.enabled !== false;
  renderWhitelist(data.whitelist || []);

  // Save server config
  saveServerBtn.addEventListener('click', async () => {
    await chrome.storage.local.set({
      serverUrl: serverUrlInput.value.trim().replace(/\/$/, ''),
      apiKey: apiKeyInput.value.trim()
    });
    notifyConfigUpdated();
    showSaved(saveServerBtn);
  });

  // Add contact to whitelist
  async function addContact() {
    const name = newContactInput.value.trim();
    if (!name) return;

    const current = await chrome.storage.local.get(['whitelist']);
    const list = current.whitelist || [];
    if (!list.some(w => w.toLowerCase() === name.toLowerCase())) {
      list.push(name);
      await chrome.storage.local.set({ whitelist: list });
      notifyConfigUpdated();
    }
    newContactInput.value = '';
    renderWhitelist(list);
  }

  addContactBtn.addEventListener('click', addContact);
  newContactInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') addContact();
  });

  // Toggle enabled
  enabledToggle.addEventListener('change', async () => {
    await chrome.storage.local.set({ enabled: enabledToggle.checked });
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
    list.forEach(name => {
      const li = document.createElement('li');
      li.className = 'whitelist-entry';

      const span = document.createElement('span');
      span.textContent = name;

      const removeBtn = document.createElement('button');
      removeBtn.textContent = 'x';
      removeBtn.className = 'btn-remove';
      removeBtn.addEventListener('click', async () => {
        const current = await chrome.storage.local.get(['whitelist']);
        const updated = (current.whitelist || []).filter(w => w !== name);
        await chrome.storage.local.set({ whitelist: updated });
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
