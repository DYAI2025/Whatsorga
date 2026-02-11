# Observability & Analytics Testing Checklist

**Purpose**: Comprehensive test cases for all features implemented in Tasks 1-11 of the observability and analytics implementation.

**Test Environment**:
- Chrome browser with extension loaded
- WhatsApp Web (web.whatsapp.com)
- API running locally or deployed
- PostgreSQL database available

---

## Extension Testing

### Task 1: Message Queue Manager

**Queue Basics**
- [ ] Queue manager script loads correctly (check console for no errors)
- [ ] `window.MessageQueue` is defined after page load
- [ ] Queue persists in localStorage under key `radar_message_queue`

**Enqueue Operations**
- [ ] Messages are enqueued with unique IDs format: `{messageId}_{timestamp}`
- [ ] Each queue item has required fields: `id`, `message`, `status`, `retryCount`, `lastAttempt`, `enqueuedAt`
- [ ] Queue items default to `status: 'pending'` and `retryCount: 0`
- [ ] Multiple messages can be enqueued rapidly without data loss

**Queue Confirmation**
- [ ] `markConfirmed(id)` removes message from queue
- [ ] `markConfirmed()` with invalid ID returns false
- [ ] Confirmed messages no longer appear in `getPending()`

**Retry Logic**
- [ ] `incrementRetry(id)` increments the retry counter
- [ ] After 3 retries, message is automatically removed from queue
- [ ] Failed message removal logs error to console with message ID
- [ ] `lastAttempt` timestamp updates on each retry

**Queue Management**
- [ ] `getQueueSize()` returns accurate count
- [ ] `getPending()` filters only `status: 'pending'` items
- [ ] `cleanup()` removes oldest messages when queue exceeds 100 items
- [ ] Queue survives page reloads (persists in localStorage)

**Error Handling**
- [ ] Corrupted localStorage data doesn't crash the queue manager
- [ ] Parse errors return empty array and log to console
- [ ] Queue operations work even if localStorage is full

---

### Task 2: Extension Retry Scheduler Integration

**Initialization**
- [ ] `RadarTracker` constructor initializes `messageQueue` property
- [ ] Retry timer `_retryTimer` is set up on init
- [ ] Retry scheduler runs every 10 seconds

**Message Flow**
- [ ] `sendToAPI()` enqueues messages before attempting to send
- [ ] Each message receives a queue ID on enqueue
- [ ] `processPendingQueue()` is called immediately after enqueue
- [ ] Retry scheduler processes pending queue every 10 seconds

**Batch Processing**
- [ ] Queue processes maximum 10 messages per cycle
- [ ] Batch messages are extracted from queue correctly
- [ ] All messages in batch are sent in single API request

**Success Handling**
- [ ] On API success (200 OK), all batch items marked as confirmed
- [ ] Confirmed messages removed from queue
- [ ] Console logs confirmation count: `"[Radar] Confirmed X messages"`

**Error Handling - Auth Errors**
- [ ] 401 response stops retrying (no queue increment)
- [ ] 403 response stops retrying (no queue increment)
- [ ] Auth error logs to console: `"[Radar] Auth error - check API key"`

**Error Handling - Server Errors**
- [ ] 5xx responses increment retry counter for each message
- [ ] Console logs warning with status code
- [ ] Messages remain in queue for retry

**Error Handling - Network Errors**
- [ ] Network failures (offline, timeout) increment retry counter
- [ ] Console logs warning with error message
- [ ] Messages remain in queue for retry

**Queue Cleanup**
- [ ] Cleanup runs every 10 seconds alongside retry
- [ ] Old messages removed when queue exceeds 100 items

**Reliability Test Scenario**
1. Stop API: `cd deploy && docker compose stop radar-api`
2. Send 5 test messages on WhatsApp Web
3. Verify in console: `"[Radar] Enqueued 5 messages"`
4. Verify retry attempts logged every 10s
5. Start API: `docker compose start radar-api`
6. Wait 10s, verify: `"[Radar] Confirmed 5 messages"`
7. Check queue size in localStorage: should be 0

---

### Task 3: Extension Heartbeat Sender

