# Full Architecture — DYAI Multi-Machine Network

Stand: 21.02.2026 (Ports gehaertet 21.02. abends) | 4 Maschinen, ~30 Services, 6+ AI-Agents

Dieses Dokument beschreibt das gesamte verteilte System inklusive aller Maschinen, Services, Agents und deren Verbindungen. Es dient als Referenz fuer alle Agenten und Entwickler.

---

## Netzwerk-Uebersicht

```
                                    INTERNET
                                       |
                    ┌──────────────────┼──────────────────┐
                    |                  |                   |
             ┌──────┴──────┐   ┌──────┴──────┐    ┌──────┴──────┐
             |  DYAI VPS   |   | Hetzner VPS |    |   Vercel    |
             | Hostinger   |   |   "SemOT"   |    |   (CDN)     |
             | Agent Hub   |   |  WhatsOrga  |    |  Kanban UI  |
             └──────┬──────┘   └──────┬──────┘    └─────────────┘
                    |                  |
                    |     TAILSCALE MESH (WireGuard)
                    |          |
             ┌──────┴──────────┴──────┐
             |      Linux PC Berlin   |
             |   Memory Hub + Bridge  |
             └────────────┬───────────┘
                          |
                    ┌─────┴─────┐
                    |  Mac M1   |
                    | Developer |
                    └───────────┘
```

---

## Maschine 1: Mac (Lokal)

**Rolle**: Entwicklung, Claude Code Sessions, Chrome Extension

| Aspekt | Detail |
|--------|--------|
| Chip | Apple Silicon (M1/M2) |
| OS | macOS Darwin 25.2.0 |
| User | benjaminpoersch |
| Projekte | ~/Projects/ (30+ Repos) |

**Laufende Services**:
- Claude Code (Entwicklungs-Sessions)
- Chrome + WhatsOrga Extension (WhatsApp Web DOM Observer)
- FileOrganizer (Python file watcher + dashboard)

**Wichtige Pfade**:
```
~/Projects/_TOOLZ/WhatsOrga/Whatsorga/    # WhatsOrga Repo
~/.claude/commands/                        # Slash-Commands/Skills
~/.claude/projects/                        # Projekt-Memories
~/OMNI-SKILLS/                             # Skill-Library
```

---

## Maschine 2: DYAI VPS (Hostinger)

**Rolle**: Agent-Orchestrierung, OpenClaw, Perr00bot

| Aspekt | Detail |
|--------|--------|
| Host | srv1308064.hstgr.cloud |
| SSH | `ssh -i ~/.ssh/id_ed25519 root@srv1308064.hstgr.cloud` |
| OS | Ubuntu Linux (AMD64) |
| Users | root, moltbot (Agent-User) |
| Tailscale IP | 100.115.155.7 |

### Services

| Service | Port | Binding | User | Beschreibung |
|---------|------|---------|------|--------------|
| nginx | 80, 443 | public | root | Reverse Proxy |
| OpenClaw Gateway | 18789, 18792 | localhost | moltbot | Agent-Gateway (Tailscale WS) |
| OpenClaw Agent | - | - | moltbot | Agentic execution |
| Nanobot Gateway | 18791 | localhost | moltbot | Nanobot agent |
| Perr00bot TTS | 8002 | localhost | moltbot | TTS Server (Python 3.14) |
| Perr00bot API | 3003 | **localhost** | moltbot | Node.js server.cjs (abgesichert 21.02.) |
| REST Proxy | 3005 | localhost | moltbot | Node.js rest-proxy.mjs |
| Kanban Spec-Server | 3004 | localhost | moltbot | Kanban backend |
| Kanban Task-Runner | - | - | moltbot | Task execution |
| Redis | 6379 | localhost | root | Cache + State |
| Claude (5x) | - | - | moltbot | Parallel Claude Code agents |
| claude-mem MCP | - | - | moltbot | Memory plugin (Bun worker) |
| chroma-mcp | - | - | moltbot | Vector DB MCP |

### Git Repo
```
/opt/agent-zero-data/  (remote: DYAI2025/agent-zero)
```
Memory-Sync Cron: alle 15 Min via `/opt/agent-zero-data/scripts/memory-sync.sh`

