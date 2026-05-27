# Vault Crawler

Multi-agent Obsidian vault management service powered by CrewAI.

## Quick Start

### 1. Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (or pip)
- [Podman](https://podman.io/) + podman-compose (`brew install podman podman-compose`)
  - **or** Docker + Docker Compose

#### Podman users: one-time setup
Configure Podman to use `podman-compose` as its compose provider so `podman compose` and `podman-compose` are interchangeable:

```bash
mkdir -p ~/.config/containers
cat >> ~/.config/containers/containers.conf << 'EOF'
[engine]
compose_providers = ["/opt/homebrew/bin/podman-compose"]
compose_warning_logs = false
EOF
```

Without this, `podman compose` delegates to the system `docker-compose` binary which uses incompatible network labels.

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

Use the provided startup script which automatically enables services based on your `.env`:

```bash
./scripts/start-services.sh
```

The script will:
- Start Postgres (always)
- Start Redis if `ENABLE_REDIS=true`
- Start Ollama if `ENABLE_OLLAMA=true`
- Auto-pull Ollama models specified in `OLLAMA_MODELS`

**Manual Docker Compose:**
```bash
# Minimal (Postgres only)
docker compose up -d

# With Redis
docker compose --profile redis up -d

# With Ollama
docker compose --profile ollama up -d

# Everything
docker compose --profile redis --profile ollama up -d
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
uv run vault-crawler serve
```

Or with explicit options:

```bash
uv run vault-crawler serve --host 0.0.0.0 --port 8000
```

### CLI Commands

| Command | Description |
|---|---|
| `vault-crawler serve` | Start the API server + scheduler + file watcher |
| `vault-crawler scan` | Scan vault and print a note summary |
| `vault-crawler index` | Upsert all vault notes into storage |
| `vault-crawler migrate` | Run Alembic database migrations |
| `vault-crawler status` | Check connectivity of all components |

Run `vault-crawler <command> --help` for per-command options.

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
