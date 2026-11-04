from typing import Protocol

from app.schemas.domain import ContextChunk


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    async def upsert(self, project_id: str, chunks: list[ContextChunk],
                     embeddings: list[list[float]]) -> None: ...
    async def search(self, project_id: str, embedding: list[float],
                     limit: int = 8) -> list[ContextChunk]: ...
