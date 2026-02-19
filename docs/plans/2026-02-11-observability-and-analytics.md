# Observability and Analytics Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Add capture reliability monitoring and enhanced dashboard analytics to Beziehungs-Radar

**Architecture:** Extension gains local message queue with retry logic and heartbeat monitoring. API adds capture-stats tracking and new analysis endpoints. Dashboard gets real-time monitoring view and interactive charts with new communication pattern visualizations.

**Tech Stack:** Vanilla JS (Extension), FastAPI + SQLAlchemy (API), Recharts (Dashboard Charts)

---

## Task 1: Extension Message Queue Manager

**Files:**
- Create: `extension/queue-manager.js`
- Modify: `extension/manifest.json` (add new script)

**Step 1: Create queue manager module**

Create `extension/queue-manager.js`:

```javascript
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
```

**Step 2: Update manifest.json**

Modify `extension/manifest.json` to load queue-manager before content script:

```json
"content_scripts": [
  {
    "matches": ["*://web.whatsapp.com/*"],
    "js": ["queue-manager.js", "content.js"],
    "run_at": "document_idle",
    "all_frames": false
  }
]
```

**Step 3: Commit**

```bash
git add extension/queue-manager.js extension/manifest.json
git commit -m "feat: add message queue manager with retry logic"
```

---

## Task 2: Extension Retry Scheduler Integration

**Files:**
- Modify: `extension/content.js` (integrate queue)

**Step 1: Initialize queue in RadarTracker**

Modify `extension/content.js`, add to constructor:

```javascript
constructor() {
  this.sentMessageIds = new Set();
  this.whitelist = [];
  this.enabled = false;
  this.currentChat = { id: 'unknown', name: 'Unknown' };
  this._scanTimer = null;
  this._audioBlobCache = new Map();
  this.messageQueue = new MessageQueue(); // NEW
  this._retryTimer = null; // NEW
  this.init();
}
```

**Step 2: Replace direct send with queue**

Find the `sendToAPI()` method in `content.js` and replace direct fetch with queue:

```javascript
async sendToAPI(messages) {
  if (!messages || messages.length === 0) return;

  // Enqueue all messages first
  const queueIds = [];
  for (const msg of messages) {
    const id = await this.messageQueue.enqueue(msg);
    queueIds.push(id);
  }

  console.log(`[Radar] Enqueued ${messages.length} messages`);

  // Attempt to send immediately
  await this.processPendingQueue();
}

async processPendingQueue() {
  const pending = await this.messageQueue.getPending();
  if (pending.length === 0) return;

  // Batch send (max 10 at a time)
  const batch = pending.slice(0, 10);
  const messages = batch.map(item => item.message);

  try {
    const config = await chrome.storage.local.get(['apiUrl', 'apiKey']);
    const apiUrl = config.apiUrl || 'http://localhost:8900';
    const apiKey = config.apiKey || 'changeme';

    const response = await fetch(`${apiUrl}/api/ingest`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body: JSON.stringify({ messages })
    });

    if (response.ok) {
      // Mark all as confirmed
      for (const item of batch) {
        await this.messageQueue.markConfirmed(item.id);
      }
      console.log(`[Radar] Confirmed ${batch.length} messages`);
    } else if (response.status === 401 || response.status === 403) {
      // Auth error - stop retrying
      console.error('[Radar] Auth error - check API key');
      return;
    } else {
      // Server error - increment retry
      for (const item of batch) {
        await this.messageQueue.incrementRetry(item.id);
      }
      console.warn(`[Radar] Server error ${response.status}, will retry`);
    }
  } catch (error) {
    // Network error - increment retry
    for (const item of batch) {
      await this.messageQueue.incrementRetry(item.id);
    }
    console.warn('[Radar] Network error, will retry:', error.message);
  }
}
```

**Step 3: Add retry scheduler**

Add retry timer setup in `init()` method:

```javascript
async init() {
  await this.loadConfig();
  this.waitForWhatsApp();

  // Start retry scheduler (every 10 seconds)
  this._retryTimer = setInterval(() => {
    this.processPendingQueue();
    this.messageQueue.cleanup();
  }, 10000);

  // Listen for config changes from popup
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    // ... existing code ...
  });
}
```

