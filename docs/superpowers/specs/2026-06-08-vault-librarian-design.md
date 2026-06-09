# Vault Librarian — Design Spec
_2026-06-08_

## Overview

A persistent, autonomous multi-agent service that manages an Obsidian vault. Agents run on file events, scheduled jobs, git hooks, and external webhooks (n8n). Agent autonomy is configurable per-agent — from fully automatic to supervised (propose-only). All config lives in a hot-reloadable vault note. An MCP server exposes vault operations to Claude Code and Copilot CLI. An activity log note provides Obsidian-native observability over all agent actions.

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
- APScheduler — cron jobs (Daily Brief, Weekly Review, Auditor)
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

### Agent enrollment

Which agents are active is configured at startup — not hardcoded. Priority order: CLI flag > env var > config file.

```yaml
# config.yaml
agents:
  enabled:
    - librarian
    - formatter
    - linker
    - meeting_enricher
    - moc_maintainer
    - inline_directive
    - auditor
    - daily_brief
    - weekly_review
    - scaffolder
```

```bash
# env var (comma-separated, overrides config.yaml)
LIBRARIAN_AGENTS=librarian,formatter,auditor

# CLI flag (overrides both, per-invocation)
vault-librarian serve --agents librarian,formatter,auditor
```

Unenrolled agents are never instantiated and never appear in the expected-agents map for reconciliation. This lets you run a lightweight mode (e.g. just `librarian,formatter`) during development or on low-powered hardware.

### Autonomy levels

Each agent operates in one of three modes. The global default applies to all agents; per-agent overrides take precedence. Both are set in `.librarian/config.md` (see Section 6).

| Level | Behaviour |
|---|---|
| `full` | Agent executes immediately, writes directly to vault files. |
| `supervised` | Agent calls `propose_action()` — appends a `- [ ]` item to `.librarian/Inbox.md` instead of writing. Execution happens when the user checks the item and saves. |
| `off` | Agent is enrolled but never runs. Useful for temporarily disabling without removing from config. |

**Librarian Inbox** lives at `.librarian/Inbox.md`. All supervised agents write proposals here regardless of which agent proposed them — one place to review everything. Checked items are picked up by the execution loop and marked `✅ Executed — YYYY-MM-DD`.

Sensible defaults — agents whose actions are low-risk default to `full`; agents that move, merge, or delete default to `supervised`:

```yaml
# .librarian/config.md frontmatter defaults
agents:
  autonomy: supervised       # global default
  overrides:
    formatter: full          # frontmatter edits are safe
    inline_directive: full   # explicitly requested by user
    meeting_enricher: full   # extracting action items is low risk
    linker: supervised       # modifies other notes
    librarian: supervised    # moving files is destructive
    moc_maintainer: supervised
    auditor: supervised      # destructive ops always supervised
```

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
| **Auditor (quick)** | Every file event (same pipeline as other agents) | Lightweight check on the affected note and its immediate linked notes only — broken links, new orphan status, root-level strays. Cheap, runs in milliseconds. |
| **Auditor (full)** | Scheduled (configurable, default nightly) + on-demand | Full-vault sweep: broken links, orphaned notes, stale notes, misclassified types, duplicate folder detection, unprocessed `<agent-*>` tags. Creates stubs for broken wiki-links. Writes `Vault Audit — YYYY-MM-DD.md` with actionable TODO list (see Section 5). |

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

## 5. Auditor TODO Loop & Conflict Resolution

### Actionable TODO list

The Auditor writes `Vault Audit — YYYY-MM-DD.md` with a `## 🔧 Actionable Items` section using Tasks plugin syntax:

```markdown
## 🔧 Actionable Items
<!-- Check items you want the librarian to execute, then save the file -->

- [ ] Move "Sri's Bach Party Gameplan.md" → Personal/
- [ ] Create stub for [[CSharp]] in Tech Notes/
- [ ] Merge "Desk Check 2026-04-30 2" into "Desk Check 2026-04-30"
- [ ] Delete duplicate folder "docs/superpowers 2"
```

