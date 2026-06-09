# Configuration Reference

All configuration is read from environment variables (via `.env`). Variables use the `LIBRARIAN_` prefix.

---

## Quick start

```bash
cp .env.example .env
# edit .env with your values
uv run vault-librarian serve
```

---

## Environment variables

### Core

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARIAN_VAULT_PATH` | ✅ | — | Absolute path to your Obsidian vault root |
| `LIBRARIAN_SECRET` | | `change-me` | Shared secret for MCP/API auth |
| `LIBRARIAN_LOG_LEVEL` | | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### LLM Providers

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARIAN_LLM_PROVIDER` | | `copilot` | Provider: `copilot`, `anthropic`, `ollama` |
| `LIBRARIAN_LLM_MODEL` | | `gpt-4o-mini` | **Fast** model — used for real-time pipeline agents (on every file save) |
| `LIBRARIAN_LLM_MODEL_HEAVY` | | *(falls back to `LLM_MODEL`)* | **Heavy** model — used for scheduled/async jobs (audits, briefs, consolidation, scaffolding) |
| `LIBRARIAN_LLM_API_KEY` | | — | API key (GitHub token for Copilot, or Anthropic key) |

> **Tip:** Use a cheap/fast model (e.g. `gpt-4o-mini`) for `LLM_MODEL` since it runs on every file save, and a more capable model (e.g. `gpt-4o`) for `LLM_MODEL_HEAVY` which only runs on scheduled jobs.

### Embeddings

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARIAN_EMBEDDING_PROVIDER` | | `openai` | `openai` (text-embedding-3-small via API) or `local` (HuggingFace all-MiniLM-L6-v2) |

The embedding provider is independent of the LLM provider. Use `local` when you have network access to HuggingFace (e.g. off corporate VPN) and `openai` when you have a GitHub Models API key.

### Agents

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARIAN_ENROLLED_AGENTS` | | all agents | Comma-separated list of agents to enable |
| `LIBRARIAN_AUTONOMY_DEFAULT` | | `supervised` | Default autonomy level: `supervised` or `full` |

### Scheduler

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARIAN_AUDITOR_SCHEDULE` | | `0 2 * * *` | Cron expression for the Auditor agent |
| `LIBRARIAN_DAILY_BRIEF_SCHEDULE` | | `0 7 * * *` | Cron expression for Daily Brief |
| `LIBRARIAN_WEEKLY_REVIEW_SCHEDULE` | | `0 18 * * 0` | Cron expression for Weekly Review |

### Vault

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARIAN_VAULT_EXCLUDED_FOLDERS` | | `.obsidian,.git,.librarian,Librarian,Attachments` | Comma-separated folder names to skip |
| `LIBRARIAN_VAULT_EXCLUDED_FILES` | | `CLAUDE.md` | Comma-separated filenames to skip |
| `LIBRARIAN_STALE_DAYS` | | `60` | Days before a note is considered stale |

### Debounce

| Variable | Required | Default | Description |
|---|---|---|---|
| `LIBRARIAN_DEBOUNCE_STANDARD` | | `3.0` | Seconds to debounce standard file events |
| `LIBRARIAN_DEBOUNCE_DIRECTIVE` | | `0.5` | Seconds to debounce inline directive events |

---

## Storage

### SQLite (default)

Vault Librarian uses SQLite via SQLAlchemy + aiosqlite for relational state. No external database is required. Tables are created automatically on first startup.

### LanceDB (vector search)

Semantic search uses LanceDB, an embedded vector database stored inside the vault at `.librarian/lancedb/`. No setup required — it is created automatically on first index.

---

## Docker Compose

The only containerized service is **Ollama** (optional, for local LLM inference). It is behind a compose profile:

```bash
# Start Ollama
docker compose --profile ollama up -d

# Or use the helper script
./scripts/start-services.sh
```

Set `OLLAMA_MODELS` in `.env` to auto-pull models on container start (comma-separated).
