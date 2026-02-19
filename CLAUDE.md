# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**WhatsOrga** (v0.2.0, formerly Beziehungs-Radar) — WhatsApp message analysis system with semantic memory. Three components:
1. **Chrome Extension** (`extension/`) — Captures messages from whitelisted contacts on WhatsApp Web
2. **FastAPI Backend** (`radar-api/`) — AI/ML analysis pipeline + EverMemOS semantic memory
3. **Deployment Stack** (`deploy/`) — Docker Compose: 12 services including EverMemOS memory stack

## Development Commands

```bash
# API (local dev)
cd radar-api && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# API docs: http://localhost:8000/docs

# Tests
cd radar-api
pytest                                # fast tests only
pytest -m slow                        # ML model tests (loads sentence-transformer)
pytest tests/test_unified_engine.py   # single file
pytest -k test_engine_regex           # single test by name

# Marker registry compilation (gitignored artifact, must build locally)
cd radar-api
python -m scripts.compile_registry \
  --markers-dir ../../Marker/WTME_ALL_Marker-LD3.4.1-5.1 \
  --category-mapping data/category_mapping.yaml \
  --output data/marker_registry_radar.json

# Deployment
cd deploy && cp .env.template .env   # then configure RADAR_* variables
docker compose up -d
docker compose logs -f radar-api

# Extension — load unpacked in Chrome (chrome://extensions/ → Developer mode)

# Database migrations (manual, not Alembic)
cd radar-api && python migrations/add_capture_stats.py upgrade
```

## Architecture

### Message Flow
Extension → `POST /api/ingest` (Bearer auth) → parallel analysis:
- Audio → Groq Whisper transcription → semantic enrichment via conversation context
- Text → Marker detection (two-phase: regex then embedding cosine similarity)
- Text → Sentiment scoring (-1.0 to +1.0)
- Text → RAG embedding (ChromaDB)
- Text → Semantic thread weaving
- Text → Termin extraction (LLM cascade) → CalDAV sync (Apple iCloud)
- Text → EverMemOS `memorize()` (fire-and-forget, non-blocking)

### EverMemOS Integration (Semantic Memory)
EverMemOS provides persistent conversational memory. It runs as a separate service (port 8001) with its own infrastructure stack (MongoDB, Elasticsearch, Milvus, Redis).

- **Memorize**: fire-and-forget after ingestion, chunks messages and stores semantic memories
- **Recall**: `recall(query, chat_id, mode="rrf", top_k=10)` returns `MemoryContext` with episodes, profiles, facts
- **Graceful degradation**: if EverMemOS is down, WhatsOrga continues without memory context
- **Redis buffer**: boundary detection lives in Redis DB 8, key `chat_history:{group_id}` — NOT MongoDB
- **LLM stack**: DeepInfra Llama 3.3 70B, Qwen3-Embedding-4B, Qwen3-Reranker-4B
- **Gotcha**: 2000+ accumulated messages in Redis buffer can exceed Llama 3.3's 131k token limit; clear with `redis-cli -n 8 DEL chat_history:{group_id}` before reimport

### Termin Extraction (Most Complex Module)
`analysis/termin_extractor.py` — LLM-only, no regex fallback (German appointment context requires LLM understanding).

