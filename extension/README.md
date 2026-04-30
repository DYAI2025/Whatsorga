# WhatsOrga Extension

![extension-ci](https://github.com/DYAI2025/Whatsorga/actions/workflows/extension-ci.yml/badge.svg?branch=main)

Captures messages from whitelisted contacts on WhatsApp Web and forwards them to a
self-hosted radar-api server. Designed to never lose a captured message.

## Requirements

- Chrome 122 or later (content-script ES modules + `chrome.storage.session`).
- A reachable radar-api with a valid `RADAR_API_KEY`.

## Install (developer)

1. Clone the repo, then `cd extension && npm install`.
2. In Chrome, open `chrome://extensions/`, enable Developer mode, click **Load unpacked**, pick this directory.
3. Click the WhatsOrga icon, paste the server URL (e.g. `http://localhost:8900`) and the API key. The dot under the Save button turns green when `/health` responds.
4. Add the WhatsApp display name(s) you want captured to the whitelist.

## Architecture

```text
content.js (WhatsApp Web tab)
   │  scrape DOM, dedup via src/lib/dedup
   ▼
chrome.runtime.sendMessage({type:'NEW_MESSAGES', data:[...]})
   ▼
background.js (MV3 service worker, type:"module")
   │  createRouter() — composes config + queue + transport + retry
   ▼
fetch POST /api/ingest        ↘   on failure  → enqueue to chrome.storage.session
   │                              schedule chrome.alarms.create('whatsorga_retry')
   ▼
radar-api → Postgres → GBrain bridge → Obsidian vault
```

Heartbeat: a 1-minute `chrome.alarms` tick flushes per-chat counters via parallel `POST /api/heartbeat`.

## Module map

| Module                   | Public API                                      | Owns               |
|--------------------------|-------------------------------------------------|--------------------|
| `src/lib/url.js`         | `normalizeServerUrl`, `isValidServerUrl`        | URL hygiene        |
| `src/lib/storage.js`     | `createStorage(area)`                           | typed storage      |
| `src/lib/config.js`      | `loadConfig`, `saveConfig`, `isConfigured`      | config schema      |
| `src/lib/queue.js`       | `createQueue(key,{maxSize})`                    | durable FIFO       |
| `src/lib/transport.js`   | `sendBatch`                                     | HTTP + timeouts    |
| `src/lib/retry.js`       | `backoffMinutes`, `scheduleRetry`, `clearRetry` | alarm-based timer  |
| `src/lib/heartbeat.js`   | `runHeartbeat`                                  | periodic flush     |
| `src/lib/dedup.js`       | `createDedup`                                   | rolling window     |
| `src/lib/router.js`      | `createRouter`                                  | orchestration      |

## Storage map

| Area      | Key                              | Owner       | Purpose                                | Survives  |
|-----------|----------------------------------|-------------|----------------------------------------|-----------|
| `local`   | `whatsorga_config_v1`            | popup       | serverUrl, apiKey, whitelist, enabled  | restart   |
| `local`   | `sentMessageIds_v2`              | content.js  | rolling 5000-id dedup window           | restart   |
| `local`   | `heartbeatCounts`                | background  | per-chat counters                      | restart   |
| `session` | `whatsorga_send_queue`           | router      | FIFO queue of failed batches           | session   |
| `session` | `whatsorga_send_queue__dropped`  | router      | counter of evicted batches             | session   |
| `session` | `whatsorga_retry_attempt`        | router      | exponential backoff index              | session   |

`chrome.storage.session` is capped at 10 MB. The router enforces both `QUEUE_MAX = 200` batches and `QUEUE_MAX_BYTES = 8 MB` of serialized payload — whichever evicts first. Audio messages (~100 KB each) hit the byte cap before the count cap, so dropped messages always reflect a real storage-pressure event surfaced via `droppedCount`.

## Schema versioning

Every payload includes `eventVersion` (currently `1`). Increment when changing the message shape so the server can tolerate or reject specific extension versions.

## Tests

```bash
npm run ci       # full gate (lint + typecheck + manifest + tests + coverage)
npm run test:watch
```

Coverage threshold for `src/lib/**`: 90 % lines, 85 % branches.

## Known limitations

- **In-page send-failure**: if `chrome.runtime.sendMessage` from `content.js` fails (e.g., during extension reload), the message is lost. Mitigation: WhatsApp Web's DOM scan picks the same message up on the next sweep, dedup re-allows it because the `sentMessageIds_v2` window did not get the prior write. This means duplicate-send is more likely than message loss in this edge case.
- **`chrome.storage.session` is per-Chrome-session**: closing Chrome empties the queue. Long network outages spanning a Chrome restart will drop queued messages. The dedup window in `local` storage persists, so a re-scan will re-emit recent messages.
- **WhatsApp Web layout changes**: the DOM scraper in `content.js` is brittle by definition. If WhatsApp ships a redesign, the scraper needs an update; the rest of the extension is decoupled.
