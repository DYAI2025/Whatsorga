// WhatsOrga Content Script
// Forked from What's That!? v2.7 — keeps DOM scanning, adds whitelist + server forwarding
console.log('[Radar] Content script loaded');

class RadarTracker {
  constructor() {
    this.sentMessageIds = new Set();
    this.whitelist = [];
    this.enabled = false;
    this.currentChat = { id: 'unknown', name: 'Unknown' };
    this._scanTimer = null;
    this._audioBlobCache = new Map();
    this.messageQueue = new MessageQueue();
    this._retryTimer = null;

    // Watchdog state
    this._currentMainEl = null;
    this._mainObserver = null;
    this._audioObserver = null;
    this._lastScanTime = 0;
    this._lastChatName = null;
    this._reconnectCount = 0;
    this._watchdogInterval = null;
    this._observerActive = false;

    this.init();
  }

  async init() {
    await this.loadConfig();
    await this._loadSentMessageIds();
    this.waitForWhatsApp();

    // Start retry scheduler (every 10 seconds)
    this._retryTimer = setInterval(() => {
      this.processPendingQueue();
      this.messageQueue.cleanup();
    }, 10000);

    // Start watchdog (every 5 seconds)
    this._watchdogInterval = setInterval(() => this.watchdog(), 5000);

    // Listen for config changes from popup
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg.type === 'CONFIG_UPDATED') {
        this.loadConfig();
        sendResponse({ ok: true });
      }
      if (msg.type === 'GET_STATUS') {
        sendResponse({
          enabled: this.enabled,
          currentChat: this.currentChat,
          isWhitelisted: this.isChatWhitelisted(),
          sentCount: this.sentMessageIds.size,
          observerActive: this._observerActive,
          lastScanAge: this._lastScanTime ? Math.round((Date.now() - this._lastScanTime) / 1000) : null,
          reconnectCount: this._reconnectCount
        });
      }
      return true;
    });
  }

  async loadConfig() {
    const data = await chrome.storage.local.get(['whitelist', 'enabled']);
    this.whitelist = data.whitelist || [];
    this.enabled = data.enabled !== false;
    console.log(`[Radar] Config: enabled=${this.enabled}, whitelist=[${this.whitelist.join(', ')}]`);
  }

  // --- sentMessageIds persistence ---

  async _loadSentMessageIds() {
    try {
      const data = await chrome.storage.local.get(['sentMessageIds']);
      const ids = data.sentMessageIds || [];
      this.sentMessageIds = new Set(ids);
      console.log(`[Radar] Loaded ${this.sentMessageIds.size} sent message IDs from storage`);
    } catch (e) {
      console.log(`[Radar] Failed to load sentMessageIds: ${e.message}`);
    }
  }

  async _saveSentMessageIds() {
    try {
      let ids = Array.from(this.sentMessageIds);
      // Rolling window: keep only the most recent 5000
      if (ids.length > 5000) {
        ids = ids.slice(ids.length - 5000);
        this.sentMessageIds = new Set(ids);
      }
      await chrome.storage.local.set({ sentMessageIds: ids });
    } catch (e) {
      console.log(`[Radar] Failed to save sentMessageIds: ${e.message}`);
    }
  }

  // --- Watchdog: permanent health check loop ---

  watchdog() {
    if (!chrome?.runtime?.id) return;

    const mainEl = document.querySelector('#main');

    // 1. Is #main present?
    if (!mainEl) {
      if (this._observerActive) {
        console.log('[Radar] Watchdog: #main gone, observer orphaned');
        this._disconnectObservers();
      }
      return;
    }

    // 2. Has #main changed (new DOM reference)?
    if (mainEl !== this._currentMainEl) {
      console.log('[Radar] Watchdog: #main changed, reconnecting observer');
      this._reconnectCount++;
      this._setupObservers(mainEl);
    }

    // 3. Has chat name changed?
    const chatInfo = this.getCurrentChatInfo();
    if (chatInfo.name !== this._lastChatName && chatInfo.name !== 'Unknown') {
      console.log(`[Radar] Watchdog: chat changed from "${this._lastChatName}" to "${chatInfo.name}"`);
      this._lastChatName = chatInfo.name;
      this.currentChat = chatInfo;
      this.scheduleScan();
    }

    // 4. Force-scan safety net every 30s
    if (Date.now() - this._lastScanTime > 30000) {
      console.log('[Radar] Watchdog: force-scan (30s safety net)');
      this.scheduleScan();
    }
  }

  _disconnectObservers() {
    if (this._mainObserver) {
      this._mainObserver.disconnect();
      this._mainObserver = null;
    }
    if (this._audioObserver) {
      this._audioObserver.disconnect();
      this._audioObserver = null;
    }
    this._observerActive = false;
    this._currentMainEl = null;
  }

  _setupObservers(mainEl) {
    // Disconnect old observers first
    this._disconnectObservers();

    // Main message observer
    this._mainObserver = new MutationObserver(() => {
      if (!chrome?.runtime?.id) { this._disconnectObservers(); return; }
      this.scheduleScan();
    });
    this._mainObserver.observe(mainEl, { childList: true, subtree: true });

    // Audio observer
    this._audioObserver = new MutationObserver((mutations) => {
      if (!chrome?.runtime?.id) { this._disconnectObservers(); return; }
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (!(node instanceof HTMLElement)) continue;
          const audioEls = node.tagName === 'AUDIO' ? [node] : node.querySelectorAll?.('audio') || [];
          for (const audioEl of audioEls) {
            if (audioEl.src) {
              this._captureBlobImmediately(audioEl);
            }
          }
        }
      }
    });
    this._audioObserver.observe(mainEl, { childList: true, subtree: true });

    this._currentMainEl = mainEl;
    this._observerActive = true;
    console.log('[Radar] Observers attached to #main');
  }

  // --- WhatsApp readiness (initial setup, watchdog takes over) ---

  waitForWhatsApp(attempts = 0) {
    if (!chrome?.runtime?.id) return;

    const main = document.querySelector('#main');
    const messages = document.querySelectorAll('[data-pre-plain-text]');

    if (main && messages.length > 0) {
      console.log('[Radar] WhatsApp ready');
      this._setupObservers(main);
      this.scanMessages();
    } else if (attempts < 15) {
      setTimeout(() => this.waitForWhatsApp(attempts + 1), 2000);
    } else {
      console.log('[Radar] Initial wait timeout — watchdog will keep trying');
    }
  }

  // Legacy methods kept for compatibility but routed through new system
  setupObserver() {
    const mainEl = document.querySelector('#main');
    if (mainEl) this._setupObservers(mainEl);
  }

  setupAudioObserver() {
    // Now handled by _setupObservers
  }

  async _captureBlobImmediately(audioEl) {
    const src = audioEl.src;
    if (!src || this._audioBlobCache.has(src)) return;

    try {
      const response = await fetch(src);
      if (!response.ok) return;
      const blob = await response.blob();
      const buffer = await blob.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = '';
      for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      const base64 = btoa(binary);
      this._audioBlobCache.set(src, base64);
      console.log(`[Radar] Audio blob captured: ${bytes.length} bytes`);
    } catch (e) {
      console.log(`[Radar] Audio blob capture failed: ${e.message}`);
    }
  }

  scheduleScan() {
    if (this._scanTimer) clearTimeout(this._scanTimer);
    this._scanTimer = setTimeout(() => {
      this.scanMessages();
      this._scanTimer = null;
    }, 500);
  }

  // --- Chat info extraction ---

  getCurrentChatInfo() {
    // Strategy 1: conversation-info-header chat title (2025+ DOM)
    const chatTitle = document.querySelector('span[data-testid="conversation-info-header-chat-title"]');
    if (chatTitle?.textContent?.trim()) {
      const name = chatTitle.textContent.trim();
      return { id: name, name };
    }
    // Strategy 2: header with title attribute
    const headerTitle = document.querySelector('#main header span[title]');
    if (headerTitle) {
      const name = headerTitle.getAttribute('title');
      return { id: name, name };
    }
    // Strategy 3: conversation-header testid
    const convHeader = document.querySelector('[data-testid="conversation-header"] span[title]');
    if (convHeader) {
      const name = convHeader.getAttribute('title');
      return { id: name, name };
    }
    // Strategy 4: span with dir="auto" in #main header (2026 WhatsApp Web)
    const headerArea = document.querySelector('#main header');
    if (headerArea) {
      const autoSpan = headerArea.querySelector('span[dir="auto"]');
      if (autoSpan?.textContent?.trim()) {
        const name = autoSpan.textContent.trim();
        if (name.length > 1 && name.length < 100) {
          return { id: name, name };
        }
      }
    }
    // Strategy 5: aria-label on header
    const headerEl = document.querySelector('#main header [role="button"][aria-label]');
    if (headerEl) {
      const name = headerEl.getAttribute('aria-label');
      if (name) return { id: name, name };
    }
    return { id: 'unknown', name: 'Unknown' };
  }

  isChatWhitelisted() {
    if (this.whitelist.length === 0) return false;
    const chatName = this.currentChat.name.toLowerCase();
    return this.whitelist.some(w => chatName.includes(w.toLowerCase()));
  }

  // --- Message scanning (adapted from What's That!?) ---

  async scanMessages() {
    if (!this.enabled) { console.log('[Radar] Scan skipped: disabled'); return; }

    this._lastScanTime = Date.now();

    this.currentChat = this.getCurrentChatInfo();
    console.log('[Radar] Current chat:', this.currentChat.name, '| Whitelisted:', this.isChatWhitelisted());
    if (!this.isChatWhitelisted()) return;

    // Multi-strategy message detection (from What's That!?)
    let messages = document.querySelectorAll('[data-pre-plain-text]');
    if (messages.length === 0) {
      messages = document.querySelectorAll('[role="row"] .copyable-text');
    }
    if (messages.length === 0) {
      messages = document.querySelectorAll('.copyable-text[data-id]');
    }
    if (messages.length === 0) {
      const mainChat = document.querySelector('#main');
      if (mainChat) {
        messages = mainChat.querySelectorAll('[data-id^="true"], [data-id^="false"]');
      }
    }

    const newMessages = [];

    for (const msg of messages) {
      const prePlainText = msg.getAttribute('data-pre-plain-text') || '';
      const text = this.extractMessageText(msg);
      const messageId = this.generateStableId(prePlainText, text);

      if (this.sentMessageIds.has(messageId)) continue;

      const sender = this.extractSenderName(msg, prePlainText);
      const timestamp = this.extractMessageTimestamp(msg, prePlainText);
      const replyTo = this.extractReplyTo(msg, sender);
      const audioInfo = await this.extractAudioInfo(msg);

      if (!text && !audioInfo) continue;

      newMessages.push({
        messageId,
        sender: sender || 'Unknown',
        text: text || '',
        timestamp,
        chatId: this.currentChat.id,
        chatName: this.currentChat.name,
        replyTo: replyTo || null,
        hasAudio: !!audioInfo,
        audioBlob: audioInfo?.blob || null
      });
    }

    if (newMessages.length > 0) {
      newMessages.forEach(m => this.sentMessageIds.add(m.messageId));
      this._saveSentMessageIds();
      this.sendToAPI(newMessages);
    }
  }

  // --- Extraction methods (from What's That!?) ---

  generateMessageId(element, prePlainText) {
    const text = element.textContent || '';
    const raw = `${prePlainText}|${text.substring(0, 100)}|${this.currentChat.id}`;
    let hash = 0;
    for (let i = 0; i < raw.length; i++) {
      hash = ((hash << 5) - hash + raw.charCodeAt(i)) | 0;
    }
    return `msg_${Math.abs(hash)}`;
  }

  // Stable hash using extracted text (not raw DOM textContent which changes with read receipts)
  generateStableId(prePlainText, extractedText) {
    const raw = `${prePlainText}|${(extractedText || '').substring(0, 100)}|${this.currentChat.id}`;
    let hash = 0;
    for (let i = 0; i < raw.length; i++) {
      hash = ((hash << 5) - hash + raw.charCodeAt(i)) | 0;
    }
    return `msg_${Math.abs(hash)}`;
  }

  extractSenderName(element, prePlainText) {
    // From data-pre-plain-text: "[14:23, 10.2.2026] Contact Name: "
    const match = prePlainText.match(/\]\s*([^:]+):/);
    if (match) return match[1].trim();

    // From aria-label
    const row = element.closest('[role="row"]');
    if (row) {
      const label = row.getAttribute('aria-label') || '';
      const nameMatch = label.match(/^([^:]+):/);
      if (nameMatch) return nameMatch[1].trim();
    }

    return null;
  }

  extractMessageText(element) {
    // Strategy 1: selectable-text copyable-text
    let el = element.querySelector('.selectable-text.copyable-text');
    if (el?.textContent?.trim()) return el.textContent.trim();

    // Strategy 2: any selectable-text
    el = element.querySelector('.selectable-text');
    if (el?.textContent?.trim()) return el.textContent.trim();

    // Strategy 3: message row parent
    const row = element.closest('[role="row"]');
    if (row) {
      el = row.querySelector('.selectable-text.copyable-text, .selectable-text, [data-testid="conversation-text"]');
      if (el?.textContent?.trim()) return el.textContent.trim();
    }

    // Strategy 4: innerText fallback
    if (element.innerText) {
      let text = element.innerText.trim();
      text = text.replace(/^\d{1,2}:\d{2}\s*[AP]M\s*/i, '');
      text = text.replace(/\s*\d{1,2}:\d{2}\s*[AP]M\s*$/i, '');
      if (text.length > 0 && text.length < 10000) return text;
    }

    return null;
  }

  extractMessageTimestamp(element, prePlainText) {
    // From data-pre-plain-text: "[14:23, 10.2.2026]"
    const match = prePlainText.match(/\[(\d{1,2}:\d{2}),?\s*(\d{1,2}\.\d{1,2}\.\d{4})\]/);
    if (match) {
      const [_, time, date] = match;
      const [day, month, year] = date.split('.');
      return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}T${time}:00`;
    }

    // From data-testid or time element
    const timeEl = element.querySelector('span[data-testid="msg-time"], time');
    if (timeEl) return timeEl.textContent?.trim() || null;

    return new Date().toISOString();
  }

  extractReplyTo(element, sender) {
    const row = element.closest('[role="row"]');
    if (!row) return null;

    const quotedHeader = row.querySelector('[data-testid="quoted-message"] [aria-label]');
    if (quotedHeader) {
      const label = quotedHeader.getAttribute('aria-label') || '';
      const nameMatch = label.match(/^([^:,]+)/);
      if (nameMatch && nameMatch[1].trim() !== sender) return nameMatch[1].trim();
    }

    return null;
  }

  // --- Audio extraction ---

  async extractAudioInfo(element) {
    const row = element.closest('[role="row"]') || element;

    // Look for audio play button or audio element
    const audioPlay = row.querySelector(
      '[data-testid="audio-play"], [data-testid="ptt-play"], audio, [data-testid*="audio"]'
    );
    if (!audioPlay) return null;

    // Try to find the audio source URL
    const audioEl = row.querySelector('audio');
    if (audioEl?.src) {
      // Check cache first (blob captured before it expired)
      const cached = this._audioBlobCache.get(audioEl.src);
      if (cached) {
        return { blob: cached, type: 'audio_base64' };
      }

      // Try live fetch — await so the cache gets populated
      await this._captureBlobImmediately(audioEl);
      const justCached = this._audioBlobCache.get(audioEl.src);
      if (justCached) {
        return { blob: justCached, type: 'audio_base64' };
      }

      return { blob: null, type: 'audio_url_expired' };
    }

    // Mark as audio even without extractable blob (server can log it)
    console.log('[Radar] Audio detected but no <audio> element yet (needs play tap)');
    return { blob: null, type: 'audio_detected' };
  }

  // --- Queue-based sending with retry logic ---

  sendToAPI(messages) {
    if (!messages || messages.length === 0) return;

    // Enqueue all messages first (synchronous - no await)
    const queueIds = [];
    for (const msg of messages) {
      const id = this.messageQueue.enqueue(msg);
      queueIds.push(id);

      // Notify background for heartbeat tracking
      chrome.runtime.sendMessage({
        type: 'MESSAGE_CAPTURED',
        chatId: msg.chatId
      }).catch(err => console.log('[Radar] Background notification failed:', err.message));
    }

    console.log(`[Radar] Enqueued ${messages.length} messages`);

    // Attempt to send immediately
    this.processPendingQueue();
  }

  async processPendingQueue() {
    const pending = this.messageQueue.getPending();
    if (pending.length === 0) return;

    // Batch send (max 10 at a time)
    const batch = pending.slice(0, 10);
    const messages = batch.map(item => item.message);

    try {
      // Route through background service worker (bypasses WhatsApp Web CSP)
      const response = await chrome.runtime.sendMessage({
        type: 'NEW_MESSAGES',
        data: messages
      });

      if (response?.ok) {
        for (const item of batch) {
          this.messageQueue.markConfirmed(item.id);
        }
        console.log(`[Radar] Confirmed ${batch.length} messages via background`);
      } else if (response?.authError) {
        for (const item of batch) {
          this.messageQueue.markConfirmed(item.id);
        }
        console.error('[Radar] Auth error - check API key');
      } else {
        for (const item of batch) {
          this.messageQueue.incrementRetry(item.id);
        }
        console.warn('[Radar] Background send failed, will retry');
      }
    } catch (error) {
      // Service worker channel closed — don't burn retries, just wait and retry
      if (error.message?.includes('message channel closed')) {
        console.warn('[Radar] Service worker inactive, retrying in 3s...');
        setTimeout(() => this.processPendingQueue(), 3000);
        return;
      }
      for (const item of batch) {
        this.messageQueue.incrementRetry(item.id);
      }
      console.warn('[Radar] Background message error, will retry:', error.message);
    }
  }
}

// Start tracker
window.radarTracker = new RadarTracker();
