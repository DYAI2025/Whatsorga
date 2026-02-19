// Message Queue Manager for reliable message capture
class MessageQueue {
  constructor() {
    this.storageKey = 'radar_message_queue';
  }

  enqueue(message) {
    const queue = this._getQueue();
    const queueItem = {
      id: `${message.messageId}_${Date.now()}`,
      message: message,
      status: 'pending',
      retryCount: 0,
      lastAttempt: null,
      enqueuedAt: new Date().toISOString()
    };
    queue.push(queueItem);
    this._saveQueue(queue);
    return queueItem.id;
  }

  markConfirmed(id) {
    const queue = this._getQueue();
    const index = queue.findIndex(item => item.id === id);
    if (index !== -1) {
      queue.splice(index, 1); // Remove confirmed messages
      this._saveQueue(queue);
      return true;
    }
    return false;
  }

  getPending() {
    const queue = this._getQueue();
    return queue.filter(item => item.status === 'pending');
  }

  incrementRetry(id) {
    const queue = this._getQueue();
    const item = queue.find(item => item.id === id);
    if (item) {
      item.retryCount++;
      item.lastAttempt = new Date().toISOString();

      // After 5 retries, mark as failed and remove
      if (item.retryCount >= 5) {
        console.error('[Radar Queue] Message failed after 5 retries:', item.id);
        const index = queue.indexOf(item);
        queue.splice(index, 1);
      }

      this._saveQueue(queue);
      return item.retryCount;
    }
    return 0;
  }

  getQueueSize() {
    const queue = this._getQueue();
    return queue.length;
  }

  cleanup() {
    // Remove old confirmed messages (> 100 in queue)
    const queue = this._getQueue();
    if (queue.length > 100) {
      console.log('[Radar Queue] Cleaning up old messages');
      queue.splice(0, queue.length - 100);
      this._saveQueue(queue);
    }
  }

  _getQueue() {
    try {
      const data = localStorage.getItem(this.storageKey);
      return data ? JSON.parse(data) : [];
    } catch (error) {
      console.error('[Radar Queue] Error reading queue from localStorage:', error);
      return [];
    }
  }

  _saveQueue(queue) {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify(queue));
    } catch (error) {
      console.error('[Radar Queue] Error saving queue to localStorage:', error);
    }
  }
}

// Export for use in content.js
window.MessageQueue = MessageQueue;