**Background Script Setup**
- [ ] `background.js` defines `heartbeatState` object
- [ ] `heartbeatState.chatCounts` is an object (not array)
- [ ] `heartbeatState.timer` is set on startup
- [ ] `startHeartbeat()` called on extension load

**Heartbeat Timer**
- [ ] Heartbeat sends every 60 seconds
- [ ] Timer persists across service worker restarts
- [ ] Heartbeat only sends if serverUrl and apiKey configured

**Message Counting**
- [ ] Content script sends `MESSAGE_CAPTURED` to background
- [ ] Background increments counter for specific `chatId`
- [ ] Multiple chats tracked independently
- [ ] Counter resets to 0 after heartbeat sent

**Heartbeat Payload**
- [ ] Payload includes: `chatId`, `messageCount`, `queueSize`, `timestamp`
- [ ] Timestamp is ISO 8601 format
- [ ] `queueSize` reflects current retry queue length
- [ ] Only chats with `messageCount > 0` send heartbeat

**Network Behavior**
- [ ] POST request to `/api/heartbeat` with Bearer token
- [ ] Console logs on success: `"[Radar Heartbeat] Sent for {chatId}: {count} messages"`
- [ ] Network errors logged but don't crash extension
- [ ] Failed heartbeats don't block future attempts

**Integration with Content Script**
- [ ] Content script calls `chrome.runtime.sendMessage` with type `MESSAGE_CAPTURED`
- [ ] Background receives message and updates counter
- [ ] Content script continues execution after send (async)

**Test Scenario**
1. Load extension and configure API
2. Whitelist a chat
3. Send 3 messages on WhatsApp Web
4. Wait 60 seconds
5. Check API database: `SELECT * FROM capture_stats WHERE chat_id = 'test';`
6. Verify: `messages_captured_24h = 3`, `last_heartbeat` within last minute
7. Send 2 more messages
8. Wait 60 seconds
9. Verify: `messages_captured_24h = 5`

---

## API Testing

### Task 4: API CaptureStats Model

**Database Model**
- [ ] `capture_stats` table exists in database
- [ ] Schema includes columns: `id`, `chat_id`, `last_heartbeat`, `messages_captured_24h`, `error_count_24h`, `created_at`, `updated_at`
- [ ] `chat_id` has unique constraint
- [ ] `chat_id` has index for fast lookups
- [ ] `created_at` defaults to current timestamp
- [ ] `updated_at` auto-updates on row modification

**Data Types**
- [ ] `id` is Integer primary key
- [ ] `chat_id` is String (not nullable)
- [ ] `last_heartbeat` is DateTime (not nullable)
- [ ] `messages_captured_24h` is Integer (defaults to 0)
- [ ] `error_count_24h` is Integer (defaults to 0)

**Migration**
- [ ] Migration script `migrations/add_capture_stats.py` exists
- [ ] Running migration creates table without errors
- [ ] Re-running migration doesn't cause errors (idempotent)

**Manual Verification**
```bash
# Connect to database
docker compose exec postgres psql -U radar -d radar

# Check table structure
\d capture_stats

# Insert test data
INSERT INTO capture_stats (chat_id, last_heartbeat, messages_captured_24h, error_count_24h)
VALUES ('test-chat', NOW(), 10, 0);

# Verify
SELECT * FROM capture_stats;
```

---

### Task 5: API Heartbeat Endpoint

**Endpoint Basics**
- [ ] Endpoint: `POST /api/heartbeat`
- [ ] Requires Bearer token authentication
- [ ] Accepts JSON payload with: `chatId`, `messageCount`, `queueSize`, `timestamp`
- [ ] Returns: `{"status": "ok"}` on success

**Authentication**
- [ ] Missing token returns 401 Unauthorized
- [ ] Invalid token returns 403 Forbidden
- [ ] Valid token allows request

**Payload Validation**
- [ ] Missing `chatId` returns 422 Unprocessable Entity
- [ ] Missing `messageCount` returns 422
- [ ] Invalid timestamp format accepted (not validated)
- [ ] Extra fields in payload ignored

