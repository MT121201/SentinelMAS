"""
Request middleware:
  - Injects X-Request-ID (UUID) into every request/response
  - Structured JSON request logging (method, path, status, duration)
  - Attaches request_id to request.state for use in error responses
"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        log.info(
            "request_start",
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            client=request.client.host if request.client else "unknown",
        )

        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            log.error(
                "request_error",
                method=request.method,
                path=request.url.path,
                request_id=request_id,
                error=str(exc),
            )
            raise

        duration_ms = int((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = request_id

        log.info(
            "request_end",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response