---

## Maschine 3: Hetzner VPS "SemOT"

**Rolle**: WhatsOrga Private — Termin-Extraktion, semantisches Gedaechtnis

| Aspekt | Detail |
|--------|--------|
| IP | 46.225.120.255 |
| SSH | `ssh -i ~/.ssh/id_ed25519 root@46.225.120.255` |
| Spec | CAX21 ARM64 Ampere, 4 vCPU, 8GB RAM, 80GB SSD |
| OS | Ubuntu (ARM64) |
| Repo | /opt/Whatsorga |
| Deploy | /opt/Whatsorga/deploy |
| Domain | semot.whatsorga.de (via Caddy) |

### Docker-Services (12 Container)

**WhatsOrga Core:**

| Container | Port (Host) | Port (Intern) | Beschreibung |
|-----------|-------------|---------------|--------------|
| caddy | 80, 443 | - | Reverse Proxy + TLS |
| radar-api | 8900 | 8000 | FastAPI Backend (Python 3.12) |
| postgres | - | 5432 | Message DB (PostgreSQL 16) |
| chromadb | - | 8000 | Vector Store (RAG Embeddings) |
| ollama | - | 11434 | Legacy, nicht aktiv genutzt |

**EverMemOS Private Stack:**

| Container | Port (Host) | Port (Intern) | Beschreibung |
|-----------|-------------|---------------|--------------|
| evermemos | 127.0.0.1:8001 | 8001 | Memory API (abgesichert) |
| mongodb | - | 27017 | Memory Storage |
| elasticsearch | - | 9200 | Textsuche |
| milvus-standalone | - | 19530 | Vektor-Suche |
| milvus-etcd | - | 2379 | Milvus Metadata |
| milvus-minio | - | 9000 | Milvus Object Storage |
| redis | - | 6379 | Boundary Detection Buffer (DB 8) |

### Cron-Jobs
```
*/30 * * * * /opt/Whatsorga/radar-api/reflection/reflect.sh >> /var/log/whatsorga-reflect.log 2>&1
```
Reflection Agent: Liest 50 Nachrichten, analysiert via `claude -p --model sonnet`, schreibt YAML-Updates.

### Datenfluss
```
Chrome Extension (Mac)
  → POST https://semot.whatsorga.de/api/ingest
    → Caddy (443) → radar-api (8000)
      → PostgreSQL (messages)
      → EverMemOS memorize (Docker-intern)
      → Groq LLM → Termin-Extraktion
      → CalDAV Sync → Apple iCloud Kalender
```

---

## Maschine 4: Linux PC Berlin

**Rolle**: Memory Hub (Agentisches EverMemOS), WhatsApp Bridge, Selina UI

| Aspekt | Detail |
|--------|--------|
| Tailscale IP | 100.103.64.33 |
| SSH | `ssh dyai@100.103.64.33` |
| OS | Ubuntu Desktop (AMD64) |
| Users | dyai (primary), dyai2026, root |

### Native Services

| Service | Port | Binding | User | Beschreibung |
|---------|------|---------|------|--------------|
| EverMemOS API | 8003 | 0.0.0.0 | dyai | Agentisches Gedaechtnis REST API (braucht Tailscale) |
| EverMemOS Memsys | 1995 | 0.0.0.0 | dyai | Default Memsys Port |
| EverMemOS Metrics | 9090 | 0.0.0.0 | dyai | Prometheus Metrics |
| EverMemOS MCP | - | - | dyai | MCP Server fuer Claude |
| Selina (Next.js) | 3000 | public | dyai | Selina Web UI |
| WhatsApp Radar Bridge | - | - | dyai | Node.js + Puppeteer/Chrome headless |
| OpenClaw Gateway | 18789, 18792 | localhost | dyai | Agent Gateway |
| Ollama WebUI | 8080 | public | root | LLM UI (snap) |
| Streamlit | 8501 | public | dyai | Dashboard |
| Qwen CLI | - | - | dyai | Qwen Agent (2 Sessions) |

