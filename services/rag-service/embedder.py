"""
Text embedding via OpenAI text-embedding-3-small.

Single and batch embedding with retry on rate limit.
Returns 1536-dimensional float vectors.
"""

import asyncio
import logging
from typing import Optional

from openai import AsyncOpenAI, RateLimitError

from config import settings

log = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def embed_text(text: str, retries: int = 3) -> list[float]:
    """
    Embed a single text string.
    Returns a 1536-dimensional float vector.
    Retries up to `retries` times on RateLimitError with exponential backoff.
    """
    client = _get_client()
    for attempt in range(retries):
        try:
            response = await client.embeddings.create(
                input=text,
                model=settings.embedding_model,
            )
            return response.data[0].embedding
        except RateLimitError:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("embedding rate limit hit, retrying in %ds", wait)
            await asyncio.sleep(wait)
    raise RuntimeError("embed_text exhausted retries")


async def embed_batch(texts: list[str], retries: int = 3) -> list[list[float]]:
    """
    Embed a list of texts in a single API call (more efficient than looping embed_text).
    OpenAI supports up to 2048 inputs per request — we cap at 100 for safety.
    """
    if not texts:
        return []

    client = _get_client()
    results: list[list[float]] = []

    # Process in chunks of 100
    for i in range(0, len(texts), 100):
        chunk = texts[i : i + 100]
        for attempt in range(retries):
            try:
                response = await client.embeddings.create(
                    input=chunk,
                    model=settings.embedding_model,
                )
                results.extend([item.embedding for item in sorted(response.data, key=lambda x: x.index)])
                break
            except RateLimitError:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

    return results
