# Configuration Reference

All configuration is read from environment variables (via `.env`) and/or `config.yaml`. Environment variables always take precedence.

---

## Quick start

```bash
cp .env.example .env
# edit .env with your values
uv run vault-crawler serve
```

---

## Environment variables

### Core

| Variable | Required | Default | Description |
|---|---|---|---|
| `OBSIDIAN_VAULT_PATH` | ✅ | — | Absolute path to your Obsidian vault root |
| `ENVIRONMENT` | | `development` | `development` or `production` |
| `LOG_LEVEL` | | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `SECRET_KEY` | | auto | Secret key for API tokens (generate with `openssl rand -hex 32`) |

### Database (Postgres — primary)

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | | `postgresql+asyncpg://...` | Full SQLAlchemy async connection URL |
| `POSTGRES_HOST` | | `localhost` | Used if `DATABASE_URL` is not set |
| `POSTGRES_PORT` | | `5432` | |
| `POSTGRES_USER` | | `vault_crawler` | |
| `POSTGRES_PASSWORD` | | `vault_crawler` | |
| `POSTGRES_DB` | | `vault_crawler` | |
| `STORAGE_BACKEND` | | `postgres` | `postgres` or `sqlite` (dev/offline fallback) |

### Redis (optional)

| Variable | Required | Default | Description |
|---|---|---|---|
| `ENABLE_REDIS` | | `false` | Enable Redis cache + pub/sub event bus |
| `REDIS_URL` | | `redis://localhost:6379/0` | Redis connection URL |
| `REDIS_TTL_SECONDS` | | `3600` | Default cache TTL in seconds |

### LLM Providers

| Variable | Required | Default | Description |
|---|---|---|---|
| `DEFAULT_LLM_PROVIDER` | | `copilot` | Default provider: `copilot`, `anthropic`, `ollama` |
| `GITHUB_TOKEN` | | — | Required for GitHub Models (Copilot) |
| `COPILOT_MODEL` | | `gpt-4o-mini` | GitHub Models model ID |
| `ANTHROPIC_API_KEY` | | — | Required for Claude |
| `ANTHROPIC_MODEL` | | `claude-sonnet-4-5` | Claude model ID |
| `OLLAMA_BASE_URL` | | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | | `llama3.2` | Ollama model to use for chat |
| `OLLAMA_EMBEDDING_MODEL` | | `nomic-embed-text` | Ollama model for embeddings |
| `ENABLE_OLLAMA` | | `false` | Start the Ollama container in Docker Compose |
| `OLLAMA_MODELS` | | `llama3.2` | Comma-separated models to pull on container start |

### Vault

| Variable | Required | Default | Description |
|---|---|---|---|
| `VAULT_EXCLUDED_FOLDERS` | | `.obsidian,_archive,_templates` | Comma-separated folder names to skip |
| `VAULT_EXCLUDED_FILES` | | `Untitled.md` | Comma-separated filenames to skip |
| `JIRA_FOLDER` | | `Work/Jira` | Vault sub-folder for synced Jira notes |

### Scheduler

| Variable | Required | Default | Description |
|---|---|---|---|
| `SCHEDULER_ENABLED` | | `true` | Enable background job scheduler |
| `DAILY_AUDIT_HOUR` | | `2` | Hour (0–23) to run daily audit |
| `DAILY_AUDIT_MINUTE` | | `0` | Minute to run daily audit |
| `JIRA_SYNC_INTERVAL_MINUTES` | | `60` | How often to sync Jira tickets |
| `WEEKLY_DIGEST_DAY` | | `sun` | Day of week for weekly digest |
| `WEEKLY_DIGEST_HOUR` | | `8` | Hour to generate weekly digest |

### Jira

| Variable | Required | Default | Description |
|---|---|---|---|
| `JIRA_ENABLED` | | `false` | Enable Jira sync |
| `JIRA_BASE_URL` | | — | Your Jira instance URL, e.g. `https://myorg.atlassian.net` |
| `JIRA_USERNAME` | | — | Jira account email |
| `JIRA_API_TOKEN` | | — | Jira API token (from [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens)) |
| `JIRA_JQL_FILTER` | | `assignee = currentUser() AND sprint in openSprints()` | JQL to select tickets to sync |

### API

| Variable | Required | Default | Description |
|---|---|---|---|
| `API_HOST` | | `0.0.0.0` | Bind host for the API server |
| `API_PORT` | | `8000` | Bind port |
| `ALLOWED_ORIGINS` | | `*` in dev | CORS allowed origins (comma-separated) in production |

---

## config.yaml

A `config.yaml` file can override individual settings. See `config.example.yaml` for the full reference. All keys map 1:1 to environment variable names (snake_case).

```yaml
environment: production
storage_backend: postgres

vault:
  path: /Users/me/Documents/vault
  excluded_folders:
    - .obsidian
    - _archive
    - _templates

llm:
  default_provider: copilot
  copilot_model: gpt-4o

scheduler:
  enabled: true
  daily_audit_hour: 2

jira:
  enabled: true
  base_url: https://myorg.atlassian.net
  jql_filter: "project = ENG AND sprint in openSprints()"
```

---

## LLM routing

The system routes tasks to providers based on task type. You can override defaults via `config.yaml`:

```yaml
llm:
  routing:
    classify_note: ollama       # cheap local model
    summarize_meeting: copilot  # better quality
    embed: ollama               # nomic-embed-text is fast
    chat: copilot
  fallback_chain:
    - copilot
    - anthropic
    - ollama
```

### Task types

| Task | Default provider | Notes |
|---|---|---|
| `classify_note` | copilot | Assigns type/tags/folder |
| `summarize` | copilot | Meeting notes, digests |
| `embed` | ollama (or copilot) | `nomic-embed-text` preferred |
| `chat` | copilot | Conversational interface |
| `link` | copilot | Wikilink suggestions |
| `audit` | copilot | Vault health review |

---

## Storage backends

### PostgreSQL (recommended)

Default. Requires the `pgvector` extension (included in the Docker Compose service).

```
DATABASE_URL=postgresql+asyncpg://vault_crawler:vault_crawler@localhost:5432/vault_crawler
```

Run migrations:

```bash
uv run vault-crawler migrate
```

### SQLite (dev/offline)

No setup required. No vector search support (similarity uses in-memory cosine on full recall).

```
STORAGE_BACKEND=sqlite
DATABASE_URL=sqlite+aiosqlite:///./vault_crawler.db
```

### Migration between backends

Use the provided script to copy data from SQLite → Postgres:

```bash
uv run python scripts/migrate_storage.py \
  --from "sqlite+aiosqlite:///./vault_crawler.db" \
  --to   "postgresql+asyncpg://..."
```

---

## Docker Compose profiles

| Profile | Services started |
|---|---|
| *(default)* | `postgres` only |
| `redis` | `postgres` + `redis` |
| `ollama` | `postgres` + `ollama` |
| `redis,ollama` | all three |

Start with:

```bash
./scripts/start-services.sh
```

Or manually:

```bash
ENABLE_REDIS=true ENABLE_OLLAMA=true ./scripts/start-services.sh
```
