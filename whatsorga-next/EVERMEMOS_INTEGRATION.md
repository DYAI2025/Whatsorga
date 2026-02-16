# EverMemOS Integration — Architektur & Implementierung

## Was wurde gebaut

Die Integration verbindet vier Repositories zu einem funktionierenden System, in dem jede WhatsApp-Nachricht durch ein semantisches Kontextgedächtnis fließt und dadurch Pronomen aufgelöst, Fakten gespeichert und Termine kontextrichtig erkannt werden.

---

## Systemarchitektur nach Integration

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        UNIFIED DOCKER STACK                              │
│                                                                          │
│  ┌─────────────────┐         ┌──────────────────────────────────────┐   │
│  │  Chrome Extension│────────→│  radar-api (FastAPI :8000)           │   │
│  │  WhatsApp Web    │  HTTPS  │                                      │   │
│  └─────────────────┘         │  1. Nachricht speichern (PostgreSQL)  │   │
│                               │  2. ▶ EverMemOS memorize() ◀         │   │
│                               │  3. Sentiment + Marker Analyse       │   │
│                               │  4. RAG Embedding (ChromaDB)         │   │
│                               │  5. Thread Weaving                   │   │
│                               │  6. ▶ Context-aware Termin-          │   │
│                               │     Extraktion mit recall() ◀        │   │
│                               │  7. CalDAV → Apple Kalender          │   │
│                               └──────────┬───────────────────────────┘   │
│                                          │ HTTP                          │
│                               ┌──────────▼───────────────────────────┐   │
│                               │  EverMemOS (FastAPI :8001)           │   │
│                               │                                      │   │
│                               │  /memorize → MemCell Extraction      │   │
│                               │  /retrieve → Hybrid Search (RRF)     │   │
│                               │                                      │   │
│                               │  Speicher:                           │   │
│                               │  • MongoDB (Dokumente, MemCells)     │   │
│                               │  • Elasticsearch (BM25 Keyword)      │   │
│                               │  • Milvus (Vektor-Semantik)          │   │
│                               │  • Redis (Cache, Boundary Detection) │   │
│                               └──────────────────────────────────────┘   │
│                                                                          │
│  Bestehend:  PostgreSQL, ChromaDB, Caddy, Ollama                        │
│  Neu:        EverMemOS, MongoDB, Elasticsearch, Milvus, Redis            │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Neue Dateien

### `radar-api/app/memory/` — Integration Module

| Datei | Zweck |
|-------|-------|
| `evermemos_client.py` | Async HTTP Client zu EverMemOS. Zwei Kern-Operationen: `memorize()` (speichern) und `recall()` (abrufen). Connection-pooled, resilient — wenn EverMemOS down ist, läuft Whatsorga weiter. |
| `context_termin.py` | Kontextgestützte Termin-Extraktion. Ruft vor der Analyse EverMemOS ab, injiziert Personenwissen und Fakten in den LLM-Prompt. Löst das "Marike/Romy-Problem". |
| `whisper_integration.py` | Super_semantic_whisper Anbindung. Sprachnachrichten werden chronologisch verarbeitet, mit Kontext angereichert, und das Ergebnis zurück in EverMemOS gespeichert. |
| `context_init.py` | WhatsApp Chat-Export Parser. `POST /api/context/init` nimmt einen Export und füttert alle Nachrichten in EverMemOS für initiales Weltwissen. |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `config.py` | +`evermemos_url`, +`evermemos_enabled` Einstellungen |
| `main.py` | +Context Router, +Health Check mit EverMemOS Status, +Shutdown Hook |
| `ingestion/router.py` | Jede Nachricht → `evermemos_client.memorize()`. Termin-Extraktion nutzt `extract_termine_with_context()` statt raw. |
| `deploy/docker-compose.yml` | 12 Services statt 5. EverMemOS Stack komplett integriert. |
| `deploy/.env.template` | +EverMemOS Variablen (LLM, DeepInfra, Flags) |

