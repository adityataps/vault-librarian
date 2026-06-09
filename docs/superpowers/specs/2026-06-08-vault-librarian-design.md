# Vault Librarian — Design Spec
_2026-06-08_

## Overview

A persistent, autonomous multi-agent service that manages an Obsidian vault. Agents run on file events, scheduled jobs, git hooks, and external webhooks (n8n). All changes are written directly to vault files with no approval step; git history and an in-app audit log serve as the review mechanism. An MCP server exposes vault operations to Claude Code and Copilot CLI.

This is a complete rewrite of the previous `vault-crawler` repo. No existing code is carried forward.

---

## 1. Architecture

```
Triggers (file events · cron · webhooks · git hooks · CLI)
       ↓
  Dispatcher  ←── debounce map + per-file asyncio.Lock
       ↓
  LangGraph pipeline  ←── LangChain LLM (Copilot or Claude, config-driven)
       ↓
  Vault tools  (read · write · move · frontmatter · search · MOC · git)
       ↓
  SQLite (metadata + runs + action items + audit log)
  ChromaDB (embeddings, file-backed)
  Git (atomic audit trail)
```

**Services in one process:**
- FastAPI — REST + webhook endpoints + MCP server
- Watchdog — file system events → event queue
- APScheduler — cron jobs (Daily Brief, Weekly Review, Auditor, STAR Miner)
- LangGraph agent pipelines — triggered by dispatcher or scheduler

**No Docker required for local dev.** SQLite and ChromaDB are file-backed. Optional Postgres upgrade path for production via config.

---

## 2. Trigger System

| Source | Mechanism | Notes |
|---|---|---|
| File events | Watchdog → debounced dispatcher | 0.5s debounce if `<agent-*>` tags detected; 3s otherwise |
| Scheduled jobs | APScheduler cron | Times configurable in `.env` |
| Git commit hook | POST to `/webhook/git` | Installed via `vault-librarian install-hooks` |
| n8n / external | POST to `/webhook/{event}` | Authenticated via `X-Librarian-Secret` header |
| Manual / CLI | `vault-librarian run <agent> [--note path]` | Bypasses debounce |

### Debounce logic

On the first file event, the dispatcher does a cheap regex peek for `<agent-` in the file. If found, the debounce timer is 0.5s. Otherwise 3s. Each subsequent event for the same path resets the active timer. On expiry, the dispatcher acquires the per-file lock and dispatches the pipeline.

### Startup reconciliation

On every startup the service scans all vault files and compares current content hashes against the `agent_runs` table. Any file whose hash has no completed run record for all expected agents is re-queued. This ensures no events are silently dropped during downtime.

---

## 3. Agent Roster

### Pipeline agents (run on file settle)

| Agent | Activates when | Responsibility |
|---|---|---|
| **Librarian** | New file (no existing run record) | Classifies note type, moves to correct folder, sets `type` frontmatter. Handles root janitor — files at vault root are filed automatically. |
| **Formatter** | Any settled file | Audits frontmatter schema; fills `date`, `tags`, `created`, `modified`; normalizes tag casing; enforces template structure for Project and Career notes; preserves Dataview code blocks untouched. |
| **Inline Directive** | Settled file with `<agent-*>` tags | Processes inline directives (see Section 5), replaces tags with generated content, preserves original prompt as a comment. |
| **Meeting Enricher** | `type: meeting` notes | Enforces meeting template (date, attendees, linked project); extracts action items and appends them to the linked project note using Tasks plugin syntax. |
| **Linker** | New notes post-Librarian; weekly batch | Embeds note content via ChromaDB; finds semantically related notes; injects `## Related` section with `[[wiki-links]]`; links Meeting notes to referenced projects. |
| **MOC Maintainer** | After Librarian files a note | Inserts a row into the relevant MOC (Work MOC, etc.); updates Jira ticket status rows when a Jira note's `status` field changes. |

### Scheduled agents (cron)

| Agent | Schedule | Responsibility |
|---|---|---|
| **Daily Brief** | Nightly (configurable) | Synthesizes `Daily Brief — YYYY-MM-DD.md`: open Jira tickets, recent meetings, unresolved action items from last 7 days, vault health score. |
| **Weekly Review** | Sunday evening | Synthesizes `Weekly Review — YYYY-WNN.md`: closed tickets, meetings attended, key decisions logged, action items resolved, notable learnings. |
| **Auditor** | Nightly + on-demand | Full-vault sweep: broken links, orphaned notes, stale notes (90+ days), misclassified types, duplicate folder detection (`Folder 2`/`Folder 3` patterns). Creates stubs for broken wiki-links. Writes `Vault Audit — YYYY-MM-DD.md`. |
| **STAR Story Miner** | Weekly | Scans Project and Career notes for notable events (decisions, problems, outcomes). Suggests or drafts STAR story entries into relevant project notes. |

