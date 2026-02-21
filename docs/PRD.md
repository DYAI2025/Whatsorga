# WhatsOrga — Projektanforderung (PRD)

Stand: 21.02.2026 | Version: 0.2.1-dev

## Vision

WhatsOrga ersetzt die mentale Last der Familien-Koordination. Aus WhatsApp-Nachrichten zwischen getrennten Elternteilen werden automatisch Termine extrahiert, in den Apple-Kalender synchronisiert und per semantischem Gedächtnis kontextuell verstanden. Das System lernt selbständig und verbessert sich durch Feedback und periodische Reflexion.

**Zielzustand**: Ich öffne meinen Kalender und alle relevanten Termine sind da — korrekt, ohne mein Zutun.

## Architektur-Überblick

```
WhatsApp Web (Browser)
       │
       ▼
Chrome Extension ──POST──▶ FastAPI Backend (radar-api)
  (DOM Observer)              │
  (Dedup Hash)                ├── Termin-Extractor (LLM: Groq Llama 3.3 70B → Gemini Flash)
                              ├── Marker Detection (Regex + Embedding Cosine)
                              ├── Sentiment Scoring
                              ├── Semantic Threading
                              ├── EverMemOS Client (memorize + recall)
                              └── CalDAV Sync → Apple iCloud Kalender
                                    │
                                    ├── "WhatsOrga" (auto-confirmed, confidence ≥ 0.85)
                                    └── "WhatsOrga ?" (suggested, confidence < 0.85)

Reflection Agent (cron */30)
       │
       ├── Liest PostgreSQL (letzte 24h Nachrichten)
       ├── Liest Person-YAML-Profile
       ├── Analysiert via `claude -p --model sonnet`
       └── Schreibt Learnings in YAML-Profile

Infrastruktur: Hetzner VPS CAX21 (ARM64, 4 vCPU, 8GB RAM)
12 Docker-Services: caddy, radar-api, postgres, chromadb, ollama,
                    evermemos, mongodb, elasticsearch, milvus, etcd, minio, redis
```

## Komponenten

### 1. Chrome Extension (`extension/`)

**Was sie tut**: Observiert WhatsApp Web DOM, extrahiert neue Nachrichten, schickt sie per API an den Backend.

**Schlüssellogik**:
- `content.js`: DOM MutationObserver auf `#main`, Multi-Strategie Message Detection
- `queue-manager.js`: LocalStorage-Queue mit Retry-Logik (max 5 Versuche)
- `background.js`: Service Worker als Relay (CSP-Bypass), Heartbeat-Tracking via `chrome.alarms`
- Dedup: `sentMessageIds` Set in `chrome.storage.local` (Rolling 5000 Window)
- Hash-Funktion: `generateStableId(prePlainText, extractedText)` — nutzt extrahierten Text statt rohem DOM

**Bekannte Schwächen**:
- MV3 Service Workers suspendieren nach ~30s Idle — alle Timer sterben
- Audio-Capture braucht Blob-Fetch vor URL-Expiration
- Chat-Wechsel-Erkennung über 5 DOM-Strategien (fragil bei WhatsApp Web Updates)

### 2. FastAPI Backend (`radar-api/`)

**Ingest-Pipeline** (`ingestion/router.py`):
```
POST /api/ingest → Dedup-Check (sender+text+timestamp+chatId)
  → Audio-Transkription (Groq Whisper)
  → DB Insert (messages)
  → Parallel: Marker + Sentiment + EverMemOS memorize + RAG embed + Thread weave
  → Termin-Extraktion (context_termin.py → termin_extractor.py)
  → CalDAV Sync
  → Person-Learner (learn_from_termin)
```

**Termin-Extractor** (`analysis/termin_extractor.py`):
- 6-Dimensionen-Analyse (Tree-of-Thoughts): Zeit, Familie, Handlung, Kontext, Plausibilität, Intention
- LLM-Cascade: Groq Llama 3.3 70B (primary, 45s timeout) → Gemini 2.5 Flash (fallback)
- Gate-Funktion `_might_contain_date(text, context)`: Regex-Vorfilter, akzeptiert auch Konversations-Kontext
- Cross-Message Resolution: Q&A-Pattern ("Wann morgen?" + "13:45 Uhr" → Termin morgen 13:45)
- ENDZEIT-Logik: "bis 18 Uhr" = Endzeit, nicht Startzeit
- Prep-Task-Filter: "Proviant einpacken" für existierenden Wettkampf → kein eigener Eintrag
- Duplikat-Erkennung: DB-Abgleich + Title-Word-Overlap

