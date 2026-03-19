# dev_note — rag-service

## Purpose
Hybrid retrieval service: dense vector (Qdrant) + sparse BM25, cross-encoder reranked, with Redis semantic cache in front. Knowledge base for GPU error+fix patterns.

## Files
> Phase 0 scaffold — no code files yet. Built in Phase 3.

Planned files (from TODO.md P3-xx):
- `main.py` — FastAPI app
- `routes.py` — POST /rag/search, POST /rag/ingest, DELETE /rag/entry/{id}, GET /rag/stats
- `embedder.py` — OpenAI text-embedding-3-small, batch support
- `vector_store.py` — Qdrant client: collection setup, upsert, cosine search
- `bm25_index.py` — rank_bm25 index; persisted to Postgres, loaded on startup
- `hybrid_search.py` — parallel dense+sparse, Reciprocal Rank Fusion merge
- `reranker.py` — cross-encoder rerank top-20 → top-5 (model loaded once at startup)
- `semantic_cache.py` — Redis cosine cache check (threshold: 0.92) before retrieval
- `sanitiser.py` — strip PII/IPs/hostnames from patterns before storage

## Cross-Service Contracts
- Called by: `client-agent` (search + ingest)
- Depends on: Qdrant (vector store), Redis (semantic cache), Postgres (BM25 index persistence)
- Listens on: port 8005
- KB starts EMPTY — degrades gracefully to caller's web search fallback

## Cache TTL Policy
| Type | TTL |
|---|---|
| Active error fix (last 7 days) | 3600s |
| Static knowledge | 86400s |
| Web search results | 1800s |

## Known Gaps / Deferred
- Phase 0: directory scaffold only
- Reranker model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) downloads on first container start (~90MB)
