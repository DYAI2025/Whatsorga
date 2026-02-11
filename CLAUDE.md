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