When you check an item and save, the file watcher fires with a 0.5s debounce (audit reports are treated as directive-containing files). The Auditor execution pass reads all `- [x]` items, executes each action, then replaces the checkbox with `✅ Executed — YYYY-MM-DD`. Unchecked items carry forward to the next audit report unchanged.

This gives human-in-the-loop control for destructive operations (moves, merges, deletes) without requiring a UI.

### File conflict resolution

**Agent vs. agent** — prevented by the per-file `asyncio.Lock`. Only one agent pipeline runs on a given file at a time.

**Agent vs. human** — handled via optimistic concurrency:
1. At dispatch time, the dispatcher records the file's current content hash.
2. Before any agent writes, `write_note` re-reads the hash from disk.
3. If the hash changed (human edited while the agent was processing), the write is aborted and the note is re-queued. The file watcher will pick up the human's version naturally on next settle.
4. No data is ever lost — worst case the agent re-runs on the updated content.

**Obsidian Sync conflicts** (mobile edits) surface as `filename.md.sync-conflict-...` files. The Auditor detects these by filename pattern and lists them in the actionable TODO section for manual resolution.

---

## 6. Vault Config File

The service is configured through `.librarian/config.md` — a standard Obsidian note inside the vault. It is version-controlled with the vault and editable in Obsidian like any other note.

### Format

YAML frontmatter holds structured settings. Markdown body sections contain **natural language instructions** injected directly into each agent's system prompt at runtime — no Python required to customise agent behaviour.

````markdown
---
agents:
  autonomy: supervised
  overrides:
    formatter: full
    inline_directive: full
    meeting_enricher: full
debounce:
  standard: 3.0
  directive: 0.5
auditor:
  quick: true
  schedule: "0 2 * * *"
daily_brief:
  schedule: "0 7 * * *"
weekly_review:
  schedule: "0 18 * * 0"
---

## Librarian

When classifying notes, use this folder taxonomy:
- Projects/ — active work with deliverables
- Career/ — interview prep, retrospectives, STAR stories
- Meetings/ — any meeting, desk check, sprint demo
- Jira/ — ticket notes matching AICOE-* pattern
- Personal/ — anything non-work related

Prefer Projects/ over Career/ for AI platform work even if it
mentions interview topics.

## Formatter

Always add `company: finastra` to notes mentioning Finastra,
AICOE, or any agent-platform repo.

## Auditor

Mark notes as stale after 60 days, not 90.
````

### Hot reload

The config file path has a dedicated handler in the dispatcher — it never dispatches agents, only reloads config. On save:

1. Config is re-parsed and validated.
2. Updated settings are applied to the shared `AppConfig` object immediately.
3. Schedule changes trigger APScheduler job updates at runtime.
4. A log entry is appended to `.librarian/Activity.md`: `Config reloaded — N agents, autonomy: supervised`.

No restart required. Changes apply to the next agent run.

### Scaffolding on first run

On first startup, if `.librarian/config.md` does not exist, the Scaffolder generates it pre-populated with the vault's detected folder structure and sensible defaults. On subsequent startups, frontmatter takes precedence over `config.yaml` and env vars (vault config is the highest-priority source).

---

## 7. Inline Directives

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

## 8. Audit Trail

Three layers serve different observability needs.

### `.librarian/Activity.md` — primary observable surface

A rolling vault note appended to in real-time, newest entries first. Uses Obsidian callout syntax for visual scanning without reading every line:

```markdown
## 2026-06-08 · 14:32

> [!success] Librarian
> Moved `Sri's Bach Party Gameplan.md` → `Personal/`

> [!info] Formatter
> `Projects/Agent Platform.md` — added `created`, `modified`; normalized 2 tags

> [!tip] Linker
> `Meetings/Sprint Demo 2026-05-20.md` — injected 3 backlinks: [[Agent Platform]], [[Observability]], [[Cloud Run]]

> [!warning] Auditor → Inbox
> Proposed: merge `Desk Check 2026-04-30 2` into `Desk Check 2026-04-30`