### On-demand agents

| Agent | Trigger | Responsibility |
|---|---|---|
| **Scaffolder** | `/trigger/scaffold`, CLI, or MCP tool | Generates a structured note stub for a given `{title, type}`. Uses existing Templates folder as source of truth. Can accept optional context to pre-fill fields (e.g., seed from related Jira tickets). |

### Standard pipeline for a new note
```
file settled → Librarian → Formatter → Inline Directive* → Linker → MOC Maintainer → git commit [librarian]
```

### Standard pipeline for a new meeting note
```
file settled → Librarian → Formatter → Meeting Enricher → Linker → MOC Maintainer → git commit [librarian]
```

### Standard pipeline for an edited note
```
file settled → Formatter → Inline Directive* → (Linker if word count delta > 10% since last run) → git commit [librarian]
```
_*Only runs if `<agent-*>` tags present._

---

## 4. LangGraph Internals

Each agent is a `StateGraph`. All agents in a pipeline run share a single `VaultState` object that flows through nodes as edges.

```python
class VaultState(TypedDict):
    note_path: str
    note_content: str
    frontmatter: dict
    note_type: str | None
    directives: list[Directive]       # <agent-*> tags found
    action_items: list[str]           # extracted from meeting notes
    related_notes: list[str]          # found by Linker
    changes: list[str]                # audit trail for this run
```

Conditional edges handle routing — e.g. Meeting Enricher node only activates if `state["note_type"] == "meeting"`. The final node in every pipeline commits all changes to git in one atomic operation and writes to `agent_runs`.

### Vault tools (available to all agents)

| Tool | Description |
|---|---|
| `read_note(path)` | Returns content + parsed frontmatter |
| `write_note(path, content)` | Atomic write (temp file → rename), updates SQLite hash |
| `move_note(src, dst)` | Moves file, updates SQLite path |
| `update_frontmatter(path, fields)` | Merges fields into YAML frontmatter block |
| `search_similar(content, k)` | ChromaDB semantic search → ranked note paths |
| `read_template(type)` | Returns template content for a note type |
| `get_moc(name)` | Reads a MOC note as structured data |
| `update_moc(name, entry)` | Adds/updates a row in a MOC table |
| `create_note(path, content)` | Creates new note (Daily Brief, audit reports, stubs) |
| `list_notes(folder?, type?)` | Lists notes with metadata from SQLite |
| `get_action_items(resolved?)` | Returns action items from SQLite |
| `git_commit(message)` | Commits all pending vault changes with `[librarian]` author tag |

---

## 5. Inline Directives

Embedding a directive tag in any note triggers the Inline Directive agent with a 0.5s debounce.

| Tag | Behavior |
|---|---|
| `<agent-scaffold>prompt</agent-scaffold>` | Generates a full section or block of content in place |
| `<agent-fill/>` | Fills a single inline blank based on surrounding context |
| `<agent-context>question</agent-context>` | Pulls in and synthesizes content from related vault notes |

After processing, the tag is replaced with generated content. The original prompt is preserved as an HTML comment above the output:

```markdown
<!-- agent-scaffold: list acceptance criteria for this feature -->
- Operators can list agents with stable pagination
- Filters work for org, workload, and lifecycle status
```

Unprocessed tags act as a natural TODO queue visible in the Auditor report.

---

## 6. Storage

### SQLite schema

```sql
notes(
  path TEXT PRIMARY KEY,
  title TEXT,
  type TEXT,
  tags TEXT,           -- JSON array
  content_hash TEXT,
  last_modified TEXT,
  word_count INTEGER,
  indexed_at TEXT
)

agent_runs(
  note_path TEXT,
  content_hash TEXT,
  agent TEXT,
  completed_at TEXT,
  PRIMARY KEY (note_path, content_hash, agent)
)

action_items(
  id INTEGER PRIMARY KEY,
  source_note TEXT,
  content TEXT,
  due_date TEXT,       -- Tasks plugin date if present
  resolved INTEGER DEFAULT 0,
  created_at TEXT
)

audit_log(
  id INTEGER PRIMARY KEY,
  agent TEXT,
  note_path TEXT,
  action TEXT,
  detail TEXT,
  timestamp TEXT
)
```

### ChromaDB

Embedded, file-backed collection at `.librarian/chroma/` inside the vault. One document per note, embedding updated on content hash change. Used by Linker and `<agent-context>` directives.

### Resilience mechanisms

