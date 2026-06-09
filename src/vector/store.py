from __future__ import annotations

import logging
from pathlib import Path

import lancedb
from langchain_core.embeddings import Embeddings

log = logging.getLogger(__name__)

_TABLE = "vault"


class VectorStore:
    def __init__(self, vault_root: str, embedder: Embeddings) -> None:
        persist_dir = str(Path(vault_root) / ".librarian" / "lancedb")
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(persist_dir)
        self._embedder = embedder
        self._table = None
        try:
            self._table = self._db.open_table(_TABLE)
        except Exception:
            pass  # created on first upsert

    def upsert(self, path: str, content: str) -> None:
        embedding = self._embedder.embed_query(content)
        row = {"path": path, "content": content, "vector": embedding}
        if self._table is None:
            self._table = self._db.create_table(_TABLE, data=[row])
        else:
            safe_path = path.replace("'", "''")
            try:
                self._table.delete(f"path = '{safe_path}'")
            except Exception:
                pass
            self._table.add([row])

    def search_similar(self, content: str, k: int = 5) -> list[str]:
        if self._table is None:
            return []
        try:
            embedding = self._embedder.embed_query(content)
            results = self._table.search(embedding).limit(k).to_list()
            return [r["path"] for r in results]
        except Exception as exc:
            log.warning("Vector search failed: %s", exc)
            return []

    def delete(self, path: str) -> None:
        if self._table is None:
            return
        safe_path = path.replace("'", "''")
        try:
            self._table.delete(f"path = '{safe_path}'")
        except Exception as exc:
            log.warning("Vector delete failed for %s: %s", path, exc)
