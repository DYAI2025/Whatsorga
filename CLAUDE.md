# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Beziehungs-Radar** (Relationship Radar) is a WhatsApp message analysis system consisting of:
1. **Chrome Extension** (`extension/`) - Captures WhatsApp messages from whitelisted contacts
2. **FastAPI Backend** (`radar-api/`) - Analyzes messages with AI/ML pipeline
3. **Deployment Stack** (`deploy/`) - Docker Compose orchestration with Caddy, PostgreSQL, ChromaDB, Ollama

## Architecture

### Message Flow
1. Extension monitors WhatsApp Web (`web.whatsapp.com`)
2. Content script captures text + audio messages from whitelisted contacts
3. Messages forwarded to `/api/ingest` with Bearer token auth
4. Analysis pipeline processes each message:
   - Audio → Groq Whisper transcription
   - Text → Marker detection (sentiment indicators)
   - Text → Sentiment scoring (-1 to +1)
   - Text → RAG embedding (ChromaDB)
   - Text → Semantic thread weaving
   - Text → Appointment extraction → CalDAV sync (Apple iCloud)

### Core Analysis Modules (`radar-api/app/analysis/`)
- `marker_engine.py` - Detects relationship markers (engagement, conflict, support, etc.)
- `sentiment_tracker.py` - Scores emotional tone
- `semantic_transcriber.py` - Enriches transcripts with conversation context
- `termin_extractor.py` - Extracts appointments using Groq/Gemini LLMs
- `weaver.py` - Maintains semantic threads across conversations

### Storage Layer
- **PostgreSQL** - Messages, analyses, threads, appointments (SQLAlchemy async)
- **ChromaDB** - RAG vector store for semantic search
- **CalDAV** - Syncs extracted appointments to Apple Calendar

### External Services
- **Groq** - Whisper (audio transcription) + LLaMA (enrichment)
- **Gemini** - Fallback LLM for termin extraction
- **Ollama** - Local LLM (currently unused, legacy)

## Development Commands

### Local Development (API)
```bash
cd radar-api

# Install dependencies
pip install -r requirements.txt

# Run locally (requires PostgreSQL + ChromaDB running)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Access API docs
open http://localhost:8000/docs
```

### Extension Development
```bash
cd extension

# Load unpacked extension in Chrome:
# 1. Go to chrome://extensions/
# 2. Enable "Developer mode"
# 3. Click "Load unpacked" and select the extension/ directory

# Test on WhatsApp Web
open https://web.whatsapp.com
```

### Deployment (Production)
```bash
cd deploy

# Initial setup (Oracle Cloud ARM VM)
bash setup.sh

# Configure environment
cp .env.template .env
nano .env  # Edit all RADAR_* variables

# Start stack
docker compose up -d

# View logs
docker compose logs -f radar-api

# Pull Ollama models (if using local LLM)
docker compose exec ollama ollama pull llama3.1:8b

# Health check
curl https://your-domain.de/health
```

### Database Operations
```bash
# Access PostgreSQL
docker compose exec postgres psql -U radar -d radar

# Inspect tables
\dt

# Query messages
SELECT chat_name, sender, text, timestamp FROM messages ORDER BY timestamp DESC LIMIT 10;

# Check ChromaDB
curl http://localhost:8000/api/v1/heartbeat
```

## Configuration

### Environment Variables (via `.env` in deploy/)
All settings use `RADAR_` prefix (see `radar-api/app/config.py`):
- `RADAR_API_KEY` - Bearer token for extension authentication
- `RADAR_DATABASE_URL` - PostgreSQL connection (asyncpg)
- `RADAR_GROQ_API_KEY` - Groq API key for Whisper + LLM
- `RADAR_GEMINI_API_KEY` - Gemini fallback LLM
- `RADAR_CALDAV_*` - Apple iCloud calendar sync credentials
- `RADAR_CHROMADB_URL` - Vector store endpoint
- `RADAR_DOMAIN` - Public domain for Caddy auto-TLS

### Extension Configuration
Stored in Chrome's `chrome.storage.local`:
- `whitelist` - Array of contact names to monitor
- `enabled` - Boolean to enable/disable capture
- Configure via extension popup (popup.html)

## API Endpoints

### Ingestion
- `POST /api/ingest` - Bulk message ingestion (extension → API)
- `POST /api/transcribe` - Standalone audio transcription endpoint

