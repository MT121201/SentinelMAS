# RAG Service

Hybrid retrieval service for GPU error+fix patterns. Dense vector search (Qdrant) + sparse BM25, merged with Reciprocal Rank Fusion, reranked by a cross-encoder, with a Redis semantic cache in front.

**Port:** `8005` | **Built in:** Phase 3 | **Status:** scaffold

---

## Query Pipeline

```mermaid
flowchart TD
    Q["Agent search query\ne.g. 'CUDA out of memory error'"]
    Q --> EMB["embed query\ntext-embedding-3-small"]
    EMB --> CACHE{"Redis semantic cache\ncosine ≥ 0.92?"}
    CACHE -->|hit < 20ms| RESULT["return cached results"]
    CACHE -->|miss| PARALLEL

    subgraph PARALLEL["Parallel retrieval"]
        DENSE["Qdrant\ntop-20 by cosine similarity"]
        SPARSE["BM25 index\ntop-20 by BM25 score"]
    end

    DENSE & SPARSE --> RRF["Reciprocal Rank Fusion\nmerge dense + sparse"]
    RRF --> RERANK["Cross-encoder rerank\ntop-20 → top-5\ncross-encoder/ms-marco-MiniLM-L-6-v2"]
    RERANK --> WRITE["write to Redis cache\nTTL by content type"]
    WRITE --> RESULT
```

## Ingest Pipeline

```mermaid
flowchart LR
    FIX["confirmed error+fix pair\nfrom client-agent"] --> SAN["sanitiser.py\nstrip IPs, hostnames, paths"]
    SAN --> EMB["embed error_pattern\ntext-embedding-3-small"]
    EMB --> QDRANT["upsert to Qdrant\n+ store payload"]
    SAN --> BM25["update BM25 index\npersist to PostgreSQL"]
```

## Cache TTL Policy

| Content Type | TTL |
|---|---|
| Active error fix (recent) | 1 hour |
| Static / general knowledge | 24 hours |
| Web search results | 30 minutes |

**KB starts empty.** System degrades gracefully to web search fallback until patterns are populated from real ticket resolutions.

## Design References
- `systemdev_docs/AGENT_DESIGN.md §3` — full RAG architecture
- `alembic/dev_note.md` — `rag_kb_entries` table schema
- `services/rag-service/dev_note.md`
