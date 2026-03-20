# dev_note — rag-service

> Last updated: 2026-03-20
> Owner: RAG pipeline — knowledge base ingestion and retrieval for agent fix suggestions.

---

## config.py

| Setting | Default | Purpose |
|---|---|---|
| `openai_api_key` | `""` | OpenAI text-embedding-3-small |
| `embedding_model` | `text-embedding-3-small` | Embedding model name |
| `embedding_dim` | `1536` | Vector dimension |
| `rerank_model` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranker model |
| `qdrant_url` | `http://qdrant:6333` | Qdrant vector store URL |
| `qdrant_collection` | `gpu_errors` | Collection name |
| `postgres_dsn` | `...` | Async DB URL |
| `redis_url` | `redis://localhost:6379/0` | Cache store |
| `cache_ttl_active` | `3600` | TTL for recent error caches (1h) |
| `cache_ttl_static` | `86400` | TTL for general knowledge caches (24h) |
| `cache_cosine_threshold` | `0.92` | Minimum similarity for cache hit |

---

## sanitiser.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `sanitise_pattern` | `(text: str) -> str` | Strip PII from error patterns before KB storage. Truncates to 2000 chars. |
| `sanitise_fix_steps` | `(text: str) -> str` | Strip PII from fix steps. Same rules. |

**Rules applied** (10 regex rules):
1. IPv4 → `[IP]`
2. IPv6 → `[IPv6]`
3. Hostnames `.internal/.local/.company.com/.corp` → `[HOST]`
4. `/home/<user>` → `/home/[USER]`
5. `/root` → `/[ROOT]`
6. `/users/<user>` → `/users/[USER]`
7. `password=X`, `token=X`, etc. → `\1=[REDACTED]`
8. PEM/SSH key blocks → `[KEY_REDACTED]`
9. UUIDs → `[UUID]`
10. Numeric IDs > 6 digits → `[ID]`

---

## embedder.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `embed_text` | `(text: str, retries: int = 3) -> list[float]` | Single text embedding with exponential backoff on RateLimitError |
| `embed_batch` | `(texts: list[str], retries: int = 3) -> list[list[float]]` | Batch embedding, chunks of 100, sorted by index |
| `_get_client` | `() -> AsyncOpenAI` | Lazy singleton OpenAI async client |

---

## vector_store.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `ensure_collection` | `() -> None` | Create Qdrant collection on startup if missing |
| `upsert_entry` | `(embedding_id, vector, payload) -> None` | Upsert single KB entry into Qdrant |
| `delete_entry` | `(embedding_id: str) -> None` | Delete point by UUID |
| `dense_search` | `(query_vector, top_k, tags?) -> list[ScoredPoint]` | Semantic cosine search, optional tag filter |
| `collection_size` | `() -> int` | Total points in collection |
| `_get_client` | `() -> AsyncQdrantClient` | Lazy singleton Qdrant client |

**Payload schema stored per point:**
```
kb_entry_id, error_pattern, fix_steps, tags, confidence, source
```

---

## bm25_index.py

### State Fields (BM25Index dataclass)

| Field | Type | Purpose |
|---|---|---|
| `_bm25` | `BM25Okapi \| None` | Rank-BM25 instance; None until first build ⚠️ STUB until ingest |
| `_doc_ids` | `list[int]` | bm25_doc_id ordered list; index == bm25_doc_id |
| `_kb_ids` | `list[int]` | rag_kb_entries.id for each doc |
| `_patterns` | `list[str]` | error_pattern text |
| `_fix_steps` | `list[str]` | fix_steps text |

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `BM25Index.build` | `(session: AsyncSession) -> None` | Full rebuild from DB ordered by bm25_doc_id |
| `BM25Index.search` | `(query: str, top_k: int) -> list[dict]` | BM25 keyword search; returns [] if empty |
| `BM25Index.size` | property → `int` | Count of indexed documents |
| `init_index` | `(session) -> BM25Index` | Create + build module-level singleton |
| `get_index` | `() -> BM25Index` | Get singleton; raises RuntimeError if not initialised |