- **LLM cascade**: Groq llama-3.3-70b-versatile (primary, 45s timeout) → Gemini 2.5 Flash (fallback)
- **Tree-of-Thoughts reasoning**: 6 dimensions evaluated per message (Zeit, Familie, Handlung, Kontext, Plausibilität, Intention)
- **Calendar lookup table**: dynamically generated to prevent LLM date calculation errors
- **Context layers**: last 10 messages + existing termine (60-day window) + EverMemOS recall + feedback examples
- **Actions**: `create` | `update` | `cancel` with `updates_termin_id` for dedup
- **Dual calendar**: auto-confirm (confidence ≥ 0.85) → "WhatsOrga" calendar, suggest (< 0.85) → "WhatsOrga ?" calendar
- **Relevance types**: `for_me` | `shared` | `partner_only` | `affects_me` (family-aware: children's appointments always "shared")
- **JSON parsing**: resilient multi-strategy extraction — handles reasoning text before JSON, natural language fallback detection

### Two-Phase Marker Detection
`analysis/unified_engine.py` — singleton loaded at startup via `engine.load()`.
- **Phase 1**: compiled regex patterns from marker registry (deterministic, fast)
- **Phase 2**: pre-computed embeddings matrix (384 dims, all-MiniLM-L6-v2) with cosine similarity (threshold 0.65)
- Falls back to legacy `marker_engine.py` if `data/marker_registry_radar.json` missing

### Extension Architecture
- **DOM observer** on WhatsApp Web with watchdog: checks `#main` every 5s, force-rescans every 30s
- **Message dedup**: `sentMessageIds` Set in chrome.storage.local (rolling 5000 window)
- **Queue manager**: batches messages before API calls
- Audio captured as base64 blob in message payload
- **MV3 heartbeat**: uses `chrome.alarms` (not `setInterval`) — service workers suspend after ~30s idle, killing timers and in-memory state. All heartbeat state persisted to `chrome.storage.local`

## Key Technical Patterns

- **Async everywhere**: SQLAlchemy async with asyncpg, httpx.AsyncClient for external LLM/API calls
- **Singletons**: marker engine loaded once at startup; EverMemOS client is lazy-init with connection pooling
- **All env vars** use `RADAR_` prefix (Pydantic Settings in `config.py`)
- **Auth**: `verify_api_key` dependency on all endpoints, Bearer token vs `RADAR_API_KEY`
- **DB**: tables auto-created via `Base.metadata.create_all` on startup (no Alembic)
- **Migrations**: manual scripts in `radar-api/migrations/` with `upgrade`/`downgrade`/`verify` commands, idempotent
- **Error philosophy**: EverMemOS failures non-fatal, LLM timeouts cascade to fallback, missing context → empty string (never crashes)
- **Embedding model**: `all-MiniLM-L6-v2` (384 dims), pre-downloaded in Docker image at build time
- Python 3.12, FastAPI 0.115, SQLAlchemy 2.0

## Configuration

**Public repo rule**: never hardcode personal/family data in source. Use env vars (`RADAR_TERMIN_USER_NAME`, `RADAR_TERMIN_PARTNER_NAME`, `RADAR_TERMIN_CHILDREN_NAMES`) for all PII.

All env vars use `RADAR_` prefix (see `radar-api/app/config.py`):
- `RADAR_API_KEY` — Bearer token for extension auth
- `RADAR_DATABASE_URL` — PostgreSQL (asyncpg)
- `RADAR_GROQ_API_KEY` — Groq Whisper + LLM (primary)
- `RADAR_GEMINI_API_KEY` — Gemini fallback LLM
- `RADAR_CALDAV_*` — Apple iCloud calendar sync
- `RADAR_CALDAV_CALENDAR` / `RADAR_CALDAV_SUGGEST_CALENDAR` — dual calendar names
- `RADAR_TERMIN_AUTO_CONFIDENCE` — threshold for auto-confirm (default 0.85)
- `RADAR_CHROMADB_URL` — Vector store endpoint
- `RADAR_EVERMEMOS_URL` / `RADAR_EVERMEMOS_ENABLED` — semantic memory

## Docker Services (deploy/docker-compose.yml)
**WhatsOrga core**: caddy (443/80), radar-api (8900→8000), postgres (5432 internal), chromadb (8000 internal), ollama (legacy)
**EverMemOS stack**: evermemos (8001), mongodb, elasticsearch, milvus-standalone + etcd + minio, redis

## Database Tables
- `messages` — raw messages with `raw_payload` JSONB (messageId, replyTo, hasAudio)
- `analysis` — per-message sentiment + `markers`/`marker_categories` (JSONB)
- `threads` — semantic conversation groupings (theme, emotional_arc)
- `termine` — extracted appointments, `status` (auto|suggested|confirmed|rejected|skipped|cancelled), `caldav_uid`, `all_day`
- `termin_feedback` — user corrections (confirmed|rejected|edited) with `correction` JSONB
- `capture_stats` — extension heartbeat health
- `drift_snapshots` — sentiment trend snapshots (currently unused)

## API Endpoints
**Ingestion**: `POST /api/ingest`, `POST /api/transcribe`, `POST /api/heartbeat`
**Dashboard**: `GET /api/overview/{chat_id}`, `/drift/{chat_id}`, `/markers/{chat_id}`, `/threads/{chat_id}`, `/termine/{chat_id}`, `/search?q=`, `/status`
**Monitoring**: `GET /api/capture-stats`, `/communication-pattern/{chat_id}`, `/response-times/{chat_id}`
**Memory**: `GET /api/context/status`, `/api/context/recall`
**Health**: `GET /health`

## Root-Level Utility Scripts
- `import_context.py` — batch WhatsApp export importer into EverMemOS (smart chunking by time gaps, async with semaphore)
- `transcribe_voices.py` — batch .opus voice transcription via Groq Whisper into EverMemOS
