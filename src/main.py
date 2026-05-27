"""vault-crawler main entrypoint — CLI and service launcher."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

app = typer.Typer(
    name="vault-crawler",
    help="Multi-agent Obsidian vault management service",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
    # Quieten noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("watchdog").setLevel(logging.WARNING)


def _get_settings():
    from src.config import get_settings
    return get_settings()


# ── Commands ───────────────────────────────────────────────────────────────────

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev)"),
    log_level: str = typer.Option("info", "--log-level", help="Uvicorn log level"),
) -> None:
    """Start the vault-crawler API server with scheduler and file watcher."""
    _setup_logging(log_level.upper())
    settings = _get_settings()

    console.print(f"[bold green]vault-crawler[/] v0.1.0 — {settings.environment} mode")
    console.print(f"  Vault:   [cyan]{settings.vault.path}[/]")
    console.print(f"  Storage: [cyan]{settings.storage_backend}[/]")
    console.print(f"  LLM:     [cyan]{settings.llm.default_provider}[/]")
    console.print(f"  API:     [cyan]http://{host}:{port}[/]")
    console.print()

    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


@app.command()
def scan(
    output: str = typer.Option("table", "--output", "-o", help="Output format: table | json"),
) -> None:
    """Scan the vault and print a summary of all notes."""
    _setup_logging()
    settings = _get_settings()
    from src.watcher.scanner import VaultScanner

    console.print(f"Scanning vault: [cyan]{settings.vault.path}[/]")
    scanner = VaultScanner(
        vault_root=settings.vault.path,
        excluded_folders=list(settings.vault.excluded_folders),
        excluded_files=list(settings.vault.excluded_files),
    )
    result = scanner.scan()

    if output == "json":
        import json
        data = [
            {"path": n.path, "title": n.title, "folder": n.folder,
             "type": n.note_type, "tags": n.tags, "word_count": n.word_count}
            for n in result.parsed
        ]
        console.print_json(json.dumps(data))
    else:
        table = Table(title=f"Vault Scan — {result.success_count} notes")
        table.add_column("Path", style="cyan", no_wrap=False, max_width=60)
        table.add_column("Type", style="green")
        table.add_column("Tags", style="yellow")
        table.add_column("Words", justify="right")
        for n in result.parsed[:50]:
            table.add_row(n.path, n.note_type or "—", ", ".join(n.tags[:3]), str(n.word_count))
        if result.success_count > 50:
            table.add_row(f"… and {result.success_count - 50} more", "", "", "")
        console.print(table)

    if result.errors:
        console.print(f"\n[red]{result.error_count} parse errors:[/]")
        for path, err in result.errors[:5]:
            console.print(f"  {path}: {err}")


@app.command()
def migrate(
    revision: str = typer.Argument("head", help="Target revision (default: head)"),
) -> None:
    """Run Alembic database migrations."""
    _setup_logging()
    import subprocess
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", revision],
        capture_output=False,
    )
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
    console.print("[green]✓ Migrations applied[/]")


@app.command()
def index(
    force: bool = typer.Option(False, "--force", "-f", help="Re-index all notes, even unchanged"),
) -> None:
    """Index all vault notes into storage (upserts changed notes)."""
    _setup_logging()
    settings = _get_settings()

    async def _run() -> None:
        from src.storage import build_storage, NoteCreate
        from src.watcher.scanner import VaultScanner
        from src.tools.note_parser import compute_hash

        storage = build_storage(settings)
        await storage.initialize()

        scanner = VaultScanner(
            vault_root=settings.vault.path,
            excluded_folders=list(settings.vault.excluded_folders),
            excluded_files=list(settings.vault.excluded_files),
        )

        created = updated = skipped = 0
        with console.status("Indexing vault notes…"):
            for parsed in scanner.iter_notes():
                existing = await storage.get_note_by_path(parsed.path)
                if existing and existing.content_hash == parsed.content_hash and not force:
                    skipped += 1
                    continue

                note = NoteCreate(
                    path=parsed.path,
                    title=parsed.title,
                    folder=parsed.folder,
                    tags=parsed.tags,
                    type=parsed.note_type,  # type: ignore[arg-type]
                    status=parsed.status,  # type: ignore[arg-type]
                    content_hash=parsed.content_hash,
                    word_count=parsed.word_count,
                    last_modified=parsed.frontmatter.get("last_modified") or
                                  __import__("datetime").datetime.utcnow(),
                )
                await storage.save_note(note)
                if existing:
                    updated += 1
                else:
                    created += 1

        await storage.close()
        console.print(
            f"[green]✓ Index complete:[/] {created} created, {updated} updated, {skipped} skipped"
        )

    asyncio.run(_run())


@app.command()
def status() -> None:
    """Show service status: storage connectivity, LLM providers, scheduler jobs."""
    _setup_logging()
    settings = _get_settings()

    async def _run() -> None:
        from src.storage import build_storage, NoteFilter
        from src.llm import build_llm_router

        storage = build_storage(settings)
        await storage.initialize()

        table = Table(title="vault-crawler status")
        table.add_column("Component")
        table.add_column("Status")
        table.add_column("Detail")

        # Storage
        try:
            notes = await storage.query_notes(NoteFilter(limit=1))
            table.add_row("Storage", "[green]OK[/]", f"{settings.storage_backend}")
        except Exception as exc:
            table.add_row("Storage", "[red]ERROR[/]", str(exc))

        # LLM providers
        router = build_llm_router(settings)
        for name in ["copilot", "anthropic", "ollama"]:
            prov = router.get_provider(name)
            if prov:
                try:
                    ok = await prov.health_check()
                    table.add_row(f"LLM/{name}", "[green]OK[/]" if ok else "[yellow]UNREACHABLE[/]", "")
                except Exception as exc:
                    table.add_row(f"LLM/{name}", "[red]ERROR[/]", str(exc))

        # Vault
        table.add_row("Vault", "[green]OK[/]", str(settings.vault.path))

        # Jira
        jira_status = "[green]enabled[/]" if settings.jira.enabled else "[dim]disabled[/]"
        table.add_row("Jira", jira_status, settings.jira.base_url or "—")

        await storage.close()
        console.print(table)

    asyncio.run(_run())


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
