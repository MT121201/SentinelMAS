"""
Qdrant vector store client for the RAG knowledge base.

Collection: gpu_errors
Vectors: 1536-dimensional cosine similarity (text-embedding-3-small)
Payload: error_pattern, fix_steps, tags, confidence, source, kb_entry_id
"""

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from config import settings

log = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None


def _get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client


async def ensure_collection() -> None:
    """Create collection if it does not exist. Called on service startup."""
    client = _get_client()
    exists = await client.collection_exists(settings.qdrant_collection)
    if not exists:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(
                size=settings.embedding_dim,
                distance=Distance.COSINE,
            ),
        )
        log.info("created qdrant collection %s", settings.qdrant_collection)
    else:
        log.info("qdrant collection %s already exists", settings.qdrant_collection)


async def upsert_entry(
    embedding_id: str,
    vector: list[float],
    payload: dict[str, Any],
) -> None:
    """
    Upsert a single KB entry into Qdrant.

    embedding_id: UUID string used as the Qdrant point ID.
    payload keys expected: kb_entry_id, error_pattern, fix_steps, tags, confidence, source
    """
    client = _get_client()
    await client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            PointStruct(
                id=embedding_id,
                vector=vector,
                payload=payload,
            )
        ],
    )


async def delete_entry(embedding_id: str) -> None:
    """Delete a point by its UUID embedding_id."""
    client = _get_client()
    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=[embedding_id],
    )


async def dense_search(
    query_vector: list[float],
    top_k: int = 10,
    tags: list[str] | None = None,
) -> list[ScoredPoint]:
    """
    Semantic vector search. Optionally filter by tags (OR match).

    Returns up to top_k ScoredPoints with payload.
    """
    client = _get_client()
    query_filter = None
    if tags:
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="tags",
                    match=MatchAny(any=tags),
                )
            ]
        )

    results = await client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_vector,
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )
    return results


async def collection_size() -> int:
    """Return total number of points in the collection."""
    client = _get_client()
    info = await client.get_collection(settings.qdrant_collection)
    return info.points_count or 0