**Step 4: Test manually**

1. Load extension in Chrome
2. Stop API: `cd deploy && docker compose stop radar-api`
3. Send test message on WhatsApp Web
4. Check console: Should see "Enqueued 1 messages"
5. Start API: `docker compose start radar-api`
6. Wait 10s, check console: Should see "Confirmed 1 messages"

**Step 5: Commit**

```bash
git add extension/content.js
git commit -m "feat: integrate queue with retry scheduler"
```

---

## Task 3: Extension Heartbeat Sender

**Files:**
- Modify: `extension/background.js` (add heartbeat)

**Step 1: Add heartbeat state**

Add to `extension/background.js`:

```javascript
// Heartbeat tracking
let heartbeatState = {
  chatCounts: {}, // { chatId: messageCount }
  lastBeat: null,
  timer: null
};

// Initialize heartbeat on extension load
startHeartbeat();

function startHeartbeat() {
  // Send heartbeat every 60 seconds
  heartbeatState.timer = setInterval(async () => {
    await sendHeartbeat();
  }, 60000);
}

async function sendHeartbeat() {
  const config = await chrome.storage.local.get(['apiUrl', 'apiKey']);
  const apiUrl = config.apiUrl || 'http://localhost:8900';
  const apiKey = config.apiKey || 'changeme';

  // Get queue size from content script
  chrome.tabs.query({ url: '*://web.whatsapp.com/*' }, async (tabs) => {
    if (tabs.length === 0) return;

    const tab = tabs[0];
    try {
      // Send heartbeat for each tracked chat
      for (const [chatId, count] of Object.entries(heartbeatState.chatCounts)) {
        if (count === 0) continue;

        await fetch(`${apiUrl}/api/heartbeat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`
          },
          body: JSON.stringify({
            chatId,
            messageCount: count,
            queueSize: 0, // Will be updated when we can query queue
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
  });
}

// Listen for messages from content script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'MESSAGE_CAPTURED') {
    const { chatId } = message;
    heartbeatState.chatCounts[chatId] = (heartbeatState.chatCounts[chatId] || 0) + 1;
    sendResponse({ ok: true });
  }
  return true;
});
```

**Step 2: Notify background from content script**

Add to `extension/content.js` in `sendToAPI()` method after enqueue:

```javascript
async sendToAPI(messages) {
  if (!messages || messages.length === 0) return;

  // Enqueue all messages first
  const queueIds = [];
  for (const msg of messages) {
    const id = await this.messageQueue.enqueue(msg);
    queueIds.push(id);

    // Notify background for heartbeat tracking
    chrome.runtime.sendMessage({
      type: 'MESSAGE_CAPTURED',
      chatId: msg.chatId
    });
  }

  console.log(`[Radar] Enqueued ${messages.length} messages`);
  await this.processPendingQueue();
}
```

**Step 3: Commit**

```bash
git add extension/background.js extension/content.js
git commit -m "feat: add heartbeat sender for capture monitoring"
```

---

## Task 4: API CaptureStats Model

**Files:**
- Modify: `radar-api/app/storage/database.py` (add model)

**Step 1: Add CaptureStats model**

Add to `radar-api/app/storage/database.py` after the Termin model:

