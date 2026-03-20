"""
Web search client — Tavily API with SerpAPI fallback.

Returns a list of {title, snippet, url} dicts.
Falls back silently: Tavily → SerpAPI → empty list.
"""

import logging
from typing import Any

import httpx

from config import settings

log = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"
_SERPAPI_URL = "https://serpapi.com/search"


async def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """
    Search the web for query. Returns up to max_results results.
    Tries Tavily first; falls back to SerpAPI; returns [] if both fail.
    """
    if settings.tavily_api_key:
        results = await _tavily_search(query, max_results)
        if results:
            return results

    if settings.serpapi_key:
        results = await _serpapi_search(query, max_results)
        if results:
            return results

    log.warning("web_search: both Tavily and SerpAPI unavailable — returning empty")
    return []


async def web_fetch(url: str) -> str:
    """
    Fetch a URL and return its text content (truncated to 8000 chars).
    Used for reading documentation pages found via web_search.
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "SentinelMAS/1.0"})
            resp.raise_for_status()
            return resp.text[:8000]
    except Exception as exc:
        log.warning("web_fetch failed for %s: %s", url, exc)
        return f"[fetch error: {exc}]"


async def _tavily_search(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _TAVILY_URL,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title": r.get("title", ""),
                    "snippet": r.get("content", ""),
                    "url": r.get("url", ""),
                }
                for r in data.get("results", [])
            ]
    except Exception as exc:
        log.warning("tavily search failed: %s", exc)
        return []


async def _serpapi_search(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                _SERPAPI_URL,
                params={
                    "q": query,
                    "api_key": settings.serpapi_key,
                    "engine": "google",
                    "num": max_results,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                    "url": r.get("link", ""),
                }
                for r in data.get("organic_results", [])[:max_results]
            ]
    except Exception as exc:
        log.warning("serpapi search failed: %s", exc)
        return []
