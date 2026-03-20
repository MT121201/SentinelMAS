"""
Cross-encoder reranker using sentence-transformers.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (loaded once at startup).
Takes (query, passage) pairs and returns relevance scores.
Reranks the top-N candidates from hybrid search.
"""

import logging
from functools import lru_cache

from sentence_transformers import CrossEncoder

from config import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_model() -> CrossEncoder:
    """Load cross-encoder model. Cached — only loads once per process."""
    log.info("loading reranker model %s", settings.rerank_model)
    model = CrossEncoder(settings.rerank_model)
    log.info("reranker model loaded")
    return model


def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """
    Rerank candidate passages using the cross-encoder.

    candidates: list of dicts from hybrid_search — must have 'error_pattern' and 'fix_steps'.
    Returns top_k candidates sorted by cross-encoder score descending.
    Each returned dict gains a 'rerank_score' key.
    """
    if not candidates:
        return []

    model = _load_model()

    # Build (query, passage) pairs — concatenate pattern + fix_steps as the passage
    pairs = [
        (query, f"{c['error_pattern']} {c['fix_steps']}")
        for c in candidates
    ]

    scores = model.predict(pairs)

    ranked = sorted(
        zip(candidates, scores),
        key=lambda x: x[1],
        reverse=True,
    )

    results = []
    for candidate, score in ranked[:top_k]:
        results.append({**candidate, "rerank_score": float(score)})

    return results


async def preload_model() -> None:
    """Trigger model load at startup so the first request isn't slow."""
    import asyncio
    await asyncio.to_thread(_load_model)
