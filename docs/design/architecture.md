# Architecture Overview

## System Components

### Multi-Agent System (CrewAI)
- **Agents** — Individual AI workers with specific roles
- **Crews** — Orchestrated teams of agents working together
- **Tools** — Functions agents can call to interact with the vault and external systems

### Storage Layer
- **PostgreSQL + pgvector** — Primary storage for state and embeddings
- **Redis (optional)** — Caching and pub/sub event bus
- **SQLite** — Development mode fallback

### LLM Providers
- **GitHub Copilot (GitHub Models API)** — Primary provider
- **Anthropic Claude** — Alternative provider
- **Ollama** — Local model support
- **Router** — Intelligent task-based routing between providers

### Event System
- **File Watcher** — Monitors vault for changes using watchdog
- **Event Bus** — Redis pub/sub or in-memory queue
- **Scheduler** — APScheduler for cron-style jobs

### API Layer
- **FastAPI** — RESTful API for conversational queries
- **WebSocket (future)** — Streaming responses

## Data Flow

### New Note Processing
```
1. User creates note.md in vault root
2. File watcher detects event → publishes to event bus
3. NewNoteCrew subscribes → activates
4. Librarian agent: classifies note, assigns tags/folder
5. Note moved to target folder, frontmatter updated
6. Embedding service: generates vector embedding
7. Linker agent: finds similar notes via semantic search
8. Linker agent: injects backlinks into related notes
9. Storage layer: persists metadata and embedding
```

### Daily Audit
```
1. Scheduler triggers DailyAuditCrew at 2am
2. Auditor agent: scans all notes, re-evaluates placement
3. Auditor agent: flags misplaced notes
4. Archivist agent: detects stale notes (90+ days)
5. Archivist agent: finds broken links and orphans
6. Report generated and saved to vault
```

## Technology Stack

- **Language**: Python 3.11+
- **Framework**: CrewAI
- **Web**: FastAPI + Uvicorn
- **Database**: PostgreSQL 16 + pgvector extension
- **Cache**: Redis 7
- **ORM**: SQLAlchemy (async)
- **Migrations**: Alembic
- **Packaging**: uv
- **Containers**: Docker Compose

## Design Principles

1. **Agent Autonomy** — Each agent is self-contained with clear responsibilities
2. **Tool-Based Actions** — Agents interact with the vault only through defined tools
3. **Provider Flexibility** — LLM providers are pluggable and configurable
4. **Storage Abstraction** — Storage layer is swappable (Postgres/SQLite)
5. **Event-Driven** — React to changes in real-time
6. **Scheduled Intelligence** — Proactive maintenance through cron jobs
