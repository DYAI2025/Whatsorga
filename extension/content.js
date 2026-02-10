// Beziehungs-Radar Content Script
// Forked from What's That!? v2.7 — keeps DOM scanning, adds whitelist + server forwarding
console.log('[Radar] Content script loaded');

class RadarTracker {
  constructor() {
    this.sentMessageIds = new Set();
    this.whitelist = [];
    this.enabled = false;
    this.currentChat = { id: 'unknown', name: 'Unknown' };
    this._scanTimer = null;
    this.init();
  }

  async init() {
    await this.loadConfig();
    this.waitForWhatsApp();

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
          sentCount: this.sentMessageIds.size
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

  // --- WhatsApp readiness (from What's That!?) ---

  waitForWhatsApp(attempts = 0) {
    if (!chrome?.runtime?.id) return;

    const main = document.querySelector('#main');
    const messages = document.querySelectorAll('[data-pre-plain-text]');

    if (main && messages.length > 0) {
      console.log('[Radar] WhatsApp ready');
      this.scanMessages();
      this.setupObserver();
    } else if (attempts < 15) {
      setTimeout(() => this.waitForWhatsApp(attempts + 1), 2000);
    } else {
      console.log('[Radar] Timeout waiting for WhatsApp');
    }
  }

  setupObserver() {
    const mainContainer = document.querySelector('#main');
    if (!mainContainer) return;

    const observer = new MutationObserver(() => {
      if (!chrome?.runtime?.id) { observer.disconnect(); return; }
      this.scheduleScan();
    });

    observer.observe(mainContainer, { childList: true, subtree: true });
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
    // Strategy 1: header title
    const headerTitle = document.querySelector('#main header span[title]');
    if (headerTitle) {
      return { id: headerTitle.getAttribute('title'), name: headerTitle.getAttribute('title') };
    }
    // Strategy 2: conversation panel header
    const convHeader = document.querySelector('[data-testid="conversation-header"] span[title]');
    if (convHeader) {
      return { id: convHeader.getAttribute('title'), name: convHeader.getAttribute('title') };
    }
    return { id: 'unknown', name: 'Unknown' };
  }

  isChatWhitelisted() {
    if (this.whitelist.length === 0) return false;
    const chatName = this.currentChat.name.toLowerCase();
    return this.whitelist.some(w => chatName.includes(w.toLowerCase()));
  }

  // --- Message scanning (adapted from What's That!?) ---

  scanMessages() {
    if (!this.enabled) return;

    this.currentChat = this.getCurrentChatInfo();
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

    messages.forEach(msg => {
      const prePlainText = msg.getAttribute('data-pre-plain-text') || '';
      const messageId = this.generateMessageId(msg, prePlainText);

      if (this.sentMessageIds.has(messageId)) return;

      const sender = this.extractSenderName(msg, prePlainText);
      const text = this.extractMessageText(msg);
      const timestamp = this.extractMessageTimestamp(msg, prePlainText);
      const replyTo = this.extractReplyTo(msg, sender);
      const audioInfo = this.extractAudioInfo(msg);

      if (!text && !audioInfo) return;

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
    });

    if (newMessages.length > 0) {
      newMessages.forEach(m => this.sentMessageIds.add(m.messageId));
      chrome.runtime.sendMessage({ type: 'NEW_MESSAGES', data: newMessages });
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

  extractSenderName(element, prePlainText) {
    // From data-pre-plain-text: "[14:23, 10.2.2026] Marike Stucke: "
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

  // --- Audio extraction (NEW) ---

  extractAudioInfo(element) {
    const row = element.closest('[role="row"]') || element;

    // Look for audio play button or audio element
    const audioPlay = row.querySelector(
      '[data-testid="audio-play"], [data-testid="ptt-play"], audio, [data-testid*="audio"]'
    );
    if (!audioPlay) return null;

    // Try to find the audio source URL
    const audioEl = row.querySelector('audio');
    if (audioEl?.src) {
      return { blob: audioEl.src, type: 'audio_url' };
    }

    // Mark as audio even without extractable blob (server can log it)
    return { blob: null, type: 'audio_detected' };
  }
}

// Start tracker
window.radarTracker = new RadarTracker();