**Kontext-Schichten** (`memory/context_termin.py`):
1. Conversation Context (letzte 10 Nachrichten mit Datum+Uhrzeit)
2. Existierende Termine aus DB (60-Tage-Fenster, max 30)
3. EverMemOS Recall (Episoden, Profile, Fakten)
4. Feedback-Beispiele (rejected/edited Termine)
5. Person-YAML-Profile (Fakten, Aktivitäten, Termin-Hinweise)

**Personen-System** (`memory/person_context.py` + `memory/person_learner.py`):
- YAML-Profile pro Familienmitglied in `data/persons/`
- Singleton-Cache mit `load_persons()` / `reload_persons()`
- `detect_persons(text, context)`: Findet erwähnte Personen per Name/Alias
- Auto-Learning: Neue Aktivitäten aus Termin-Extraktionen, Lessons aus Feedback
- Pattern Detection: 3+ gleicher Wochentag → automatische Regel

### 3. Reflection Agent (`radar-api/reflection/`)

**Was er tut**: Cron-Job (alle 30 Min), liest aktuelle Nachrichten + Profile, analysiert via Claude CLI, schreibt YAML-Updates.

**Dateien**:
- `mission.md`: Philosophischer Basisprompt ("Du verstehst diese Familie nicht. Noch nicht.")
- `reflect.sh`: Bash-Script mit Lock-File, PostgreSQL-Abfragen, `claude -p --model sonnet`
- `last_reflection.json`: Debug-Output der letzten Analyse

**Lernfelder**:
- `neue_fakten`: Neue biographische Fakten (z.B. "Enno zeigt Tunnel-Modus vor Wettkämpfen")
- `neue_aktivitaeten`: Neue regelmäßige Aktivitäten
- `neue_termin_hinweise`: Reasoning-Regeln für den Termin-Extractor
- `confidence_notes`: Unsichere Beobachtungen (in `_uncertain` gespeichert)
- `gaps_identified`: Was das System noch nicht weiß

**Autopoiesis-Prinzip**: Die Unvollständigkeit der Profile ist der Antrieb. Der Agent soll nie "fertig" sein, sondern durch strukturelle Spannung (Lücken) immer weiter lernen.

### 4. EverMemOS Integration

**Zweck**: Persistentes semantisches Gedächtnis über Konversationen hinweg.

**Stack**: EverMemOS Service (Port 8001) + MongoDB + Elasticsearch + Milvus + Redis
**LLMs**: DeepInfra Llama 3.3 70B (Chunking/Analyse), Qwen3-Embedding-4B, Qwen3-Reranker-4B

**Operationen**:
- `memorize(chat_id, sender, text, timestamp)` — fire-and-forget nach Ingestion
- `recall(query, chat_id, mode="rrf", top_k=10)` → MemoryContext (Episoden, Profile, Fakten)
- Redis-Buffer (DB 8, Key `chat_history:{group_id}`) für Boundary Detection

**Gotcha**: >2000 akkumulierte Messages im Redis-Buffer sprengen Llama 3.3's 131k Token-Limit. Vor Reimport: `redis-cli -n 8 DEL chat_history:{group_id}`

### 5. CalDAV Sync (`outputs/caldav_sync.py`)

**Zwei Kalender**:
- `RADAR_CALDAV_CALENDAR` ("WhatsOrga") — auto-confirmed (confidence ≥ 0.85)
- `RADAR_CALDAV_SUGGEST_CALENDAR` ("WhatsOrga ?") — suggested (confidence < 0.85)

**Operationen**: `sync_termin_to_calendar()`, `update_termin_in_calendar()`, `delete_termin_from_calendar()`

---

## Datenmodell

### PostgreSQL Tables

