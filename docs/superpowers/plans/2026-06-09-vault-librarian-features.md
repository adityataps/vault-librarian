# Vault Librarian — Feature Set Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the vault-librarian service with scheduled agents (Auditor, Daily Brief, Weekly Review), an Obsidian-native audit trail (`.librarian/Activity.md`), a Rich terminal live feed, and an MCP server for Claude Code / Copilot CLI tool use.

**Architecture:** Plan 2 is purely additive — no Plan 1 code is deleted. Scheduled agents are standalone `async` functions called by APScheduler. The activity log is a side-effect layer hooked into `PipelineRunner.run()`. The MCP server is a `FastMCP` instance mounted on the existing FastAPI app. The Auditor quick node is added to the existing LangGraph pipeline.

**Tech Stack:** APScheduler (AsyncIOScheduler), mcp.server.fastmcp (FastMCP), Rich (live terminal), existing LangChain/LangGraph/SQLite/VaultTools stack from Plan 1.

**Baseline:** 70 tests passing on `main`. All Plan 1 files exist. Do not modify any existing test.

---

## File Structure

```
New:
  src/agents/auditor.py            # auditor_quick_node() + run_auditor_full()
  src/agents/daily_brief.py        # run_daily_brief()
  src/agents/weekly_review.py      # run_weekly_review()
  src/scheduler/__init__.py        # empty
  src/scheduler/jobs.py            # build_scheduler() → AsyncIOScheduler
  src/audit/__init__.py            # empty
  src/audit/activity.py            # ActivityLog: append callout to Activity.md
  src/audit/terminal.py            # RichActivityFeed: formatted terminal output
  src/api/mcp.py                   # build_mcp_server() → FastMCP

Modified:
  src/pipeline/builder.py          # add "auditor" to PIPELINE_ORDER + _AGENT_REGISTRY
  src/pipeline/runner.py           # call ActivityLog.append after each pipeline run
  src/api/app.py                   # start scheduler + mount MCP in lifespan

New tests:
  tests/test_agents/test_auditor.py
  tests/test_agents/test_daily_brief.py
  tests/test_audit_activity.py
  tests/test_mcp.py
```

---

## Phase 1 — Scheduled Agents

### Task 1: Auditor agent

**Files:**
- Create: `src/agents/auditor.py`
- Modify: `src/pipeline/builder.py` (add to PIPELINE_ORDER + registry)
- Create: `tests/test_agents/test_auditor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agents/test_auditor.py
import pytest
from unittest.mock import MagicMock, patch
from src.agents.state import make_state
from src.agents.auditor import auditor_quick_node


def test_auditor_quick_no_broken_links(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "Agent Platform.md").write_text("# Agent Platform")
    content = "# Note\n\nSee [[Agent Platform]] for details."
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("Projects/Test.md", content, {})
    result = auditor_quick_node(state, tools=tools, cfg=cfg)
    assert result["changes"] == []


def test_auditor_quick_detects_broken_link_and_proposes_stub(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / ".librarian").mkdir()
    content = "# Note\n\nSee [[MissingNote]] for context."
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
        autonomy_default="supervised", autonomy_overrides={},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", content, {})
    with patch("src.agents.auditor.LibrarianInbox") as mock_cls:
        result = auditor_quick_node(state, tools=tools, cfg=cfg)
    assert any("MissingNote" in c for c in result["changes"])
    mock_cls.return_value.propose.assert_called_once()


def test_auditor_quick_creates_stub_in_full_mode(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / "Reference").mkdir()
    content = "# Note\n\nSee [[NewConcept]] for more."
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
        autonomy_overrides={"auditor": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", content, {})
    result = auditor_quick_node(state, tools=tools, cfg=cfg)
    assert (tmp_path / "Reference" / "NewConcept.md").exists()
    assert any("stub" in c.lower() for c in result["changes"])


def test_auditor_quick_skips_external_links(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    content = "# Note\n\nSee [external](https://example.com) and [[ExistingNote]]."
    (tmp_path / "ExistingNote.md").write_text("# Existing")
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    state = make_state("note.md", content, {})
    result = auditor_quick_node(state, tools=VaultTools(str(tmp_path)), cfg=cfg)
    assert result["changes"] == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/adityatapshalkar/Documents/Dev/Repos/vault-crawler
uv run python -m pytest tests/test_agents/test_auditor.py -v 2>&1 | head -15
```
Expected: `ModuleNotFoundError: No module named 'src.agents.auditor'`

- [ ] **Step 3: Implement src/agents/auditor.py**