```python
class CaptureStats(Base):
    __tablename__ = "capture_stats"

    id = Column(Integer, primary_key=True)
    chat_id = Column(String, unique=True, index=True, nullable=False)
    last_heartbeat = Column(DateTime, nullable=False)
    messages_captured_24h = Column(Integer, default=0)
    error_count_24h = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Step 2: Run migration**

Create migration script `radar-api/migrations/add_capture_stats.py`:

```python
"""Add capture_stats table"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from app.storage.database import Base
from app.config import settings

engine = create_engine(settings.database_url_sync)

# Create table
Base.metadata.create_all(engine, tables=[CaptureStats.__table__])
print("Created capture_stats table")
```

**Step 3: Test locally**

```bash
cd radar-api
python migrations/add_capture_stats.py
```

Expected: "Created capture_stats table"

**Step 4: Commit**

```bash
git add radar-api/app/storage/database.py radar-api/migrations/add_capture_stats.py
git commit -m "feat: add CaptureStats database model"
```

---

## Task 5: API Heartbeat Endpoint

**Files:**
- Modify: `radar-api/app/ingestion/router.py` (add endpoint)

**Step 1: Add heartbeat endpoint**

Add to `radar-api/app/ingestion/router.py`:

```python
from app.storage.database import CaptureStats

class HeartbeatPayload(BaseModel):
    chatId: str
    messageCount: int
    queueSize: int
    timestamp: str


@router.post("/heartbeat")
async def receive_heartbeat(
    payload: HeartbeatPayload,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Receive heartbeat from extension with capture stats."""

    # Upsert capture_stats
    result = await session.execute(
        select(CaptureStats).where(CaptureStats.chat_id == payload.chatId)
    )
    stats = result.scalar_one_or_none()

    if stats:
        stats.last_heartbeat = datetime.utcnow()
        stats.messages_captured_24h += payload.messageCount
        stats.updated_at = datetime.utcnow()
    else:
        stats = CaptureStats(
            chat_id=payload.chatId,
            last_heartbeat=datetime.utcnow(),
            messages_captured_24h=payload.messageCount,
            error_count_24h=0,
        )
        session.add(stats)

    await session.commit()

    logger.info(f"Heartbeat received for {payload.chatId}: +{payload.messageCount} messages")
    return {"status": "ok"}
```

**Step 2: Test endpoint**

```bash
curl -X POST http://localhost:8900/api/heartbeat \
  -H "Authorization: Bearer changeme" \
  -H "Content-Type: application/json" \
  -d '{"chatId": "test", "messageCount": 5, "queueSize": 0, "timestamp": "2026-02-11T14:00:00"}'
```

Expected: `{"status":"ok"}`

**Step 3: Commit**

```bash
git add radar-api/app/ingestion/router.py
git commit -m "feat: add heartbeat endpoint for capture monitoring"
```

---

## Task 6: API Capture Stats Endpoint

**Files:**
- Modify: `radar-api/app/dashboard/router.py` (add endpoint)

**Step 1: Add capture-stats endpoint**

Add to `radar-api/app/dashboard/router.py`:

```python
from app.storage.database import CaptureStats