### Monitoring & Analytics (requires Bearer auth)
- `POST /api/heartbeat` - Extension heartbeat with capture stats
- `GET /api/capture-stats` - Capture health monitoring for all chats
- `GET /api/communication-pattern/{chat_id}` - Weekday x hour heatmap
- `GET /api/response-times/{chat_id}` - Per-sender response time analysis

### Dashboard (requires Bearer auth)
- `GET /api/overview/{chat_id}` - Summary stats
- `GET /api/drift/{chat_id}` - Sentiment over time
- `GET /api/markers/{chat_id}` - Marker heatmap
- `GET /api/threads/{chat_id}` - Semantic conversation threads
- `GET /api/termine/{chat_id}` - Upcoming appointments
- `GET /api/search?q=query` - RAG-powered semantic search
- `GET /api/status` - Service health (Whisper, LLM, ChromaDB, CalDAV)

### Health
- `GET /health` - Simple health check
- `GET /dashboard` - Static dashboard frontend (if built)

## Database Schema

### Key Tables (SQLAlchemy models in `storage/database.py`)
- `messages` - Raw message data (text, audio_path, timestamp)
- `analysis` - Per-message sentiment + markers
- `threads` - Semantic conversation groupings (theme, emotional_arc)
- `termine` - Extracted appointments (datetime, participants, caldav_uid)
- `drift_snapshots` - Sentiment trend snapshots (unused currently)

## Testing Production Deployment

```bash
# Test ingestion endpoint
curl -X POST https://your-domain.de/api/ingest \
  -H "Authorization: Bearer $RADAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"messageId": "test", "sender": "Ben", "text": "Hello", "chatId": "test", "chatName": "Test Chat"}]}'

# Test transcription endpoint
curl -X POST https://your-domain.de/api/transcribe \
  -H "Authorization: Bearer $RADAR_API_KEY" \
  -F "audio=@test.ogg" \
  -F "chat_id=test" \
  -F "sender=Ben"

# Test dashboard data
curl https://your-domain.de/api/overview/test \
  -H "Authorization: Bearer $RADAR_API_KEY"
```

## Port Mapping
- Caddy: `443` (HTTPS), `80` (HTTP redirect)
- radar-api: Internal `8000`, exposed as `8900` (host)
- PostgreSQL: Internal `5432` only
- ChromaDB: Internal `8000` only
- Ollama: Internal `11434` only

## Notes
- Extension requires `host_permissions` for `web.whatsapp.com` and API domain
- Audio capture uses WhatsApp Web's `<audio>` elements with blob URLs
- Transcription pipeline: Groq Whisper (primary) with Gemini fallback
- Sentiment drift calculation aggregates daily averages from `analysis` table
- Thread weaving uses ChromaDB similarity search to group related messages
- CalDAV sync creates iCal events with confidence scores in description

## Monitoring & Analytics Endpoints

### POST /api/heartbeat

**Purpose**: Extension sends periodic heartbeats with capture statistics.

**Authentication**: Bearer token required

**Request Body**:
```json
{
  "chatId": "string",
  "messageCount": 5
}
```

**Response**:
```json
{
  "status": "ok"
}
```

**Behavior**:
- Upserts `capture_stats` table with last heartbeat timestamp
- Increments 24h message counter
- Used by extension to report capture health

**Example**:
```bash
curl -X POST https://your-domain.de/api/heartbeat \
  -H "Authorization: Bearer $RADAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"chatId": "partner-chat", "messageCount": 3}'
```

---

### GET /api/capture-stats

**Purpose**: Dashboard view of capture health for all monitored chats.

**Authentication**: Bearer token required

**Query Parameters**: None

**Response**:
```json
{
  "chats": [
    {
      "chat_id": "string",
      "last_heartbeat": "2026-02-11T15:30:00",
      "messages_captured_24h": 42,
      "error_count_24h": 0,
      "status": "green",
      "created_at": "2026-02-10T10:00:00",
      "updated_at": "2026-02-11T15:30:00"
    }
  ]
}
```

**Status Computation**:
- **Green**: Heartbeat within last 5 minutes, no errors
- **Yellow**: Heartbeat 5-15 minutes ago, or 1-5 errors
- **Red**: Heartbeat >15 minutes ago, or >5 errors, or no heartbeat