> [!failure] Librarian
> Could not classify `scratch.md` — no content. Skipped.
```

| Callout type | Meaning |
|---|---|
| `success` | Agent executed directly (full autonomy) |
| `info` | Non-destructive metadata change |
| `tip` | Enrichment (backlinks, action items) |
| `warning` | Proposed to Inbox (supervised autonomy) |
| `failure` | Skipped or errored |

Rolling window of configurable length (default: last 7 days). Older entries auto-truncated. Config reloads also appear here.

### SQLite `audit_log` — authoritative queryable history

The activity note is a human-readable view over the `audit_log` table. Exposed via MCP tools (`get_audit_report`, `get_agent_runs`) and the CLI:

```
vault-librarian log [--agent formatter] [--note path] [--since 7d] [--limit 50]
```

### Rich terminal output — live feed

When `vault-librarian serve` is running, each agent action is printed in real-time using Rich: color-coded by agent, with timing and outcome. Good for watching the system during initial setup or debugging.

### Daily Brief integration

The Daily Brief includes a "Yesterday's agent activity" summary:

```markdown
## 🤖 Agent Activity (yesterday)
- Formatter touched 4 notes
- Librarian moved 2 notes, proposed 1 item to Inbox
- Auditor added 3 items to Inbox
- 0 errors
```

---

## 9. Storage

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

LanceDB is a viable drop-in replacement (Rust-backed, faster at scale, same embedded model) and is noted as a future upgrade path. ChromaDB is chosen for v1 due to more LangChain usage examples. The storage interface will be wrapped so swapping is a config change, not a code change.

### Resilience mechanisms

1. **Startup reconciliation scan** — on startup, compare all vault file hashes against `agent_runs`. Queue any note missing a completed run for any expected agent.
2. **Idempotency via `agent_runs`** — before running an agent, check if `(path, hash, agent)` is already complete. If yes, skip. Re-running the full pipeline on an already-processed note is a safe no-op. Expected agents per note type are defined in a static config map (e.g. `meeting` → `[librarian, formatter, meeting_enricher, linker, moc_maintainer]`).
3. **Atomic writes** — `write_note` writes to a temp file then renames into place. Partial writes never corrupt a note.

---

## 10. LLM Provider Abstraction

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

## 11. HTTP + MCP API

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

## 12. Obsidian Plugin Compatibility

| Plugin | Compatibility note |
|---|---|
| **obsidian-tasks** | Action items written in Tasks plugin syntax: `- [ ] text ⏰ YYYY-MM-DD` |
| **dataview** | Formatter never rewrites content inside ` ```dataview ``` ` blocks |
| **obsidian-git** | Vault assumed to be a git repo; librarian commits use `[librarian]` author tag to distinguish from manual commits |
| **templater** | Scaffolder reads from `/Templates` folder; does not invoke Templater JS — generates static content only |
| **obsidian-linter** | Formatter is aware of common linter rules (blank lines around headings, trailing newline) to avoid conflicts |

---

## 13. CLI

```
vault-librarian serve              Start API server + scheduler + file watcher
vault-librarian run <agent>        Run a specific agent (--note for single note)
vault-librarian scan               Scan vault, print note summary table
vault-librarian index              Reconcile all notes into SQLite + ChromaDB
vault-librarian install-hooks      Install post-commit hook into vault's .git/hooks/
vault-librarian status             Health check: storage, LLM providers, watcher
vault-librarian migrate            Run database migrations
vault-librarian log                Query audit log (--agent, --note, --since, --limit)
```

---

## 14. Technology Stack

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

## 15. Out of Scope (v1)

- Chat / conversational query interface (handled by Claude Code + Copilot CLI via MCP)
- Multi-vault support
- Real-time collaboration / conflict resolution between users
- Cloud hosting / containerisation (runs locally or on homelab)

## 16. Future Consideration

- Web UI dashboard — status view, agent run history, vault health score, Inbox management
- LanceDB as a drop-in ChromaDB replacement (better performance at scale, same embedded model)
- STAR story miner — scan Project and Career notes for STAR story candidates (interview/perf review prep)