1. **Startup reconciliation scan** — on startup, compare all vault file hashes against `agent_runs`. Queue any note missing a completed run for any expected agent.
2. **Idempotency via `agent_runs`** — before running an agent, check if `(path, hash, agent)` is already complete. If yes, skip. Re-running the full pipeline on an already-processed note is a safe no-op. Expected agents per note type are defined in a static config map (e.g. `meeting` → `[librarian, formatter, meeting_enricher, linker, moc_maintainer]`).
3. **Atomic writes** — `write_note` writes to a temp file then renames into place. Partial writes never corrupt a note.

---

## 7. LLM Provider Abstraction

```python
def build_llm(config: LLMConfig) -> BaseChatModel:
    match config.provider:
        case "copilot":
            return ChatOpenAI(
                base_url="https://models.inference.ai.azure.com",
                api_key=config.api_key,
                model=config.model,   # e.g. "gpt-4o"
            )
        case "anthropic":
            return ChatAnthropic(model=config.model, api_key=config.api_key)
        case "ollama":
            return ChatOllama(model=config.model)
```

All agents receive `llm: BaseChatModel` via dependency injection. Switching providers is one line in `.env`. Embeddings use a separate configurable model (default: `sentence-transformers/all-MiniLM-L6-v2` via local inference, no API cost).

---

## 8. HTTP + MCP API

### Webhook / REST endpoints (FastAPI)

```
POST /webhook/git                    ← vault git post-commit hook
POST /webhook/jira                   ← n8n Jira status change event
POST /trigger/{agent}                ← manual agent invocation
POST /trigger/scaffold               ← body: {title, type, context?}
GET  /status                         ← health: storage, LLM, watcher
GET  /runs?path=&limit=              ← recent agent_runs for a note
```

All `/webhook/*` and `/trigger/*` endpoints require `X-Librarian-Secret` header.

### MCP server (Claude Code / Copilot CLI)

Exposed on the same FastAPI process via a `/mcp` mount. Tools auto-discovered by MCP clients on connect.

| MCP Tool | Description |
|---|---|
| `scaffold_note(title, type, context?)` | Creates a structured note stub |
| `run_agent(agent, note_path)` | Manually triggers any agent on a specific note |
| `search_vault(query, k?)` | Semantic search across all notes |
| `get_note_metadata(path)` | Returns frontmatter + recent agent run history |
| `list_notes(folder?, type?)` | Lists notes with metadata |
| `get_action_items(resolved?)` | Returns outstanding action items |
| `get_audit_report()` | Returns the latest Auditor report content |

### n8n integration pattern

n8n is a trigger source only — not an orchestrator. Example workflow:

```
Jira webhook → n8n → POST /webhook/jira {ticket_id, status}
                              ↓
                   vault-librarian updates Jira note + Work MOC
```

---

## 9. Obsidian Plugin Compatibility

| Plugin | Compatibility note |
|---|---|
| **obsidian-tasks** | Action items written in Tasks plugin syntax: `- [ ] text ⏰ YYYY-MM-DD` |
| **dataview** | Formatter never rewrites content inside ` ```dataview ``` ` blocks |
| **obsidian-git** | Vault assumed to be a git repo; librarian commits use `[librarian]` author tag to distinguish from manual commits |
| **templater** | Scaffolder reads from `/Templates` folder; does not invoke Templater JS — generates static content only |
| **obsidian-linter** | Formatter is aware of common linter rules (blank lines around headings, trailing newline) to avoid conflicts |

---

## 10. CLI

```
vault-librarian serve              Start API server + scheduler + file watcher
vault-librarian run <agent>        Run a specific agent (--note for single note)
vault-librarian scan               Scan vault, print note summary table
vault-librarian index              Reconcile all notes into SQLite + ChromaDB
vault-librarian install-hooks      Install post-commit hook into vault's .git/hooks/
vault-librarian status             Health check: storage, LLM providers, watcher
vault-librarian migrate            Run database migrations
```

---

## 11. Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Agent framework | LangGraph + LangChain |
| Web / MCP | FastAPI + Uvicorn |
| File watching | Watchdog |
| Scheduling | APScheduler |
| Metadata storage | SQLite (via SQLAlchemy) |
| Vector storage | ChromaDB (embedded) |
| Embeddings | sentence-transformers (local) |
| Packaging | uv |
| LLM providers | GitHub Copilot (primary), Anthropic Claude, Ollama |

---

## 12. Out of Scope (v1)

- Chat / conversational query interface (handled by Claude Code + Copilot CLI via MCP)
- Web UI or dashboard
- Multi-vault support
- Real-time collaboration / conflict resolution between users
- Cloud hosting / containerisation (runs locally or on homelab)