---

## Nachrichtenfluss VORHER vs. NACHHER

### Vorher: "Kannst du an ihrem Geburtstag Süßigkeiten-Tüten mitbringen?"

```
Text → Termin-Extraktor → ❌ Kein Datum erkannt ("ihrem" = wer?)
                         → ❌ Kein Termin erstellt
```

### Nachher:

```
Text → EverMemOS memorize()
     → EverMemOS recall("Termine Geburtstage: Kannst du an ihrem...")
       → Kontext: "Romy = Tochter, Geb: 18.02., Feier: 21.02., 8 Gäste"
     → Kontextgestützter Termin-Extraktor:
       → ✅ "ihrem" = Romys
       → ✅ Datum: 21.02. (Feier, nicht Geburtstag)
       → ✅ Aufgabe: "Süßigkeiten-Tüten für 8 Gäste"
       → CalDAV → Apple Kalender ✅
```

---

## Deployment

### Voraussetzungen

- Docker & Docker Compose
- Min. 6 GB RAM (Elasticsearch + Milvus brauchen Speicher)
- Groq API Key (für Whisper + LLM)
- DeepInfra API Key (für Embeddings + Reranking)

### Starten

```bash
cd deploy
cp .env.template .env
nano .env  # Keys eintragen

# EverMemOS Source muss neben radar-api liegen:
# Whatsorga/
#   ├── radar-api/
#   ├── EverMemOS/    ← hierhin kopiert
#   ├── deploy/
#   └── extension/

docker compose up -d

# Logs
docker compose logs -f radar-api evermemos

# Health Check
curl http://localhost:8900/health
# → {"status":"ok","service":"beziehungs-radar","memory":{"status":"ok","evermemos":"connected"}}
```

### Basis-Kontext laden (WhatsApp Export)

```bash
curl -X POST http://localhost:8900/api/context/init \
  -H "Authorization: Bearer $RADAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "marike",
    "chat_name": "Marike",
    "export_text": "12.01.26, 14:30 - Marike: Romy hat am 18. Februar Geburtstag\n13.01.26, 09:15 - Marike: Sollen wir die Feier am 21. machen?\n..."
  }'
```

---

## Konfigurierbare Variablen

| Variable | Default | Beschreibung |
|----------|---------|--------------|
| `RADAR_EVERMEMOS_URL` | `http://evermemos:8001` | EverMemOS API Endpunkt |
| `RADAR_EVERMEMOS_ENABLED` | `true` | Memory ein/aus |
| `EVERMEMOS_LLM_MODEL` | `meta-llama/llama-3.3-70b-instruct` | LLM für MemCell Extraktion |
| `EVERMEMOS_LLM_BASE_URL` | `https://api.groq.com/openai/v1` | LLM API Basis-URL |
| `EVERMEMOS_DEEPINFRA_KEY` | — | DeepInfra Key für Embeddings |

---

## Was jetzt emergent möglich wird

Durch das persistente semantische Gedächtnis entstehen neue Fähigkeiten, die vorher nicht programmiert werden mussten — sie emergieren aus dem Kontext:

1. **Pronomen-Auflösung**: "ihrem" → Romy, weil EverMemOS den Beziehungsgraph kennt
2. **Temporale Logik**: Geburtstag (18.02.) ≠ Feier (21.02.), weil die Fakten gespeichert sind
3. **Mengen-Inferenz**: "Süßigkeiten-Tüten für ihre Gäste" → 8 Stück, weil die Gästezahl bekannt ist
4. **Proaktive Erinnerungen**: System kann Aufgaben vor einem Event erkennen und rechtzeitig erinnern
5. **Themen-Kontinuität**: Sprachnachricht-Ketten werden als zusammenhängender Kontext verstanden
6. **Lernende Profile**: Jede Nachricht reichert das Wissen über Personen weiter an
