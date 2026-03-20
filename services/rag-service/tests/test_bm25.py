"""
Unit tests for BM25 index.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import AsyncMock, MagicMock
from bm25_index import BM25Index, init_index, get_index
import bm25_index as bm25_mod


def _make_row(id_, bm25_doc_id, error_pattern, fix_steps):
    row = MagicMock()
    row.id = id_
    row.bm25_doc_id = bm25_doc_id
    row.error_pattern = error_pattern
    row.fix_steps = fix_steps
    return row


@pytest.fixture
def empty_index():
    return BM25Index()


@pytest.fixture
def populated_index():
    idx = BM25Index()
    idx._kb_ids = [1, 2, 3]
    idx._doc_ids = [0, 1, 2]
    idx._patterns = [
        "CUDA out of memory during training",
        "GPU driver crash on startup nvml",
        "disk full /var/log nvidia-smi error",
    ]
    idx._fix_steps = [
        "reduce batch size free memory",
        "reinstall nvidia driver reboot",
        "clear logs rotate disk",
    ]
    from rank_bm25 import BM25Okapi
    corpus = [
        (p + " " + f).lower().split()
        for p, f in zip(idx._patterns, idx._fix_steps)
    ]
    idx._bm25 = BM25Okapi(corpus)
    return idx


class TestBM25IndexSearch:
    def test_search_returns_results(self, populated_index):
        results = populated_index.search("CUDA memory out", top_k=2)
        assert len(results) >= 1
        assert results[0]["kb_entry_id"] == 1  # CUDA entry should rank first

    def test_search_gpu_driver(self, populated_index):
        results = populated_index.search("nvidia driver nvml", top_k=3)
        ids = [r["kb_entry_id"] for r in results]
        assert 2 in ids  # driver entry

    def test_search_empty_index(self, empty_index):
        results = empty_index.search("anything", top_k=5)
        assert results == []

    def test_top_k_respected(self, populated_index):
        results = populated_index.search("nvidia error disk", top_k=1)
        assert len(results) <= 1

    def test_zero_score_excluded(self, populated_index):
        # Query with no overlap should return 0 results
        results = populated_index.search("zzzzz unrelated term", top_k=5)
        assert all(r["score"] > 0 for r in results)

    def test_result_has_required_keys(self, populated_index):
        results = populated_index.search("cuda memory", top_k=1)
        if results:
            r = results[0]
            assert "kb_entry_id" in r
            assert "score" in r
            assert "error_pattern" in r
            assert "fix_steps" in r

    def test_size_property(self, populated_index):
        assert populated_index.size == 3

    def test_size_empty(self, empty_index):
        assert empty_index.size == 0


class TestBM25IndexBuild:
    @pytest.mark.asyncio
    async def test_build_from_db(self):
        idx = BM25Index()

        rows = [
            _make_row(10, 0, "CUDA memory error", "reduce batch"),
            _make_row(11, 1, "disk full error", "clear logs"),
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_session.execute = AsyncMock(return_value=mock_result)

        await idx.build(mock_session)

        assert idx.size == 2
        assert idx._kb_ids == [10, 11]

    @pytest.mark.asyncio
    async def test_build_empty_db(self):
        idx = BM25Index()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        await idx.build(mock_session)

        assert idx.size == 0
        assert idx._bm25 is None


class TestGetIndex:
    def test_get_index_raises_before_init(self):
        bm25_mod._index = None
        with pytest.raises(RuntimeError, match="not initialised"):
            get_index()