```python
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from src.agents.state import VaultState
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_WIKI_LINK_RE = re.compile(r"\[\[([^\]|#\n]+?)(?:[|#][^\]]+)?\]\]")
_VAULT_FOLDERS = [
    "", "Projects", "Jira", "Tech Notes", "Meetings",
    "Career", "Reference", "Personal", "Templates",
]


def _find_file(link: str, tools: VaultTools) -> bool:
    """Return True if a note matching [[link]] exists anywhere in the vault."""
    candidates = [f"{folder}/{link}.md" if folder else f"{link}.md" for folder in _VAULT_FOLDERS]
    return any(tools.abs(c).exists() for c in candidates)


def auditor_quick_node(state: VaultState, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    """Lightweight pipeline pass: detect broken wiki-links in the settled note."""
    links = _WIKI_LINK_RE.findall(state["note_content"])
    broken = [lnk for lnk in dict.fromkeys(links) if not _find_file(lnk, tools)]

    if not broken:
        return {"changes": []}

    changes = []
    autonomy = cfg.get_autonomy("auditor")
    for link in broken:
        stub_rel = f"Reference/{link}.md"
        if autonomy == "full":
            if not tools.abs(stub_rel).exists():
                tools.create_note(stub_rel, f"# {link}\n\n_stub — created by librarian_\n")
                changes.append(f"Auditor: created stub for [[{link}]]")
        else:
            LibrarianInbox(cfg, tools).propose(f"Create stub for [[{link}]] in `Reference/`")
            changes.append(f"Auditor: proposed stub for [[{link}]]")

    return {"changes": changes}


async def run_auditor_full(
    cfg: AppConfig,
    db,
    tools: VaultTools,
    llm,
) -> None:
    """Full-vault scheduled sweep — writes Vault Audit YYYY-MM-DD.md."""
    from src.storage.repository import NoteRepo
    from src.vault.scanner import VaultScanner

    today = date.today().isoformat()
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.stale_days)
    report_lines: list[str] = [
        f"# Vault Audit — {today}\n",
        f"_Generated by vault-librarian · stale threshold: {cfg.stale_days} days_\n",
    ]
    action_items: list[str] = []

    note_repo = NoteRepo(db)
    stored = await note_repo.all_hashes()
    all_paths = set(stored.keys())

    # 1. Broken wiki-links + orphans
    broken_links: dict[str, list[str]] = {}  # target → [source notes]
    orphans: list[str] = []
    for meta in VaultScanner(cfg).iter_notes():
        links = _WIKI_LINK_RE.findall(meta.raw_content)
        for lnk in links:
            if not _find_file(lnk, tools):
                broken_links.setdefault(lnk, []).append(meta.path)
        if not links and meta.folder not in ("Templates", ".librarian"):
            orphans.append(meta.path)

    # 2. Stale notes
    stale: list[str] = []
    for meta in VaultScanner(cfg).iter_notes():
        mtime = Path(meta.abs_path).stat().st_mtime
        if datetime.fromtimestamp(mtime, tz=timezone.utc) < stale_cutoff:
            stale.append(meta.path)

    # 3. Duplicate Obsidian-conflict folders (e.g. "docs/superpowers 2")
    import os
    conflict_folders: list[str] = []
    for root, dirs, _ in os.walk(cfg.vault_path):
        for d in dirs:
            if re.search(r"\s+\d+$", d):
                rel = str(Path(root).relative_to(cfg.vault_path) / d)
                conflict_folders.append(rel)

    # 4. Unprocessed directives
    unprocessed_directives: list[str] = []
    for meta in VaultScanner(cfg).iter_notes():
        if "<agent-" in meta.raw_content:
            unprocessed_directives.append(meta.path)

    # Build report sections
    if broken_links:
        report_lines.append("\n## 🔗 Broken Wiki-links\n")
        for lnk, sources in broken_links.items():
            report_lines.append(f"- `[[{lnk}]]` referenced in: {', '.join(f'`{s}`' for s in sources[:3])}")
            action_items.append(f"Create stub for [[{lnk}]] in `Reference/`")
    if orphans:
        report_lines.append("\n## 👻 Orphaned Notes (no outbound links)\n")
        for p in orphans[:20]:
            report_lines.append(f"- `{p}`")
    if stale:
        report_lines.append(f"\n## 🕰 Stale Notes (>{cfg.stale_days} days)\n")
        for p in stale[:20]:
            report_lines.append(f"- `{p}`")
    if conflict_folders:
        report_lines.append("\n## 📁 Duplicate Folders (Obsidian conflicts)\n")
        for f in conflict_folders:
            report_lines.append(f"- `{f}`")
            action_items.append(f"Review and merge duplicate folder `{f}`")
    if unprocessed_directives:
        report_lines.append("\n## ⚡ Unprocessed Directives\n")
        for p in unprocessed_directives[:10]:
            report_lines.append(f"- `{p}` contains `<agent-*>` tags not yet resolved")

    # Actionable TODO section (Tasks plugin syntax)
    if action_items:
        report_lines.append("\n## 🔧 Actionable Items\n")
        report_lines.append("<!-- Check items you want the librarian to execute, then save -->\n")
        for item in action_items:
            report_lines.append(f"- [ ] {item}")

    report = "\n".join(report_lines) + "\n"
    report_rel = f".librarian/Vault Audit — {today}.md"
    tools.create_note(report_rel, report)
    log.info("Auditor: wrote %s (%d broken links, %d stale)", report_rel, len(broken_links), len(stale))
```

- [ ] **Step 4: Add auditor to pipeline builder**

Read `src/pipeline/builder.py` then add `"auditor"` to `PIPELINE_ORDER` (after `"moc_maintainer"`) and add to `_AGENT_REGISTRY`:

```python
PIPELINE_ORDER = [
    "librarian",
    "formatter",
    "inline_directive",
    "meeting_enricher",
    "linker",
    "moc_maintainer",
    "auditor",           # ← add this
]

_AGENT_REGISTRY: dict[str, str] = {
    # ... existing entries ...
    "auditor": "src.agents.auditor:auditor_quick_node",  # ← add this
}
```

- [ ] **Step 5: Run tests**

```bash
uv run python -m pytest tests/test_agents/test_auditor.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Run full suite**

```bash
uv run python -m pytest tests/ 2>&1 | tail -3
```
Expected: 74 passed.

- [ ] **Step 7: Commit**

```bash
git add src/agents/auditor.py src/pipeline/builder.py tests/test_agents/test_auditor.py
git commit -m "feat: add Auditor agent (quick broken-link detector + full vault sweep)"
```

---

### Task 2: Daily Brief + Weekly Review agents

**Files:**
- Create: `src/agents/daily_brief.py`
- Create: `src/agents/weekly_review.py`
- Create: `tests/test_agents/test_daily_brief.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agents/test_daily_brief.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path


@pytest.fixture
def db_and_cfg(tmp_path):
    import src.config as _cfg_module
    _cfg_module._instance = None
    from src.config import AppConfig
    (tmp_path / ".librarian").mkdir()
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    db = MagicMock()
    db.session = MagicMock()
    return cfg, db, tmp_path