| Table | Zweck | Schlüsselfelder |
|-------|-------|-----------------|
| `messages` | Rohdaten | `chat_id`, `sender`, `text`, `timestamp`, `raw_payload` (JSONB) |
| `analysis` | Marker + Sentiment | `message_id` FK, `sentiment_score`, `markers` (JSONB) |
| `termine` | Extrahierte Termine | `title`, `datetime`, `status`, `confidence`, `caldav_uid`, `all_day`, `relevance` |
| `termin_feedback` | User-Korrekturen | `termin_id` FK, `action` (confirmed/rejected/edited), `correction` (JSONB) |
| `threads` | Semantische Threads | `theme`, `emotional_arc` |
| `capture_stats` | Extension-Health | `chat_id`, `last_heartbeat`, `messages_captured_24h` |

### Termin-Status-Flow

```
LLM Extract → confidence ≥ 0.85 → "auto" → WhatsOrga Kalender
            → confidence < 0.85 → "suggested" → WhatsOrga ? Kalender
            → User bestätigt   → "confirmed"
            → User lehnt ab    → "rejected" → Feedback gespeichert
            → User editiert    → Status bleibt, Feedback gespeichert
            → Nachricht sagt ab → "cancelled" → CalDAV gelöscht
```

### Person YAML Schema (`data/persons/*.yaml`)

```yaml
name: Enno
rolle: Sohn                    # Familien-Rolle
alias: [enno, ansen]           # Aliases für detect_persons()
fakten:                        # Biographische Fakten
  - Schwimmt im Verein (SG Neukölln)
  - Geht in den Hort
aktivitaeten:                  # Regelmäßige Aktivitäten
  schwimmen:
    typ: Regelmaessig
    muster: "Trainings + Wettkämpfe am Wochenende"
    termin_logik:
      - "'bis X Uhr' = ENDZEIT, nicht Startzeit"
      - "'Proviant einpacken' = kein Termin"
termin_hinweise:               # LLM-Reasoning-Regeln
  - "Wenn Enno + 'abholen' + Hort → Nachmittag-Termin"
_uncertain:                    # Unsichere Beobachtungen (max 20)
  - "Trainingszeiten noch nicht bestätigt"
```

---

## Feature-Status

### Implementiert & Deployed

| Feature | Status | Qualität | Dateien |
|---------|--------|----------|---------|
| Message Ingestion + Dedup | Deployed | Server-side Dedup seit 21.02. | `ingestion/router.py` |
| Termin-Extraktion (6 Dimensionen) | Deployed | Grundlegend funktional, siehe Bugs | `analysis/termin_extractor.py` |
| Cross-Message Termin Resolution | Deployed | Neu, noch nicht validiert | `termin_extractor.py`, `context_termin.py` |
| CalDAV Sync (Dual-Kalender) | Deployed | Funktional | `outputs/caldav_sync.py` |
| Person YAML Profile | Deployed | 4 Profile (Ben, Marike, Romy, Enno) | `data/persons/*.yaml` |
| Auto-Learning (Termin → YAML) | Deployed | Nicht end-to-end getestet | `memory/person_learner.py` |
| Reflection Agent | Deployed (Cron) | Läuft, lernt korrekt | `reflection/reflect.sh` |
| EverMemOS Integration | Deployed | memorize funktional, recall oft "0 items" | `memory/evermemos_client.py` |
| Marker Detection (Two-Phase) | Deployed | Legacy Fallback aktiv (Registry fehlt) | `analysis/unified_engine.py` |
| Sentiment Scoring | Deployed | Funktional | `analysis/sentiment_tracker.py` |
| Extension DOM Observer | Deployed | Stabil mit Watchdog | `extension/content.js` |

### Geplant / Feature-Gaps

