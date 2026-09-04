"""Typer CLI (architecture.md §4.16).

`run` starts the live service. `log`/`rollback` are standalone git wrappers that work even
when the service isn't running (§4.19). `status`/`list` inspect state without needing a
live control-plane connection for this Phase 1 pass (the unified MCP/REST control plane is
a fast-follow — see FR-22).
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import signal
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from vault_librarian import state
from vault_librarian.config import ConfigManager
from vault_librarian.dispatcher import Dispatcher
from vault_librarian.git_safety import GitSafetyNet
from vault_librarian.jobs.store import JobStore
from vault_librarian.llm.factory import LLMFactory
from vault_librarian.logging_setup import configure_logging
from vault_librarian.watcher import Watcher

app = typer.Typer(add_completion=False, help="Vault Librarian — Obsidian vault automation service")
console = Console()

VAULT_ENV_VAR = "VAULT_LIBRARIAN_VAULT"


def _resolve_vault(vault: Optional[Path]) -> Path:
    if vault is None:
        env = os.environ.get(VAULT_ENV_VAR)
        if env:
            vault = Path(env)
    if vault is None:
        console.print(f"[red]No vault specified.[/red] Pass --vault <path> or set {VAULT_ENV_VAR}.")
        raise typer.Exit(code=1)
    vault = vault.expanduser().resolve()
    if not vault.is_dir():
        console.print(f"[red]Vault path does not exist or is not a directory:[/red] {vault}")
        raise typer.Exit(code=1)
    return vault


def _abs(vault_path: Path, file: Path) -> Path:
    return file if file.is_absolute() else (vault_path / file)


def _acquire_lock(lock_path: Path):
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.write(str(os.getpid()))
    f.flush()
    return f


def _release_lock(lock_file, lock_path: Path) -> None:
    if lock_file is None:
        return
    fcntl.flock(lock_file, fcntl.LOCK_UN)
    lock_file.close()
    try:
        lock_path.unlink()
    except OSError:
        pass


@app.command()
def run(
    vault: Optional[Path] = typer.Option(None, "--vault", help="Path to the Obsidian vault to watch"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Log what would change without writing/committing"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose (debug) logging"),
    polling: bool = typer.Option(
        False, "--polling", help="Use a polling filesystem observer (for containers/bind mounts)"
    ),
) -> None:
    """Start the service: watch the vault and run reactive workflows."""
    vault_path = _resolve_vault(vault)
    configure_logging(verbose=verbose)
    asyncio.run(_run_async(vault_path, dry_run=dry_run, polling=polling))


async def _run_async(vault_path: Path, dry_run: bool, polling: bool) -> None:
    logger = logging.getLogger("vault_librarian.cli")
    state.register_vault(vault_path)
    vault_state_dir = state.state_dir(vault_path)

    lock_path = vault_state_dir / "vault-librarian.lock"
    lock_file = _acquire_lock(lock_path)
    if lock_file is None:
        console.print(
            f"[red]Another vault-librarian instance is already running for this vault[/red] "
            f"({vault_path})."
        )
        raise typer.Exit(code=1)

    try:
        config_manager = ConfigManager(vault_path)
        config = config_manager.config

        git_safety = GitSafetyNet(vault_path, ignore_paths=config.ignore_paths)
        recovered_sha = await git_safety.recover_dirty_tree()
        if recovered_sha:
            logger.warning("recovered dirty working tree on startup: %s", recovered_sha[:10])

        job_store = JobStore(vault_state_dir / "jobs.db")
        await job_store.init()

        llm_factory = LLMFactory(config.models)
        dispatcher = Dispatcher(vault_path, config_manager, git_safety, job_store, llm_factory, dry_run=dry_run)
        dispatcher.start()

        watcher = Watcher(vault_path, config.ignore_paths, use_polling=polling)

        async def _config_watch_loop() -> None:
            config_path = vault_path / "Librarian" / "Config.md"
            last_mtime = config_path.stat().st_mtime if config_path.exists() else None
            while True:
                await asyncio.sleep(2)
                if not config_path.exists():
                    continue
                mtime = config_path.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    ok, error = config_manager.reload()
                    if ok:
                        logger.info("Config.md reloaded")
                        git_safety.sync_gitignore(config_manager.config.ignore_paths)
                    else:
                        logger.error("Config.md reload failed, keeping previous config: %s", error)

        async def _forward_events() -> None:
            while True:
                event_type, path = await watcher.events.get()
                dispatcher.notify(event_type, path)

        watcher.start()
        logger.info("vault-librarian started for %s (dry_run=%s)", vault_path, dry_run)

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        forward_task = asyncio.create_task(_forward_events())
        config_task = asyncio.create_task(_config_watch_loop())
        try:
            await stop_event.wait()
        finally:
            logger.info("shutting down...")
            forward_task.cancel()
            config_task.cancel()
            watcher.stop()
            await dispatcher.stop()
            await job_store.close()
    finally:
        _release_lock(lock_file, lock_path)


@app.command()
def log(
    file: Path = typer.Argument(..., help="File path (relative to vault or absolute)"),
    vault: Optional[Path] = typer.Option(None, "--vault"),
    max_count: int = typer.Option(20, "--max"),
) -> None:
    """Show vault-librarian's git history for a file."""
    vault_path = _resolve_vault(vault)
    git_safety = GitSafetyNet(vault_path)
    history = asyncio.run(git_safety.log_history(_abs(vault_path, file), max_count))
    if not history:
        console.print("[yellow]No history found for this file.[/yellow]")
        return
    table = Table(show_header=True)
    table.add_column("SHA")
    table.add_column("Date")
    table.add_column("Author")
    table.add_column("Message")
    for entry in history:
        table.add_row(entry["sha"], entry["date"], entry["author"], entry["message"])
    console.print(table)


@app.command()
def rollback(
    file: Path = typer.Argument(...),
    vault: Optional[Path] = typer.Option(None, "--vault"),
    commit: Optional[str] = typer.Option(
        None, "--commit", help="Specific commit sha to roll back to (defaults to the commit before the latest)"
    ),
) -> None:
    """Revert a file to a prior commit."""
    vault_path = _resolve_vault(vault)
    git_safety = GitSafetyNet(vault_path)
    try:
        sha = asyncio.run(git_safety.rollback(_abs(vault_path, file), commit))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Rolled back {file} (now at {sha[:10]})[/green]")


@app.command(name="list")
def list_vaults() -> None:
    """List known vaults (previously run against)."""
    vaults = state.list_vaults()
    if not vaults:
        console.print("[yellow]No known vaults yet — run `vault-librarian run --vault <path>` first.[/yellow]")
        return
    table = Table(show_header=True)
    table.add_column("ID")
    table.add_column("Path")
    for vault_id, path in vaults.items():
        table.add_row(vault_id, path)
    console.print(table)


@app.command()
def status(vault: Optional[Path] = typer.Option(None, "--vault")) -> None:
    """Show whether the service is currently running for a vault (via its PID lockfile)."""
    vault_path = _resolve_vault(vault)
    vault_state_dir = state.state_dir(vault_path)
    lock_path = vault_state_dir / "vault-librarian.lock"
    if not lock_path.exists():
        console.print("[yellow]Not running[/yellow] (no lockfile found).")
        return
    pid_text = lock_path.read_text().strip()
    console.print(f"[green]Lockfile present[/green] (pid {pid_text}) at {lock_path}")


if __name__ == "__main__":
    app()