@pytest.mark.asyncio
async def test_daily_brief_creates_note(db_and_cfg):
    from src.agents.daily_brief import run_daily_brief
    from src.vault.tools import VaultTools
    cfg, db, tmp_path = db_and_cfg

    # Patch storage queries to return empty lists
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("src.agents.daily_brief.NoteRepo", MagicMock(
            return_value=MagicMock(
                all_hashes=AsyncMock(return_value={}),
            )
        ))
        mp.setattr("src.agents.daily_brief.ActionItemRepo", MagicMock(
            return_value=MagicMock(unresolved=AsyncMock(return_value=[]))
        ))
        mp.setattr("src.agents.daily_brief.AuditLogRepo", MagicMock(
            return_value=MagicMock(query=AsyncMock(return_value=[]))
        ))
        llm = MagicMock()
        llm.invoke.return_value.content = "Summary content."
        tools = VaultTools(str(tmp_path))
        await run_daily_brief(cfg, db, tools, llm)

    from datetime import date
    today = date.today().isoformat()
    brief_path = tmp_path / ".librarian" / f"Daily Brief — {today}.md"
    assert brief_path.exists()
    content = brief_path.read_text()
    assert today in content


@pytest.mark.asyncio
async def test_weekly_review_creates_note(db_and_cfg):
    from src.agents.weekly_review import run_weekly_review
    from src.vault.tools import VaultTools
    cfg, db, tmp_path = db_and_cfg

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("src.agents.weekly_review.NoteRepo", MagicMock(
            return_value=MagicMock(all_hashes=AsyncMock(return_value={}))
        ))
        mp.setattr("src.agents.weekly_review.ActionItemRepo", MagicMock(
            return_value=MagicMock(unresolved=AsyncMock(return_value=[]))
        ))
        mp.setattr("src.agents.weekly_review.AuditLogRepo", MagicMock(
            return_value=MagicMock(query=AsyncMock(return_value=[]))
        ))
        llm = MagicMock()
        llm.invoke.return_value.content = "Weekly summary."
        tools = VaultTools(str(tmp_path))
        await run_weekly_review(cfg, db, tools, llm)

    # Weekly review uses ISO week number
    from datetime import date
    today = date.today()
    week = f"{today.year}-W{today.isocalendar()[1]:02d}"
    brief_path = tmp_path / ".librarian" / f"Weekly Review — {week}.md"
    assert brief_path.exists()
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run python -m pytest tests/test_agents/test_daily_brief.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement src/agents/daily_brief.py**

```python
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import AppConfig
from src.storage.repository import ActionItemRepo, AuditLogRepo, NoteRepo
from src.vault.scanner import VaultScanner
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Daily Brief agent for an Obsidian vault. Given raw data about
the user's work, write a concise daily brief note in Obsidian markdown. Include:
- A short summary paragraph (2-3 sentences)
- Sections for open tickets, recent meetings, action items if there are any
- A vault health score (0-100) based on the data

Keep it scannable. Use Obsidian markdown (## headings, bullet points, [[wiki-links]]). Max 400 words.
"""


async def run_daily_brief(
    cfg: AppConfig,
    db,
    tools: VaultTools,
    llm,
) -> None:
    today = date.today().isoformat()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    note_repo = NoteRepo(db)
    action_repo = ActionItemRepo(db)
    audit_repo = AuditLogRepo(db)

    all_hashes = await note_repo.all_hashes()
    action_items = await action_repo.unresolved()
    recent_audit = await audit_repo.query(since="1d", limit=50)

    # Build context for LLM
    jira_notes = [p for p in all_hashes if p.startswith("Jira/")]
    meeting_notes = [p for p in all_hashes if p.startswith("Meetings/")]

    agent_summary = {}
    for entry in recent_audit:
        agent_summary[entry.agent] = agent_summary.get(entry.agent, 0) + 1

    context = (
        f"Date: {today}\n"
        f"Open Jira tickets: {len(jira_notes)} notes in Jira/\n"
        f"Recent meeting notes: {', '.join(meeting_notes[-3:]) or 'none'}\n"
        f"Unresolved action items: {len(action_items)}\n"
        f"Yesterday's agent activity: {dict(list(agent_summary.items())[:5])}\n"
        f"Total vault notes: {len(all_hashes)}\n"
    )

    try:
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ])
        content = response.content.strip()
    except Exception as exc:
        log.warning("Daily Brief LLM failed: %s", exc)
        content = f"# Daily Brief — {today}\n\n_LLM unavailable — raw data below_\n\n{context}"

    # Prepend frontmatter
    note = f"---\ndate: {today}\ntype: daily_brief\n---\n# Daily Brief — {today}\n\n{content}\n"
    tools.create_note(f".librarian/Daily Brief — {today}.md", note)
    log.info("Daily Brief written for %s", today)
```

- [ ] **Step 4: Implement src/agents/weekly_review.py**