**Database Operations - New Chat**
- [ ] First heartbeat creates new `capture_stats` row
- [ ] `chat_id` set from payload
- [ ] `last_heartbeat` set to current UTC time
- [ ] `messages_captured_24h` set to `messageCount` from payload
- [ ] `error_count_24h` defaults to 0
- [ ] `created_at` and `updated_at` auto-populated

**Database Operations - Existing Chat**
- [ ] Subsequent heartbeats update existing row (no duplicate)
- [ ] `last_heartbeat` updated to current UTC time
- [ ] `messages_captured_24h` incremented by `messageCount`
- [ ] `updated_at` refreshed
- [ ] `created_at` unchanged

**Logging**
- [ ] Successful heartbeat logs: `"Heartbeat received for {chatId}: +{messageCount} messages"`
- [ ] Log level is INFO

**Test Commands**
```bash
# First heartbeat
curl -X POST http://localhost:8900/api/heartbeat \
  -H "Authorization: Bearer changeme" \
  -H "Content-Type: application/json" \
  -d '{"chatId": "test-chat", "messageCount": 5, "queueSize": 0, "timestamp": "2026-02-11T14:00:00"}'

# Expected: {"status":"ok"}

# Verify in database
docker compose exec postgres psql -U radar -d radar -c "SELECT * FROM capture_stats WHERE chat_id = 'test-chat';"

# Second heartbeat (should increment)
curl -X POST http://localhost:8900/api/heartbeat \
  -H "Authorization: Bearer changeme" \
  -H "Content-Type: application/json" \
  -d '{"chatId": "test-chat", "messageCount": 3, "queueSize": 0, "timestamp": "2026-02-11T14:01:00"}'

# Verify messages_captured_24h = 8
```

---

### Task 6: API Capture Stats Endpoint

**Endpoint Basics**
- [ ] Endpoint: `GET /api/capture-stats`
- [ ] Requires Bearer token authentication
- [ ] Optional query param: `chat_id` for filtering
- [ ] Returns JSON with `stats` array

**Response Structure**
- [ ] Response contains `chats` array (or `stats` array - verify actual implementation)
- [ ] Each chat object includes: `chat_id`, `last_heartbeat`, `messages_captured_24h`, `error_count_24h`, `status`, `created_at`, `updated_at`
- [ ] Timestamps in ISO 8601 format
- [ ] Results ordered by `last_heartbeat` descending (most recent first)

**Status Computation Logic**
- [ ] Status is one of: `"green"`, `"yellow"`, `"red"`
- [ ] **Green**: Heartbeat within last 5 minutes AND error rate < 5%
- [ ] **Yellow**: Heartbeat 5-15 minutes ago OR error rate 5-20%
- [ ] **Red**: Heartbeat >15 minutes ago OR error rate >20% OR no heartbeat
- [ ] Error rate = `error_count_24h / max(messages_captured_24h, 1)`

**Filtering**
- [ ] No `chat_id` param returns all chats
- [ ] `?chat_id=test` returns only matching chat
- [ ] Non-existent chat returns empty stats array (not 404)

**Edge Cases**
- [ ] Empty database returns `{"stats": []}`
- [ ] Chat with `messages_captured_24h = 0` doesn't cause division by zero
- [ ] Very old heartbeat (>1 day) returns `"red"` status

**Test Commands**
```bash
# Get all stats
curl http://localhost:8900/api/capture-stats \
  -H "Authorization: Bearer changeme"

# Filter by chat_id
curl http://localhost:8900/api/capture-stats?chat_id=test-chat \
  -H "Authorization: Bearer changeme"

# Test status colors (seed test data first)
# Green status: recent heartbeat, no errors
# Yellow status: 7 min old heartbeat
# Red status: 20 min old heartbeat
```

**Manual Status Verification**
```sql
-- Create test data with different statuses
INSERT INTO capture_stats (chat_id, last_heartbeat, messages_captured_24h, error_count_24h)
VALUES
  ('green-chat', NOW() - INTERVAL '2 minutes', 50, 1),
  ('yellow-chat', NOW() - INTERVAL '7 minutes', 40, 3),
  ('red-chat', NOW() - INTERVAL '20 minutes', 30, 10);

-- Query endpoint and verify status colors
```

---

### Task 9: API Communication Pattern Endpoint

