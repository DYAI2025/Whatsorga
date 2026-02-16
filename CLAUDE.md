# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Beziehungs-Radar** (Relationship Radar) — WhatsApp message analysis system with three components:
1. **Chrome Extension** (`extension/`) — Captures messages from whitelisted contacts on WhatsApp Web
2. **FastAPI Backend** (`radar-api/`) — Analyzes messages with AI/ML pipeline
3. **Deployment Stack** (`deploy/`) — Docker Compose with Caddy, PostgreSQL, ChromaDB, Ollama

## Architecture

### Message Flow
Extension → `POST /api/ingest` (Bearer auth) → Analysis pipeline:
- Audio → Groq Whisper transcription
- Text → Marker detection (regex + embedding similarity via `all-MiniLM-L6-v2`)
- Text → Sentiment scoring (-1 to +1)
- Text → RAG embedding (ChromaDB)
- Text → Semantic thread weaving
- Text → Appointment extraction → CalDAV sync (Apple iCloud)

### Backend Structure (`radar-api/app/`)
- `main.py` — FastAPI app, mounts routers and static dashboard
- `config.py` — Pydantic Settings with `RADAR_` env prefix
- `ingestion/router.py` — `/api/ingest`, `/api/transcribe`, `/api/heartbeat`
- `dashboard/router.py` — All `/api/*` read endpoints (overview, drift, markers, threads, termine, search, status, capture-stats, communication-pattern, response-times)
- `analysis/unified_engine.py` — Two-phase marker detection (Phase 1: regex, Phase 2: embedding cosine similarity). Falls back to legacy `marker_engine.py` if registry missing
- `analysis/sentiment_tracker.py` — Sentiment scoring
- `analysis/weaver.py` — Semantic thread grouping via ChromaDB similarity
- `analysis/termin_extractor.py` — Appointment extraction using Groq/Gemini LLMs
- `analysis/semantic_transcriber.py` — Transcript enrichment with conversation context
- `storage/database.py` — SQLAlchemy async models (Message, Analysis, Thread, Termin, DriftSnapshot, CaptureStats)
- `storage/rag_store.py` — ChromaDB vector store wrapper
- `outputs/caldav_sync.py` — Apple Calendar iCal event creation

### Extension Structure (`extension/`)
- `manifest.json` — Manifest V3, content scripts on `web.whatsapp.com`
- `content.js` — DOM observer for WhatsApp Web messages and audio
- `queue-manager.js` — Message batching/queue before sending to API
- `background.js` — Service worker, manages API communication
- `popup.html/js/css` — Config UI (whitelist, enable/disable, API URL)
- Config stored in `chrome.storage.local`: `whitelist` (contact names), `enabled` (boolean)

## Development Commands

### API (local)
```bash
cd radar-api
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# API docs: http://localhost:8000/docs
```

### Tests
```bash
cd radar-api
pytest                     # run all tests (fast only)
pytest -m slow             # run slow tests (loads ML models)
pytest tests/test_unified_engine.py  # single test file
pytest -k test_engine_regex         # single test by name
```

### Marker Registry Compilation
```bash
cd radar-api
python -m scripts.compile_registry \
  --markers-dir ../../Marker/WTME_ALL_Marker-LD3.4.1-5.1 \
  --category-mapping data/category_mapping.yaml \
  --output data/marker_registry_radar.json
```
The compiled registry (`data/marker_registry_radar.json`) is gitignored — must be compiled locally or in Docker build.

### Deployment (Production)
```bash
cd deploy
cp .env.template .env  # configure all RADAR_* variables
docker compose up -d
docker compose logs -f radar-api
```

### Extension
Load unpacked in Chrome (`chrome://extensions/` → Developer mode → Load unpacked → select `extension/`).

## Configuration

All env vars use `RADAR_` prefix (see `radar-api/app/config.py`):
- `RADAR_API_KEY` — Bearer token for extension auth
- `RADAR_DATABASE_URL` — PostgreSQL (asyncpg)
- `RADAR_GROQ_API_KEY` — Groq Whisper + LLM
- `RADAR_GEMINI_API_KEY` — Gemini fallback LLM
- `RADAR_CALDAV_*` — Apple iCloud calendar sync
- `RADAR_CHROMADB_URL` — Vector store endpoint

## Key Technical Details

- Auth: All API endpoints use `verify_api_key` dependency checking Bearer token against `RADAR_API_KEY`
- DB: SQLAlchemy async with asyncpg; tables auto-created via `Base.metadata.create_all` on startup
- Marker engine is a singleton (`engine = UnifiedMarkerEngine()`) loaded once at startup via `engine.load()`
- Embedding model: `all-MiniLM-L6-v2` (384 dimensions), pre-downloaded in Docker image
- Response time calculation excludes gaps >24 hours as outliers
- Timestamps: extension sends ISO format, API falls back to `datetime.utcnow()` on parse failure
- Python 3.12, FastAPI 0.115, SQLAlchemy 2.0

## Port Mapping (Docker)
- Caddy: 443/80 (public HTTPS)
- radar-api: internal 8000, host-exposed 8900
- PostgreSQL: internal 5432 only
- ChromaDB: internal 8000 only
- Ollama: internal 11434 only (legacy, unused)

## Database Tables
- `messages` — Raw messages (text, audio_path, timestamp, chat_id, sender)
- `analysis` — Per-message sentiment + markers (JSONB)
- `threads` — Semantic conversation groupings (theme, emotional_arc)
- `termine` — Extracted appointments (datetime, participants, caldav_uid)
- `capture_stats` — Extension heartbeat health tracking
- `drift_snapshots` — Sentiment trend snapshots (currently unused)

## API Endpoints Quick Reference
**Ingestion**: `POST /api/ingest`, `POST /api/transcribe`, `POST /api/heartbeat`
**Dashboard**: `GET /api/overview/{chat_id}`, `/drift/{chat_id}`, `/markers/{chat_id}`, `/threads/{chat_id}`, `/termine/{chat_id}`, `/search?q=`, `/status`
**Monitoring**: `GET /api/capture-stats`, `/communication-pattern/{chat_id}`, `/response-times/{chat_id}`
**Health**: `GET /health`