### Docker-Services (Ports gehaertet 21.02.2026)

| Container | Port (Host) | Binding | Beschreibung |
|-----------|-------------|---------|--------------|
| memsys-mongodb | 27017 | **127.0.0.1** | Memory Storage |
| memsys-elasticsearch | 19200 | **127.0.0.1** | Textsuche (remapped) |
| memsys-milvus-standalone | 19530, 9091 | **127.0.0.1** | Vektor-DB |
| memsys-milvus-etcd | - | - | Milvus Metadata (UNHEALTHY!) |
| memsys-milvus-minio | 9000, 9001 | **127.0.0.1** | Object Storage |
| memsys-redis | 6379 | **127.0.0.1** | Cache |
| deploy-radar-api-1 | 8900 | **127.0.0.1** | Zweite radar-api Instanz (Dev/Test) |
| deploy-postgres-1 | - | intern | PostgreSQL |
| deploy-chromadb-1 | - | intern | ChromaDB |
| deploy-ollama-1 | - | intern | Ollama |
| auto-claude-falkordb | 6380 | **127.0.0.1** | FalkorDB Graph-DB |
| auto-claude-graphiti-mcp | 8010 | **127.0.0.1** | Graphiti MCP Server (von 8000 auf 8010 wg. LPrint-Konflikt) |
| backend | 32768 | 0.0.0.0 | Unbekannte App (Backend) |
| client | 32769 | 0.0.0.0 | Unbekannte App (Frontend) |
| clickhouse | - | intern | Analytics DB |
| postgres | - | intern | Zweites PostgreSQL |

### WhatsApp Radar Bridge
```
/home/dyai/whatsapp-radar-bridge/
  - Node.js + tsx (TypeScript)
  - Puppeteer + Headless Chrome (WhatsApp Web)
  - .wwebjs_auth/session/ (WhatsApp Session)
```
Headless Chrome Prozess laeuft seit 12.02. mit gespoofer User-Agent (macOS Chrome 101).

---

## AI-Agents

### Agent-Uebersicht

| Agent | Maschine | Technologie | Funktion |
|-------|----------|-------------|----------|
| **OpenClaw** | DYAI VPS + Berlin PC | openclaw-gateway (Go?) | Multi-Agent Gateway, WS-basiert |
| **Perr00bot** | DYAI VPS | Python TTS + Node.js | Voice Agent mit TTS |
| **Marvin** | DYAI VPS | Cron | Task-Agent (geplante Aufgaben) |
| **Nanobot** | DYAI VPS | nanobot gateway | Agent Framework |
| **Claude (5x)** | DYAI VPS | claude CLI | Parallel Claude Code Sessions |
| **Selina** | Berlin PC | Next.js | Web UI Agent |
| **Qwen** | Berlin PC | qwen CLI | Qwen LLM Agent (2 Sessions) |
| **Reflection Agent** | Hetzner VPS | claude -p + cron | WhatsOrga Profil-Lernen |
| **WhatsApp Bridge** | Berlin PC | Node.js + Puppeteer | WhatsApp Web Headless |

### Memory-Systeme

| System | Maschine | Port | Zweck | Agenten |
|--------|----------|------|-------|---------|
| EverMemOS (Shared) | Berlin PC | 8003 | Agent-Gedaechtnis | Perr00bot, Marvin, OpenClaw, Selina |
| EverMemOS (Private) | Hetzner VPS | 8001 (localhost) | WhatsApp-Familien-Kontext | radar-api, Reflection Agent |
| claude-mem | DYAI VPS + Berlin PC | MCP | Claude Code Memory Plugin | Claude Sessions |
| chroma-mcp | DYAI VPS + Berlin PC | MCP | Vector DB fuer Claude | Claude Sessions |
| FalkorDB | Berlin PC | 6380 | Graph-Datenbank | auto-claude |

---

## Cross-Machine Verbindungen