@router.get("/capture-stats")
async def get_capture_stats(
    chat_id: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get capture stats for monitoring dashboard."""

    query = select(CaptureStats)
    if chat_id:
        query = query.where(CaptureStats.chat_id == chat_id)

    result = await session.execute(query.order_by(desc(CaptureStats.last_heartbeat)))
    stats_list = result.scalars().all()

    now = datetime.utcnow()
    return {
        "stats": [
            {
                "chat_id": s.chat_id,
                "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
                "messages_24h": s.messages_captured_24h,
                "error_count": s.error_count_24h,
                "age_minutes": int((now - s.last_heartbeat).total_seconds() / 60) if s.last_heartbeat else 999,
                "status": _compute_status(s, now),
            }
            for s in stats_list
        ]
    }


def _compute_status(stats: CaptureStats, now: datetime) -> str:
    """Compute traffic light status: green, yellow, red."""
    if not stats.last_heartbeat:
        return "red"

    age_minutes = (now - stats.last_heartbeat).total_seconds() / 60
    error_rate = stats.error_count_24h / max(stats.messages_captured_24h, 1)

    if age_minutes > 15 or error_rate > 0.2:
        return "red"
    elif age_minutes > 5 or error_rate > 0.05:
        return "yellow"
    else:
        return "green"
```

**Step 2: Test endpoint**

```bash
curl http://localhost:8900/api/capture-stats \
  -H "Authorization: Bearer changeme"
```

Expected: `{"stats": [...]}`

**Step 3: Commit**

```bash
git add radar-api/app/dashboard/router.py
git commit -m "feat: add capture-stats endpoint with status logic"
```

---

## Task 7: Dashboard Monitoring View (HTML)

**Files:**
- Create: `radar-api/app/dashboard/static/monitoring.html`

**Step 1: Create monitoring page**

Create `radar-api/app/dashboard/static/monitoring.html`:

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Beziehungs-Radar Monitoring</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      margin: 0;
      padding: 20px;
      background: #f5f5f7;
    }
    .header {
      margin-bottom: 30px;
    }
    h1 {
      margin: 0 0 10px 0;
      font-size: 32px;
      font-weight: 600;
    }
    .subtitle {
      color: #666;
      font-size: 14px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 20px;
    }
    .chat-card {
      background: white;
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      position: relative;
    }
    .status-indicator {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      position: absolute;
      top: 20px;
      right: 20px;
    }
    .status-green { background: #34c759; }
    .status-yellow { background: #ffcc00; }
    .status-red { background: #ff3b30; }

    .chat-name {
      font-size: 18px;
      font-weight: 600;
      margin-bottom: 12px;
      padding-right: 24px;
    }
    .stat-row {
      display: flex;
      justify-content: space-between;
      margin: 8px 0;
      font-size: 14px;
    }
    .stat-label {
      color: #666;
    }
    .stat-value {
      font-weight: 500;
    }
    .last-sync {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #eee;
      font-size: 12px;
      color: #999;
    }
    .refresh-info {
      text-align: center;
      margin-top: 20px;
      color: #999;
      font-size: 12px;
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>🛰️ Capture Monitoring</h1>
    <div class="subtitle">Echtzeit-Status der WhatsApp-Erfassung</div>
  </div>

  <div id="grid" class="grid">
    <!-- Cards will be injected here -->
  </div>

  <div class="refresh-info">
    Auto-refresh alle 30 Sekunden
  </div>

  <script>
    const API_KEY = localStorage.getItem('radar_api_key') || 'changeme';
    const API_URL = 'http://localhost:8900';

    async function loadStats() {
      try {
        const response = await fetch(`${API_URL}/api/capture-stats`, {
          headers: { 'Authorization': `Bearer ${API_KEY}` }
        });
        const data = await response.json();
        renderCards(data.stats);
      } catch (error) {
        console.error('Failed to load stats:', error);
      }
    }

    function renderCards(stats) {
      const grid = document.getElementById('grid');

      if (stats.length === 0) {
        grid.innerHTML = '<p style="grid-column: 1/-1; text-align: center; color: #666;">Noch keine Chats erfasst</p>';
        return;
      }

      grid.innerHTML = stats.map(s => `
        <div class="chat-card">
          <div class="status-indicator status-${s.status}"></div>
          <div class="chat-name">${escapeHtml(s.chat_id)}</div>
          <div class="stat-row">
            <span class="stat-label">Messages (24h):</span>
            <span class="stat-value">${s.messages_24h}</span>
          </div>
          <div class="stat-row">
            <span class="stat-label">Fehlerrate:</span>
            <span class="stat-value">${((s.error_count / Math.max(s.messages_24h, 1)) * 100).toFixed(1)}%</span>
          </div>
          <div class="last-sync">
            Letztes Signal: vor ${s.age_minutes} min
          </div>
        </div>
      `).join('');
    }

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    // Initial load
    loadStats();

    // Auto-refresh every 30 seconds
    setInterval(loadStats, 30000);
  </script>
</body>
</html>
```

**Step 2: Test page**

Open `http://localhost:8900/static/monitoring.html` in browser.

Expected: Grid of chat cards with status indicators.

**Step 3: Commit**

```bash
git add radar-api/app/dashboard/static/monitoring.html
git commit -m "feat: add monitoring dashboard view"
```

---

## Task 8: Dashboard Interactive Charts Setup

**Files:**
- Create: `radar-api/app/dashboard/static/charts.html` (demo page with Recharts)

**Step 1: Create charts demo page**

Create `radar-api/app/dashboard/static/charts.html`:

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Interactive Charts Demo</title>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <script src="https://unpkg.com/recharts@2.5.0/dist/Recharts.js"></script>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      margin: 0;
      padding: 20px;
      background: #f5f5f7;
    }
    .chart-container {
      background: white;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }
    h2 {
      margin-top: 0;
      font-size: 20px;
      font-weight: 600;
    }
  </style>
</head>
<body>
  <h1>📊 Interactive Charts Demo</h1>
  <div id="root"></div>

  <script type="text/babel">
    const { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } = Recharts;

    // Sample sentiment drift data
    const sentimentData = [
      { date: '2026-02-01', avg_sentiment: 0.45, message_count: 12 },
      { date: '2026-02-02', avg_sentiment: 0.62, message_count: 8 },
      { date: '2026-02-03', avg_sentiment: 0.38, message_count: 15 },
      { date: '2026-02-04', avg_sentiment: 0.55, message_count: 10 },
      { date: '2026-02-05', avg_sentiment: 0.71, message_count: 18 },
      { date: '2026-02-06', avg_sentiment: 0.49, message_count: 14 },
      { date: '2026-02-07', avg_sentiment: 0.58, message_count: 11 },
    ];

    function SentimentChart() {
      return (
        <div className="chart-container">
          <h2>Sentiment Drift (Interactive)</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={sentimentData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis domain={[-1, 1]} />
              <Tooltip
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    return (
                      <div style={{
                        background: 'white',
                        padding: '10px',
                        border: '1px solid #ccc',
                        borderRadius: '4px'
                      }}>
                        <p><strong>{payload[0].payload.date}</strong></p>
                        <p>Sentiment: {payload[0].value.toFixed(3)}</p>
                        <p>Messages: {payload[0].payload.message_count}</p>
                      </div>
                    );
                  }
                  return null;
                }}
              />
              <Line
                type="monotone"
                dataKey="avg_sentiment"
                stroke="#007aff"
                strokeWidth={2}
                dot={{ fill: '#007aff', r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      );
    }

    function App() {
      return (
        <div>
          <SentimentChart />
          <p style={{ textAlign: 'center', color: '#666', fontSize: '14px' }}>
            Hover over Datenpunkte für Details • Scroll für Zoom
          </p>
        </div>
      );
    }

    ReactDOM.render(<App />, document.getElementById('root'));
  </script>
</body>
</html>
```

**Step 2: Test page**

Open `http://localhost:8900/static/charts.html` in browser.

Expected: Interactive line chart with hover tooltips.

**Step 3: Commit**

```bash
git add radar-api/app/dashboard/static/charts.html
git commit -m "feat: add interactive charts demo with Recharts"
```

---

## Task 9: API Communication Pattern Endpoint

**Files:**
- Modify: `radar-api/app/dashboard/router.py` (add new endpoint)

**Step 1: Add communication-pattern endpoint**

Add to `radar-api/app/dashboard/router.py`:

```python
@router.get("/communication-pattern/{chat_id}")
async def get_communication_pattern(
    chat_id: str,
    days: int = Query(default=30, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get message frequency by weekday and hour for heatmap."""
    since = datetime.utcnow() - timedelta(days=days)

    result = await session.execute(
        select(Message.timestamp, Message.sender)
        .where(and_(Message.chat_id == chat_id, Message.timestamp >= since))
    )
    rows = result.all()

    # Build heatmap: weekday x hour
    heatmap = [[0 for _ in range(24)] for _ in range(7)]  # 7 days x 24 hours

    for row in rows:
        weekday = row.timestamp.weekday()  # 0=Monday, 6=Sunday
        hour = row.timestamp.hour
        heatmap[weekday][hour] += 1

    return {
        "chat_id": chat_id,
        "days": days,
        "heatmap": heatmap,
        "weekday_labels": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    }
```

**Step 2: Test endpoint**

```bash
curl "http://localhost:8900/api/communication-pattern/test?days=7" \
  -H "Authorization: Bearer changeme"
```

Expected: `{"chat_id": "test", "heatmap": [[...], ...], ...}`

**Step 3: Commit**

```bash
git add radar-api/app/dashboard/router.py
git commit -m "feat: add communication-pattern endpoint for heatmap"
```

---

## Task 10: API Response Time Endpoint

**Files:**
- Modify: `radar-api/app/dashboard/router.py` (add endpoint)

**Step 1: Add response-time endpoint**

Add to `radar-api/app/dashboard/router.py`:

```python
@router.get("/response-times/{chat_id}")
async def get_response_times(
    chat_id: str,
    days: int = Query(default=30, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Calculate average response times per sender."""
    since = datetime.utcnow() - timedelta(days=days)

    result = await session.execute(
        select(Message.sender, Message.timestamp)
        .where(and_(Message.chat_id == chat_id, Message.timestamp >= since))
        .order_by(Message.timestamp)
    )
    rows = result.all()

    # Calculate response times
    response_times = {}
    last_timestamp = None
    last_sender = None

    for row in rows:
        if last_timestamp and last_sender != row.sender:
            # Different sender = response
            delta = (row.timestamp - last_timestamp).total_seconds() / 60  # minutes
            if delta < 1440:  # Ignore responses > 24h
                if row.sender not in response_times:
                    response_times[row.sender] = []
                response_times[row.sender].append(delta)

        last_timestamp = row.timestamp
        last_sender = row.sender

    # Calculate averages
    averages = {
        sender: sum(times) / len(times)
        for sender, times in response_times.items()
        if len(times) > 0
    }

    return {
        "chat_id": chat_id,
        "days": days,
        "response_times": [
            {"sender": sender, "avg_minutes": round(avg, 1)}
            for sender, avg in averages.items()
        ],
    }
```

**Step 2: Test endpoint**

```bash
curl "http://localhost:8900/api/response-times/test?days=7" \
  -H "Authorization: Bearer changeme"
```

Expected: `{"response_times": [{"sender": "...", "avg_minutes": ...}]}`

**Step 3: Commit**

```bash
git add radar-api/app/dashboard/router.py
git commit -m "feat: add response-times endpoint"
```

---

## Task 11: Documentation Update

**Files:**
- Modify: `CLAUDE.md` (add new endpoints)

**Step 1: Add new endpoints to API documentation**

Add to CLAUDE.md under "## API Endpoints" section:

```markdown
### Monitoring
- `POST /api/heartbeat` - Extension heartbeat (chat stats)
- `GET /api/capture-stats?chat_id=` - Capture monitoring stats

### Analytics
- `GET /api/communication-pattern/{chat_id}?days=30` - Message frequency heatmap
- `GET /api/response-times/{chat_id}?days=30` - Average response times per sender
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add new monitoring and analytics endpoints"
```

---

## Task 12: Testing & Verification

**Files:**
- Create: `docs/testing-checklist.md`

**Step 1: Create testing checklist**

Create `docs/testing-checklist.md`:

```markdown
# Observability & Analytics Testing Checklist

## Extension Testing

### Queue Reliability
- [ ] Stop API, send 5 messages, start API → all messages delivered
- [ ] Browser offline, send 3 messages, go online → retry works
- [ ] Fast conversation (10+ messages in 30s) → no duplicates
- [ ] Queue > 100 messages → old messages cleaned up

### Heartbeat
- [ ] Extension sends heartbeat every 60s
- [ ] Heartbeat counter resets after send
- [ ] Multiple chats tracked separately

## API Testing

### Endpoints
- [ ] POST /api/heartbeat → 200 OK, DB updated
- [ ] GET /api/capture-stats → returns all chats with status
- [ ] GET /api/communication-pattern/test → heatmap data
- [ ] GET /api/response-times/test → averages calculated

### Database
- [ ] capture_stats table created
- [ ] Upsert works (existing chat updated)
- [ ] Status calculation correct (green/yellow/red)

## Dashboard Testing

### Monitoring View
- [ ] monitoring.html loads
- [ ] Cards show correct status colors
- [ ] Auto-refresh works (30s)
- [ ] Empty state handled

### Interactive Charts
- [ ] charts.html loads
- [ ] Hover shows tooltip with details
- [ ] Chart responsive to window resize

## Integration Testing

### End-to-End
1. Configure extension with API key
2. Whitelist a chat
3. Send 5 messages on WhatsApp Web
4. Wait 60s for heartbeat
5. Open monitoring.html → chat card shows green
6. Open charts.html → see sentiment data

Expected: Full pipeline works, no errors in console
```

**Step 2: Run through checklist manually**

Execute each test item and check off completed items.

**Step 3: Commit**

```bash
git add docs/testing-checklist.md
git commit -m "docs: add testing checklist for verification"
```

---

## Execution Options

**Plan complete and saved to `docs/plans/2026-02-11-observability-and-analytics.md`.**

**Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
