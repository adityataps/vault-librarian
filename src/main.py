"""vault-librarian CLI entrypoint."""

from __future__ import annotations

import logging

import truststore
import typer
from rich.console import Console
from rich.logging import RichHandler

# Use the OS trust store for SSL so corporate/system CAs are respected.
truststore.inject_into_ssl()

app = typer.Typer(name="vault-librarian", no_args_is_help=True)
console = Console()


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
    for noisy in ("httpx", "apscheduler", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
    agents: str = typer.Option("", "--agents", help="Comma-separated agent override"),
) -> None:
    """Start the vault-librarian service."""
    import uvicorn

    from src.config import get_config

    _setup_logging()
    cfg = get_config()
    if agents:
        cfg.enrolled_agents = [a.strip() for a in agents.split(",")]
    console.print(f"[bold green]vault-librarian[/] — vault: [cyan]{cfg.vault_path}[/]")
    uvicorn.run("src.api.app:create_app", factory=True, host=host, port=port, reload=reload)


@app.command()
def scan() -> None:
    """Scan vault and print note summary."""
    from src.config import get_config
    from src.vault.scanner import VaultScanner

    _setup_logging()
    cfg = get_config()
    scanner = VaultScanner(cfg)
    result = scanner.scan()
    console.print(f"Found [bold]{result.total}[/] notes, [red]{result.errors}[/] errors")


@app.command()
def index(force: bool = typer.Option(False, "--force")) -> None:
    """Reconcile all vault notes into storage."""
    import asyncio

    from src.config import get_config
    from src.pipeline.runner import reconcile_all

    _setup_logging()
    cfg = get_config()
    asyncio.run(reconcile_all(cfg, force=force))


@app.command()
def status() -> None:
    """Check service health."""
    from src.config import get_config

    _setup_logging()
    cfg = get_config()
    console.print(f"Vault: [cyan]{cfg.vault_path}[/]")
    console.print(f"Provider: [cyan]{cfg.llm_provider}/{cfg.llm_model}[/]")
    console.print(f"Agents: [cyan]{', '.join(cfg.enrolled_agents)}[/]")


@app.command()
def log(
    agent: str = typer.Option("", "--agent"),
    since: str = typer.Option("7d", "--since"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """Query agent audit log."""
    import asyncio

    from src.config import get_config
    from src.storage.db import build_db
    from src.storage.repository import AuditLogRepo

    _setup_logging()
    cfg = get_config()

    async def _run() -> None:
        db = build_db(cfg)
        await db.initialize()
        repo = AuditLogRepo(db)
        entries = await repo.query(agent=agent or None, since=since, limit=limit)
        for e in entries:
            console.print(f"[dim]{e.timestamp}[/] [bold]{e.agent}[/] {e.action} — {e.detail}")

    asyncio.run(_run())


@app.command("consolidate-inbox")
def consolidate_inbox() -> None:
    """Deduplicate and consolidate the Librarian Inbox using the LLM."""
    import asyncio

    from src.autonomy.inbox import LibrarianInbox
    from src.config import get_config
    from src.vault.tools import VaultTools

    _setup_logging()
    cfg = get_config()
    tools = VaultTools(cfg.vault_path)
    inbox = LibrarianInbox(cfg, tools)
    count = asyncio.run(inbox.consolidate())
    console.print(f"[green]✓[/] Consolidated inbox — [bold]{count}[/] curated items")


@app.command("install-hooks")
def install_hooks() -> None:
    """Install git post-commit hook into vault .git/hooks/."""
    import os
    from pathlib import Path

    from src.config import get_config

    cfg = get_config()
    hook_path = Path(cfg.vault_path) / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    # Secret is read from the environment inside the hook — never embedded in the file.
    # Atomic open with 0o700 (owner-only rwx) avoids the chmod-after-write race
    # and prevents other users from reading the script.
    script = (
        "#!/bin/sh\n"
        'SECRET="${LIBRARIAN_SECRET:-}"\n'
        'if [ -z "$SECRET" ]; then\n'
        "  echo 'vault-librarian: LIBRARIAN_SECRET not set, skipping webhook' >&2\n"
        "  exit 0\n"
        "fi\n"
        "curl -s -X POST http://localhost:8000/webhook/git "
        '-H "X-Librarian-Secret: $SECRET" || true\n'
    )
    fd = os.open(str(hook_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o700)
    try:
        os.write(fd, script.encode())
    finally:
        os.close(fd)

    console.print(f"[green]✓[/] Hook installed at {hook_path}")
    console.print("  Set [cyan]LIBRARIAN_SECRET[/] in your shell environment before committing.")


if __name__ == "__main__":
    app()
