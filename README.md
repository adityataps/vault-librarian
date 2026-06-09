# Vault Librarian

Autonomous multi-agent Obsidian vault management service powered by LangGraph.

## Quick Start

### 1. Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (or pip)
- (Optional) Docker or Podman — only needed for local Ollama

### 2. Configuration

Copy the example env file and configure:
```bash
cp .env.example .env
```

Edit `.env` with your settings:
- `LIBRARIAN_VAULT_PATH` — Path to your Obsidian vault
- `LIBRARIAN_LLM_API_KEY` — GitHub token (for Copilot) or Anthropic API key
- `LIBRARIAN_LLM_PROVIDER` — `copilot` (default), `anthropic`, or `ollama`
- `LIBRARIAN_SECRET` — Shared secret for MCP/API auth

### 3. Install Dependencies

```bash
uv sync
```

### 4. Run Migrations

```bash
uv run alembic upgrade head
```

### 5. Start the Service

```bash
uv run vault-librarian serve
```

Or with explicit options:
```bash
uv run vault-librarian serve --host 0.0.0.0 --port 8000
```

### (Optional) Local Ollama

If using Ollama as an LLM provider, start it via Docker Compose:
```bash
docker compose --profile ollama up -d
```

Or use the helper script:
```bash
./scripts/start-services.sh
```

## CLI Commands

| Command | Description |
|---|---|
| `vault-librarian serve` | Start the API server + scheduler + file watcher |
| `vault-librarian scan` | Scan vault and print a note summary |
| `vault-librarian index` | Upsert all vault notes into vector storage |
| `vault-librarian migrate` | Run Alembic database migrations |
| `vault-librarian status` | Check connectivity of all components |

Run `vault-librarian <command> --help` for per-command options.

## Architecture

See [docs/design/architecture.md](docs/design/architecture.md) for full architecture overview.

### Agents
- **Librarian** — Classifies and files new notes into the correct vault folder
- **Formatter** — Normalizes frontmatter and note structure
- **Linker** — Cross-references related notes via wikilinks
- **Meeting Enricher** — Extracts action items and context from meeting notes
- **MoC Maintainer** — Keeps Maps of Content up to date
- **Scaffolder** — Generates note templates from inline directives
- **Inline Directive** — Processes `vault-librarian::` directives embedded in notes
- **Auditor** — Scheduled sweep for broken links, orphans, and misplaced notes
- **Daily Brief** — Generates a daily activity summary
- **Weekly Review** — Produces a weekly vault health report

### Storage
- **SQLite** — Primary relational state (via SQLAlchemy + aiosqlite)
- **LanceDB** — Embedded vector search (stored in `.librarian/lancedb/` inside the vault)

### LLM Providers
- **GitHub Copilot** — Primary (GitHub Models API)
- **Anthropic Claude** — Alternative
- **Ollama** — Local models (requires Docker or native install)

### MCP Server

An MCP (Model Context Protocol) server is mounted at `/mcp`, enabling LLM tool-use integrations to interact with the vault programmatically. Authenticated via `X-Librarian-Secret` header.

### Scheduler

APScheduler runs scheduled agents (Auditor, Daily Brief, Weekly Review) on configurable cron expressions. See `LIBRARIAN_*_SCHEDULE` env vars.

## Documentation

- [Architecture Overview](docs/design/architecture.md)
- [Configuration Reference](docs/configuration.md)

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

## License

MIT
