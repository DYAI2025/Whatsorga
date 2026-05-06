# Konzept: Universal Context Capture — Semantische Kontexterfassung über WhatsApp hinaus

**Version:** 1.0 — Mai 2026  
**Status:** Konzept / Machbarkeitsbewertung

---

## 1. Ausgangslage

WhatsOrga liest heute genau eine Quelle: WhatsApp-Nachrichten via Browser-Extension. Die semantische Infrastruktur (EverMemOS, Termin-Extraktion, Embedding-Pipeline) ist aber source-agnostisch — sie versteht Kontext, Personen, Ereignisse.

Die Frage: Kann das System auch andere Bildschirminhalte miterfassen, diese kontextbezogen speichern und über Zeit semantisch verknüpfen?

---

## 2. Erweiterte Quellen — Kategorien

### 2a. Weitere Messaging-Apps (hohe Machbarkeit)
Signal, Telegram, iMessage, Slack, Teams — alle haben Web-Clients oder Desktop-Apps mit inspizierb­arem DOM.

**Mechanismus:** Gleiche Extension-Architektur wie WhatsApp. `content.js` als Source-Adapter pro App.  
**Aufwand:** Mittel — jede App hat andere DOM-Struktur, aber die Pipeline dahinter ist identisch.

### 2b. Browser-Kontext: gelesene Artikel, geöffnete Tabs (mittlere Machbarkeit)
Was der Nutzer im Browser liest, beeinflusst seinen Kontext.

**Mechanismus:** Content-Script auf allen Tabs (`<all_urls>`), das gelesene Artikel extrahiert (Haupttext via `Readability.js` o.ä.), den Tab-Titel und URL mitschickt.  
**Datenmenge:** Hoch — jede Seite wäre ein Event. Notwendig: aggressive Filterung (nur bei relevanten Domains, nur bei >30s Verweildauer).

### 2c. Desktop-Screen-Content (niedrige bis mittlere Machbarkeit)
Alle Bildschirminhalte — Dokumente, E-Mails, Kalender, andere Apps.

Hier gibt es zwei grundlegend verschiedene Mechanismen:

**Option A — Screen-OCR (Low-Level):**  
Regelmäßige Screenshots + OCR (Tesseract oder Cloud Vision). Funktioniert für alle Apps.  
Problem: Datenmenge, Datenschutz, Latenz, hoher Compute-Bedarf.

**Option B — Betriebssystem-Accessibility-APIs (High-Level):**  
macOS Accessibility API, Windows UI Automation, AT-SPI (Linux) liefern strukturierten Text direkt aus der UI-Hierarchie — ohne OCR.  
Das ist dieselbe Schnittstelle, die Screen-Reader nutzen.

---

## 3. Architektur: Universal Context Capture

```
┌─────────────────────────────────────────────────────┐
│              CAPTURE LAYER                          │
├─────────────────┬───────────────┬───────────────────┤
│ Browser Extension│ Native Agent  │  Screen-OCR       │
│ (WhatsApp, Slack,│ (macOS/Win   │  (Fallback für     │
│  Telegram, Web)  │  Accessibility│   Legacy-Apps)    │
│                  │  API)         │                   │
└────────┬─────────┴───────┬───────┴──────────────────┘
         │                 │
         ▼                 ▼
┌─────────────────────────────────────────────────────┐
│           INGEST ROUTER (radar-api)                 │
│  POST /api/ingest  ←  unified payload               │
│  source: "whatsapp" | "browser" | "screen" | "mail" │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│           ANALYSIS PIPELINE (bestehend)             │
│  EverMemOS memorize() → Termin-Extraktion →        │
│  Marker-Erkennung → Sentiment → ChromaDB           │
└─────────────────────────────────────────────────────┘
```

**Schlüsselprinzip:** Die bestehende Pipeline braucht keine Änderung. Nur der Ingest-Payload bekommt ein `source`-Feld — alle anderen Verarbeitungsschritte sind source-agnostisch.

---

## 4. Native Agent: macOS Accessibility API

### Technischer Ansatz

```python
# Beispiel: macOS Accessibility via pyobjc
from ApplicationServices import AXUIElementCreateApplication
from AppKit import NSWorkspace

def get_frontmost_window_text():
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = app.processIdentifier()
    ax_app = AXUIElementCreateApplication(pid)
    # Rekursiv alle AXStaticText-Elemente traversieren
    return extract_text_recursive(ax_app)
```

**Was damit erreichbar ist:**
- Geöffnete E-Mails in Apple Mail / Outlook (Betreff + Body)
- Kalendereinträge in Fantastical / Apple Calendar
- Dokumente in Pages / Word (sichtbarer Bereich)
- Notizen in Bear, Notes, Obsidian
- Slack/Teams Desktop-Client
- Beliebige andere native Apps

**Voraussetzungen macOS:** App muss Accessibility-Berechtigung haben (`System Preferences → Privacy → Accessibility`). Das ist eine explizite Nutzergenehmigung.

