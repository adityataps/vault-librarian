# Vault Librarian — Requirements

Companion to `docs/design/architecture.md`. Captures functional/non-functional
requirements and phase boundaries agreed during the design discussion.

## 1. Goals

Rework of a previously not-entirely-functional service. This iteration must
be reliable, safe against data loss (git-backed rollback), and cost/latency
aware (deterministic-first, model tiering, throttled concurrency).

## 2. Phasing

### Phase 1 — MVP
- Reactive lightweight workflows on file create/save/delete:
  - Formatting
  - Backlinking/tagging suggestions
  - Frontmatter updates
  - Spellcheck
  - Mermaid diagram validation (+ fix cascade, see below)
- Quiescence-based debounce (per-file timer, resets on new writes).
- Vault-resident `Config.md`, hot-reloaded on save. Drives:
  - Per-workflow enable/disable
  - Debounce window
  - Model tier per workflow
  - Path ignore-list (also feeds `.gitignore`)
- Frontmatter automation control, granular and opt-out by default:
  ```yaml
  vault-librarian:
    enabled: true
    skip: [spellcheck, backlink]
  ```
- Git safety net: local-only commits, scoped `git add`, distinct commit
  author, one commit per workflow run.
- Global workflow concurrency = 1 (single sequential worker, FIFO queue).
- Tiered stdout logging (info/verbose/warning/error).
- `Librarian/Activity Log.md` and `Librarian/Failed Processing.md`.
- Failure quarantine: stop retrying a file after N consecutive failures.
- LLM providers: `github_copilot/*` (LiteLLM, OAuth device flow),
  `anthropic/*` (API key), `ollama/*` (local).
- `--dry-run` CLI mode.

### Phase 2 — Directives + Knowledge base
- Inline agent directives: `<agent-research>`, `<agent-do>`,
  `<agent-diagram>`, wrapped in real HTML comments (invisible in Obsidian's
  Reading/Live Preview, visible in Source mode).
  - Lifecycle: `pending → running → done`, re-runnable by resetting status.
  - Original prompt preserved in a hidden attribute for re-runs.
  - Results carry timestamp + model-used for staleness tracking.
- Vault-wide vector KB (LanceDB, embedded, external to vault), incrementally
  indexed; throttled backfill via the same concurrency=1 queue.

### Phase 3 — Organizational agent
- Scheduled full-vault review proposing moves/renames/restructuring into
  `Librarian/Todo.md` as checkboxes (native Obsidian editing — no custom
  plugin needed for MVP of this phase).
- User approves/comments directly in `Todo.md`.
- Execution on schedule or save-debounce; multi-file operations (e.g.
  renames touching backlinks across files) committed as **one atomic git
  transaction**.
- Internal agent reasoning kept as hidden markdown comments.

### Phase 4 — MCP server + on-demand access
- MCP server exposing workflows as tools to Copilot, Claude, and other MCP
  clients, backed by the same dispatcher/queue.
- Scheduled backup workflow (non-AI): git push of vault history to a remote
  (private GitHub repo or local bare repo on external/NAS storage) +
  separate rsync/rclone leg for gitignored attachments.

### Phase 5+ — Nice to have
- Obsidian companion plugin (subsumes terminal/web UI ask — bigger
  investment, separate TS/JS codebase against the Obsidian Plugin API).
- Multi-vault support in a single service instance.

## 3. Functional requirements

| ID | Requirement | Phase |
|---|---|---|
| FR-1 | Watch vault for file create/save/delete events | 1 |
| FR-2 | Debounce workflow execution using quiescence (not fixed delay) | 1 |
| FR-3 | Run formatting, backlink/tag, frontmatter, spellcheck workflows | 1 |
| FR-4 | Validate mermaid diagrams deterministically; auto-fix mechanically; escalate to LLM fix agent with parser error context if needed; quarantine after ~3 failed attempts | 1 |
| FR-5 | Per-file, per-workflow automation opt-out via frontmatter, opt-out by default (enabled unless explicitly skipped) | 1 |
| FR-6 | Vault-resident `Config.md`, hot-reloaded on save, driving workflow enablement, debounce window, model tiers, ignore-list | 1 |
| FR-7 | Commit every automated edit to local git, scoped to touched files, distinct author, never touch remotes | 1 |
| FR-8 | Serialize all workflow execution globally (concurrency = 1) | 1 |
| FR-9 | Tiered stdout logging + vault-resident Activity Log | 1 |
| FR-10 | Vault-resident Failed Processing log after retry exhaustion | 1 |
| FR-11 | Support `github_copilot`, `anthropic`, `ollama` as LLM providers via LiteLLM | 1 |
| FR-12 | `--dry-run` CLI mode | 1 |
| FR-13 | Inline agent directives with pending/running/done lifecycle, invisible via HTML comments | 2 |
| FR-14 | Vault-wide vector KB, incrementally indexed | 2 |
| FR-15 | Scheduled organizational agent proposing changes to `Todo.md` | 3 |
| FR-16 | Atomic multi-file git commits for org-agent executions | 3 |
| FR-17 | MCP server exposing workflows on demand | 4 |
| FR-18 | Scheduled git-remote backup + attachment rsync leg | 4 |

## 4. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | Deterministic implementations preferred over LLM calls wherever the task is mechanical; LLM used only for fuzzy/generative tasks or as an escalation path |
| NFR-2 | Librarian's own operational state (job DB, vector DB, logs) lives outside the vault, keyed by vault path — vault git history contains only content changes |
| NFR-3 | One path ignore-list is the single source of truth for both watcher exclusions and `.gitignore` contents |
| NFR-4 | Feedback-loop guard: the watcher must not reprocess the librarian's own writes |
| NFR-5 | No secrets in vault content; API keys via `.env`/OS keychain; Copilot uses OAuth device flow (no static key) |
| NFR-6 | Cold-start backfill on an existing large vault must not burst-call the LLM API — same throttled concurrency=1 queue applies |
| NFR-7 | Model tier configurable per workflow type, with sensible defaults (cheap/fast for reactive workflows, stronger for research/org-agent) |

## 5. Explicitly out of scope (for now)
- Pushing librarian's safety-net commits to any remote.
- git-lfs / binary diffing for attachments (attachments are gitignored
  entirely instead).
- A dedicated web/terminal UI before Phase 5 (Todo.md checkboxes cover
  Phase 3's approval flow; Obsidian plugin is the eventual richer UI).
- Separate "privacy tier" concept — local-only processing is achieved by
  selecting the `ollama` provider for a given workflow/note, not a distinct
  mechanism.
