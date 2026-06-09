from __future__ import annotations

import glob
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)


class _SecretAuthMiddleware(BaseHTTPMiddleware):
    """Require X-Librarian-Secret on every MCP request."""

    def __init__(self, app, secret_getter) -> None:
        super().__init__(app)
        self._get_secret = secret_getter

    async def dispatch(self, request: Request, call_next) -> Response:
        import hmac
        provided = request.headers.get("x-librarian-secret", "")
        if not hmac.compare_digest(provided, self._get_secret()):
            return Response("Unauthorized", status_code=401)
        return await call_next(request)


def _get_deps():
    """Late-import live state from the FastAPI lifespan module-level refs."""
    import src.api.app as _app
    from src.config import get_config
    return _app._db, _app._runner, get_config(), getattr(_app._runner, "_vector_store", None)


def _validate_note_path(path: str, cfg) -> Path:
    """Resolve and validate a note path against the vault root. Raises ValueError on escape."""
    from src.vault.tools import VaultTools
    tools = VaultTools(cfg.vault_path)
    if not path.endswith(".md"):
        raise ValueError(f"Path must end in .md: {path!r}")
    return tools.abs(path)  # raises ValueError on traversal or symlink


def build_mcp_server_lazy() -> FastMCP:
    """Build the MCP server using lazy dependency resolution via closures."""
    mcp = FastMCP("vault-librarian")

    @mcp.tool()
    async def scaffold_note(title: str, note_type: str, context: str = "") -> str:
        """Create a structured note stub in the vault."""
        from src.agents.scaffolder import run_scaffolder
        from src.llm.factory import build_llm
        from src.vault.tools import VaultTools
        db, runner, cfg, _ = _get_deps()
        if runner is None:
            return "Service not ready — start vault-librarian serve first"
        llm = build_llm(cfg)
        tools = VaultTools(cfg.vault_path)
        rel = run_scaffolder(title, note_type, context, llm, tools, cfg)
        return f"Created: {rel}"

    @mcp.tool()
    async def run_agent(agent: str, note_path: str) -> str:
        """Manually trigger a specific agent on a vault note."""
        from src.pipeline.builder import PIPELINE_ORDER
        db, runner, cfg, _ = _get_deps()
        if runner is None:
            return "Service not ready — start vault-librarian serve first"
        if agent not in PIPELINE_ORDER and agent not in ("auditor", "scaffolder"):
            return f"Unknown agent: {agent!r}. Valid: {PIPELINE_ORDER}"
        try:
            _validate_note_path(note_path, cfg)
        except ValueError as exc:
            return f"Invalid note path: {exc}"
        await runner.run(note_path)
        return f"Agent '{agent}' dispatched for {note_path}"

    @mcp.tool()
    async def search_vault(query: str, k: int = 5) -> str:
        """Semantic search across all vault notes. Returns ranked note paths."""
        db, runner, cfg, vector_store = _get_deps()
        if runner is None or vector_store is None:
            return "Service not ready"
        results = vector_store.search_similar(query, k=k)
        if not results:
            return "No results found."
        return "\n".join(f"- {r}" for r in results)

    @mcp.tool()
    async def get_note_metadata(path: str) -> str:
        """Get frontmatter and agent run history for a vault note."""
        from src.storage.repository import AgentRunRepo
        from src.vault.parser import parse_note
        db, runner, cfg, _ = _get_deps()
        if runner is None:
            return "Service not ready"
        try:
            abs_path = str(_validate_note_path(path, cfg))
        except ValueError as exc:
            return f"Invalid path: {exc}"
        try:
            meta = parse_note(abs_path, cfg.vault_path)
        except FileNotFoundError:
            return f"Note not found: {path}"
        completed = await AgentRunRepo(db).completed_agents(path, meta.content_hash)
        fm_str = "\n".join(f"  {k}: {v}" for k, v in meta.frontmatter.items())
        return (
            f"Path: {meta.path}\n"
            f"Title: {meta.title}\n"
            f"Type: {meta.note_type}\n"
            f"Tags: {meta.tags}\n"
            f"Words: {meta.word_count}\n"
            f"Frontmatter:\n{fm_str}\n"
            f"Completed agents: {sorted(completed)}"
        )

    @mcp.tool()
    async def list_notes(folder: str = "") -> str:
        """List notes in the vault with optional folder filter (max 50)."""
        from src.storage.repository import NoteRepo
        db, runner, cfg, _ = _get_deps()
        if runner is None:
            return "Service not ready"
        hash_by_path = await NoteRepo(db).all_hashes()
        paths = sorted(hash_by_path.keys())
        if folder:
            paths = [p for p in paths if p.startswith(folder.rstrip("/") + "/")]
        return "\n".join(f"- {p}" for p in paths[:50]) if paths else "No notes found."

    @mcp.tool()
    async def get_action_items() -> str:
        """Get outstanding unresolved action items extracted from vault notes."""
        from src.storage.repository import ActionItemRepo
        db, runner, cfg, _ = _get_deps()
        if runner is None:
            return "Service not ready"
        items = await ActionItemRepo(db).unresolved()
        if not items:
            return "No unresolved action items."
        return "\n".join(f"- [ ] {i.content} (from `{i.source_note}`)" for i in items[:20])

    @mcp.tool()
    async def get_audit_report() -> str:
        """Return the content of the latest vault audit report."""
        db, runner, cfg, _ = _get_deps()
        pattern = str(Path(cfg.vault_path) / ".librarian" / "Vault Audit — *.md")
        reports = sorted(glob.glob(pattern), reverse=True)
        if not reports:
            return "No audit report found. Run `vault-librarian run auditor` to generate one."
        return Path(reports[0]).read_text(encoding="utf-8")

    return mcp