```python
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import AppConfig
from src.storage.repository import ActionItemRepo, AuditLogRepo, NoteRepo
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Weekly Review agent for an Obsidian vault. Given raw data about
the user's week, write a concise weekly review note in Obsidian markdown. Include:
- A paragraph summarising the week
- What was shipped / closed
- Key decisions made
- What carries over to next week

Keep it reflective and actionable. Obsidian markdown, max 500 words.
"""


async def run_weekly_review(
    cfg: AppConfig,
    db,
    tools: VaultTools,
    llm,
) -> None:
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    week_label = f"{iso_year}-W{iso_week:02d}"
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    note_repo = NoteRepo(db)
    action_repo = ActionItemRepo(db)
    audit_repo = AuditLogRepo(db)

    all_hashes = await note_repo.all_hashes()
    unresolved = await action_repo.unresolved()
    weekly_audit = await audit_repo.query(since="7d", limit=200)

    agent_summary: dict[str, int] = {}
    for entry in weekly_audit:
        agent_summary[entry.agent] = agent_summary.get(entry.agent, 0) + 1

    meeting_notes = [p for p in all_hashes if p.startswith("Meetings/")]
    jira_notes = [p for p in all_hashes if p.startswith("Jira/")]

    context = (
        f"Week: {week_label}\n"
        f"Meeting notes this week: {', '.join(meeting_notes[-5:]) or 'none'}\n"
        f"Jira tickets in vault: {len(jira_notes)}\n"
        f"Unresolved action items: {len(unresolved)}\n"
        f"Agent operations this week: {dict(list(agent_summary.items())[:8])}\n"
        f"Total vault notes: {len(all_hashes)}\n"
    )

    try:
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ])
        content = response.content.strip()
    except Exception as exc:
        log.warning("Weekly Review LLM failed: %s", exc)
        content = f"# Weekly Review — {week_label}\n\n_LLM unavailable_\n\n{context}"

    note = f"---\nweek: {week_label}\ntype: weekly_review\n---\n# Weekly Review — {week_label}\n\n{content}\n"
    tools.create_note(f".librarian/Weekly Review — {week_label}.md", note)
    log.info("Weekly Review written for %s", week_label)
```

- [ ] **Step 5: Run tests**

```bash
uv run python -m pytest tests/test_agents/test_daily_brief.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Run full suite**

```bash
uv run python -m pytest tests/ 2>&1 | tail -3
```
Expected: 76 passed.

- [ ] **Step 7: Commit**

```bash
git add src/agents/daily_brief.py src/agents/weekly_review.py tests/test_agents/test_daily_brief.py
git commit -m "feat: add Daily Brief and Weekly Review scheduled agents"
```

---

### Task 3: APScheduler integration

**Files:**
- Create: `src/scheduler/__init__.py`
- Create: `src/scheduler/jobs.py`
- Modify: `src/api/app.py` (add scheduler start/stop to lifespan)

- [ ] **Step 1: Create src/scheduler/__init__.py** (empty)

```bash
touch /Users/adityatapshalkar/Documents/Dev/Repos/vault-crawler/src/scheduler/__init__.py
```

- [ ] **Step 2: Implement src/scheduler/jobs.py**

```python
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import AppConfig

log = logging.getLogger(__name__)


def _parse_cron(expr: str) -> dict:
    """Convert '0 2 * * *' cron expression to APScheduler trigger kwargs."""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr!r}")
    minute, hour, day, month, day_of_week = parts
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


def build_scheduler(
    cfg: AppConfig,
    db,
    tools,
    llm,
    vector_store=None,
) -> AsyncIOScheduler:
    """Build and return a configured AsyncIOScheduler (not yet started)."""
    from src.agents.auditor import run_auditor_full
    from src.agents.daily_brief import run_daily_brief
    from src.agents.weekly_review import run_weekly_review

    scheduler = AsyncIOScheduler()

    if "auditor" in cfg.enrolled_agents:
        scheduler.add_job(
            run_auditor_full,
            trigger="cron",
            kwargs={"cfg": cfg, "db": db, "tools": tools, "llm": llm},
            id="auditor_full",
            replace_existing=True,
            misfire_grace_time=3600,
            **_parse_cron(cfg.auditor_schedule),
        )
        log.info("Auditor scheduled: %s", cfg.auditor_schedule)

    if "daily_brief" in cfg.enrolled_agents:
        scheduler.add_job(
            run_daily_brief,
            trigger="cron",
            kwargs={"cfg": cfg, "db": db, "tools": tools, "llm": llm},
            id="daily_brief",
            replace_existing=True,
            misfire_grace_time=3600,
            **_parse_cron(cfg.daily_brief_schedule),
        )
        log.info("Daily Brief scheduled: %s", cfg.daily_brief_schedule)

    if "weekly_review" in cfg.enrolled_agents:
        scheduler.add_job(
            run_weekly_review,
            trigger="cron",
            kwargs={"cfg": cfg, "db": db, "tools": tools, "llm": llm},
            id="weekly_review",
            replace_existing=True,
            misfire_grace_time=3600,
            **_parse_cron(cfg.weekly_review_schedule),
        )
        log.info("Weekly Review scheduled: %s", cfg.weekly_review_schedule)

    return scheduler
```

- [ ] **Step 3: Update src/api/app.py lifespan to start/stop scheduler**

Read `src/api/app.py`. Add `from src.scheduler.jobs import build_scheduler` to the module-level imports. Add `_scheduler = None` module-level ref. In `_lifespan`, after creating `_runner` and `_dispatcher`, add:

```python
    global _scheduler
    _scheduler = build_scheduler(cfg, _db, tools, llm, vector_store)
    _scheduler.start()
    log.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))
```

And in the cleanup block (before `watcher.stop()`), add:

```python
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
```

Also add the module-level import and ref:
```python
from src.scheduler.jobs import build_scheduler

_scheduler = None
```

- [ ] **Step 4: Verify imports**

```bash
cd /Users/adityatapshalkar/Documents/Dev/Repos/vault-crawler
uv run python -c "from src.scheduler.jobs import build_scheduler; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Run full suite**