**Endpoint Basics**
- [ ] Endpoint: `GET /api/communication-pattern/{chat_id}`
- [ ] Requires Bearer token authentication
- [ ] Query param: `days` (default: 30, min: 1, max: 90)
- [ ] Returns JSON with heatmap data

**Response Structure**
- [ ] Response includes: `chat_id`, `days`, `heatmap`, `weekday_labels`
- [ ] `heatmap` is 7x24 matrix (array of arrays)
- [ ] Rows represent weekdays (0=Monday, 6=Sunday)
- [ ] Columns represent hours (0=midnight, 23=11pm)
- [ ] Values are integer message counts
- [ ] `weekday_labels` array: `["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]`

**Heatmap Calculation**
- [ ] Queries messages from last N days
- [ ] Groups by weekday and hour of `timestamp` field
- [ ] Counts messages per cell
- [ ] Initializes all cells to 0 (no gaps)

**Days Parameter Validation**
- [ ] `?days=7` returns last 7 days
- [ ] `?days=90` returns last 90 days
- [ ] `?days=0` returns 422 error (below minimum)
- [ ] `?days=100` returns 422 error (above maximum)
- [ ] No `days` param defaults to 30

**Edge Cases**
- [ ] Non-existent chat_id returns zero-filled heatmap
- [ ] Chat with no messages returns zero-filled heatmap
- [ ] Timezone handling: uses UTC from `timestamp` column

**Test Commands**
```bash
# Default 30 days
curl "http://localhost:8900/api/communication-pattern/test-chat" \
  -H "Authorization: Bearer changeme"

# Last 7 days
curl "http://localhost:8900/api/communication-pattern/test-chat?days=7" \
  -H "Authorization: Bearer changeme"

# Verify heatmap structure
# Should have 7 rows (weekdays) x 24 columns (hours)
```

**Data Verification**
```sql
-- Seed test messages across different times
INSERT INTO messages (chat_id, sender, text, timestamp)
VALUES
  ('test-chat', 'Alice', 'Morning msg', '2026-02-11 08:00:00'),  -- Tuesday 8am
  ('test-chat', 'Bob', 'Evening msg', '2026-02-11 20:00:00'),    -- Tuesday 8pm
  ('test-chat', 'Alice', 'Weekend', '2026-02-09 14:00:00');       -- Sunday 2pm

-- Query endpoint and verify:
-- heatmap[1][8] should be >= 1 (Tuesday 8am)
-- heatmap[1][20] should be >= 1 (Tuesday 8pm)
-- heatmap[6][14] should be >= 1 (Sunday 2pm)
```

---

### Task 10: API Response Time Endpoint

**Endpoint Basics**
- [ ] Endpoint: `GET /api/response-times/{chat_id}`
- [ ] Requires Bearer token authentication
- [ ] Query param: `days` (default: 30, min: 1, max: 90)
- [ ] Returns JSON with per-sender response time stats

**Response Structure**
- [ ] Response includes: `chat_id`, `days`, `response_times`
- [ ] `response_times` is array of objects
- [ ] Each object has: `sender`, `avg_minutes`
- [ ] `avg_minutes` rounded to 1 decimal place
- [ ] Results sorted by sender name (or fastest first - verify implementation)

**Response Time Calculation**
- [ ] Sorts messages chronologically by `timestamp`
- [ ] Identifies responses: consecutive messages from different senders
- [ ] Calculates time delta in minutes
- [ ] Filters outliers: ignores responses >24 hours (1440 minutes)
- [ ] Averages response times per sender

**Edge Cases**
- [ ] Single message chat returns empty response_times array
- [ ] Monologue (same sender) returns empty response_times array
- [ ] First message in chat not counted as response
- [ ] Gaps >24 hours not counted (overnight messages excluded)

**Days Parameter Validation**
- [ ] `?days=7` returns last 7 days
- [ ] `?days=90` returns last 90 days
- [ ] `?days=0` returns 422 error
- [ ] `?days=100` returns 422 error

**Test Commands**
```bash
# Default 30 days
curl "http://localhost:8900/api/response-times/test-chat" \
  -H "Authorization: Bearer changeme"

# Last 7 days
curl "http://localhost:8900/api/response-times/test-chat?days=7" \
  -H "Authorization: Bearer changeme"
```

