# SentinelMAS — First-Time Setup Guide

> Complete setup from a fresh Linux server to a fully running GPU-MAS stack. Follow steps in order.

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Python 3.12+ (for key generation and local dev)
- Git

```bash
# Verify
docker --version         # Docker version 24.x.x
docker compose version   # Docker Compose version v2.x.x
python3 --version        # Python 3.12.x
```

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/MT121201/SentinelMAS.git
cd SentinelMAS
```

---

## Step 2 — Configure Environment

```bash
# Copy the example file
cp .env.example .env
```

Open `.env` and fill in the required values:

```bash
# Required — obtain from Anthropic dashboard
ANTHROPIC_API_KEY=sk-ant-...

# Required — generate with make
make generate-vault-key   # → VAULT_MASTER_KEY=...
make rotate-jwt-secret    # → JWT_SECRET_KEY=...

# Required — set strong passwords
POSTGRES_PASSWORD=choose-a-strong-password
REDIS_PASSWORD=choose-a-strong-redis-password
INTERNAL_API_KEY=choose-a-strong-internal-key

# Required for Langfuse (can be any random strings)
LANGFUSE_NEXTAUTH_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
LANGFUSE_SALT=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
GRAFANA_PASSWORD=choose-a-grafana-password

# Optional — for report delivery
MANAGER_WEBHOOK_URL=https://hooks.slack.com/services/...
SMTP_HOST=smtp.yourcompany.com
SMTP_TO=ops-team@yourcompany.com

# Optional — for web search in client-agent
TAVILY_API_KEY=tvly-...
```

---

## Step 3 — Generate the Vault Master Key

The vault master key encrypts all SSH credentials at rest. Generate once; store securely.

```bash
make generate-vault-key
# Output: VAULT_MASTER_KEY=abc123...base64...
# Copy the value into your .env file
```

**Important:** If you lose this key, all stored SSH credentials become unrecoverable. Back it up to your team's password manager immediately.

---

## Step 4 — Build and Start

```bash
# Development (with logs in foreground)
make dev

# Or in detached mode
docker compose up --build -d
docker compose logs -f
```

First build takes 5–10 minutes (downloads Python deps, pulls Docker images, downloads the reranker model).

---

## Step 5 — Run Database Migrations

```bash
make migrate
```

This creates all tables: `server_credentials`, `tickets`, `daily_health_snapshots`, `rag_kb_entries`, `task_queue`, `apscheduler_jobs`.

---

## Step 6 — Verify All Services Are Healthy

```bash
# Quick health check
for svc in "8000" "8001" "8002" "8003" "8004" "8005" "8100"; do
  echo -n "Port $svc: "
  curl -sf http://localhost:$svc/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "FAIL"
done

# Or run the full smoke test suite
pytest tests/smoke/ -v
```

All services should return `ok`.

---

## Step 7 — Add Your First GPU Server

Get a JWT token, then register a server:

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-admin-password"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Register a server (replace values with your server's details)
curl -X POST http://localhost:8000/admin/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "srv-gpu-01",
    "display_name": "GPU Node 01",
    "hostname": "YOUR_SERVER_IP",
    "port": 22,
    "username": "ubuntu",
    "ssh_private_key": "-----BEGIN RSA PRIVATE KEY-----\nYOUR_KEY_HERE\n-----END RSA PRIVATE KEY-----"
  }'
```

---

## Step 8 — Open the Dashboards

| Dashboard | URL | Credentials |
|---|---|---|
| Ops live view | `http://localhost:8000/ops/ui/ops.html` | None (internal) |
| Grafana metrics | `http://localhost:3001` | admin / `$GRAFANA_PASSWORD` |
| Langfuse traces | `http://localhost:3000` | Create account on first visit |
| Prometheus raw | `http://localhost:9090` | None |

---

## Step 9 — Submit a Test Ticket

```bash
curl -X POST http://localhost:8000/tickets \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "srv-gpu-01",
    "description": "Test ticket: check GPU temperature and disk usage",
    "user_id": "ops-setup-test"
  }'

# Poll status (replace TICKET_ID)
curl http://localhost:8000/tickets/TICKET_ID \
  -H "Authorization: Bearer $TOKEN"
```

The ticket should progress: `queued` → `assigned` → `executing` → `done` (or `escalated` if SSH unreachable).

---

## Step 10 — Production Deployment

For production, use the prod compose overlay:

```bash
# 1. Create secrets directory
mkdir -p secrets
chmod 700 secrets

# 2. Write secret files (one per line, no trailing newline)
printf '%s' "$VAULT_MASTER_KEY" > secrets/vault_master_key.txt
printf '%s' "$ANTHROPIC_API_KEY" > secrets/anthropic_api_key.txt
printf '%s' "$POSTGRES_PASSWORD" > secrets/postgres_password.txt
printf '%s' "$REDIS_PASSWORD" > secrets/redis_password.txt
printf '%s' "$JWT_SECRET_KEY" > secrets/jwt_secret_key.txt
printf '%s' "$INTERNAL_API_KEY" > secrets/internal_api_key.txt
printf '%s' "$LANGFUSE_NEXTAUTH_SECRET" > secrets/langfuse_nextauth_secret.txt
printf '%s' "$LANGFUSE_SALT" > secrets/langfuse_salt.txt
chmod 600 secrets/*.txt

# 3. Start with prod overlay
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Production changes from the prod overlay:
- All secrets injected via Docker secrets (not env vars)
- No internal service ports exposed to host
- Swagger (`/docs`) disabled on all services
- Grafana bound to `127.0.0.1` only

---

## Scheduled Jobs (Automatic)

These run without any manual trigger once the stack is up:

| Job | Schedule | What it does |
|---|---|---|
| Daily health check | 00:05 UTC every day | SSH into all active servers, run health checks, emit snapshots |
| Weekly report | Monday 06:00 UTC | Generate & deliver weekly operations report |
| Hourly cache cleanup | :00 every hour | Remove expired entries from Redis semantic cache |

---

## Running Tests

```bash
# Unit + integration (no stack needed)
pip install -r tests/requirements-test.txt
pytest -q

# Per-service tests
make test-service SERVICE=client-agent
make test-service SERVICE=rag-service

# Smoke tests (stack must be running)
pytest tests/smoke/ -v

# Load test (stack must be running)
locust -f tests/load/locustfile.py \
  --host=http://localhost \
  --users=50 --spawn-rate=10 --run-time=60s --headless
```

---

## Where to Look When Things Go Wrong

| Problem | Where to look |
|---|---|
| Service won't start | `docker compose logs <service-name>` |
| Tickets not processing | Grafana → Agent Overview → Queue Depth |
| High API cost | Grafana → Token Spend → Daily Cost Accumulation |
| SSH commands failing | `docker compose logs ssh-vault` → look for `SafetyResult` or `paramiko` errors |
| LLM traces missing | Langfuse UI → check `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` in .env |
| DB connection errors | `docker compose logs pgbouncer postgres` |

For deeper investigation, see [RUNBOOK.md](RUNBOOK.md).
