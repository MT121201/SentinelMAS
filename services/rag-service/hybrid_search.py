"""
Hybrid retrieval: dense (Qdrant) + sparse (BM25) merged via Reciprocal Rank Fusion.

RRF formula: score(d) = Σ 1 / (k + rank(d))   where k=60 (standard default)
Results are keyed by kb_entry_id to deduplicate across both lists.
"""

import asyncio
import logging

from bm25_index import get_index
from embedder import embed_text
from vector_store import dense_search

log = logging.getLogger(__name__)

_RRF_K = 60


def _rrf_merge(
    dense_hits: list[dict],
    sparse_hits: list[dict],
) -> list[dict]:
    """
    Merge two ranked lists with Reciprocal Rank Fusion.

    dense_hits: list of dicts with kb_entry_id, score, error_pattern, fix_steps
    sparse_hits: same shape

    Returns merged list sorted by RRF score descending.
    """
    scores: dict[int, float] = {}
    meta: dict[int, dict] = {}

    for rank, hit in enumerate(dense_hits):
        kid = hit["kb_entry_id"]
        scores[kid] = scores.get(kid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        meta[kid] = hit

    for rank, hit in enumerate(sparse_hits):
        kid = hit["kb_entry_id"]
        scores[kid] = scores.get(kid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        if kid not in meta:
            meta[kid] = hit

    merged = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return [
        {**meta[kid], "rrf_score": scores[kid]}
        for kid in merged
    ]


async def hybrid_search(
    query: str,
    top_k: int = 10,
    tags: list[str] | None = None,
) -> list[dict]:
    """
    Run dense and sparse retrieval in parallel, then RRF-merge.

    Returns up to top_k results ordered by RRF score.
    Each result dict has: kb_entry_id, error_pattern, fix_steps, rrf_score.
    Dense results also carry: confidence, source, tags from Qdrant payload.
    """
    # Embed query and run BM25 concurrently
    query_vector, sparse_hits_raw = await asyncio.gather(
        embed_text(query),
        asyncio.to_thread(_bm25_search, query, top_k * 2),
    )

    # Dense search with the freshly computed vector
    dense_points = await dense_search(query_vector, top_k=top_k * 2, tags=tags)

    dense_hits = []
    for point in dense_points:
        payload = point.payload or {}
        dense_hits.append(
            {
                "kb_entry_id": payload.get("kb_entry_id"),
                "error_pattern": payload.get("error_pattern", ""),
                "fix_steps": payload.get("fix_steps", ""),
                "confidence": payload.get("confidence", 0.0),
                "source": payload.get("source", ""),
                "tags": payload.get("tags", []),
                "dense_score": point.score,
            }
        )
    # Filter out any hits where kb_entry_id is None (malformed entries)
    dense_hits = [h for h in dense_hits if h["kb_entry_id"] is not None]

    merged = _rrf_merge(dense_hits, sparse_hits_raw)
    return merged[:top_k]


def _bm25_search(query: str, top_k: int) -> list[dict]:
    """Synchronous BM25 search wrapper for asyncio.to_thread."""
    try:
        return get_index().search(query, top_k=top_k)
    except RuntimeError:
        log.warning("bm25 index not ready, skipping sparse retrieval")
        return []