**Test Scenario with Known Data**
```sql
-- Seed conversation with known response times
INSERT INTO messages (chat_id, sender, text, timestamp)
VALUES
  ('resp-test', 'Alice', 'Message 1', '2026-02-11 10:00:00'),
  ('resp-test', 'Bob', 'Response 1', '2026-02-11 10:05:00'),    -- Bob responds in 5 min
  ('resp-test', 'Alice', 'Response 2', '2026-02-11 10:15:00'),  -- Alice responds in 10 min
  ('resp-test', 'Bob', 'Response 3', '2026-02-11 10:20:00'),    -- Bob responds in 5 min
  ('resp-test', 'Alice', 'Response 4', '2026-02-11 11:00:00');  -- Alice responds in 40 min

-- Expected results:
-- Bob: avg_minutes = 5.0 (average of 5 and 5)
-- Alice: avg_minutes = 25.0 (average of 10 and 40)
```

---

## Dashboard Testing

### Task 7: Dashboard Monitoring View

**Page Loading**
- [ ] `monitoring.html` loads without errors
- [ ] Dark theme applied (check CSS variables)
- [ ] Header displays title: "Monitoring" or "Capture Monitoring"
- [ ] Auto-refresh notice visible: "Auto-refresh alle 30 Sekunden"

**API Integration**
- [ ] Page reads API key from `localStorage.getItem('radar_api_key')`
- [ ] Page reads API URL from config (or hardcoded)
- [ ] Initial data fetch on page load
- [ ] Auto-refresh every 30 seconds

**Chat Cards**
- [ ] Each chat displays as a card in grid layout
- [ ] Card shows: chat name, status indicator, message count, error rate, last heartbeat age
- [ ] Status indicator colors: green/yellow/red dot
- [ ] Grid responsive (cards reflow on window resize)

**Status Indicators**
- [ ] Green dot for healthy chats
- [ ] Yellow dot for warning state
- [ ] Red dot for failed/stale chats
- [ ] Dot positioned in top-right corner of card

**Empty State**
- [ ] No chats shows message: "Noch keine Chats erfasst" or similar
- [ ] Empty grid doesn't crash page

