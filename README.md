# Vault Crawler

Multi-agent Obsidian vault management service powered by CrewAI.

## Quick Start

### 1. Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (or pip)
- Docker and Docker Compose

### 2. Configuration

Copy the example env file and configure:
```bash
cp .env.example .env
```

Edit `.env` with your settings:
- `OBSIDIAN_VAULT_PATH` — Path to your Obsidian vault
- `GITHUB_TOKEN` — GitHub token for Copilot API
- `ANTHROPIC_API_KEY` — (Optional) Anthropic API key

### 3. Start Infrastructure

**With Redis and Ollama:**
```bash
docker compose --profile with-redis --profile with-ollama up -d
```

**Minimal (Postgres only):**
```bash
docker compose up -d
```

### 4. Install Dependencies

```bash
uv sync
```

### 5. Run Migrations

```bash
uv run alembic upgrade head
```

### 6. Start the Service

```bash
uv run python -m src.main serve
```

## Architecture

See [docs/design/architecture.md](docs/design/architecture.md) for full architecture overview.

### Agents
- **Librarian** — Classifies and files new notes
- **Auditor** — Daily re-evaluation of note placement
- **Linker** — Cross-references related notes
- **Archivist** — Detects stale notes and broken links
- **Summarizer** — Extracts action items from meetings
- **Jira Sync** — Syncs Jira tickets to vault notes

### Storage
- **PostgreSQL + pgvector** — Primary state and semantic search
- **Redis** — Optional caching and event bus
- **SQLite** — Dev mode fallback

### LLM Providers
- **GitHub Copilot** — Primary (GitHub Models API)
- **Anthropic Claude** — Alternative
- **Ollama** — Local models

## Documentation

- [Architecture Overview](docs/design/architecture.md)
- [Data Models](docs/design/data-models.md)
- [Agent Behaviors](docs/features/agents.md)
- [LLM Routing](docs/features/llm-routing.md)

## Development

### Run Tests
```bash
uv run pytest
```

### Lint
```bash
uv run ruff check .
```

### Type Check
```bash
uv run mypy src/
```

## CLI Commands

```bash
# Start API server
uv run python -m src.main serve

# Watch vault for changes
uv run python -m src.main watch

# Run Jira sync manually
uv run python -m src.main sync

# Run daily audit manually
uv run python -m src.main audit
```

## License

MIT