```
Mac ──Chrome Extension──▶ Hetzner VPS (HTTPS :443)
  |                            |
  |                            ├── radar-api → EverMemOS (Docker intern)
  |                            └── Reflection Agent → claude -p → YAML-Profile
  |
  ├──SSH──▶ Hetzner VPS (Deployment, Debugging)
  ├──SSH──▶ DYAI VPS (Agent Management)
  └──Tailscale SSH──▶ Berlin PC (Memory Queries)

DYAI VPS ──Tailscale WS──▶ Berlin PC (OpenClaw Gateway :18789)
DYAI VPS ──HTTP──▶ Berlin PC (EverMemOS :8003, Memory Read/Write)

Berlin PC ──WhatsApp Bridge──▶ WhatsApp Servers (headless Chrome)
Berlin PC ──Tailscale──▶ Mac (SSH-zurueck, wenn noetig)
```

### Sicherheits-Status (aktualisiert 21.02.2026 abends)

| Service | Port | Binding | Auth | Risiko |
|---------|------|---------|------|--------|
| EverMemOS (Hetzner) | 8001 | **localhost** | keine | OK (abgesichert 21.02.) |
| EverMemOS (Berlin) | 8003 | 0.0.0.0 | keine | MITTEL (braucht Tailscale-Zugang) |
| MongoDB (Berlin) | 27017 | **localhost** | admin/memsys123 | OK (abgesichert 21.02.) |
| Elasticsearch (Berlin) | 19200 | **localhost** | keine | OK (abgesichert 21.02.) |
| Redis (Berlin) | 6379 | **localhost** | keine | OK (abgesichert 21.02.) |
| Milvus (Berlin) | 19530 | **localhost** | keine | OK (abgesichert 21.02.) |
| Minio (Berlin) | 9000 | **localhost** | minioadmin | OK (abgesichert 21.02.) |
| FalkorDB (Berlin) | 6380 | **localhost** | keine | OK (abgesichert 21.02.) |
| radar-api (Berlin) | 8900 | **localhost** | Bearer Token | OK (abgesichert 21.02.) |
| radar-api (Hetzner) | 8900 | 0.0.0.0 | Bearer Token | OK |
| Perr00bot API (DYAI) | 3003 | **localhost** | keine | OK (abgesichert 21.02.) |

---

## LLM-Stack

| Provider | Modell | Genutzt von | Zweck |
|----------|--------|-------------|-------|
| Groq (kostenlos) | Llama 3.3 70B Versatile | radar-api | Termin-Extraktion (primary) |
| Groq (kostenlos) | Whisper Large v3 | radar-api | Audio-Transkription |
| Google (kostenlos) | Gemini 2.5 Flash | radar-api | Termin-Extraktion (fallback) |
| DeepInfra | Llama 3.3 70B Instruct | EverMemOS (beide) | Chunking, Analyse, Boundary |
| DeepInfra | Qwen3-Embedding-4B | EverMemOS (beide) | Embeddings (1024 dims) |
| DeepInfra | Qwen3-Reranker-4B | EverMemOS (beide) | Reranking |
| Anthropic | Claude Sonnet (CLI) | Reflection Agent | Profil-Analyse (Claude Max) |
| Anthropic | Claude Code | DYAI VPS (5x) | Agent-Sessions |
| lokal | all-MiniLM-L6-v2 | radar-api | Marker Embeddings (384 dims) |
| lokal | Ollama | Berlin PC, Hetzner | Legacy / nicht aktiv |

---

## Datenbanken