**Voraussetzungen Windows:** UI Automation API via `pywinauto` oder COM-Interop. Gleiches Berechtigungsmodell.

### Sampling-Strategie

Nicht kontinuierlich pollen — das wäre zu laut. Stattdessen event-getrieben:

```
Trigger-Events:
- Fensterwechsel (neues Fenster im Vordergrund)
- Clipboard-Änderung (Nutzer kopiert Text)
- Timer: alle 60s Snapshot des aktiven Fensters
- Idle-Ende: nach >5min Pause, erster Tastendruck → Snapshot
```

### Datenmenge & Filterung

Rohtext aus allen Apps wäre zu viel. Notwendige Filter-Kaskade:

1. **App-Whitelist:** Nur konfigurierte Apps (Mail, Calendar, Messaging)
2. **Deduplizierung:** Hash des extrahierten Texts — gleicher Text innerhalb 10min → skip
3. **Minimum-Relevanz:** Weniger als 20 Wörter → skip (Toolbar-Labels, Menüs)
4. **Domänen-Classifier:** Schnelles ML-Modell (DistilBERT, quantized) klassifiziert: appointment | personal | work | irrelevant
5. **Confidence-Gate:** Nur bei `relevance > 0.6` an die Pipeline weiterleiten

---

## 5. Screen-OCR als Fallback

Für Apps ohne Accessibility-API (z.B. Electron-Apps mit blocked DOM, legacy Software):

```
macOS Screenshot API → PIL/Pillow → Tesseract OCR → Textextraktion
```

**Realistische Latenz:** 1-3s pro Screenshot  
**Kosten auf M-Serie Mac:** ~2-5% CPU bei 1 Screenshot/10s  
**Qualität:** 85-95% Genauigkeit für klaren Desktop-Text

**Wann nicht nutzen:** Für Webinhalte (Browser-Extension besser), für native Apps mit Accessibility-API.

---

## 6. Semantische Verknüpfung über Zeit

Das ist der eigentlich interessante Teil. EverMemOS übernimmt bereits:
- Persistente Episoden (was wann passiert ist)
- Personenprofile (wer ist wer, Beziehungen)
- Semantische Fakten (was wurde gesagt/gelesen)

**Was hinzukommt mit mehreren Quellen:**

### Cross-Source Entity Resolution
"Marike" in WhatsApp = `marike@example.com` in Apple Mail = Kontakt "Marike Stucke" in Apple Calendar.  
EverMemOS verbindet diese über den `sender`/`user_id` Key.

### Temporal Knowledge Graph
Über Zeit entsteht ein Graph:
- Montag 14:00: WhatsApp "Training fällt aus"
- Montag 14:01: Kalender "Enno Training" → soll das geändert werden?
- Dienstag 09:00: E-Mail "Trainingsplan nächste Woche"
→ EverMemOS verknüpft alle drei als dasselbe Thema

### Proaktive Kontextanreicherung
Wenn EverMemOS beim Termin-Recall jetzt auch Browser- und E-Mail-Kontext enthält:
"Arzttermin Donnerstag" aus WhatsApp wird angereichert mit:
- E-Mail-Kontext: "Reminder: Laborwerte mitbringen"
- Browser-History: "Arztbewertung gelesen"
→ Vollständigerer Termin ohne manuelles Tippen

---

## 7. Datenschutz & Privacy — Kritische Bewertung

### Risiken (ehrliche Einschätzung)

Ein System das alle Bildschirminhalte liest, ist ein **erhebliches Datenschutzrisiko**:

| Risiko | Schwere | Mitigation |
|---|---|---|
| Passwörter im Browser/Terminal werden gelesen | KRITISCH | App-Blacklist: Terminal, Password-Manager, Browser-URL-Bar |
| Fremde PII (Kontakte, Kunden) landet in EverMemOS | HOCH | PII-Scrubbing vor Speicherung |
| Sensible Arbeitsdokumente in Cloud-Memory | HOCH | On-premise only; kein Cloud-Speicher ohne explizite Freigabe |
| Nutzungsdaten für Dritte sichtbar (API-Keys) | MITTEL | Lokaler EverMemOS-Stack (bereits gegeben) |
| Missbrauch durch Malware (Screen-Scraper-Backdoor) | MITTEL | Code-Signierung, Betriebssystem-Permissions |

### Prinzipien für sichere Implementierung

1. **Local-first:** EverMemOS läuft lokal (bereits so). Kein Screen-Inhalt verlässt das Gerät außer für LLM-Calls.
2. **Explizite App-Whitelist statt Blacklist:** Nur explizit freigegebene Apps werden gelesen.
3. **PII-Scrubbing:** E-Mail-Adressen, Telefonnummern, Kreditkartennummern werden vor der Speicherung gehasht/entfernt.
4. **Transparenz-Log:** Jedes Capture-Event wird in einem lokalen Audit-Log festgehalten.
5. **Nutzer-Kontrolle:** Explizites Dashboard "Was wurde heute gelesen?" mit Delete-Option.

