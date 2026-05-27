"""Redis-backed event bus for inter-component pub/sub messaging."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable
from uuid import uuid4

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventType(str, Enum):
    """All event types published on the bus."""

    # File system events
    NOTE_CREATED = "note.created"
    NOTE_MODIFIED = "note.modified"
    NOTE_DELETED = "note.deleted"
    NOTE_MOVED = "note.moved"

    # Agent lifecycle
    CREW_STARTED = "crew.started"
    CREW_COMPLETED = "crew.completed"
    CREW_FAILED = "crew.failed"

    # Jira events
    JIRA_TICKET_SYNCED = "jira.ticket.synced"
    JIRA_SYNC_COMPLETED = "jira.sync.completed"

    # Audit events
    AUDIT_COMPLETED = "audit.completed"
    AUDIT_FINDING = "audit.finding"

    # System
    VAULT_SCAN_STARTED = "vault.scan.started"
    VAULT_SCAN_COMPLETED = "vault.scan.completed"


@dataclass
class Event:
    """A published event on the bus."""

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: str = "vault-crawler"

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "type": self.type.value,
                "payload": self.payload,
                "timestamp": self.timestamp,
                "source": self.source,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "Event":
        data = json.loads(raw)
        return cls(
            type=EventType(data["type"]),
            payload=data.get("payload", {}),
            id=data.get("id", str(uuid4())),
            timestamp=data.get("timestamp", ""),
            source=data.get("source", ""),
        )


class InMemoryEventBus:
    """Synchronous in-memory event bus — fallback when Redis is unavailable."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Handler]] = {}

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: Event) -> None:
        for handler in self._handlers.get(event.type, []):
            try:
                await handler(event.payload)
            except Exception as exc:
                logger.error("Handler error for %s: %s", event.type, exc)

    async def close(self) -> None:
        pass


class RedisEventBus:
    """Redis pub/sub event bus.

    Publishers call ``publish(event)`` which writes to a Redis channel.
    Subscribers register handlers via ``subscribe(event_type, handler)``.
    Call ``start_consuming()`` to begin listening on a background task.
    """

    CHANNEL_PREFIX = "vc:events"

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._pub: aioredis.Redis | None = None
        self._sub: aioredis.client.PubSub | None = None
        self._handlers: dict[EventType, list[Handler]] = {}
        self._consumer_task: asyncio.Task | None = None

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Register an async handler for the given event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def on(self, event_type: EventType):
        """Decorator: @bus.on(EventType.NOTE_CREATED) async def handler(payload): ..."""
        def decorator(fn: Handler) -> Handler:
            self.subscribe(event_type, fn)
            return fn
        return decorator

    async def initialize(self) -> None:
        """Connect publisher and subscriber clients."""
        self._pub = aioredis.from_url(self._redis_url, decode_responses=True)
        sub_client = aioredis.from_url(self._redis_url, decode_responses=True)
        self._sub = sub_client.pubsub()
        # Subscribe to the wildcard channel pattern
        await self._sub.psubscribe(f"{self.CHANNEL_PREFIX}:*")
        logger.info("Redis event bus connected to %s", self._redis_url)

    async def start_consuming(self) -> None:
        """Start background consumer task."""
        if self._consumer_task and not self._consumer_task.done():
            return
        self._consumer_task = asyncio.create_task(self._consume_loop())
        logger.info("Event bus consumer started")

    async def publish(self, event: Event) -> None:
        """Publish an event to the Redis channel."""
        if not self._pub:
            raise RuntimeError("Event bus not initialized — call initialize() first")
        channel = f"{self.CHANNEL_PREFIX}:{event.type.value}"
        await self._pub.publish(channel, event.to_json())
        logger.debug("Published %s (id=%s)", event.type.value, event.id)

    async def close(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._sub:
            await self._sub.unsubscribe()
            await self._sub.aclose()
        if self._pub:
            await self._pub.aclose()
        logger.info("Event bus closed")

    async def _consume_loop(self) -> None:
        """Background loop that dispatches incoming messages to handlers."""
        if not self._sub:
            return
        try:
            async for message in self._sub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    event = Event.from_json(message["data"])
                    await self._dispatch(event)
                except Exception as exc:
                    logger.error("Failed to process event: %s", exc)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Consumer loop crashed: %s", exc)

    async def _dispatch(self, event: Event) -> None:
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            return
        await asyncio.gather(
            *[self._safe_call(h, event.payload) for h in handlers],
            return_exceptions=True,
        )

    @staticmethod
    async def _safe_call(handler: Handler, payload: dict[str, Any]) -> None:
        try:
            await handler(payload)
        except Exception as exc:
            logger.error("Event handler error: %s", exc)


def build_event_bus(redis_enabled: bool, redis_url: str = "") -> InMemoryEventBus | RedisEventBus:
    """Return the appropriate event bus based on config."""
    if redis_enabled and redis_url:
        return RedisEventBus(redis_url=redis_url)
    logger.info("Event bus: using in-memory fallback (Redis disabled)")
    return InMemoryEventBus()
