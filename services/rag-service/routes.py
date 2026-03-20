"""
RAG service HTTP routes.

POST /rag/search   — full pipeline: cache → hybrid → rerank
POST /rag/ingest   — add error+fix pair to KB (sanitise → embed → upsert)
DELETE /rag/entry/{id} — remove entry from KB
GET /rag/stats     — KB size, cache hit rate
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import bm25_index as bm25_mod
import vector_store
from embedder import embed_text
from hybrid_search import hybrid_search
from reranker import rerank
from sanitiser import sanitise_fix_steps, sanitise_pattern
from semantic_cache import cache_lookup, cache_stats, cache_write

log = logging.getLogger(__name__)
router = APIRouter(prefix="/rag")


# ── Pydantic models ──────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    tags: list[str] | None = None
    use_cache: bool = True


class SearchResult(BaseModel):
    kb_entry_id: int
    error_pattern: str
    fix_steps: str
    rerank_score: float
    rrf_score: float | None = None
    source: str | None = None
    tags: list[str] | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    cache_hit: bool
    total: int


class IngestRequest(BaseModel):
    error_pattern: str = Field(..., min_length=10, max_length=2000)
    fix_steps: str = Field(..., min_length=10, max_length=2000)
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source: str = Field(default="manual")


class IngestResponse(BaseModel):
    kb_entry_id: int
    embedding_id: str


class StatsResponse(BaseModel):
    kb_size: int
    bm25_index_size: int
    cache: dict


# ── Dependencies ─────────────────────────────────────────────────────────────


async def _get_db(request: Request) -> AsyncSession:
    async with request.app.state.db_factory() as session:
        yield session


async def _get_redis(request: Request):
    return request.app.state.redis


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    redis=Depends(_get_redis),
):
    query_embedding = await embed_text(body.query)

    # 1. Semantic cache lookup
    if body.use_cache:
        cached = await cache_lookup(query_embedding, redis)
        if cached is not None:
            return SearchResponse(
                results=[SearchResult(**r) for r in cached[: body.top_k]],
                cache_hit=True,
                total=len(cached),
            )

    # 2. Hybrid retrieval
    candidates = await hybrid_search(body.query, top_k=body.top_k * 3, tags=body.tags)

    # 3. Rerank
    reranked = rerank(body.query, candidates, top_k=body.top_k)

    results = [
        SearchResult(
            kb_entry_id=r["kb_entry_id"],
            error_pattern=r["error_pattern"],
            fix_steps=r["fix_steps"],
            rerank_score=r.get("rerank_score", 0.0),
            rrf_score=r.get("rrf_score"),
            source=r.get("source"),
            tags=r.get("tags"),
        )
        for r in reranked
    ]

    # 4. Write to cache
    if body.use_cache and results:
        serialised = [r.model_dump() for r in results]
        await cache_write(query_embedding, serialised, redis, kind="active")

    return SearchResponse(results=results, cache_hit=False, total=len(results))


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest(
    body: IngestRequest,
    db: AsyncSession = Depends(_get_db),
):
    # Sanitise before storage
    clean_pattern = sanitise_pattern(body.error_pattern)
    clean_fix = sanitise_fix_steps(body.fix_steps)

    # Assign next bm25_doc_id
    row = await db.execute(text("SELECT COALESCE(MAX(bm25_doc_id), -1) + 1 FROM rag_kb_entries"))
    next_bm25_id: int = row.scalar()

    embedding_id = str(uuid.uuid4())

    # Insert into Postgres
    result = await db.execute(
        text(
            """
            INSERT INTO rag_kb_entries
                (error_pattern, fix_steps, tags, confidence, embedding_id, bm25_doc_id, source)
            VALUES
                (:pattern, :fix, :tags, :confidence, :embedding_id, :bm25_doc_id, :source)
            RETURNING id
            """
        ),
        {
            "pattern": clean_pattern,
            "fix": clean_fix,
            "tags": body.tags,
            "confidence": body.confidence,
            "embedding_id": embedding_id,
            "bm25_doc_id": next_bm25_id,
            "source": body.source,
        },
    )
    kb_id: int = result.scalar()
    await db.commit()

    # Embed and upsert into Qdrant
    vector = await embed_text(clean_pattern + " " + clean_fix)
    await vector_store.upsert_entry(
        embedding_id=embedding_id,
        vector=vector,
        payload={
            "kb_entry_id": kb_id,
            "error_pattern": clean_pattern,
            "fix_steps": clean_fix,
            "tags": body.tags,
            "confidence": body.confidence,
            "source": body.source,
        },
    )

    # Rebuild BM25 index in background (full rebuild from DB)
    import asyncio
    from bm25_index import get_index
    async def _rebuild():
        async with db.bind.connect() as conn:
            async with AsyncSession(bind=conn) as s:
                await get_index().build(s)
    asyncio.create_task(_rebuild())

    log.info("ingested kb_entry_id=%d embedding_id=%s", kb_id, embedding_id)
    return IngestResponse(kb_entry_id=kb_id, embedding_id=embedding_id)


@router.delete("/entry/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: int,
    db: AsyncSession = Depends(_get_db),
):
    row = await db.execute(
        text("SELECT embedding_id FROM rag_kb_entries WHERE id = :id"),
        {"id": entry_id},
    )
    record = row.fetchone()
    if not record:
        raise HTTPException(status_code=404, detail="Entry not found")

    embedding_id = record.embedding_id

    await db.execute(
        text("DELETE FROM rag_kb_entries WHERE id = :id"),
        {"id": entry_id},
    )
    await db.commit()

    if embedding_id:
        await vector_store.delete_entry(embedding_id)

    log.info("deleted kb_entry_id=%d", entry_id)


@router.get("/stats", response_model=StatsResponse)
async def stats(
    db: AsyncSession = Depends(_get_db),
    redis=Depends(_get_redis),
):
    kb_size = await vector_store.collection_size()
    try:
        bm25_size = bm25_mod.get_index().size
    except RuntimeError:
        bm25_size = 0
    cache = await cache_stats(redis)

    return StatsResponse(
        kb_size=kb_size,
        bm25_index_size=bm25_size,
        cache=cache,
    )
