# WhatsOrga

**WhatsApp message analysis system with persistent semantic memory**

WhatsOrga captures WhatsApp messages from whitelisted contacts, analyzes them through an AI/ML pipeline (sentiment, markers, semantic threads), and syncs extracted appointments to Apple Calendar. With the EverMemOS integration, every message is memorized in a semantic knowledge graph — enabling pronoun resolution, fact tracking, and context-aware appointment extraction across weeks of conversation.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Components](#components)
   - [Chrome Extension](#chrome-extension)
   - [FastAPI Backend](#fastapi-backend)
   - [Analysis Pipeline](#analysis-pipeline)
   - [EverMemOS Memory](#evermemos-semantic-memory)
   - [Storage](#storage)
4. [Message Flow](#message-flow)
5. [API Reference](#api-reference)
6. [Extension Setup & Configuration](#extension-setup--configuration)
7. [Deployment](#deployment)
8. [Configuration Reference](#configuration-reference)
9. [Development](#development)

---

## System Overview

```
┌─────────────────┐     HTTPS/JSON      ┌──────────────────────────────────────┐
│  Chrome Extension│ ──────────────────→ │         FastAPI Backend (v0.2.0)     │
│  (WhatsApp Web)  │                     │                                      │
│                  │  Messages            │  1. Store in PostgreSQL              │
│  • Whitelist     │  + Audio blobs      │  2. EverMemOS memorize()             │
│  • DOM scraping  │                     │  3. Sentiment + Marker analysis      │
│  • Queue/retry   │                     │  4. RAG embedding (ChromaDB)         │
└─────────────────┘                     │  5. Thread weaving                   │
                                         │  6. Context-aware termin extraction  │
                                         │     (EverMemOS recall → LLM)        │
                                         │  7. CalDAV → Apple Calendar          │
                                         └──────────┬───────────┬──────────────┘
                                                    │           │
                                    ┌───────────────┘           │
                                    │                           │
                         ┌──────────▼──┐  ┌─────────▼─────┐  ┌─────────────────┐
                         │ PostgreSQL   │  │ ChromaDB      │  │ EverMemOS       │
                         │ (messages,   │  │ (RAG vectors) │  │ (semantic       │
                         │  analysis,   │  │               │  │  memory:        │
                         │  threads,    │  └───────────────┘  │  MongoDB,       │
                         │  termine)    │                      │  Milvus, ES,   │
                         └──────────────┘                      │  Redis)        │
                                    │                          └─────────────────┘
                         ┌──────────▼──────────┐
                         │ Apple iCloud CalDAV  │
                         └─────────────────────┘
```

**Three main components:**

| Component | Directory | Technology | Purpose |
|---|---|---|---|
| Chrome Extension | `extension/` | JavaScript (Manifest V3) | Captures messages from WhatsApp Web |
| FastAPI Backend | `radar-api/` | Python 3.12, FastAPI | Analysis pipeline + REST API |
| Deployment | `deploy/` | Docker Compose, Caddy | Orchestration, HTTPS, databases |

**External services:**

| Service | Purpose | Model |
|---|---|---|
| Groq | Audio transcription + LLM | Whisper Large V3 Turbo + LLaMA 3.3 70B |
| Gemini | Fallback LLM | Gemini 2.5 Flash |
| DeepInfra | EverMemOS embeddings + reranking | Qwen3-Embedding-4B + Qwen3-Reranker-4B |
| Apple iCloud | Calendar sync | CalDAV protocol |

---

## Architecture

### Message Flow (Overview)

```
WhatsApp Web → Extension (DOM scraping + whitelist filter)
  → POST /api/ingest (Bearer auth)
    → Store in PostgreSQL
    → EverMemOS memorize() — persistent semantic memory
    → Sentiment score (-1.0 to +1.0)
    → Marker detection (regex + embedding, 2-phase)
    → RAG embedding → ChromaDB
    → Semantic thread weaving
    → Context-aware termin extraction (EverMemOS recall → enriched LLM prompt)
    → [Termin found? → CalDAV sync → Apple Calendar]
```

### Before vs. After EverMemOS

**Before** — "Kannst du an ihrem Geburtstag Süßigkeiten-Tüten mitbringen?"
```
Text → Termin extractor → No date recognized ("ihrem" = who?) → No appointment created
```

**After** — same message with EverMemOS context:
```
Text → EverMemOS memorize()
     → EverMemOS recall("Termine Geburtstage: Kannst du an ihrem...")
       → Context: "Child = daughter, birthday: 18.02., party: 21.02., 8 guests"
     → Context-enriched termin extractor:
       → "ihrem" = Child's
       → Date: 21.02. (party, not birthday)
       → Task: "Süßigkeiten-Tüten für 8 Gäste"
       → CalDAV → Apple Calendar
```

---

## Components

### Chrome Extension

The extension runs on `web.whatsapp.com` and captures messages exclusively from contacts on the whitelist.

**Files:**

| File | Purpose |
|---|---|
| `manifest.json` | Manifest V3 — permissions, content scripts, service worker |
| `content.js` | DOM scraping of WhatsApp Web UI (`RadarTracker` class) |
| `background.js` | Service worker — retry queue, heartbeat, message forwarding |
| `queue-manager.js` | Persistent message queue in `localStorage` |
| `popup.html/js/css` | Configuration UI (server URL, API key, whitelist, status) |

**How `content.js` works:**

1. **Init**: Waits for WhatsApp DOM readiness (up to 30 seconds)
2. **Chat detection**: 5 strategies for different WhatsApp Web versions (data-testid, header spans, etc.)
3. **Whitelist check**: Only chats whose name contains a whitelist entry (case-insensitive)
4. **MutationObserver**: Watches DOM changes in `#main` container
5. **Message extraction** (6 strategies per field): sender, text, timestamp from `data-pre-plain-text` attribute (primary), fallback via `aria-label`, `.selectable-text`, `innerText`
6. **Audio capture**: Detects `<audio>` elements, fetches blob URLs, base64-encodes
7. **Deduplication**: Content hash + message ID prevents duplicate capture
8. **Batching**: Messages are batched (groups of 10) and sent via `background.js`

**Retry logic (`background.js`):**
- Exponential backoff: 5s → 15s → 1min → 5min
- Max queue size: 500 messages
- 401/403: Message discarded (auth error)
- 5xx: Retry with backoff
- Queue survives browser restarts (localStorage persistence)

---

### FastAPI Backend

**Entry point:** `radar-api/app/main.py` (v0.2.0)

- Ingestion router (`/api/ingest`, `/api/transcribe`, `/api/heartbeat`)
- Dashboard router (analysis endpoints)
- Context router (`/api/context/init` — WhatsApp export seeding)
- Health check with EverMemOS status (`/health`)
- EverMemOS startup connectivity check + shutdown cleanup

**Authentication:** Bearer token (`RADAR_API_KEY`) required for all endpoints.

---

### Analysis Pipeline

Every incoming message passes through these steps:

#### 1. Sentiment Tracker

Scores emotional tone from **-1.0** (very negative) to **+1.0** (very positive).
- ~35 positive and ~35 negative keywords, specialized for German everyday language
- Context modifiers: negation detection (previous 2 words), intensifier multiplication (1.5x)
- Labels: `"positive"` (>0.15), `"negative"` (<-0.15), `"neutral"`

#### 2. Marker Engine (2-Phase)

**Phase 1 — Regex** (fast, deterministic): compiled patterns from `marker_registry_radar.json`

**Phase 2 — Embedding similarity** (semantic): `all-MiniLM-L6-v2` (384 dims) against precomputed marker embeddings, configurable threshold (default 0.65)

**10 dashboard categories:** waerme, distanz, stress, konflikt, freude, trauer, fuersorge, planung, dankbarkeit, unsicherheit

#### 3. EverMemOS Memorize

After analysis, the message is stored in EverMemOS for persistent context memory. This is non-blocking — if EverMemOS is down, the pipeline continues without it.

#### 4. RAG Embedding & Thread Weaving

- Stores message as vector in ChromaDB
- Semantic thread grouping via similarity overlap
- Emotional arc tracking + tension/resolution detection
- Thread dormancy after 72 hours of inactivity

#### 5. Context-Aware Termin Extraction

1. Recalls relevant context from EverMemOS (persons, facts, episodes)
2. If context found: enriches LLM prompt with `<kontext_gedächtnis>` block containing profiles, episodes, and facts
3. If no context: falls back to raw extraction (existing behavior)
4. Appointments with confidence >= 0.7 are synced to Apple Calendar via CalDAV

---

### EverMemOS Semantic Memory

[EverMemOS](https://github.com/EverMind-AI/EverMemOS) provides persistent semantic memory for the analysis pipeline. It runs as a separate service in the Docker stack.

**Storage backends:**
- **MongoDB** — Documents and MemCells (atomic knowledge units)
- **Elasticsearch** — BM25 keyword search
- **Milvus** — Vector similarity search (embeddings via Qwen3-Embedding-4B)
- **Redis** — Cache and boundary detection

**Core operations:**

| Operation | Endpoint | Purpose |
|---|---|---|
| `memorize()` | `/api/v3/agentic/memorize` | Store message → MemCell extraction (persons, facts, events) |
| `recall()` | `/api/v3/agentic/retrieve_lightweight` | Hybrid search (embedding + BM25 + RRF fusion) |
| `recall_for_termin()` | (composed) | Specialized recall for appointment extraction with pronoun resolution |

**New capabilities via EverMemOS:**
- **Pronoun resolution**: "ihrem" → Child, because EverMemOS knows the relationship graph
- **Temporal logic**: Birthday (18.02.) vs. party (21.02.), because facts are stored
- **Quantity inference**: "Süßigkeiten-Tüten für ihre Gäste" → 8, because guest count is known
- **Learning profiles**: Each message enriches person knowledge further

**Context init endpoint:** `POST /api/context/init` accepts a WhatsApp chat export (plain text) and feeds all messages into EverMemOS to bootstrap the knowledge base before real-time messages start flowing.

---

### Storage

#### PostgreSQL — Structured Data

| Table | Purpose |
|---|---|
| `messages` | Raw messages (chat_id, sender, text, timestamp, audio_path) |
| `analysis` | Per-message sentiment + markers (JSONB) |
| `threads` | Semantic conversation groupings (theme, emotional_arc) |
| `termine` | Extracted appointments (datetime, participants, caldav_uid) |
| `capture_stats` | Extension heartbeat health tracking |
| `drift_snapshots` | Sentiment trend snapshots |

#### ChromaDB — Vector Store

- Collection: `messages`, 384 dimensions, cosine distance
- Metadata: chat_id, sender, timestamp, sentiment, dominant_marker

#### EverMemOS — Semantic Memory

- MongoDB: MemCells, profiles, episodes
- Milvus: Vector embeddings (1024 dims via Qwen3-Embedding-4B)
- Elasticsearch: BM25 keyword index
- Redis: Cache layer

---

## Message Flow

### Example: Text message "Ich vermisse dich"

```
1. Extension: DOM scraping → {sender: "Partner", text: "Ich vermisse dich", chat: "Partner"}
2. Whitelist check: "Partner" → in queue
3. background.js → POST /api/ingest

4. Backend:
   a) Message → PostgreSQL (id: abc-123)
   b) EverMemOS memorize() → stores message, extracts MemCells
   c) Sentiment: score=0.65 (positive, "vermiss" → waerme)
   d) Marker: dominant="waerme"
   e) RAG: embedding → ChromaDB + query similar messages
   f) Thread: similar to existing "waerme" thread → append
   g) Termin: no date keywords → skipped
   h) Analysis → PostgreSQL

5. Response: {accepted: 1, errors: 0}
```

### Example: Voice message with appointment

```
1. Extension: <audio> element detected → fetch blob → base64
2. POST /api/ingest with {hasAudio: true, audioBlob: "base64..."}

3. Backend:
   a) Groq Whisper: "Können wir uns Samstag um 15 Uhr treffen?"
   b) Message → PostgreSQL (is_transcribed: true)
   c) EverMemOS memorize() + recall context
   d) Sentiment: score=0.2 (neutral-positive, "treffen" → planung)
   e) Marker: dominant="planung"
   f) Context-aware termin extraction:
      - EverMemOS recalls: previous plans, person profiles
      - Enriched LLM prompt → "Samstag um 15:00"
      - {title: "Treffen", datetime: "2026-02-21T15:00", confidence: 0.8}
   g) CalDAV sync: iCal event created + 4 reminders
```

---

## API Reference

### Ingestion

| Endpoint | Method | Description |
|---|---|---|
| `/api/ingest` | POST | Message batch from extension |
| `/api/transcribe` | POST | Standalone audio transcription + enrichment |
| `/api/heartbeat` | POST | Extension heartbeat with capture stats |

### Context Memory

| Endpoint | Method | Description |
|---|---|---|
| `/api/context/init` | POST | Seed EverMemOS from WhatsApp chat export |

### Dashboard & Analysis

| Endpoint | Method | Description |
|---|---|---|
| `/api/overview/{chat_id}` | GET | Summary (messages, sentiment, threads, appointments) |
| `/api/drift/{chat_id}` | GET | Sentiment trend over time |
| `/api/markers/{chat_id}` | GET | Marker distribution heatmap |
| `/api/threads/{chat_id}` | GET | Semantic conversation threads |
| `/api/termine/{chat_id}` | GET | Extracted appointments |
| `/api/search?q=query` | GET | RAG-based semantic search |
| `/api/communication-pattern/{chat_id}` | GET | Weekday x hour heatmap |
| `/api/response-times/{chat_id}` | GET | Response times per sender |
| `/api/capture-stats` | GET | Extension health across all chats |
| `/api/status` | GET | Service health (Whisper, LLM, ChromaDB, CalDAV) |

### System

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check (includes EverMemOS memory status) |
| `/dashboard` | GET | Static dashboard frontend |

All endpoints (except `/health`) require `Authorization: Bearer <API_KEY>`.

---

## Extension Setup & Configuration

### Prerequisites

- Google Chrome (or Chromium-based browser)
- A running WhatsOrga backend (local or deployed)
- The backend's API key (`RADAR_API_KEY`)

### Step 1: Install the Extension

1. Open `chrome://extensions/` in Chrome
2. Enable **Developer mode** (toggle in the top-right corner)
3. Click **"Load unpacked"**
4. Select the `extension/` directory from this repository
5. The WhatsOrga icon appears in the browser toolbar

### Step 2: Configure Server Connection

1. Click the **WhatsOrga** icon in the toolbar to open the popup
2. In the **Server** section:
   - **Server URL**: Enter your backend URL (e.g. `https://radar.your-domain.de` or `http://localhost:8900` for local development)
   - **API Key**: Enter the value of `RADAR_API_KEY` from your `.env` file
3. Click **Save**

### Step 3: Add Contacts to the Whitelist

The extension only captures messages from whitelisted contacts. This is a privacy safeguard.

1. In the **Whitelist** section of the popup:
   - Type a contact or group name exactly as it appears in WhatsApp (case-insensitive matching)
   - Click **Add** (or press Enter)
2. Repeat for each contact you want to track
3. To remove a contact, click the **x** button next to their name

### Step 4: Start Capturing

1. Open [WhatsApp Web](https://web.whatsapp.com/) in a tab
2. Navigate to a whitelisted chat
3. The extension popup shows live status:
   - **Extension**: Active / Paused
   - **Current Chat**: The chat currently open in WhatsApp Web
   - **Whitelisted**: Yes / No (whether the current chat is on the whitelist)
   - **Messages Sent**: Count of messages forwarded to the backend
   - **Retry Queue**: Messages waiting to be sent (network issues, etc.)
4. Use the **Capture enabled** toggle to pause/resume capturing

### How It Works

- The extension watches the WhatsApp Web DOM for new messages using a `MutationObserver`
- Only messages from chats matching a whitelist entry are captured
- Messages are batched (groups of 10) and sent to the backend via `POST /api/ingest`
- Audio messages are detected, fetched as blobs, base64-encoded, and included in the payload
- A persistent retry queue handles network failures with exponential backoff (5s → 15s → 1min → 5min)
- The queue survives browser restarts (persisted in `localStorage`)
- Heartbeats are sent periodically so the backend can monitor extension health

### Troubleshooting

| Symptom | Solution |
|---|---|
| Status shows "Open WhatsApp Web" | Open `web.whatsapp.com` in a tab |
| Status shows "Server not configured" | Set Server URL and API Key in the popup, click Save |
| Status shows "Paused" | Toggle "Capture enabled" on |
| Whitelisted shows "No" | The current chat name doesn't match any whitelist entry — check spelling |
| Retry Queue growing | Backend may be unreachable — check Server URL and network |
| Messages not appearing in dashboard | Verify API Key matches `RADAR_API_KEY` in backend `.env` |

---

## Deployment

### Prerequisites

- Docker & Docker Compose
- Min. **6 GB RAM** (Elasticsearch + Milvus are memory-intensive)
- Groq API key (Whisper transcription + LLM)
- DeepInfra API key (EverMemOS embeddings + reranking)

### Quick Start

```bash
cd deploy

# Configure environment
cp .env.template .env
nano .env  # Set all required keys (see Configuration Reference below)

# Start the full stack (12 services)
docker compose up -d

# Watch logs
docker compose logs -f radar-api evermemos

# Health check
curl http://localhost:8900/health
# → {"status":"ok","service":"beziehungs-radar","memory":{"status":"ok","evermemos":"connected"}}
```

### Bootstrap Context from Chat Export

Feed a WhatsApp chat export into EverMemOS to build initial world knowledge:

```bash
curl -X POST http://localhost:8900/api/context/init \
  -H "Authorization: Bearer $RADAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "partner",
    "chat_name": "Partner",
    "export_text": "12.01.26, 14:30 - Partner: Kind hat am 18. Februar Geburtstag\n13.01.26, 09:15 - Partner: Sollen wir die Feier am 21. machen?"
  }'
```

### Docker Services

```
WHATSORGA CORE (5 services):
  caddy          — HTTPS reverse proxy (443/80)
  radar-api      — Python FastAPI (8900:8000)
  postgres       — PostgreSQL 16 (internal 5432)
  chromadb       — ChromaDB 0.5.23 (internal 8000)
  ollama         — Local LLMs (internal 11434, legacy)

EVERMEMOS MEMORY STACK (7 services):
  evermemos      — FastAPI memory service (8001)
  mongodb        — Mongo 7.0 (documents, MemCells)
  elasticsearch  — ES 8.11.0 (BM25 keyword search)
  milvus-standalone — Milvus 2.5.2 (vector similarity)
  milvus-etcd    — etcd 3.5.5 (Milvus metadata)
  milvus-minio   — MinIO (Milvus object storage)
  redis          — Redis 7.2 (cache, boundary detection)
```

### Database Access

```bash
# PostgreSQL shell
docker compose exec postgres psql -U radar -d radar

# Recent messages
SELECT chat_name, sender, text, timestamp
FROM messages ORDER BY timestamp DESC LIMIT 10;

# Analysis results
SELECT m.sender, m.text, a.sentiment_score, a.marker_categories->>'dominant' as marker
FROM messages m JOIN analysis a ON a.message_id = m.id
ORDER BY m.timestamp DESC LIMIT 10;
```

---

## Configuration Reference

All radar-api settings use the `RADAR_` prefix (see `radar-api/app/config.py`):

| Variable | Type | Default | Description |
|---|---|---|---|
| `RADAR_API_KEY` | str | "changeme" | Bearer token for authentication |
| `RADAR_DATABASE_URL` | str | postgresql+asyncpg://... | PostgreSQL connection (async) |
| `RADAR_DATABASE_URL_SYNC` | str | postgresql+psycopg2://... | PostgreSQL connection (sync) |
| `RADAR_GROQ_API_KEY` | str | "" | Groq API key (Whisper + LLM) |
| `RADAR_GEMINI_API_KEY` | str | "" | Gemini fallback LLM |
| `RADAR_CHROMADB_URL` | str | http://chromadb:8000 | ChromaDB endpoint |
| `RADAR_OLLAMA_URL` | str | http://ollama:11434 | Local LLM (legacy) |
| `RADAR_CALDAV_URL` | str | "" | iCloud CalDAV server |
| `RADAR_CALDAV_USERNAME` | str | "" | iCloud email |
| `RADAR_CALDAV_PASSWORD` | str | "" | App-specific password |
| `RADAR_CALDAV_CALENDAR` | str | WhatsOrga | Calendar name |
| `RADAR_EVERMEMOS_URL` | str | http://evermemos:8001 | EverMemOS API endpoint |
| `RADAR_EVERMEMOS_ENABLED` | bool | true | Enable/disable semantic memory |

### EverMemOS Configuration

These are set in Docker environment (not `RADAR_` prefixed):

| Variable | Default | Description |
|---|---|---|
| `EVERMEMOS_LLM_MODEL` | meta-llama/llama-3.3-70b-instruct | LLM for MemCell extraction |
| `EVERMEMOS_LLM_BASE_URL` | https://api.groq.com/openai/v1 | LLM API base URL |
| `EVERMEMOS_DEEPINFRA_KEY` | — | DeepInfra API key (required for embeddings + reranking) |

### Extension Configuration

Stored in Chrome's `chrome.storage.local` (configured via popup UI):

| Setting | Description |
|---|---|
| **Server URL** | Backend address (e.g. `https://radar.your-domain.de`) |
| **API Key** | Bearer token matching `RADAR_API_KEY` |
| **Whitelist** | Array of contact/group names to capture |
| **Capture Enabled** | Boolean toggle for activation/deactivation |

---

## Development

### Local API Development

```bash
cd radar-api
pip install -r requirements.txt

# PostgreSQL + ChromaDB must be running
# Option: docker compose up postgres chromadb -d (from deploy/)

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# API docs
open http://localhost:8000/docs
```

### Tests

```bash
cd radar-api
pytest                                    # fast tests only
pytest -m slow                            # slow tests (loads ML models)
pytest tests/test_unified_engine.py       # single file
pytest -k test_engine_regex               # single test by name
```

### Marker Registry Compilation

```bash
cd radar-api
python -m scripts.compile_registry \
  --markers-dir ../../Marker/WTME_ALL_Marker-LD3.4.1-5.1 \
  --category-mapping data/category_mapping.yaml \
  --output data/marker_registry_radar.json
```

The compiled registry (`data/marker_registry_radar.json`) is gitignored — must be compiled locally or during Docker build.

### Extension Development

Load unpacked in Chrome (`chrome://extensions/` → Developer mode → Load unpacked → select `extension/`). Changes to content scripts require clicking the refresh button on the extension card. Changes to `popup.js` take effect on next popup open.