| Feature | Priorität | Beschreibung | Kontext |
|---------|-----------|--------------|---------|
| **Termin-Feedback UI** | HOCH | Dashboard-Widget zum Bestätigen/Ablehnen/Editieren von Terminen. Ohne Feedback kein Lernloop. | Feedback-Endpoint existiert (`POST /api/termine/{id}/feedback`), aber kein Frontend |
| **YAML-Sync VPS ↔ Git** | HOCH | Reflection Agent schreibt YAMLs auf VPS — divergieren von Git. Braucht Strategie (auto-commit? rsync? bidirektional?) | Am 21.02. Merge-Konflikt bei `romy.yaml` durch Reflection-Updates |
| **Marker Registry Rebuild** | MITTEL | `marker_registry_radar.json` fehlt auf VPS → Legacy Fallback aktiv. Braucht Marker-Daten + `scripts/compile_registry.py` | Warning im Log: "using legacy fallback" |
| **EverMemOS Recall Verbesserung** | MITTEL | Recall liefert häufig "0 memory items" trotz reichem Kontext. Query-Strategie prüfen. | Logs zeigen `0 memory items` bei fast jeder Nachricht |
| **Proaktive Benachrichtigungen** | NIEDRIG | System informiert User über neue Termine per Push/WhatsApp statt nur passiv in Kalender. | Braucht eigenen WhatsApp-Kanal oder NanoClaw-Integration |
| **Multi-Chat Support** | NIEDRIG | Aktuell primär für einen Chat optimiert. Erweiterung auf mehrere Chats (z.B. Schul-Gruppe). | Extension-Whitelist existiert, Backend unterstützt `chat_id` |
| **CalDAV Cleanup bei Duplikat-Löschung** | MITTEL | Wenn Duplikat-Termine aus DB gelöscht werden, bleiben CalDAV-Einträge stehen. | Beim Cleanup am 21.02. manuell Termine aus DB gelöscht — CalDAV nicht bereinigt |
| **Gemini Fallback Stabilisierung** | MITTEL | Gemini 2.5 Flash produziert oft Reasoning-Text ohne JSON → Parse-Fehler. | `_parse_extraction_response()` hat Multi-Strategy-Parsing, aber Gemini bricht trotzdem oft |
| **Extension Reconnect nach Tab-Wechsel** | NIEDRIG | Wenn WhatsApp Web Tab lange inaktiv war, kann die Extension den DOM-State verlieren | Watchdog fängt das meistens, aber nicht immer |
| **Termin-Update statt Duplikat** | HOCH | System erstellt oft neue Termine statt bestehende zu updaten. LLM nutzt `updates_termin_id` zu selten. | "Enno Wettkampf" existierte 2x mit verschiedenen Zeiten |
| **Vergangene Termine ignorieren** | HOCH | System sollte keine Termine in der Vergangenheit extrahieren bei historischen Nachrichten | "Enno Ankunft" (11.02.) aus alten Nachrichten |

---

## Kontext für andere Agenten

### Familien-Kontext (für LLM-Prompts)

- **Ben** (User): Vater, lebt getrennt von Marike
- **Marike** (Ex-Partnerin): Mutter, koordiniert per WhatsApp die Kinder-Logistik
- **Enno** (Sohn): Schwimmer (SG Neukölln), Hort, Training + Wettkämpfe
- **Romy** (Tochter): Beethoven-Gymnasium, Geburtstag 18.02.

Alle Kinder-Termine sind `relevance: shared`. Erwähnung von Kindern = immer terminrelevant.

### LLM-Stack

| Service | Modell | Zweck | Kosten |
|---------|--------|-------|--------|
| Groq | Llama 3.3 70B Versatile | Termin-Extraktion (primary) | Kostenlos (Rate-Limited) |
| Google | Gemini 2.5 Flash | Termin-Extraktion (fallback) | Kostenlos (Tier) |
| Groq | Whisper Large v3 | Audio-Transkription | Kostenlos |
| DeepInfra | Llama 3.3 70B Instruct | EverMemOS (Chunking, Analyse) | ~$0.20/1M tokens |
| DeepInfra | Qwen3-Embedding-4B | EverMemOS (Embeddings) | ~$0.02/1M tokens |
| Anthropic | Claude Sonnet (via CLI) | Reflection Agent | Claude Max Abo ($100/mo) |
| lokal | all-MiniLM-L6-v2 (384d) | Marker Embeddings | kostenlos |

### Deployment

```bash
# VPS SSH
ssh -i ~/.ssh/id_ed25519 root@46.225.120.255

# Repo auf VPS
cd /opt/Whatsorga

# Deploy-Workflow
git pull
cd deploy
docker compose build radar-api    # MUSS nach Code-Änderungen!
docker compose up -d radar-api
docker compose logs -f radar-api

# Reflection Agent
crontab -e  # */30 * * * * /opt/Whatsorga/radar-api/reflection/reflect.sh >> /var/log/whatsorga-reflect.log 2>&1
tail -f /var/log/whatsorga-reflect.log

# Person-YAMLs auf VPS (werden vom Reflection Agent modifiziert!)
ls /opt/Whatsorga/radar-api/data/persons/
```

