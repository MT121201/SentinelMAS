"""
BM25 sparse index for keyword-based retrieval.

Index is rebuilt from rag_kb_entries on every startup (ordered by bm25_doc_id).
No serialised storage — the table is the source of truth.

bm25_doc_id is a sequential integer assigned at ingest time (see routes.py).
Rows are loaded in bm25_doc_id order so that list index == bm25_doc_id.
"""

import logging
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


@dataclass
class BM25Index:
    """
    Wraps a rank_bm25 BM25Okapi instance with metadata needed to map
    result indices back to KB entry IDs and payloads.

    State fields:
        _bm25      — BM25Okapi instance; None until build() is called  ⚠️ STUB until first ingest
        _doc_ids   — list[int]: bm25_doc_id ordered list (index == bm25_doc_id)
        _kb_ids    — list[int]: rag_kb_entries.id for each document
        _patterns  — list[str]: raw error_pattern text for each document
        _fix_steps — list[str]: raw fix_steps text for each document
    """

    _bm25: BM25Okapi | None = field(default=None, init=False, repr=False)
    _doc_ids: list[int] = field(default_factory=list, init=False)
    _kb_ids: list[int] = field(default_factory=list, init=False)
    _patterns: list[str] = field(default_factory=list, init=False)
    _fix_steps: list[str] = field(default_factory=list, init=False)

    @property
    def size(self) -> int:
        return len(self._kb_ids)

    async def build(self, session: AsyncSession) -> None:
        """
        Load all entries from DB ordered by bm25_doc_id and build the BM25 index.
        Called once at startup and after each ingest (full rebuild).
        """
        rows = await session.execute(
            text(
                """
                SELECT id, bm25_doc_id, error_pattern, fix_steps
                FROM rag_kb_entries
                WHERE bm25_doc_id IS NOT NULL
                ORDER BY bm25_doc_id ASC
                """
            )
        )
        records = rows.fetchall()

        if not records:
            log.info("bm25 index: no entries, index is empty")
            self._bm25 = None
            self._doc_ids = []
            self._kb_ids = []
            self._patterns = []
            self._fix_steps = []
            return

        self._kb_ids = [r.id for r in records]
        self._doc_ids = [r.bm25_doc_id for r in records]
        self._patterns = [r.error_pattern for r in records]
        self._fix_steps = [r.fix_steps for r in records]

        corpus = [
            (r.error_pattern + " " + r.fix_steps).lower().split()
            for r in records
        ]
        self._bm25 = BM25Okapi(corpus)
        log.info("bm25 index built with %d documents", len(records))

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        BM25 keyword search. Returns list of dicts with kb_entry_id, score, pattern, fix_steps.
        Returns [] if index is empty.
        """
        if self._bm25 is None or not self._kb_ids:
            return []

        tokenised = query.lower().split()
        scores = self._bm25.get_scores(tokenised)

        # Pair (score, index) and sort descending
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in ranked[:top_k]:
            if score <= 0:
                break
            results.append(
                {
                    "kb_entry_id": self._kb_ids[idx],
                    "bm25_doc_id": self._doc_ids[idx],
                    "score": float(score),
                    "error_pattern": self._patterns[idx],
                    "fix_steps": self._fix_steps[idx],
                }
            )
        return results


# Module-level singleton; initialised in main.py startup
_index: BM25Index | None = None


def get_index() -> BM25Index:
    if _index is None:
        raise RuntimeError("BM25 index not initialised — call init_index() first")
    return _index


async def init_index(session: AsyncSession) -> BM25Index:
    """Create and build the module-level BM25Index. Called from main.py lifespan."""
    global _index
    _index = BM25Index()
    await _index.build(session)
    return _index
