"""
slowapi rate limiter instance — centralised to avoid circular imports.

Limits are applied per endpoint via @limiter.limit() decorator.
  POST /auth/token   → 5/minute   (brute force protection)
  POST /tickets      → 20/minute  (ticket spam prevention)
  GET  /tickets/{id} → 60/minute  (polling)
  GET  /reports/*    → 30/minute  (manager reports)
  POST /admin/*      → 10/minute  (admin ops)
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
