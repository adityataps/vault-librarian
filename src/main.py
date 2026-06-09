"""vault-librarian CLI entrypoint."""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

app = typer.Typer(name="vault-librarian", no_args_is_help=True)
console = Console()


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
    for noisy in ("httpx", "watchdog", "apscheduler", "chromadb"):
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


@app.command("install-hooks")
def install_hooks() -> None:
    """Install git post-commit hook into vault .git/hooks/."""
    from pathlib import Path

    from src.config import get_config

    cfg = get_config()
    hook_path = Path(cfg.vault_path) / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(
        "#!/bin/sh\ncurl -s -X POST http://localhost:8000/webhook/git "
        f"-H 'X-Librarian-Secret: {cfg.secret}' || true\n"
    )
    hook_path.chmod(0o755)
    console.print(f"[green]✓[/] Hook installed at {hook_path}")


if __name__ == "__main__":
    app()