**Error Handling**
- [ ] Network error shows in console (doesn't crash page)
- [ ] Auth error (401/403) logs to console
- [ ] Missing API key still attempts request

**Test Scenario**
1. Open `http://localhost:8900/static/monitoring.html`
2. Set API key in localStorage: `localStorage.setItem('radar_api_key', 'changeme')`
3. Reload page
4. Send some test heartbeats via curl
5. Wait 30s, verify cards update automatically
6. Stop API, wait 30s, verify error handling

---

### Task 8: Dashboard Interactive Charts

**Page Loading**
- [ ] `charts.html` loads without errors
- [ ] React, ReactDOM, Babel, and Recharts CDN scripts load
- [ ] No console errors about missing libraries
- [ ] Dark theme applied

**Recharts Integration**
- [ ] Recharts components available: `LineChart`, `XAxis`, `YAxis`, etc.
- [ ] Chart renders inside `#root` div
- [ ] Chart displays with sample/mock data or live API data

**Interactive Features**
- [ ] Hover over data points shows tooltip
- [ ] Tooltip displays: date, sentiment value, message count (or relevant data)
- [ ] Chart responsive to window resize
- [ ] Axes labeled correctly

**Chart Types Available**
- [ ] Line chart for sentiment drift
- [ ] Bar chart or heatmap for communication patterns (verify implementation)
- [ ] Multiple charts on same page work independently

**API Integration**
- [ ] Charts fetch data from API endpoints
- [ ] Loading state while fetching
- [ ] Error state on failed fetch
- [ ] Data updates when time window changed

**Test Scenario**
1. Open `http://localhost:8900/static/charts.html`
2. Verify charts render with data
3. Hover over points, verify tooltips appear
4. Resize window, verify charts reflow
5. Check network tab: API calls to `/api/drift/{chat_id}` or similar
6. Open developer console, verify no errors

---

## Integration Testing

### End-to-End Message Flow

**Setup**
1. [ ] Extension installed and loaded in Chrome
2. [ ] API running on localhost:8900 or deployed URL
3. [ ] PostgreSQL database accessible
4. [ ] Extension configured with API URL and key
5. [ ] At least one chat whitelisted

**Message Capture Flow**
1. [ ] Open WhatsApp Web (web.whatsapp.com)
2. [ ] Navigate to whitelisted chat
3. [ ] Send test message
4. [ ] Verify console log: `"[Radar] Enqueued 1 messages"`
5. [ ] Verify console log: `"[Radar] Confirmed 1 messages"` (within 10s)
6. [ ] Query database: `SELECT * FROM messages ORDER BY timestamp DESC LIMIT 1;`
7. [ ] Verify message exists with correct text, sender, chat_id

**Heartbeat Flow**
1. [ ] Send 5 messages in whitelisted chat
2. [ ] Wait 60 seconds
3. [ ] Verify console log: `"[Radar Heartbeat] Sent for {chatId}: 5 messages"`
4. [ ] Query database: `SELECT * FROM capture_stats WHERE chat_id = '{chatId}';`
5. [ ] Verify `messages_captured_24h >= 5` and `last_heartbeat` recent

**Monitoring Dashboard Flow**
1. [ ] Open monitoring.html
2. [ ] Verify chat card appears with green status
3. [ ] Verify message count displays correctly
4. [ ] Wait 30s, verify auto-refresh updates data

**Analytics Flow**
1. [ ] Open charts.html
2. [ ] Select a chat from dropdown (if implemented)
3. [ ] Verify sentiment drift chart loads with data
4. [ ] Verify communication pattern heatmap shows message distribution
5. [ ] Verify response time chart shows per-sender averages

**Retry/Reliability Flow**
1. [ ] Stop API: `docker compose stop radar-api`
2. [ ] Send 3 messages on WhatsApp Web
3. [ ] Verify console shows retry attempts every 10s
4. [ ] Start API: `docker compose start radar-api`
5. [ ] Wait 10s, verify messages delivered
6. [ ] Check database: all 3 messages exist
7. [ ] Check queue in localStorage: should be empty

**Error Handling Flow**
1. [ ] Configure extension with invalid API key
2. [ ] Send test message
3. [ ] Verify console: `"[Radar] Auth error - check API key"`
4. [ ] Messages not retried (queue cleared or not incremented)
5. [ ] Fix API key
6. [ ] Send new message, verify success

---

## Performance Testing

### Message Queue Performance
- [ ] 100 rapid messages (send burst) all enqueued successfully
- [ ] No duplicate message IDs
- [ ] No data loss in localStorage
- [ ] Queue cleanup keeps only 100 most recent

### API Throughput
- [ ] Batch ingest of 10 messages completes in <2 seconds
- [ ] Heartbeat endpoint responds in <200ms
- [ ] Capture-stats endpoint with 50 chats responds in <1 second
- [ ] Communication-pattern calculation with 10k messages completes in <5 seconds

### Dashboard Performance
- [ ] Monitoring page with 20 chat cards loads in <2 seconds
- [ ] Auto-refresh doesn't block UI
- [ ] Charts render 1000+ data points without lag
- [ ] Hover interactions remain smooth with large datasets

---

## Regression Testing

**Verify Existing Features Still Work**
- [ ] Basic message ingestion: `POST /api/ingest`
- [ ] Audio transcription: `POST /api/transcribe`
- [ ] Sentiment analysis runs on new messages
- [ ] Marker detection runs on new messages
- [ ] Thread weaving still groups related messages
- [ ] Termin extraction still detects appointments
- [ ] Dashboard overview endpoint: `GET /api/overview/{chat_id}`
- [ ] Drift endpoint: `GET /api/drift/{chat_id}`
- [ ] Search endpoint: `GET /api/search?q=query`

---

## Security Testing

### Authentication
- [ ] All monitoring endpoints require Bearer token
- [ ] Invalid token returns 401 or 403
- [ ] Missing token returns 401
- [ ] Token not logged in plaintext

### Input Validation
- [ ] SQL injection attempts in chat_id blocked
- [ ] XSS attempts in chat_id sanitized
- [ ] Oversized payloads rejected
- [ ] Invalid JSON returns 422

### Rate Limiting (if implemented)
- [ ] Rapid heartbeat spam doesn't crash API
- [ ] Queue endpoint abuse doesn't overload storage

---

## Deployment Testing

**Docker Compose Stack**
- [ ] `docker compose up -d` starts all services
- [ ] radar-api container healthy
- [ ] PostgreSQL container accessible
- [ ] ChromaDB container accessible
- [ ] Caddy reverse proxy works (if using HTTPS)

**Environment Variables**
- [ ] `RADAR_API_KEY` loaded from `.env`
- [ ] `RADAR_DATABASE_URL` connects successfully
- [ ] All required env vars documented in `.env.template`

**Migrations**
- [ ] Database migrations run on API startup
- [ ] `capture_stats` table exists after first run
- [ ] Re-running migrations is safe (idempotent)

**Health Checks**
- [ ] `GET /health` returns 200 OK
- [ ] `GET /api/status` shows all services operational

---

## Browser Compatibility

### Extension Compatibility
- [ ] Extension works on Chrome 120+
- [ ] Extension works on Edge (Chromium-based)
- [ ] Extension works on Brave
- [ ] Manifest v3 compliance (no warnings)

### Dashboard Compatibility
- [ ] monitoring.html works on Chrome
- [ ] monitoring.html works on Firefox
- [ ] monitoring.html works on Safari
- [ ] charts.html Recharts works on all modern browsers

---

## Documentation Validation

### Task 11: Documentation Update

**CLAUDE.md Updates**
- [ ] New endpoints documented under "Monitoring & Analytics Endpoints"
- [ ] Heartbeat endpoint fully documented with examples
- [ ] Capture-stats endpoint documented with response structure
- [ ] Communication-pattern endpoint documented with heatmap details
- [ ] Response-times endpoint documented with calculation logic

**Endpoint Documentation Completeness**
- [ ] Each endpoint lists: path, method, auth requirements
- [ ] Request parameters documented (path, query, body)
- [ ] Response structure documented with example JSON
- [ ] Example curl commands provided and tested
- [ ] Edge cases and error responses documented

**Code Comments**
- [ ] Queue manager has clear function comments
- [ ] Background script heartbeat logic explained
- [ ] API endpoint docstrings accurate
- [ ] Status computation logic documented

---

## Test Execution Log

**Date**: ___________
**Tester**: ___________
**Environment**: ___________

### Summary
- Total test cases: ___________
- Passed: ___________
- Failed: ___________
- Skipped: ___________

### Failed Tests
| Test Case | Expected | Actual | Notes |
|-----------|----------|--------|-------|
|           |          |        |       |

### Blocking Issues
1.
2.
3.

### Notes
-
-
-

---

## Automated Test Scripts

**Recommended Test Scripts to Create** (future work):
- `tests/test_queue_manager.js` - Unit tests for MessageQueue class
- `tests/test_retry_scheduler.js` - Integration tests for retry logic
- `tests/test_heartbeat_endpoint.py` - API endpoint tests
- `tests/test_capture_stats.py` - Status calculation tests
- `tests/test_communication_pattern.py` - Heatmap calculation tests
- `tests/test_response_times.py` - Response time calculation tests
- `tests/e2e_extension.spec.js` - Playwright/Puppeteer E2E tests

---

## Success Criteria

All features from Tasks 1-11 are considered successfully implemented when:

1. ✅ Extension queue manager persists and retries messages
2. ✅ Extension sends heartbeats every 60 seconds
3. ✅ API heartbeat endpoint updates capture_stats table
4. ✅ API capture-stats endpoint returns status for all chats
5. ✅ Monitoring dashboard displays chat cards with status colors
6. ✅ Interactive charts render with Recharts
7. ✅ Communication pattern endpoint returns 7x24 heatmap
8. ✅ Response times endpoint calculates averages per sender
9. ✅ All endpoints require authentication
10. ✅ Documentation is complete and accurate
11. ✅ No regression in existing features
12. ✅ End-to-end flow works: capture → queue → retry → heartbeat → dashboard

---

**Test Completion Date**: ___________
**Approved By**: ___________
**Ready for Production**: [ ] Yes  [ ] No