| DB | Maschine | Port | Zweck | Auth |
|----|----------|------|-------|------|
| PostgreSQL (WhatsOrga) | Hetzner VPS | 5432 (intern) | Messages, Termine, Feedback | radar/$POSTGRES_PASSWORD |
| PostgreSQL (Berlin) | Berlin PC | 5432 (intern) | Unbekannt (deploy-Stack) | ? |
| MongoDB (Hetzner) | Hetzner VPS | 27017 (intern) | EverMemOS Private Memory | admin/$MONGODB_PASSWORD |
| MongoDB (Berlin) | Berlin PC | 27017 (localhost) | EverMemOS Shared Memory | admin/memsys123 |
| Elasticsearch (Hetzner) | Hetzner VPS | 9200 (intern) | EverMemOS Textsuche | keine |
| Elasticsearch (Berlin) | Berlin PC | 19200 (localhost) | EverMemOS Textsuche | keine |
| Milvus (Hetzner) | Hetzner VPS | 19530 (intern) | EverMemOS Vektoren | keine |
| Milvus (Berlin) | Berlin PC | 19530 (localhost) | EverMemOS Vektoren | keine |
| Redis (Hetzner) | Hetzner VPS | 6379 (intern) | Boundary Detection Buffer | keine |
| Redis (Berlin) | Berlin PC | 6379 (localhost) | Cache | keine |
| ChromaDB (Hetzner) | Hetzner VPS | 8000 (intern) | RAG Embeddings | keine |
| ChromaDB (Berlin) | Berlin PC | intern | Agent Embeddings | keine |
| FalkorDB | Berlin PC | 6380 (localhost) | Graph-DB | keine |
| ClickHouse | Berlin PC | intern | Analytics | keine |

---

## Bekannte Probleme

1. ~~**Berlin PC: Alles oeffentlich!**~~ **BEHOBEN 21.02.2026** — Alle Infra-Ports (MongoDB, ES, Redis, Milvus, Minio, FalkorDB) auf 127.0.0.1 gebunden. Nur EverMemOS (8003) und Selina (3000) bleiben auf 0.0.0.0 (brauchen Tailscale-Zugang).
2. **milvus-etcd UNHEALTHY** auf Berlin PC — kann zu Milvus-Instabilitaet fuehren.
3. **Doppelte Deploy-Stacks** auf Berlin PC — `deploy-radar-api-1` und `deploy-postgres-1` laufen zusaetzlich zu den memsys-Containern. Vermutlich Test/Dev-Leftovers.
4. **5 Claude-Prozesse** auf DYAI VPS — unklar ob alle aktiv genutzt oder Zombies.
5. **WhatsApp Radar Bridge** auf Berlin PC laeuft seit 12.02. — Chrome-Session koennte auslaufen.
6. **Ollama** laeuft auf Hetzner VPS und Berlin PC, wird aber von keinem Service aktiv genutzt.
7. ~~**Port 8000 Konflikt**~~ **BEHOBEN 21.02.2026** — graphiti-mcp von Port 8000 auf 8010 verschoben (LPrint belegt 8000).

---

## Deployment-Checkliste

### Hetzner VPS (WhatsOrga)
```bash
ssh -i ~/.ssh/id_ed25519 root@46.225.120.255
cd /opt/Whatsorga
git pull
cd deploy
docker compose build radar-api    # IMMER nach Code-Aenderungen!
docker compose up -d radar-api
docker compose logs -f radar-api
```

### DYAI VPS (Agents)
```bash
ssh -i ~/.ssh/id_ed25519 root@srv1308064.hstgr.cloud
# Agent-Prozesse laufen als User "moltbot"
su - moltbot
# OpenClaw neustarten: systemctl --user restart openclaw
```

### Berlin PC (Memory Hub)
```bash
ssh dyai@100.103.64.33
# EverMemOS: laeuft nativ (nicht Docker)
cd ~/EverMemOS && source .venv/bin/activate
# Docker-Services: cd ~/deploy && docker compose up -d
```

---

## Quick Reference

```
Mac SSH → Hetzner:    ssh -i ~/.ssh/id_ed25519 root@46.225.120.255
Mac SSH → DYAI:       ssh -i ~/.ssh/id_ed25519 root@srv1308064.hstgr.cloud
Mac SSH → Berlin:     ssh dyai@100.103.64.33

WhatsOrga API:        https://semot.whatsorga.de/api/
EverMemOS (privat):   http://localhost:8001 (nur auf Hetzner VPS)
EverMemOS (shared):   http://100.103.64.33:8003
Selina UI:            http://100.103.64.33:3000
Kanban:               https://kanban-jet-seven-ashy.vercel.app/

Logs (WhatsOrga):     docker compose -f /opt/Whatsorga/deploy/docker-compose.yml logs -f radar-api
Logs (Reflection):    tail -f /var/log/whatsorga-reflect.log
```