**Design note:** No serialised storage — index is always rebuilt from DB on startup.
Full rebuild also triggered after each ingest (via asyncio.create_task).

---

## hybrid_search.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `hybrid_search` | `(query, top_k, tags?) -> list[dict]` | Parallel dense+sparse retrieval merged via RRF |
| `_rrf_merge` | `(dense_hits, sparse_hits) -> list[dict]` | Reciprocal Rank Fusion merge; k=60 |
| `_bm25_search` | `(query, top_k) -> list[dict]` | Sync BM25 wrapper for asyncio.to_thread |

**RRF formula:** `score(d) = Σ 1 / (60 + rank(d))`

**Result dict keys:** `kb_entry_id, error_pattern, fix_steps, rrf_score` + dense extras: `confidence, source, tags, dense_score`

---

## reranker.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `_load_model` | `() -> CrossEncoder` | lru_cache(1) — loads once per process |
| `rerank` | `(query, candidates, top_k) -> list[dict]` | Cross-encoder score all pairs, return top_k with `rerank_score` |
| `preload_model` | `() -> None` | Async wrapper for startup warm-up via asyncio.to_thread |

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (downloaded at Docker build time into `HF_HOME=/app/.cache/huggingface` so `appuser` uid 1000 can read it at runtime — do NOT remove that env var from the Dockerfile or the container will try to re-download on an internal network and fail)

---

## semantic_cache.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `cache_lookup` | `(query_embedding, redis) -> list[dict] \| None` | O(n) cosine scan; returns results on hit, None on miss |
| `cache_write` | `(query_embedding, results, redis, kind) -> None` | Store in Redis with TTL based on kind |
| `cache_stats` | `(redis) -> dict` | Count active/static/total cached entries |
| `_cosine` | `(a, b) -> float` | Pure-Python cosine similarity |
| `_embedding_key` | `(embedding) -> str` | SHA256-based deterministic Redis key |

**Redis key pattern:** `mas:rag_cache:{sha256_prefix_16chars}`

**kind options:** `"active"` (1h TTL) | `"static"` (24h TTL)

---

## routes.py

### Pydantic Models

| Model | Purpose |
|---|---|
| `SearchRequest` | query, top_k, tags, use_cache |
| `SearchResponse` | results, cache_hit, total |
| `SearchResult` | kb_entry_id, error_pattern, fix_steps, rerank_score, rrf_score, source, tags |
| `IngestRequest` | error_pattern, fix_steps, tags, confidence, source |
| `IngestResponse` | kb_entry_id, embedding_id |
| `StatsResponse` | kb_size, bm25_index_size, cache |

### Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/rag/search` | none | Cache → hybrid → rerank pipeline |
| `POST` | `/rag/ingest` | none | Sanitise → embed → DB insert → Qdrant upsert → BM25 rebuild |
| `DELETE` | `/rag/entry/{id}` | none | Remove from DB + Qdrant |
| `GET` | `/rag/stats` | none | KB size, BM25 size, cache stats |

**Search pipeline:** embed query → cache lookup (cosine ≥ 0.92) → hybrid (parallel dense+BM25) → cross-encoder rerank → cache write

---

## main.py

### Lifespan sequence

1. Create async SQLAlchemy engine + `async_sessionmaker`
2. Connect to Redis
3. `vector_store.ensure_collection()` — create Qdrant collection if missing
4. `bm25_mod.init_index(session)` — build BM25 from DB
5. `preload_model()` — load cross-encoder model via `asyncio.to_thread`

Port: **8005**

---

## Cross-Service Contracts

| Consumer | Field/Queue | Notes |
|---|---|---|
| client-agent | `POST /rag/search` | Returns reranked fix suggestions |
| client-agent | `POST /rag/ingest` | Stores new error+fix pair after successful resolution |
| Postgres | `rag_kb_entries` | Source of truth; BM25 rebuilt from here |
| Qdrant | `gpu_errors` collection | Dense embeddings stored here |
| Redis | `mas:rag_cache:*` | Semantic cache keys with TTL |