### Umgebungsvariablen (radar-api)

Alle mit `RADAR_`-Prefix. Definiert in `deploy/.env` (nicht in Git).

Kritisch:
- `RADAR_API_KEY` — Bearer Token für Extension-Auth
- `RADAR_DATABASE_URL` — PostgreSQL asyncpg Connection String
- `RADAR_GROQ_API_KEY` — Groq API (Whisper + LLM)
- `RADAR_GEMINI_API_KEY` — Gemini Fallback
- `RADAR_CALDAV_URL`, `RADAR_CALDAV_USERNAME`, `RADAR_CALDAV_PASSWORD` — Apple iCloud
- `RADAR_EVERMEMOS_URL` — EverMemOS Service Endpoint
- `RADAR_TERMIN_USER_NAME`, `RADAR_TERMIN_PARTNER_NAME`, `RADAR_TERMIN_CHILDREN_NAMES` — Personalisierung

### Testbarkeit

```bash
# Lokale Tests (fast)
cd radar-api && pytest

# Einzelner Test
pytest tests/test_unified_engine.py -k test_engine_regex

# Manueller Termin-Test via API
curl -X POST https://semot.whatsorga.de/api/ingest \
  -H "Authorization: Bearer $RADAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"messageId": "test_001", "sender": "Marike Stucke", "text": "Enno hat morgen um 15 Uhr Training", "chatId": "test", "chatName": "Test"}]}'

# Logs prüfen
ssh root@46.225.120.255 "docker compose -f /opt/Whatsorga/deploy/docker-compose.yml logs --tail=50 radar-api"
```

---

## Qualitätskriterien

### Termin-Extraktion

Ein Termin gilt als **korrekt**, wenn:
1. **Titel** beschreibt den Termin verständlich (nicht "Treffen um 17:30" sondern "Enno Wettkampf")
2. **Datum/Uhrzeit** stimmen (STARTZEIT, nicht ENDZEIT; richtige Woche)
3. **all_day** korrekt gesetzt (Geburtstag = ganztägig, Training = nicht ganztägig)
4. **relevance** korrekt (Kinder = shared, nur Partner = partner_only)
5. **Kein Duplikat** eines existierenden Termins
6. **Keine Prep-Tasks** (Proviant packen, Kuchen backen → kein Eintrag)
7. **Keine Meta-Einträge** (System-Tasks, Vergangenheits-Referenzen)

### Reflection Agent

Der Agent ist **nützlich**, wenn:
1. Neue Fakten stimmen (korrekte Daten, Orte, Personen)
2. `_uncertain` wirklich unsicher ist (nicht als Fakt gespeichert)
3. Keine Halluzinationen (keine erfundenen Aktivitäten)
4. Gaps sinnvoll identifiziert werden (echte Wissenslücken)
5. Termin-Hinweise den Extraktor tatsächlich verbessern

---

## Offene Architektur-Fragen

1. **YAML-Sync**: Wie synchronisieren wir VPS-Reflection-Updates zurück in Git? Auto-Commit? Separate Branch? Oder nur VPS als Source-of-Truth?
2. **Feedback-Loop**: Ohne Termin-Feedback-UI fehlt der wichtigste Lernkanal. Welches Frontend? WhatsApp-Bot? Web-Dashboard? Telegram?
3. **NanoClaw**: Das Framework bietet WhatsApp I/O + Container-Isolation + Scheduled Tasks. Lohnt sich die Migration für den Reflection-Agent oder einen interaktiven Assistenten?
4. **Rate Limits**: Groq ist kostenlos aber rate-limited. Bei 267+ Nachrichten/Woche und 1 LLM-Call/Nachricht — halten die Limits? Monitoring nötig.
5. **CalDAV-Qualität**: Werden Auto-Confirmed Termine (≥0.85) wirklich zuverlässig genug für den Kalender? Oder sollte die Schwelle höher (0.90)?
