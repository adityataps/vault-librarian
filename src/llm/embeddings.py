"""Embedding service with optional caching."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from .router import LLMRouter

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 86400 * 7  # 7 days


class EmbeddingService:
    """Generates and caches embeddings for vault notes."""

    def __init__(
        self,
        router: LLMRouter,
        redis_client: "aioredis.Redis | None" = None,
        default_model: str = "text-embedding-3-small",
    ) -> None:
        self._router = router
        self._redis = redis_client
        self._model = default_model
        # In-process LRU cache when Redis is unavailable
        self._memory_cache: dict[str, list[float]] = {}
        self._max_memory_cache = 1000

    def _cache_key(self, text: str, model: str) -> str:
        digest = hashlib.sha256(f"{model}:{text}".encode()).hexdigest()
        return f"embed:{digest}"

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        """Embed text, returning cached vector if available."""
        m = model or self._model
        key = self._cache_key(text, m)

        # Try Redis cache
        if self._redis:
            try:
                cached = await self._redis.get(key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass

        # Try memory cache
        if key in self._memory_cache:
            return self._memory_cache[key]

        # Generate embedding
        resp = await self._router.embed(text, model=m)
        vector = resp.vector

        # Store in Redis
        if self._redis:
            try:
                await self._redis.setex(key, CACHE_TTL_SECONDS, json.dumps(vector))
            except Exception:
                pass

        # Store in memory (evict oldest if full)
        if len(self._memory_cache) >= self._max_memory_cache:
            oldest = next(iter(self._memory_cache))
            del self._memory_cache[oldest]
        self._memory_cache[key] = vector

        return vector

    async def embed_batch(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Embed multiple texts. Returns vectors in same order."""
        # Sequential for now; can be parallelised later
        return [await self.embed(t, model=model) for t in texts]

    def clear_memory_cache(self) -> None:
        self._memory_cache.clear()
