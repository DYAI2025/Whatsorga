# Beziehungs-Radar

**WhatsApp-Nachrichtenanalyse-System zur Beziehungsgesundheit**

Beziehungs-Radar erfasst WhatsApp-Nachrichten von ausgewählten Kontakten, analysiert sie mit KI-Methoden (Sentiment, Marker, Threads) und stellt die Ergebnisse über ein Dashboard und eine API bereit. Termine werden automatisch erkannt und in den Apple Kalender synchronisiert.

---

## Inhaltsverzeichnis

1. [Systemübersicht](#systemübersicht)
2. [Architektur](#architektur)
3. [Komponenten im Detail](#komponenten-im-detail)
   - [Chrome Extension](#chrome-extension)
   - [FastAPI Backend](#fastapi-backend)
   - [Analyse-Pipeline](#analyse-pipeline)
   - [Speicher & Datenbank](#speicher--datenbank)
   - [Deployment Stack](#deployment-stack)
4. [Nachrichtenfluss (End-to-End)](#nachrichtenfluss-end-to-end)
5. [API-Referenz](#api-referenz)
6. [Kontextverständnis — Analyse & Schwachstellen](#kontextverständnis--analyse--schwachstellen)
7. [Vorgeschlagene Lösung: Kontextgedächtnis](#vorgeschlagene-lösung-kontextgedächtnis)
8. [Installation & Entwicklung](#installation--entwicklung)
9. [Konfiguration](#konfiguration)

---

## Systemübersicht

```
┌─────────────────┐     HTTPS/JSON      ┌──────────────────────────────────────┐
│  Chrome Extension│ ──────────────────→ │         FastAPI Backend               │
│  (WhatsApp Web)  │                     │                                      │
│                  │  Nachrichten         │  ┌──────────┐  ┌───────────────────┐│
│  • Whitelist     │  + Audio-Blobs      │  │ Sentiment │  │ Marker Engine     ││
│  • DOM-Scraping  │                     │  │ Tracker   │  │ (Regex+Embedding) ││
│  • Queue/Retry   │                     │  └──────────┘  └───────────────────┘│
└─────────────────┘                     │  ┌──────────┐  ┌───────────────────┐│
                                         │  │ Weaver   │  │ Termin Extractor  ││
                                         │  │ (Threads)│  │ (LLM + Regex)    ││
                                         │  └──────────┘  └───────────────────┘│
                                         │                                      │
                                         │  ┌────────────────────────────────┐  │
                                         │  │ Semantic Transcriber (Audio)   │  │
                                         │  │ Groq LLaMA → Gemini Fallback  │  │
                                         │  └────────────────────────────────┘  │
                                         └──────────┬───────────┬──────────────┘
                                                    │           │
                                         ┌──────────▼──┐  ┌────▼──────────┐
                                         │ PostgreSQL   │  │ ChromaDB      │
                                         │ (Nachrichten,│  │ (RAG-Vektoren)│
                                         │  Analysen,   │  │               │
                                         │  Threads,    │  └───────────────┘
                                         │  Termine)    │
                                         └──────────────┘
                                                    │
                                         ┌──────────▼──────────┐
                                         │ Apple iCloud CalDAV  │
                                         │ (Termine → Kalender) │
                                         └─────────────────────┘
```

**Drei Hauptkomponenten:**

| Komponente | Verzeichnis | Technologie | Aufgabe |
|---|---|---|---|
| Chrome Extension | `extension/` | JavaScript (Manifest V3) | Nachrichten von WhatsApp Web erfassen |
| FastAPI Backend | `radar-api/` | Python 3.12, FastAPI | Analyse-Pipeline + REST-API |
| Deployment | `deploy/` | Docker Compose, Caddy | Orchestrierung, HTTPS, Datenbanken |

---

## Architektur

### Nachrichtenfluss (Übersicht)

```
WhatsApp Web → Extension (DOM-Scraping + Whitelist-Filter)
  → POST /api/ingest (Bearer-Auth)
    → PostgreSQL speichern
    → [Audio? → Groq Whisper Transkription]
    → Sentiment-Score berechnen (-1.0 bis +1.0)
    → Marker erkennen (Regex + Embedding, 2-Phasen)
    → RAG-Embedding in ChromaDB speichern
    → Thread-Weaving (semantische Gesprächsfäden)
    → [Audio? → Semantische Transkript-Anreicherung via LLM]
    → Termin-Extraktion (Ollama/Regex)
    → [Termin erkannt? → CalDAV-Sync → Apple Kalender]
```

### Externe Services

| Service | Zweck | Modell |
|---|---|---|
| **Groq** | Audio-Transkription + LLM-Anreicherung | Whisper Large V3 Turbo + LLaMA 3.3 70B |
| **Gemini** | Fallback-LLM | Gemini 2.5 Flash |
| **Ollama** | Lokale Termin-Extraktion | LLaMA 3.1 8B |
| **Apple iCloud** | Kalender-Sync | CalDAV-Protokoll |

---

## Komponenten im Detail

### Chrome Extension

Die Extension läuft auf `web.whatsapp.com` und erfasst Nachrichten ausschließlich von Kontakten auf der Whitelist.

**Dateien:**

| Datei | Aufgabe |
|---|---|
| `manifest.json` | Berechtigungen, Content-Scripts, Service Worker |
| `content.js` | DOM-Scraping der WhatsApp-Oberfläche (Klasse `RadarTracker`) |
| `background.js` | Retry-Queue, Heartbeat, Nachrichtenweiterleitung |
| `queue-manager.js` | Persistente Warteschlange in `localStorage` |
| `popup.html/js/css` | Konfigurations-UI (Server-URL, API-Key, Whitelist) |

**Funktionsweise von `content.js`:**

1. **Initialisierung**: Wartet auf WhatsApp-DOM-Readiness (bis zu 30 Sekunden)
2. **Chat-Erkennung**: 5 Strategien für verschiedene WhatsApp-Web-Versionen:
   - `data-testid="conversation-info-header-chat-title"`
   - `#main header span[title]`
   - `#main header span[dir="auto"]`
   - usw.
3. **Whitelist-Prüfung**: Nur Chats deren Name einen Whitelist-Eintrag enthält (case-insensitive)
4. **MutationObserver**: Beobachtet DOM-Änderungen im `#main` Container
5. **Nachrichten-Extraktion** (6 Strategien pro Feld):
   - Sender, Text, Timestamp aus `data-pre-plain-text` Attribut (primär)
   - Fallback über `aria-label`, `.selectable-text`, `innerText`
6. **Audio-Erfassung**: Erkennt `<audio>`-Elemente, fetcht Blob-URLs, base64-Kodierung
7. **Deduplizierung**: Content-Hash + Message-ID verhindern doppelte Erfassung
8. **Queue**: Nachrichten werden gebatcht (10er-Gruppen) und via `background.js` gesendet

**Retry-Logik (`background.js`):**
- Exponentielles Backoff: 5s → 15s → 1min → 5min
- Max. Queue-Größe: 500 Nachrichten
- Bei 401/403: Nachricht verworfen (Auth-Fehler)
- Bei 5xx: Retry mit Backoff
- Queue überlebt Browser-Neustarts (localStorage-Persistenz)

**Popup-UI:**
- Server-URL + API-Key Konfiguration
- Whitelist-Verwaltung (Kontaktnamen hinzufügen/entfernen)
- Live-Status: Aktiv/Pausiert, aktueller Chat, Queue-Größe, Verbindungsstatus

---

### FastAPI Backend

**Einstiegspunkt:** `radar-api/app/main.py`

Initialisiert FastAPI mit:
- Ingestion-Router (`/api/ingest`, `/api/transcribe`, `/api/heartbeat`)
- Dashboard-Router (Analyse-Endpunkte)
- Health-Check (`/health`)
- Datenbankverbindung (async SQLAlchemy + asyncpg)

**Authentifizierung:** Bearer-Token (`RADAR_API_KEY`) für alle Endpunkte erforderlich.

---

### Analyse-Pipeline

Jede eingehende Nachricht durchläuft folgende Schritte:

#### 1. Sentiment Tracker (`sentiment_tracker.py`)

Berechnet einen emotionalen Tonwert von **-1.0** (sehr negativ) bis **+1.0** (sehr positiv).

**Algorithmus:**
1. Text in Wörter tokenisieren
2. Positive/negative Wort-Treffer zählen (Substring-Matching)
3. Kontext-Modifikatoren anwenden:
   - **Negation** in den vorherigen 2 Wörtern (`nicht`, `kein`, `nie`) → Valenz umkehren
   - **Intensivierer** im vorherigen Wort (`sehr`, `extrem`, `mega`) → 1.5x Multiplikator
4. Score berechnen: `(positive - negative) / gesamt`
5. Label: `"positive"` (>0.15), `"negative"` (<-0.15), `"neutral"` (sonst)

**Wortlisten:** ~35 positive Wörter (lieb, schön, toll, super, danke, ...) und ~35 negative (traurig, wütend, sauer, stress, ...) — spezialisiert auf deutsche Alltagssprache.

#### 2. Marker Engine (`unified_engine.py` + `marker_engine.py`)

Erkennt emotionale und beziehungsrelevante Marker in **zwei Phasen**:

**Phase 1 — Regex (schnell, deterministisch):**
- Kompilierte Muster aus `marker_registry_radar.json`
- Sofortige Erkennung bekannter Schlüsselwörter

**Phase 2 — Embedding-Ähnlichkeit (semantisch, genauer):**
- Sentence-Transformers Modell (`all-MiniLM-L6-v2`, 384 Dimensionen)
- Vergleich gegen vorberechnete Marker-Embeddings
- Konfigurierbarer Schwellenwert pro Marker (Standard: 0.65)
- 100+ granulare Marker (ATO, SEM, CLU, MEMA aus LeanDeep)

**10 Dashboard-Kategorien:**

| Kategorie | Bedeutung | Beispiel-Keywords |
|---|---|---|
| `waerme` | Wärme/Nähe | lieb, schatz, vermiss, kuschel |
| `distanz` | Distanz/Rückzug | brauch zeit, allein, pause |
| `stress` | Druck/Überlastung | stress, überfordert, müde |
| `konflikt` | Konflikt/Spannung | streit, wütend, sauer |
| `freude` | Freude/Begeisterung | super, toll, genial, mega |
| `trauer` | Trauer/Melancholie | traurig, weinen, einsam |
| `fuersorge` | Fürsorge/Anteilnahme | wie geht, pass auf, bin da |
| `planung` | Planung/Zukunft | wollen wir, treffen, termin |
| `dankbarkeit` | Dankbarkeit | danke, dankbar, schätze |
| `unsicherheit` | Unsicherheit | weiß nicht, angst, sorge |

**Ergebnis:**
```json
{
  "dominant": "konflikt",
  "categories": ["konflikt", "stress"],
  "scores": {"konflikt": 0.8, "stress": 0.5},
  "activated_markers": [
    {"id": "SEM_BLAME_SHIFT", "score": 0.95, "method": "embedding"}
  ]
}
```

#### 3. RAG-Embedding & ChromaDB (`rag_store.py`)

Speichert jede Nachricht als Vektor in ChromaDB für spätere Ähnlichkeitssuche.

**Aktueller Stand:**
- Verwendet **Trigram-Hash-Embedding** (`_simple_embed`) — ein einfaches, deterministisches Verfahren auf Zeichenebene (NICHT semantisch)
- 384 Dimensionen, normalisiert auf [-1, 1]
- Cosine-Distanz als Ähnlichkeitsmetrik

> **Hinweis:** Dies ist ein Provisorium. Die Trigram-Hash-Methode findet Nachrichten mit ähnlichen Buchstabenfolgen, versteht aber keine Bedeutung. "Ich bin traurig" und "Mir geht es schlecht" würden als unähnlich eingestuft. Für echte semantische Suche muss auf Sentence-Transformers (wie bereits in `unified_engine.py` verwendet) oder eine Embedding-API umgestellt werden.

#### 4. Semantic Thread Weaver (`weaver.py`)

Erkennt und verfolgt thematische Gesprächsfäden über mehrere Nachrichten hinweg.

**Algorithmus:**
1. Nachricht in ChromaDB einbetten (mit Metadaten: Chat, Sender, Sentiment, Marker)
2. Top-20 ähnliche Nachrichten abfragen
3. Aktive Threads des Chats laden
4. **Thread-Matching:** Überlappung zwischen ähnlichen Nachrichten und Thread-Mitgliedern berechnen
5. Nachricht an Thread mit größter Überlappung anhängen (≥1 Match) oder neuen Thread erstellen
6. **Emotional Arc:** Sentiment-Scores im Thread verfolgen
7. **Spannungserkennung:** Aufeinanderfolgende Sentiment-Abfälle (Δ < -0.1)
8. **Auflösungserkennung:** Sentiment-Erholung nach Tiefpunkt
9. **Dormanz:** Threads werden nach **72 Stunden** Inaktivität als "ruhend" markiert

#### 5. Semantic Transcriber (`semantic_transcriber.py`)

Reichert Audio-Transkriptionen mit Gesprächskontext an (**nur für Audio-Nachrichten**).

**Kontextquellen:**
- Letzte 10 Nachrichten im selben Chat (PostgreSQL)
- 5 ähnliche Nachrichten (ChromaDB RAG)

**LLM-Kette:**
1. Groq LLaMA 3.3 70B (primär, Temperatur 0.2)
2. Gemini 2.5 Flash (Fallback)

**Ergebnis:** Angereicherte Version des Transkripts + Zusammenfassung + Themen + Konfidenz

#### 6. Termin-Extraktion (`termin_extractor.py`)

Erkennt Datum/Uhrzeit-Angaben in deutschen Nachrichten.

**Zwei Stufen:**
1. **Ollama LLaMA 3.1 8B** (wenn verfügbar): LLM extrahiert strukturierte Termine als JSON
2. **Regex-Fallback:** Patterns wie `14.02. um 10:00`, `morgen um 10`

**Pre-Filter:** Nur Nachrichten mit Datums-/Zeit-Keywords werden verarbeitet.

**CalDAV-Sync:** Termine mit Konfidenz ≥ 0.7 werden automatisch als iCal-Events in den Apple Kalender geschrieben, mit 4 Erinnerungen (5 Tage, 2 Tage, 1 Tag, 2 Stunden vorher).

---

### Speicher & Datenbank

#### PostgreSQL — Strukturierte Daten

| Tabelle | Zweck | Wichtige Felder |
|---|---|---|
| `messages` | Rohe Nachrichten | chat_id, sender, text, timestamp, audio_path, is_transcribed |
| `analysis` | Analyse-Ergebnisse | message_id (FK), sentiment_score, markers, marker_categories |
| `threads` | Gesprächsfäden | chat_id, theme, message_ids[], emotional_arc[], status |
| `termine` | Erkannte Termine | title, datetime, participants[], confidence, caldav_uid |
| `capture_stats` | Extension-Gesundheit | chat_id, last_heartbeat, messages_captured_24h, error_count_24h |
| `drift_snapshots` | Sentiment-Trend | chat_id, date, avg_sentiment, dominant_markers, message_count |

#### ChromaDB — Vektor-Speicher

- Collection: `messages`
- Embedding-Dimension: 384
- Metadaten: chat_id, sender, timestamp, sentiment, dominant_marker
- Metrik: Cosine-Distanz

---

### Deployment Stack

```yaml
# docker-compose.yml — 5 Services
caddy:        # HTTPS Reverse-Proxy, Auto-TLS
radar-api:    # Python FastAPI Container
postgres:     # PostgreSQL 16
chromadb:     # ChromaDB 0.5.23 Vektor-DB
ollama:       # Lokale LLMs
```

**Port-Mapping:**

| Service | Intern | Extern |
|---|---|---|
| Caddy | 80/443 | 80/443 (öffentlich) |
| radar-api | 8000 | 8900 (Host) |
| PostgreSQL | 5432 | — (nur intern) |
| ChromaDB | 8000 | — (nur intern) |
| Ollama | 11434 | — (nur intern) |

---

## Nachrichtenfluss (End-to-End)

### Beispiel: Textnachricht "Ich vermisse dich"

```
1. Extension: DOM-Scraping → {sender: "Marike", text: "Ich vermisse dich", chat: "Marike"}
2. Whitelist-Check: "Marike" ✓ → in Queue
3. background.js → POST /api/ingest

4. Backend:
   a) Message in PostgreSQL speichern (id: abc-123)
   b) Sentiment: score=0.65 (positiv, "vermiss" → wärme)
   c) Marker: dominant="waerme", categories=["waerme"]
   d) RAG: Embedding in ChromaDB + Query ähnliche Nachrichten
   e) Thread: Ähnlich zu bisherigem "waerme"-Thread → anhängen
   f) Termin: Keine Datums-Keywords → übersprungen
   g) Analysis in PostgreSQL speichern

5. Response: {accepted: 1, errors: 0}
```

### Beispiel: Sprachnachricht mit Termin

```
1. Extension: <audio>-Element erkannt → Blob fetchen → base64
2. POST /api/ingest mit {hasAudio: true, audioBlob: "base64..."}

3. Backend:
   a) Groq Whisper: "Können wir uns Samstag um 15 Uhr treffen?"
   b) Message in PostgreSQL (is_transcribed: true)
   c) Sentiment: score=0.2 (neutral-positiv, "treffen" → planung)
   d) Marker: dominant="planung"
   e) Semantic Transcriber:
      - Kontext: letzte 10 Nachrichten + 5 ähnliche
      - LLM-Anreicherung: "Möchte sich Samstag um 15 Uhr treffen"
   f) Termin-Extraktion: "Samstag um 15:00" → {title: "Treffen", datetime: "2026-02-21T15:00"}
   g) CalDAV-Sync: iCal-Event erstellt (Konfidenz 0.75 ≥ 0.7)
   h) 4 Erinnerungen gesetzt
```

---

## API-Referenz

### Ingestion

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/api/ingest` | POST | Nachrichten-Batch von Extension |
| `/api/transcribe` | POST | Standalone Audio-Transkription + Anreicherung |
| `/api/heartbeat` | POST | Extension-Heartbeat mit Capture-Statistiken |

### Dashboard & Analyse

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/api/overview/{chat_id}` | GET | Zusammenfassung (Nachrichten, Sentiment, Threads, Termine) |
| `/api/drift/{chat_id}` | GET | Sentiment-Verlauf über Zeit (tägliche Durchschnitte) |
| `/api/markers/{chat_id}` | GET | Marker-Verteilung als Heatmap |
| `/api/threads/{chat_id}` | GET | Semantische Gesprächsfäden |
| `/api/termine/{chat_id}` | GET | Erkannte Termine |
| `/api/search?q=query` | GET | RAG-basierte semantische Suche |
| `/api/communication-pattern/{chat_id}` | GET | Wochentag × Stunde Heatmap |
| `/api/response-times/{chat_id}` | GET | Antwortzeiten pro Sender |
| `/api/capture-stats` | GET | Extension-Gesundheit aller Chats |
| `/api/status` | GET | Service-Gesundheit (Whisper, LLM, ChromaDB, CalDAV) |

### System

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/health` | GET | Einfacher Health-Check |
| `/dashboard` | GET | Statisches Dashboard-Frontend |

Alle Endpunkte (außer `/health`) erfordern `Authorization: Bearer <API_KEY>`.

---

## Kontextverständnis — Analyse & Schwachstellen

### Das Problem anhand eines Beispiels

Marike schreibt:
> **"Kannst du an ihrem Geburtstag noch Süßigkeiten-Tüten für ihre Gäste mitbringen?"**

Um diese Nachricht korrekt zu verstehen, muss das System wissen:
1. **Wer ist "ihrem"?** → Romy (Tochter)
2. **Wann ist der Geburtstag?** → 18. Februar
3. **Wann findet die Feier statt?** → 21. Februar (nicht am eigentlichen Geburtstag!)
4. **Wie viele Gäste?** → Aus vorherigen Gesprächen bekannt
5. **Was sind "Süßigkeiten-Tüten"?** → Mitgebsel für Kindergeburtstag

Dieses Wissen stammt aus **Wochen an Konversation** — nicht aus dieser einzelnen Nachricht.

### Aktueller Stand der Kontextverarbeitung

| Fähigkeit | Status | Details |
|---|---|---|
| Einzelnachricht-Sentiment | ✅ Funktioniert | Wortlisten-basiert, mit Negation + Intensivierern |
| Marker-Erkennung | ✅ Funktioniert | 2-Phasen (Regex + Embedding), 100+ Marker |
| Audio-Transkription | ✅ Funktioniert | Groq Whisper mit Gemini-Fallback |
| Thread-Gruppierung | ⚠️ Begrenzt | Basiert auf Trigram-Ähnlichkeit, nicht semantisch |
| Audio-Kontextanreicherung | ⚠️ Begrenzt | Nur 10 letzte Nachrichten + 5 "ähnliche" |
| **Pronomen-Auflösung** | ❌ Fehlt | "ihrem" → wer? System hat keine Ahnung |
| **Entitäten-Tracking** | ❌ Fehlt | Keine Wissensbasis über Personen, Beziehungen, Fakten |
| **Temporales Reasoning** | ❌ Fehlt | "Geburtstag am 18." vs "Feier am 21." nicht unterscheidbar |
| **Tagesübergreifender Kontext** | ❌ Fehlt | Kein Gedächtnis über Tage/Wochen hinweg |
| **Implizites Wissen** | ❌ Fehlt | "Mitgebsel" → Kindergeburtstag-Konvention |
| **Textnachricht-Kontextanreicherung** | ❌ Fehlt | Nur Audio-Nachrichten bekommen LLM-Kontext |

### Detaillierte Schwachstellen

#### 1. RAG-Embedding ist NICHT semantisch

Die aktuelle Implementierung in `rag_store.py` verwendet **Trigram-Character-Hashing** statt echter semantischer Embeddings:

```python
# rag_store.py — _simple_embed()
for i in range(len(text) - 2):
    trigram = text[i:i+3]
    h = hash(trigram) % EMBED_DIM
    vec[h] += 1.0
```

**Auswirkung:** "Ich bin traurig" und "Mir geht es schlecht" werden als **unähnlich** eingestuft, obwohl sie semantisch identisch sind. Die gesamte "semantische" Ähnlichkeitssuche, auf der der Weaver und die Kontextsuche basieren, ist faktisch eine Zeichenketten-Ähnlichkeitssuche.

**Lösung:** `sentence-transformers` (bereits als Dependency installiert und in `unified_engine.py` genutzt) für RAG-Embeddings verwenden.

#### 2. Kein Entitäten-/Wissensmodell

Das System hat **keine Wissensbasis** über:
- **Personen:** Wer ist Romy? Wer ist "sie"? Familienbeziehungen
- **Fakten:** Geburtstage, Adressen, Vorlieben, Gewohnheiten
- **Ereignisse:** Geplante Feiern, wiederkehrende Termine, Absprachen
- **Beziehungsgraph:** Marike → Mutter von → Romy; Ben → Partner von → Marike

Ohne dieses Wissen ist eine korrekte Interpretation impliziter Referenzen unmöglich.

#### 3. Kontextfenster zu klein und nur für Audio

Die semantische Anreicherung (`semantic_transcriber.py`) wird **nur für Audio-Nachrichten** aufgerufen und nutzt:
- 10 letzte Nachrichten (nur Chat-Verlauf, ohne Analyse)
- 5 "ähnliche" Nachrichten (basierend auf Trigram-Hash, nicht semantisch)

**Auswirkung:** Textnachrichten — der Großteil aller Nachrichten — bekommen keinerlei kontextuelle Anreicherung. Der Termin-Extraktor sieht nur den Rohtext ohne Kontext.

#### 4. Thread-Weaving ohne kausale Verknüpfung

Der Weaver gruppiert Nachrichten nach Oberflächen-Ähnlichkeit (Trigram-Overlap), nicht nach kausaler Beziehung. Eine Kette wie:

```
Tag 1: "Romy hat nächste Woche Geburtstag"
Tag 3: "Sollen wir die Feier am Samstag machen?"
Tag 5: "Kannst du Süßigkeiten-Tüten mitbringen?"
```

Würde möglicherweise **nicht** als zusammenhängender Thread erkannt, weil die Texte auf Zeichenebene zu unterschiedlich sind.

#### 5. Keine temporale Logik

Der Termin-Extraktor erkennt explizite Daten (`14.02. um 10:00`), hat aber kein Verständnis für:
- "An ihrem Geburtstag" → Welches Datum?
- "Die Feier" → Welcher Termin? Geburtstag ≠ Feier-Datum
- "Nächsten Samstag" → Relativ zu wann?
- Unterschied zwischen Geburtstag (18.02.) und Geburtstagsfeier (21.02.)

---

## Vorgeschlagene Lösung: Kontextgedächtnis

### Architektur-Konzept: "Chat-Gehirn"

Um das Marike/Romy-Problem zu lösen, braucht das System ein **persistentes, strukturiertes Kontextgedächtnis** — ein "Chat-Gehirn" pro Beziehung.

```
┌─────────────────────────────────────────────────────────┐
│                    KONTEXTGEDÄCHTNIS                     │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ Personen-     │  │ Fakten-      │  │ Ereignis-     │ │
│  │ Register      │  │ Speicher     │  │ Zeitleiste    │ │
│  │               │  │              │  │               │ │
│  │ Romy          │  │ Romys Geb:   │  │ 18.02 Romys   │ │
│  │ → Tochter     │  │   18.02.     │  │   Geburtstag  │ │
│  │ → 6 Jahre     │  │ Feier: 21.02 │  │ 21.02 Feier   │ │
│  │ → Geb: 18.02  │  │ Gäste: 8     │  │   8 Gäste     │ │
│  │               │  │ Ort: zuhause  │  │   Zuhause     │ │
│  │ Marike        │  │              │  │ 22.02 Aufräumen│ │
│  │ → Partnerin   │  │ Ben mag kein │  │               │ │
│  │               │  │   Koriander  │  │               │ │
│  └──────────────┘  └──────────────┘  └───────────────┘ │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Aktiver Kontext (letzte 7 Tage, gewichtet)         ││
│  │ → "Romys Geburtstagsfeier am 21.02., 8 Kinder,    ││
│  │    Motto: Einhorn, Ort: Zuhause, Mitgebsel nötig"  ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Umsetzungs-Vorschlag

#### Schritt 1: Basis-Kontext aus Chat-Export

Der Nutzer kann einen **WhatsApp Chat-Export** (Textdatei) hochladen. Ein LLM erstellt daraus einen strukturierten Basis-Kontext:

```
POST /api/context/init
Body: { "chat_id": "marike", "export_text": "..." }

→ LLM extrahiert:
  - Alle erwähnten Personen + Beziehungen
  - Wichtige Fakten (Geburtstage, Vorlieben, Adressen)
  - Wiederkehrende Themen
  - Wichtige Ereignisse der Vergangenheit
```

Dieser Basis-Kontext wird als strukturiertes JSON in einer neuen `context_memory` Tabelle gespeichert.

#### Schritt 2: Laufende Aktualisierung

Bei jeder neuen Nachricht:
1. **Entitäten-Extraktion** (NER): Personen, Orte, Daten, Beziehungen
2. **Fakten-Update**: Neue Fakten zum Kontext hinzufügen, veraltete aktualisieren
3. **Referenz-Auflösung**: "ihrem" → Kontext durchsuchen → Romy (wahrscheinlichster Bezug)
4. **Termin-Kontext**: Extrahierte Termine mit Kontextwissen anreichern

#### Schritt 3: Kontextgestützte Analyse

Jede Analyse-Stufe bekommt den aktuellen Kontext als Eingabe:

```python
# Beispiel: Termin-Extraktion mit Kontext
context = await get_chat_context(chat_id)  # Personen, Fakten, Ereignisse
termine = await extract_termine_with_context(text, sender, timestamp, context)

# LLM-Prompt:
# "Kontext: Romys Geburtstag ist am 18.02., die Feier am 21.02., 8 Gäste eingeladen.
#  Nachricht: 'Kannst du an ihrem Geburtstag noch Süßigkeiten-Tüten für ihre Gäste mitbringen?'
#  → Termin: 21.02. (Feier, nicht Geburtstag), Aufgabe: Süßigkeiten-Tüten für 8 Gäste"
```

### EverMemOS als mögliche Lösung

[EverMemOS](https://github.com/EverMind-AI/EverMemOS) ist ein Open-Source "Memory Operating System" von EverMind, das genau für diesen Anwendungsfall entwickelt wurde:

**Relevante Fähigkeiten:**

| Feature | Relevanz für Beziehungs-Radar |
|---|---|
| **MemCells** (atomare Wissenseinheiten) | Fakten wie "Romys Geburtstag = 18.02." als einzelne, referenzierbare Einheiten |
| **Hierarchisches Gedächtnis** | Episoden → Profile → Beziehungen → Fakten → Kern-Erinnerungen |
| **Hybrid-Retrieval** (BM25 + semantisch) | Kombiniert Keyword- und Bedeutungssuche für Kontext-Abruf |
| **Agentic Multi-Round Recall** | Generiert 2-3 komplementäre Suchanfragen für komplexe Kontexte |
| **Lebende Profile** | Dynamisch aktualisierte Personenprofile (Romy, Marike, etc.) |
| **MCP-Integration** | Kann als externes Tool an LLMs angebunden werden |
| **93% Genauigkeit** (LoCoMo-Benchmark) | Hohe Trefferquote bei komplexen Kontextfragen |

**Bewertung für Beziehungs-Radar:**

EverMemOS wäre eine sehr gute Basis für das Kontextgedächtnis, weil es:
- Bereits die harte Arbeit der Wissensstrukturierung übernimmt
- Profil-Aktualisierungen über Zeit hinweg automatisch handhabt
- Semantisches + Keyword-basiertes Retrieval kombiniert
- Open-Source ist und selbst-gehostet werden kann

**Einschränkungen:**
- Zusätzliche Infrastruktur (eigener Service)
- Muss an die Pipeline angebunden werden (neuer Analyse-Schritt)
- Deutschsprachige Inhalte müssen getestet werden

**Alternative: Eigene Lösung**

Eine schlankere Alternative wäre ein eigenes `context_memory`-Modul mit:
1. PostgreSQL-Tabelle für strukturierte Fakten (Personen, Daten, Beziehungen)
2. LLM-basierte Extraktion bei jedem Nachrichteneingang
3. Kontext-Injection in alle Analyse-Schritte
4. Periodische Kontext-Zusammenfassung (Daily Digest)

### Empfohlene Prioritäten

| Priorität | Maßnahme | Aufwand | Wirkung |
|---|---|---|---|
| **1** | RAG-Embeddings auf Sentence-Transformers umstellen | Niedrig | Hoch — sofort bessere Ähnlichkeitssuche |
| **2** | Textnachrichten ebenfalls kontextuell anreichern | Mittel | Hoch — 90% der Nachrichten profitieren |
| **3** | Chat-Export → Basis-Kontext Endpunkt | Mittel | Sehr hoch — initiales Weltwissen |
| **4** | Entitäten-Extraktion + Fakten-Speicher pro Chat | Hoch | Sehr hoch — Pronomen-Auflösung, Personenwissen |
| **5** | EverMemOS evaluieren/integrieren | Hoch | Sehr hoch — professionelles Kontextgedächtnis |

---

## Installation & Entwicklung

### Voraussetzungen

- Python 3.12+
- Node.js (für Extension-Entwicklung, optional)
- Docker & Docker Compose (für Deployment)
- Chrome Browser (für Extension)

### Lokale Entwicklung (API)

```bash
cd radar-api

# Dependencies installieren
pip install -r requirements.txt

# PostgreSQL + ChromaDB müssen laufen
# Alternativ: docker compose up postgres chromadb -d (im deploy/ Verzeichnis)

# API starten
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# API-Dokumentation
open http://localhost:8000/docs
```

### Extension laden

```bash
# In Chrome:
# 1. chrome://extensions/ öffnen
# 2. "Entwicklermodus" aktivieren
# 3. "Entpackte Erweiterung laden" → extension/ Verzeichnis wählen

# Konfiguration im Extension-Popup:
# - Server URL: http://localhost:8900 (oder Produktions-Domain)
# - API Key: Wert von RADAR_API_KEY
# - Whitelist: Kontaktnamen hinzufügen
```

### Produktions-Deployment

```bash
cd deploy

# Ersteinrichtung (Oracle Cloud ARM VM)
bash setup.sh

# Umgebungsvariablen konfigurieren
cp .env.template .env
nano .env  # Alle RADAR_* Variablen setzen

# Stack starten
docker compose up -d

# Logs überwachen
docker compose logs -f radar-api

# Ollama-Modelle laden (optional)
docker compose exec ollama ollama pull llama3.1:8b

# Health-Check
curl https://your-domain.de/health
```

### Datenbank

```bash
# PostgreSQL-Shell
docker compose exec postgres psql -U radar -d radar

# Letzte Nachrichten anzeigen
SELECT chat_name, sender, text, timestamp
FROM messages ORDER BY timestamp DESC LIMIT 10;

# Analyse-Ergebnisse
SELECT m.sender, m.text, a.sentiment_score, a.marker_categories->>'dominant' as marker
FROM messages m JOIN analysis a ON a.message_id = m.id
ORDER BY m.timestamp DESC LIMIT 10;

# Aktive Threads
SELECT theme, status, array_length(message_ids, 1) as msg_count
FROM threads WHERE status = 'active';
```

---

## Konfiguration

Alle Einstellungen verwenden den Prefix `RADAR_` (siehe `radar-api/app/config.py`):

| Variable | Typ | Standard | Beschreibung |
|---|---|---|---|
| `RADAR_API_KEY` | str | "changeme" | Bearer-Token für Authentifizierung |
| `RADAR_DATABASE_URL` | str | postgresql+asyncpg://... | PostgreSQL-Verbindung |
| `RADAR_GROQ_API_KEY` | str | "" | Groq API-Key (Whisper + LLM) |
| `RADAR_GEMINI_API_KEY` | str | "" | Gemini Fallback-LLM |
| `RADAR_CHROMADB_URL` | str | http://chromadb:8000 | ChromaDB-Endpunkt |
| `RADAR_OLLAMA_URL` | str | http://ollama:11434 | Lokales LLM |
| `RADAR_OLLAMA_MODEL` | str | llama3.1:8b | Ollama-Modell |
| `RADAR_CALDAV_URL` | str | "" | iCloud CalDAV-Server |
| `RADAR_CALDAV_USERNAME` | str | "" | iCloud-E-Mail |
| `RADAR_CALDAV_PASSWORD` | str | "" | App-spezifisches Passwort |
| `RADAR_CALDAV_CALENDAR` | str | Beziehungs-Radar | Kalender-Name |
| `RADAR_DOMAIN` | str | radar.localhost | Öffentliche Domain |

### Extension-Konfiguration

Wird in Chromes `chrome.storage.local` gespeichert (über Popup-UI):

- **Server URL** — Backend-Adresse
- **API Key** — Bearer-Token
- **Whitelist** — Array von Kontaktnamen
- **Capture Enabled** — Boolean für Aktivierung/Deaktivierung