---

## 8. Machbarkeitsbewertung

| Ansatz | Machbarkeit | Aufwand | Risiko | Empfehlung |
|---|---|---|---|---|
| **Weitere Chat-Apps** (Signal, Telegram Web) | ★★★★★ Sehr hoch | Gering — gleiche Extension-Architektur | Niedrig | Sofort umsetzen |
| **Browser-Artikel-Kontext** | ★★★★☆ Hoch | Mittel — Readability.js + Relevanz-Filter | Mittel | Kurzfristig (3-6M) |
| **macOS Accessibility API** | ★★★★☆ Hoch | Mittel — Python Agent, Berechtigungen | Mittel-hoch | Mittelfristig (6-12M) |
| **Windows Accessibility** | ★★★☆☆ Mittel | Hoch — andere API, schlechtere Docs | Mittel-hoch | Nach macOS |
| **Screen-OCR (vollständig)** | ★★★☆☆ Mittel | Hoch — OCR-Pipeline, Noise | Hoch | Nur als Fallback |
| **Alle Bildschirminhalte 24/7** | ★★☆☆☆ Niedrig | Sehr hoch | Sehr hoch | Nicht empfohlen |

### Warum "Alle Bildschirminhalte 24/7" nicht empfohlen wird

Die technische Machbarkeit ist gegeben. Die fundamentale Frage ist eine andere:

**Wann ist Kontext nützlich vs. invasiv?**

Ein System das ALLES liest, erzeugt Signal-Rauschen: 80% der Bildschirminhalte haben keinen Bezug zu Terminen, Familien-Logistik oder dem eigentlichen Use-Case. Das degradiert die Qualität von EverMemOS (mehr Noise als Signal).

**Besser:** Zielgerichtetes Capture mit hohem Signal-Rausch-Verhältnis:
- Chat-Apps: fast 100% relevant
- E-Mail: ~40-60% relevant (gefiltert nach Adressaten)
- Kalender: ~80% relevant
- Browser: ~10-20% relevant (nur Artikel, keine Formulare)
- Beliebiger Screen-Inhalt: ~5-10% relevant

---

## 9. Empfohlener Implementierungsplan

### Phase 1 — Quick Wins (0-3 Monate)
**Weitere Chat-Apps als Extension-Adapter**

```
extension/
  adapters/
    whatsapp.js    (bestehend)
    telegram.js    (neu)
    signal.js      (neu — Signal Desktop hat Web-App)
```

Jeder Adapter implementiert:
```javascript
export function extractMessages(container) → [{sender, text, timestamp, chatId}]
export function isOurApp(url) → boolean
```

**Aufwand:** 1-2 Wochen pro App  
**Nutzen:** Sofortige Erweiterung auf alle Chat-Quellen

### Phase 2 — Browser-Kontext (3-6 Monate)
**Artikel-Capture mit Relevanz-Filter**

```javascript
// content.js auf allen URLs
if (timeOnPage > 30000 && articleText.length > 500) {
  ingestContent({
    source: "browser",
    url: location.href,
    title: document.title,
    text: readabilityExtract(document),
    timestamp: new Date().toISOString()
  });
}
```

Neue Backend-Logik:
- `source: "browser"` → EverMemOS-only, kein Termin-Extractor (Browser-Inhalte sind selten Termine)
- Nur Embedding + Speicherung für spätere Recall-Anreicherung

### Phase 3 — Native Agent (6-12 Monate)
**macOS Accessibility Agent als separater Service**

```
deploy/docker-compose.yml:
  context-agent:        # Neuer Service (Python, läuft auf Host)
    build: ./context-agent
    volumes:
      - /tmp/context-pipe:/pipe   # Unix-Socket zu radar-api
    environment:
      - RADAR_API_KEY=${RADAR_API_KEY}
      - CAPTURE_APPS=Mail,Calendar,Notes
```

Der Context-Agent läuft direkt auf dem macOS-Host (nicht in Docker, da Accessibility-API Zugriff auf Host-UI braucht). Er sendet Captures über den lokalen API-Endpunkt.

---

## 10. Fazit

Die bestehende WhatsOrga-Architektur ist hervorragend geeignet für Universal Context Capture:
- Die Pipeline ist source-agnostisch (schon jetzt)
- EverMemOS verknüpft Quellen natürlich über Entity-Resolution
- Die Ingest-API braucht nur ein `source`-Feld

**Hauptbeschränkung ist nicht Technik, sondern Signal-Qualität und Privacy.**  
Die empfohlene Strategie ist schrittweises Erweitern auf hochwertige Quellen (Chat-Apps → E-Mail → Kalender → Browser) statt einem monolithischen "lese alles"-Ansatz.

Ein vollständiger Screen-OCR-Ansatz ist technisch machbar aber praktisch kontraproduktiv: der Noise-Anteil wäre zu hoch um die Qualität der Termin-Extraktion und Recall-Präzision aufrecht zu erhalten.
