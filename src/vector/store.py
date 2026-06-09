from __future__ import annotations

from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings


class VectorStore:
    def __init__(self, vault_root: str, embedder: Embeddings) -> None:
        persist_dir = str(Path(vault_root) / ".librarian" / "chroma")
        client = chromadb.PersistentClient(path=persist_dir)
        self._store = Chroma(
            client=client,
            collection_name="vault",
            embedding_function=embedder,
        )

    def upsert(self, path: str, content: str) -> None:
        self._store.add_texts(texts=[content], ids=[path], metadatas=[{"path": path}])

    def search_similar(self, content: str, k: int = 5) -> list[str]:
        results = self._store.similarity_search(content, k=k)
        return [doc.metadata["path"] for doc in results]

    def delete(self, path: str) -> None:
        self._store.delete(ids=[path])
