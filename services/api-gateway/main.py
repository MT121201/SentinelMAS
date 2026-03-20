"""
API Gateway — FastAPI application entry point.
Public entrypoint for all external traffic.
Port: 8000
"""

import logging
import os
import sys

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import settings
from limiter import limiter
from middleware import RequestContextMiddleware
from routes import auth, tickets, reports, ops, admin, system, ops_dashboard

# ── Structured logging ────────────────────────────────────────────────────────
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    )
)
log = structlog.get_logger()

# ── Tags metadata ─────────────────────────────────────────────────────────────
tags_metadata = [
    {"name": "auth",    "description": "Authentication — issue JWT tokens"},
    {"name": "tickets", "description": "User ticket submission and polling"},
    {"name": "reports", "description": "Manager reports (API key required)"},
    {"name": "ops",     "description": "Live operational view (API key required)"},
    {"name": "admin",   "description": "Server fleet management (API key required)"},
    {"name": "system",  "description": "Health check and metrics"},
]

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="GPU-MAS API",
    version="0.1.0",
    description="Multi-Agent GPU Server Management System",
    openapi_tags=tags_metadata,
    docs_url="/docs" if settings.env == "development" else None,
    redoc_url=None,
)

# Rate limiter state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware (order matters — outermost first)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestContextMiddleware)

# Routers
app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(reports.router)
app.include_router(ops.router)
app.include_router(ops_dashboard.router)
app.include_router(admin.router)
app.include_router(system.router)

# Prometheus metrics endpoint
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# Ops HTML page
app.mount("/ops/ui", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")


# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    log.error("unhandled_exception", error=str(exc), request_id=request_id)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            }
        },
    )


@app.on_event("startup")
async def startup():
    log.info("api_gateway_started", env=settings.env)


@app.on_event("shutdown")
async def shutdown():
    from shared.redis_client import close_redis
    await close_redis()
    log.info("api_gateway_stopped")