**Use Cases**:
- Monitor extension health across all chats
- Detect capture failures or connection issues
- Track message ingestion rate

**Example**:
```bash
curl https://your-domain.de/api/capture-stats \
  -H "Authorization: Bearer $RADAR_API_KEY"
```

---

### GET /api/communication-pattern/{chat_id}

**Purpose**: Weekday x hour heatmap showing when conversations are most active.

**Authentication**: Bearer token required

**Path Parameters**:
- `chat_id` (required): Chat identifier

**Query Parameters**:
- `days` (optional): Lookback window (default: 30, min: 1, max: 365)

**Response**:
```json
{
  "chat_id": "string",
  "days": 30,
  "heatmap": [
    [0, 0, 0, 5, 3, 2, 1, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 2, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 6, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0]
  ],
  "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
  "hours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
  "total_messages": 20
}
```

**Heatmap Structure**:
- 7x24 matrix (weekday x hour)
- Rows: 0=Monday, 6=Sunday
- Columns: 0=midnight, 23=11PM
- Values: Integer message counts

**Use Cases**:
- Identify peak communication times
- Detect unusual late-night or early-morning patterns
- Track communication habit changes over time
- Visualize relationship engagement patterns

**Example**:
```bash
# Last 30 days (default)
curl https://your-domain.de/api/communication-pattern/partner-chat \
  -H "Authorization: Bearer $RADAR_API_KEY"

# Last 7 days
curl https://your-domain.de/api/communication-pattern/partner-chat?days=7 \
  -H "Authorization: Bearer $RADAR_API_KEY"
```

**Visualization Ideas**:
- D3.js/Chart.js heatmap with color intensity
- Plotly interactive heatmap with hover tooltips
- Custom canvas rendering for dashboard

---

### GET /api/response-times/{chat_id}

**Purpose**: Calculate average response times per sender to measure engagement.

**Authentication**: Bearer token required

**Path Parameters**:
- `chat_id` (required): Chat identifier

**Query Parameters**:
- `days` (optional): Lookback window (default: 30, min: 1, max: 365)

**Response**:
```json
{
  "chat_id": "string",
  "days": 30,
  "response_times": [
    {
      "sender": "Bob",
      "avg_response_seconds": 300.0,
      "avg_response_minutes": 5.0,
      "response_count": 15,
      "message_count": 42
    },
    {
      "sender": "Alice",
      "avg_response_seconds": 600.0,
      "avg_response_minutes": 10.0,
      "response_count": 12,
      "message_count": 38
    }
  ],
  "total_messages": 80,
  "total_participants": 2
}
```

**Calculation Logic**:
1. Sort messages chronologically by timestamp
2. Track sender changes to identify actual responses
3. Calculate time gap between consecutive messages from different senders
4. Filter outliers (responses >24 hours are excluded)
5. Average response times per sender
6. Sort by fastest responder first

**Edge Cases**:
- `< 2 messages`: Returns error "Not enough messages to calculate response times"
- Same sender (monologue): Shows 0 responses, only message count
- Long delays (>24 hours): Filtered out (not counted as responses)
- Group chats: Tracks each participant independently

**Use Cases**:
- Compare engagement levels between participants
- Detect relationship health (faster responses = higher engagement)
- Track response time trends over different time windows
- Identify communication imbalances

**Example**:
```bash
# Last 30 days (default)
curl https://your-domain.de/api/response-times/partner-chat \
  -H "Authorization: Bearer $RADAR_API_KEY"

# Last 7 days
curl https://your-domain.de/api/response-times/partner-chat?days=7 \
  -H "Authorization: Bearer $RADAR_API_KEY"
```

**Visualization Ideas**:
- Bar chart: Average response time per sender
- Table: Sender stats with response/message counts
- Trend line: Response time changes across different time windows (7d, 30d, 90d)

---

## Testing Monitoring Endpoints

Test scripts are provided in the repository root:

```bash
# Test heartbeat endpoint
./test-heartbeat.sh

# Test capture stats
./test-capture-stats.sh

# Test communication pattern
./test-communication-pattern.sh [chat_id]

# Test response times
./test-response-times.sh [chat_id]
```

Python test scripts are also available:
- `test_endpoint.py` - Generic endpoint validation
- `test_communication_pattern.py` - Communication pattern unit tests
- `test_response_times_unit.py` - Response time calculation tests
