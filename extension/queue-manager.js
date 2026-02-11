// Message Queue Manager for reliable message capture
class MessageQueue {
  constructor() {
    this.storageKey = 'radar_message_queue';
  }

  async enqueue(message) {
    const queue = await this._getQueue();
    const queueItem = {
      id: `${message.messageId}_${Date.now()}`,
      message: message,
      status: 'pending',
      retryCount: 0,
      lastAttempt: null,
      enqueuedAt: new Date().toISOString()
    };
    queue.push(queueItem);
    await this._saveQueue(queue);
    return queueItem.id;
  }

  async markConfirmed(id) {
    const queue = await this._getQueue();
    const index = queue.findIndex(item => item.id === id);
    if (index !== -1) {
      queue.splice(index, 1); // Remove confirmed messages
      await this._saveQueue(queue);
      return true;
    }
    return false;
  }

  async getPending() {
    const queue = await this._getQueue();
    return queue.filter(item => item.status === 'pending');
  }

  async incrementRetry(id) {
    const queue = await this._getQueue();
    const item = queue.find(item => item.id === id);
    if (item) {
      item.retryCount++;
      item.lastAttempt = new Date().toISOString();

      // After 3 retries, mark as failed and remove
      if (item.retryCount >= 3) {
        console.error('[Radar Queue] Message failed after 3 retries:', item.id);
        const index = queue.indexOf(item);
        queue.splice(index, 1);
      }

      await this._saveQueue(queue);
      return item.retryCount;
    }
    return 0;
  }

  async getQueueSize() {
    const queue = await this._getQueue();
    return queue.length;
  }

  async cleanup() {
    // Remove old confirmed messages (> 100 in queue)
    const queue = await this._getQueue();
    if (queue.length > 100) {
      console.log('[Radar Queue] Cleaning up old messages');
      queue.splice(0, queue.length - 100);
      await this._saveQueue(queue);
    }
  }

  async _getQueue() {
    const result = await chrome.storage.local.get(this.storageKey);
    return result[this.storageKey] || [];
  }

  async _saveQueue(queue) {
    await chrome.storage.local.set({ [this.storageKey]: queue });
  }
}

// Export for use in content.js
window.MessageQueue = MessageQueue;
