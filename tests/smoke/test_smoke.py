"""
P9-07 — Docker Compose smoke test: all /health endpoints return 200.

Requires the full stack to be running:
    docker compose up --build -d

Run:
    pytest tests/smoke/test_smoke.py -v
    # or with explicit host override:
    SMOKE_BASE=http://localhost pytest tests/smoke/test_smoke.py -v

Each service is tested independently so failures are reported per-service.
A 10-second timeout per health check accommodates slow startup on first run.
"""

import os
import pytest
import httpx

# ── Service registry ───────────────────────────────────────────────────────────

BASE = os.environ.get("SMOKE_BASE", "http://localhost")

SERVICES = [
    ("api-gateway",        f"{BASE}:8000/health"),
    ("agent-orchestrator", f"{BASE}:8001/health"),
    ("inserver-agent",     f"{BASE}:8002/health"),
    ("client-agent",       f"{BASE}:8003/health"),
    ("report-agent",       f"{BASE}:8004/health"),
    ("rag-service",        f"{BASE}:8005/health"),
    ("ssh-vault",          f"{BASE}:8100/health"),
]

INFRA_SERVICES = [
    ("prometheus",         f"{BASE}:9090/-/ready"),
    ("grafana",            f"{BASE}:3001/api/health"),
    ("loki",               f"{BASE}:3100/ready"),
    ("langfuse",           f"{BASE}:3000/api/public/health"),
]

TIMEOUT = 10.0  # seconds per request


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("service,url", SERVICES)
def test_service_health(service: str, url: str):
    """
    Each application service must return HTTP 200 from its /health endpoint.
    The response body must contain {"status": "ok"}.
    """
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    except httpx.ConnectError as e:
        pytest.fail(
            f"{service} — could not connect to {url}\n"
            f"Is the stack running? Run: docker compose up --build -d\n"
            f"Error: {e}"
        )
    except httpx.TimeoutException:
        pytest.fail(f"{service} — health check timed out after {TIMEOUT}s ({url})")

    assert resp.status_code == 200, (
        f"{service} returned HTTP {resp.status_code} from {url}\n"
        f"Body: {resp.text[:300]}"
    )

    try:
        body = resp.json()
        assert body.get("status") == "ok", (
            f"{service} health response missing 'status: ok' — got: {body}"
        )
    except Exception:
        # Some endpoints return plain text "OK" — acceptable
        assert "ok" in resp.text.lower(), (
            f"{service} health response doesn't contain 'ok': {resp.text[:100]}"
        )


@pytest.mark.parametrize("service,url", INFRA_SERVICES)
def test_infra_health(service: str, url: str):
    """
    Infrastructure services (Prometheus, Grafana, Loki, Langfuse) must be reachable.
    Some return non-JSON bodies — just verify HTTP 200.
    """
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    except httpx.ConnectError as e:
        pytest.fail(
            f"{service} (infra) — could not connect to {url}\n"
            f"Error: {e}"
        )
    except httpx.TimeoutException:
        pytest.fail(f"{service} (infra) — timed out after {TIMEOUT}s ({url})")

    assert resp.status_code == 200, (
        f"{service} (infra) returned HTTP {resp.status_code} — {url}\n"
        f"Body: {resp.text[:200]}"
    )


@pytest.mark.parametrize("service,url", SERVICES)
def test_metrics_endpoint(service: str, url: str):
    """
    Each application service must expose /metrics for Prometheus scraping.
    Verifies prometheus-fastapi-instrumentator is wired in every service.
    """
    metrics_url = url.replace("/health", "/metrics")
    try:
        resp = httpx.get(metrics_url, timeout=TIMEOUT)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        pytest.fail(f"{service} /metrics unreachable: {e}")

    assert resp.status_code == 200, (
        f"{service} /metrics returned {resp.status_code} — expected 200"
    )
    # Prometheus text format always starts with a comment or metric name
    assert "http_requests_total" in resp.text or "# HELP" in resp.text, (
        f"{service} /metrics response doesn't look like Prometheus format:\n{resp.text[:200]}"
    )


def test_nginx_proxies_to_api_gateway():
    """nginx on port 80 must proxy health checks to api-gateway."""
    try:
        resp = httpx.get(f"{BASE}/health", timeout=TIMEOUT)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        pytest.fail(f"nginx proxy check failed: {e}")

    assert resp.status_code == 200, f"nginx /health returned {resp.status_code}"


def test_ops_dashboard_reachable():
    """GET /ops/dashboard must be reachable (unauthenticated) via nginx."""
    try:
        resp = httpx.get(f"{BASE}/ops/dashboard", timeout=TIMEOUT)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        pytest.fail(f"ops dashboard unreachable: {e}")

    # 200 = data returned, 401/403 = auth required (both mean it's routed correctly)
    assert resp.status_code in (200, 401, 403), (
        f"Unexpected status from /ops/dashboard: {resp.status_code}"
    )


def test_ops_html_page_reachable():
    """GET /ops/ui/ops.html must return the ops dashboard HTML page."""
    try:
        resp = httpx.get(f"{BASE}:8000/ops/ui/ops.html", timeout=TIMEOUT)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        pytest.fail(f"ops.html unreachable: {e}")

    assert resp.status_code == 200
    assert "SentinelMAS" in resp.text, "ops.html should contain 'SentinelMAS'"