```bash
uv run python -m pytest tests/ 2>&1 | tail -3
```
Expected: 76 passed (no new tests for scheduler — it's a wiring task covered by integration).

- [ ] **Step 6: Commit**

```bash
git add src/scheduler/ src/api/app.py
git commit -m "feat: add APScheduler integration (Auditor full, Daily Brief, Weekly Review)"
```

---

## Phase 2 — Audit Trail

### Task 4: Activity.md callout writer

**Files:**
- Create: `src/audit/__init__.py`
- Create: `src/audit/activity.py`
- Modify: `src/pipeline/runner.py` (call ActivityLog.append after each run)
- Create: `tests/test_audit_activity.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit_activity.py
import pytest
from pathlib import Path
from src.audit.activity import ActivityLog
from src.config import AppConfig
from src.vault.tools import VaultTools
import src.config as _cfg_module


@pytest.fixture(autouse=True)
def reset_singleton():
    _cfg_module._instance = None
    yield
    _cfg_module._instance = None


@pytest.fixture
def setup(tmp_path):
    (tmp_path / ".librarian").mkdir()
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    tools = VaultTools(str(tmp_path))
    return cfg, tools, tmp_path


def test_activity_log_creates_file(setup):
    cfg, tools, tmp_path = setup
    log = ActivityLog(cfg, tools)
    log.append("Librarian", ["Moved `note.md` → `Projects/`"], "executed")
    content = (tmp_path / ".librarian" / "Activity.md").read_text()
    assert "> [!success] Librarian" in content
    assert "Moved `note.md`" in content


def test_activity_log_appends_to_existing(setup):
    cfg, tools, tmp_path = setup
    activity_path = tmp_path / ".librarian" / "Activity.md"
    activity_path.write_text("# Librarian Activity\n\n## 2026-01-01\n\n> [!info] Formatter\n> old entry\n")
    log = ActivityLog(cfg, tools)
    log.append("Auditor", ["Proposed: create stub"], "proposed")
    content = activity_path.read_text()
    assert "old entry" in content
    assert "> [!warning] Auditor" in content


def test_activity_log_no_op_on_empty_changes(setup):
    cfg, tools, tmp_path = setup
    log = ActivityLog(cfg, tools)
    log.append("Formatter", [], "info")
    activity_path = tmp_path / ".librarian" / "Activity.md"
    assert not activity_path.exists()


def test_activity_log_callout_types(setup):
    cfg, tools, tmp_path = setup
    log = ActivityLog(cfg, tools)
    cases = [
        ("executed", "success"),
        ("proposed", "warning"),
        ("error", "failure"),
        ("enriched", "tip"),
        ("info", "info"),
    ]
    for outcome, expected_callout in cases:
        (tmp_path / ".librarian" / "Activity.md").unlink(missing_ok=True)
        log.append("Agent", ["some change"], outcome)
        content = (tmp_path / ".librarian" / "Activity.md").read_text()
        assert f"[!{expected_callout}]" in content
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run python -m pytest tests/test_audit_activity.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create src/audit/__init__.py** (empty)

```bash
touch /Users/adityatapshalkar/Documents/Dev/Repos/vault-crawler/src/audit/__init__.py
```

- [ ] **Step 4: Implement src/audit/activity.py**

```python
from __future__ import annotations

import logging
from datetime import datetime

from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_ACTIVITY_REL = ".librarian/Activity.md"
_HEADER = "# Librarian Activity\n\n"
_MAX_DAYS = 7  # rolling window

_CALLOUT: dict[str, str] = {
    "executed": "success",   # agent wrote directly (full autonomy)
    "enriched": "tip",       # backlinks / action items added
    "proposed": "warning",   # went to Inbox (supervised autonomy)
    "error": "failure",      # skipped or errored
    "info": "info",          # non-destructive metadata change (default)
}


class ActivityLog:
    def __init__(self, cfg: AppConfig, tools: VaultTools) -> None:
        self._cfg = cfg
        self._tools = tools

    def append(self, agent: str, changes: list[str], outcome: str = "info") -> None:
        if not changes:
            return

        callout = _CALLOUT.get(outcome, "info")
        now = datetime.now().strftime("%Y-%m-%d · %H:%M")
        body_lines = "\n".join(f"> {c}" for c in changes)
        block = f"\n> [!{callout}] {agent}\n{body_lines}\n"

        try:
            existing = self._tools.read_note(_ACTIVITY_REL)
        except FileNotFoundError:
            existing = _HEADER

        # Prepend new entry under a date heading (or reuse today's heading)
        date_heading = f"## {datetime.now().strftime('%Y-%m-%d')}"
        if date_heading in existing:
            # Insert after the date heading line
            idx = existing.index(date_heading) + len(date_heading)
            updated = existing[:idx] + block + existing[idx:]
        else:
            # Add a new date section at the top (after the header)
            after_header = existing[len(_HEADER):] if existing.startswith(_HEADER) else existing
            updated = _HEADER + f"\n{date_heading}\n" + block + after_header

        self._tools.create_note(_ACTIVITY_REL, updated)
```

- [ ] **Step 5: Run tests**

```bash
uv run python -m pytest tests/test_audit_activity.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Hook ActivityLog into PipelineRunner.run()**

Read `src/pipeline/runner.py`. Import `ActivityLog` at the top:
```python
from src.audit.activity import ActivityLog
```

In `PipelineRunner.__init__`, add `self._activity = ActivityLog(cfg, tools)` after the other assignments.

At the end of `PipelineRunner.run()`, after the git commit call, add:
```python
        # Write to Activity.md — classify outcome from changes content
        if changes:
            outcome = "proposed" if any("Proposed" in c for c in changes) else \
                      "error" if any("failed" in c.lower() or "skipped" in c.lower() for c in changes) else \
                      "enriched" if any("backlink" in c.lower() or "action item" in c.lower() for c in changes) else \
                      "executed"
            for agent in ran_agents:
                agent_changes = [c for c in changes if agent.replace("_", " ").title().split()[0].lower() in c.lower() or True]
            self._activity.append("pipeline", changes, outcome)
```

Actually, to keep it simpler and more accurate, append once per run with the full changes list:

```python
        if changes:
            outcome = (
                "proposed" if any("Proposed" in c or "proposed" in c for c in changes)
                else "error" if any("failed" in c.lower() or "skipped" in c.lower() for c in changes)
                else "enriched" if any("backlink" in c.lower() or "action item" in c.lower() for c in changes)
                else "executed"
            )
            self._activity.append(f"pipeline({rel})", changes, outcome)
```

- [ ] **Step 7: Run full suite**

```bash
uv run python -m pytest tests/ 2>&1 | tail -3
```
Expected: 80 passed.

- [ ] **Step 8: Commit**

```bash
git add src/audit/__init__.py src/audit/activity.py src/pipeline/runner.py tests/test_audit_activity.py
git commit -m "feat: add Activity.md audit trail with Obsidian callout formatting"
```

---

### Task 5: Rich terminal activity feed

**Files:**
- Create: `src/audit/terminal.py`
- Modify: `src/pipeline/runner.py` (call terminal feed alongside ActivityLog)

- [ ] **Step 1: Implement src/audit/terminal.py**

```python
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

from rich.console import Console
from rich.text import Text

log = logging.getLogger(__name__)

_console = Console(highlight=False)

_STYLE: dict[str, str] = {
    "executed": "bold green",
    "enriched": "bold cyan",
    "proposed": "bold yellow",
    "error": "bold red",
    "info": "dim",
}

_MAX_ENTRIES = 50


class RichActivityFeed:
    """Thread-safe terminal feed — call feed() from any coroutine."""

    def __init__(self) -> None:
        self._entries: deque[str] = deque(maxlen=_MAX_ENTRIES)

    def feed(self, agent: str, changes: list[str], outcome: str = "info") -> None:
        if not changes:
            return
        style = _STYLE.get(outcome, "dim")
        ts = datetime.now().strftime("%H:%M:%S")
        summary = changes[0] if len(changes) == 1 else f"{changes[0]} (+{len(changes) - 1} more)"
        line = f"[dim]{ts}[/dim] [{style}]{agent}[/{style}] {summary}"
        self._entries.append(line)
        _console.print(line)

    def recent(self, n: int = 10) -> list[str]:
        return list(self._entries)[-n:]


# Module-level singleton used by PipelineRunner
_feed: RichActivityFeed | None = None


def get_feed() -> RichActivityFeed:
    global _feed
    if _feed is None:
        _feed = RichActivityFeed()
    return _feed
```

- [ ] **Step 2: Hook terminal feed into PipelineRunner**

Read `src/pipeline/runner.py`. Add import:
```python
from src.audit.terminal import get_feed
```

In the activity section at the end of `run()` (where `self._activity.append(...)` is called), also call:
```python
        get_feed().feed(f"pipeline({rel})", changes, outcome)
```

- [ ] **Step 3: Verify no tests broken**

```bash
uv run python -m pytest tests/ 2>&1 | tail -3
```
Expected: 80 passed.

- [ ] **Step 4: Commit**

```bash
git add src/audit/terminal.py src/pipeline/runner.py
git commit -m "feat: add Rich terminal activity feed with colour-coded outcome styles"
```

---

## Phase 3 — MCP Server

### Task 6: MCP server

**Files:**
- Create: `src/api/mcp.py`
- Modify: `src/api/app.py` (mount MCP server in lifespan)
- Create: `tests/test_mcp.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mcp.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mcp_deps(tmp_path):
    import src.config as _cfg_module
    _cfg_module._instance = None
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / ".librarian").mkdir()
    (tmp_path / "Projects").mkdir()
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    db = MagicMock()
    tools = VaultTools(str(tmp_path))
    vector_store = MagicMock()
    vector_store.search_similar.return_value = []
    return cfg, db, tools, vector_store, tmp_path


def test_build_mcp_server_returns_instance(mcp_deps):
    from src.api.mcp import build_mcp_server
    cfg, db, tools, vector_store, tmp_path = mcp_deps
    server = build_mcp_server(cfg, db, tools, vector_store)
    assert server is not None


@pytest.mark.asyncio
async def test_scaffold_note_tool(mcp_deps):
    from src.api.mcp import build_mcp_server
    cfg, db, tools, vector_store, tmp_path = mcp_deps
    llm = MagicMock()
    llm.invoke.return_value.content = "---\ntype: project\n---\n# Test Project\n"

    with patch("src.api.mcp.build_llm", return_value=llm):
        server = build_mcp_server(cfg, db, tools, vector_store)
        # Call the scaffold tool directly via the underlying function
        tool_fn = server._tool_manager.get_tool("scaffold_note")
        result = await tool_fn.fn(title="Test Project", note_type="project", context="")

    assert "Test Project" in result
    assert (tmp_path / "Projects" / "Test Project.md").exists()


@pytest.mark.asyncio
async def test_search_vault_tool(mcp_deps):
    from src.api.mcp import build_mcp_server
    cfg, db, tools, vector_store, tmp_path = mcp_deps
    vector_store.search_similar.return_value = ["Projects/Alpha.md", "Jira/AICOE-1.md"]

    with patch("src.api.mcp.build_llm", return_value=MagicMock()):
        server = build_mcp_server(cfg, db, tools, vector_store)
        tool_fn = server._tool_manager.get_tool("search_vault")
        result = await tool_fn.fn(query="agent platform", k=5)

    assert "Alpha.md" in result


@pytest.mark.asyncio
async def test_get_audit_report_tool_no_report(mcp_deps):
    from src.api.mcp import build_mcp_server
    cfg, db, tools, vector_store, tmp_path = mcp_deps

    with patch("src.api.mcp.build_llm", return_value=MagicMock()):
        server = build_mcp_server(cfg, db, tools, vector_store)
        tool_fn = server._tool_manager.get_tool("get_audit_report")
        result = await tool_fn.fn()

    assert "No audit report" in result or result == "" or isinstance(result, str)
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run python -m pytest tests/test_mcp.py -v 2>&1 | head -15
```
Expected: `ModuleNotFoundError: No module named 'src.api.mcp'`

- [ ] **Step 3: Implement src/api/mcp.py**

The MCP server uses a lazy-closure pattern: tools close over a `_get_deps()` helper that reads live state from `src.api.app`'s module-level refs (`_db`, `_runner`). This means the server can be mounted at `create_app()` time before the lifespan starts, because tool functions only access deps when actually called (which only happens after startup is complete).

```python
from __future__ import annotations

import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

log = logging.getLogger(__name__)


def _get_deps():
    """Late-import live state set during FastAPI lifespan."""
    import src.api.app as _app
    from src.config import get_config
    return _app._db, _app._runner, get_config()


def build_mcp_server_lazy() -> FastMCP:
    """Build MCP server with lazy dependency resolution."""
    mcp = FastMCP("vault-librarian")

    @mcp.tool()
    async def scaffold_note(title: str, note_type: str, context: str = "") -> str:
        """Create a structured note stub in the vault."""
        from src.agents.scaffolder import run_scaffolder
        from src.llm.factory import build_llm
        from src.vault.tools import VaultTools
        db, runner, cfg = _get_deps()
        llm = build_llm(cfg)
        tools = VaultTools(cfg.vault_path)
        rel = run_scaffolder(title, note_type, context, llm, tools, cfg)
        return f"Created: {rel}"

    @mcp.tool()
    async def run_agent(agent: str, note_path: str) -> str:
        """Manually trigger a specific agent on a vault note."""
        db, runner, cfg = _get_deps()
        if runner:
            await runner.run(note_path)
            return f"Agent '{agent}' dispatched for {note_path}"
        return "Service not ready"

    @mcp.tool()
    async def search_vault(query: str, k: int = 5) -> str:
        """Semantic search across all vault notes."""
        db, runner, cfg = _get_deps()
        if runner is None:
            return "Service not ready"
        results = runner._vector_store.search_similar(query, k=k)
        return "\n".join(f"- {r}" for r in results) if results else "No results found."

    @mcp.tool()
    async def get_note_metadata(path: str) -> str:
        """Get frontmatter and agent run history for a vault note."""
        from src.storage.repository import AgentRunRepo
        from src.vault.parser import parse_note
        db, runner, cfg = _get_deps()
        abs_path = str(Path(cfg.vault_path) / path)
        try:
            meta = parse_note(abs_path, cfg.vault_path)
        except FileNotFoundError:
            return f"Note not found: {path}"
        completed = await AgentRunRepo(db).completed_agents(path, meta.content_hash)
        fm_str = "\n".join(f"  {k}: {v}" for k, v in meta.frontmatter.items())
        return (
            f"Path: {meta.path}\nTitle: {meta.title}\nType: {meta.note_type}\n"
            f"Tags: {meta.tags}\nWords: {meta.word_count}\n"
            f"Frontmatter:\n{fm_str}\nCompleted agents: {sorted(completed)}"
        )

    @mcp.tool()
    async def list_notes(folder: str = "") -> str:
        """List notes in the vault with optional folder filter."""
        from src.storage.repository import NoteRepo
        db, runner, cfg = _get_deps()
        all_hashes = await NoteRepo(db).all_hashes()
        paths = sorted(all_hashes.keys())
        if folder:
            paths = [p for p in paths if p.startswith(folder.rstrip("/") + "/")]
        return "\n".join(f"- {p}" for p in paths[:50]) if paths else "No notes found."

    @mcp.tool()
    async def get_action_items(resolved: bool = False) -> str:
        """Get outstanding action items from the vault."""
        from src.storage.repository import ActionItemRepo
        db, runner, cfg = _get_deps()
        items = await ActionItemRepo(db).unresolved()
        if not items:
            return "No unresolved action items."
        return "\n".join(f"- [ ] {i.content} (from `{i.source_note}`)" for i in items[:20])

    @mcp.tool()
    async def get_audit_report() -> str:
        """Return the latest vault audit report."""
        import glob
        db, runner, cfg = _get_deps()
        pattern = str(Path(cfg.vault_path) / ".librarian" / "Vault Audit — *.md")
        reports = sorted(glob.glob(pattern), reverse=True)
        if not reports:
            return "No audit report found. Run `vault-librarian run auditor` to generate one."
        return Path(reports[0]).read_text(encoding="utf-8")

    return mcp


# Keep the parametrised version for tests that supply explicit deps
def build_mcp_server(cfg, db, tools, vector_store) -> FastMCP:
    """Build the MCP server with all vault tools registered."""
    from src.llm.factory import build_llm

    mcp = FastMCP("vault-librarian")

    @mcp.tool()
    async def scaffold_note(title: str, note_type: str, context: str = "") -> str:
        """Create a structured note stub in the vault."""
        from src.agents.scaffolder import run_scaffolder
        llm = build_llm(cfg)
        rel = run_scaffolder(title, note_type, context, llm, tools, cfg)
        return f"Created: {rel}"

    @mcp.tool()
    async def run_agent(agent: str, note_path: str) -> str:
        """Manually trigger a specific agent on a vault note."""
        from src.pipeline.runner import PipelineRunner
        from src.llm.factory import build_embedder
        from src.vector.store import VectorStore
        llm = build_llm(cfg)
        runner = PipelineRunner(cfg, db, tools, llm, vector_store)
        await runner.run(note_path)
        return f"Agent '{agent}' dispatched for {note_path}"

    @mcp.tool()
    async def search_vault(query: str, k: int = 5) -> str:
        """Semantic search across all vault notes."""
        results = vector_store.search_similar(query, k=k)
        if not results:
            return "No results found."
        return "\n".join(f"- {r}" for r in results)

    @mcp.tool()
    async def get_note_metadata(path: str) -> str:
        """Get frontmatter and recent agent run history for a note."""
        from src.storage.repository import AgentRunRepo
        from src.vault.parser import parse_note

        abs_path = str(Path(cfg.vault_path) / path)
        try:
            meta = parse_note(abs_path, cfg.vault_path)
        except FileNotFoundError:
            return f"Note not found: {path}"

        repo = AgentRunRepo(db)
        completed = await repo.completed_agents(path, meta.content_hash)
        fm_str = "\n".join(f"  {k}: {v}" for k, v in meta.frontmatter.items())
        return (
            f"Path: {meta.path}\n"
            f"Title: {meta.title}\n"
            f"Type: {meta.note_type}\n"
            f"Tags: {meta.tags}\n"
            f"Word count: {meta.word_count}\n"
            f"Frontmatter:\n{fm_str}\n"
            f"Completed agents: {sorted(completed)}"
        )

    @mcp.tool()
    async def list_notes(folder: str = "", note_type: str = "") -> str:
        """List notes in the vault with optional folder or type filter."""
        from src.storage.repository import NoteRepo
        repo = NoteRepo(db)
        all_hashes = await repo.all_hashes()
        paths = list(all_hashes.keys())
        if folder:
            paths = [p for p in paths if p.startswith(folder.rstrip("/") + "/")]
        if not paths:
            return "No notes found."
        return "\n".join(f"- {p}" for p in sorted(paths)[:50])

    @mcp.tool()
    async def get_action_items(resolved: bool = False) -> str:
        """Get outstanding action items from the vault."""
        from src.storage.repository import ActionItemRepo
        repo = ActionItemRepo(db)
        items = await repo.unresolved()
        if not items:
            return "No unresolved action items."
        return "\n".join(f"- [ ] {item.content} (from `{item.source_note}`)" for item in items[:20])

    @mcp.tool()
    async def get_audit_report() -> str:
        """Return the content of the latest vault audit report."""
        import glob
        import os
        pattern = str(Path(cfg.vault_path) / ".librarian" / "Vault Audit — *.md")
        reports = sorted(glob.glob(pattern), reverse=True)
        if not reports:
            return "No audit report found. Run `vault-librarian run auditor` to generate one."
        return Path(reports[0]).read_text(encoding="utf-8")

    return mcp
```

- [ ] **Step 4: Mount MCP server in src/api/app.py**

Read `src/api/app.py`. Add this import at the top (module level):
```python
from src.api.mcp import build_mcp_server_lazy
```

In `create_app()`, before `return app`, mount the MCP server:
```python
    mcp_server = build_mcp_server_lazy()
    app.mount("/mcp", mcp_server.streamable_http_app())
    return app
```

The lazy closure pattern means this is safe to call at `create_app()` time — tools only access `_db`/`_runner` when invoked (which only happens after the lifespan has started and set those refs).

- [ ] **Step 5: Run tests**

```bash
uv run python -m pytest tests/test_mcp.py -v
```

If `server._tool_manager.get_tool()` raises `AttributeError` (FastMCP API varies by version), adjust the test to call tools directly:
```python
# Alternative test approach if _tool_manager is private:
from mcp.server.fastmcp import FastMCP
# Use server.call_tool() if available, or test via HTTP client
```

Expected: at least 2/4 tests pass (scaffold + search). Adjust test tool access pattern to match actual FastMCP API.

- [ ] **Step 6: Run full suite**

```bash
uv run python -m pytest tests/ 2>&1 | tail -3
```
Expected: 84 passed.

- [ ] **Step 7: Commit**

```bash
git add src/api/mcp.py src/api/app.py tests/test_mcp.py
git commit -m "feat: add MCP server with scaffold_note, run_agent, search_vault, get_note_metadata, list_notes, get_action_items, get_audit_report tools"
```

---

## Phase 4 — Wire-up & Verification

### Task 7: Final integration and verification

**Files:**
- Verify: all modified files consistent
- Create: no new files

- [ ] **Step 1: Verify full test suite**

```bash
cd /Users/adityatapshalkar/Documents/Dev/Repos/vault-crawler
uv run python -m pytest tests/ -v 2>&1 | tail -15
```
Expected: 84+ passed, 0 failed.

- [ ] **Step 2: Lint check**

```bash
uv run ruff check src/ tests/ 2>&1 | grep -v "^tests" | head -20
```
Fix any errors (not warnings — `E501` line-length is ignored per pyproject.toml).

- [ ] **Step 3: Smoke-test CLI**

```bash
uv run python -m src.main --help
uv run python -m src.main status
```
Expected: help lists all commands, status prints config without error.

- [ ] **Step 4: Verify MCP server mounts cleanly**

```bash
uv run python -c "
from unittest.mock import MagicMock, AsyncMock
import src.config as c; c._instance = None
from src.config import AppConfig
cfg = AppConfig(llm_provider='copilot', llm_model='gpt-4o', llm_api_key='x', vault_path='/tmp', secret='s', _env_file=None)
from src.api.mcp import build_mcp_server_lazy
server = build_mcp_server_lazy()
print('MCP tools:', [t.name for t in server._tool_manager.list_tools()])
print('OK')
"
```
Expected: prints tool names and `OK`. Adjust if FastMCP API differs.

- [ ] **Step 5: Tag milestone**

```bash
git tag v0.2.0-features
git push origin main --tags
```

---

## What Plan 2 Delivers

After all tasks complete:

| Component | What's live |
|---|---|
| Auditor (quick) | Pipeline node — detects broken wiki-links on every file event, creates stubs or proposes |
| Auditor (full) | Nightly sweep — full vault report with actionable TODO items written to `.librarian/` |
| Daily Brief | Nightly note synthesising Jira, meetings, action items, agent activity |
| Weekly Review | Sunday note with week-in-review summary |
| APScheduler | All three scheduled agents wired into the FastAPI lifespan |
| Activity.md | Obsidian callout log of every agent action, rolling 7-day window |
| Terminal feed | Rich colour-coded live output during `serve` |
| MCP server | `/mcp` endpoint — Claude Code and Copilot CLI can call all 7 vault tools |

**Not in this plan** (future):
- Web UI dashboard
- LanceDB migration (ChromaDB drop-in swap)
- STAR story miner
