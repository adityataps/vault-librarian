"""CrewAI Jira sync agent factory."""
from __future__ import annotations

from typing import TYPE_CHECKING

from crewai import Agent

from src.llm.router import LLMRouter, TaskType

from .base import _make_llm

if TYPE_CHECKING:
    from src.storage.base import StorageBackend
    from src.tools.jira_client import JiraClient


def create_jira_sync_agent(
    router: LLMRouter,
    storage: StorageBackend,
    jira_client: JiraClient | None = None,
) -> Agent:
    return Agent(
        role="Jira Sync Agent",
        goal=(
            "Synchronize Jira tickets with Obsidian vault notes. For each Jira ticket, "
            "create or update a corresponding markdown note with ticket details, status, "
            "and links. Keep notes in sync with the latest Jira data."
        ),
        backstory=(
            "You are a project management assistant who bridges Jira and Obsidian. "
            "You format Jira ticket data into clean, readable markdown notes following "
            "the vault's conventions. You update existing notes rather than creating "
            "duplicates, and you preserve any manual notes added to ticket files."
        ),
        llm=_make_llm(router, TaskType.WRITING),
        tools=[],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )
