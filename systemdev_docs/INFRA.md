# INFRA — GPU-MAS Docker & Scaling Design

## 1. Container Map

```
┌─────────────────────────────────────────────────────┐
│                  docker-compose stack               │
│                                                     │
│  [nginx]          :80/:443 → api-gateway:8000       │
│  [api-gateway]    FastAPI, 4 Gunicorn workers       │
│  [orchestrator]   LangGraph supervisor + APScheduler│
│  [inserver-agent] Maintenance agent workers (×N)    │
│  [client-agent]   Ticket resolution workers (×N)    │
│  [report-agent]   Report generation (single)        │
│  [rag-service]    Hybrid retrieval API              │
│  [ssh-vault]      Credential vault API              │
│  [scheduler]      Cron trigger service              │
│  [llmops]         Langfuse OSS self-hosted          │
│  [postgres]       Primary DB (PgBouncer in front)   │
│  [pgbouncer]      Connection pooler → postgres      │
│  [redis]          Cache + task queue + rate limiter │
│  [qdrant]         Vector database                   │
│  [prometheus]     Metrics scraper                   │
│  [grafana]        Dashboards                        │
│  [loki]           Log aggregation                   │
└─────────────────────────────────────────────────────┘
```

---

## 2. docker-compose.yml (Development)

```yaml
version: "3.9"

x-common-env: &common-env
  ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
  POSTGRES_DSN: postgresql+asyncpg://mas:${POSTGRES_PASSWORD}@pgbouncer:5432/masdb
  REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
  QDRANT_URL: http://qdrant:6333
  VAULT_URL: http://ssh-vault:8100
  LANGFUSE_HOST: http://llmops:3000
  LANGFUSE_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
  LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
  LOG_LEVEL: INFO
  ANTHROPIC_RPM_LIMIT: ${ANTHROPIC_RPM_LIMIT:-60}
  ANTHROPIC_TPM_LIMIT: ${ANTHROPIC_TPM_LIMIT:-100000}
  DAILY_COST_LIMIT_USD: ${DAILY_COST_LIMIT_USD:-50}

services:
  nginx:
    image: nginx:1.25-alpine
    ports: ["80:80"]
    volumes: ["./infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro"]
    depends_on: [api-gateway]
    networks: [public, internal]

  api-gateway:
    build: ./services/api-gateway
    environment:
      <<: *common-env
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}
    networks: [public, internal]
    depends_on: [redis, pgbouncer]
    deploy:
      resources:
        limits: { cpus: "1.0", memory: "512M" }

  orchestrator:
    build: ./services/agent-orchestrator
    environment:
      <<: *common-env
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}
      MAX_CONCURRENT_AGENTS: ${MAX_CONCURRENT_AGENTS:-10}
    networks: [internal]
    depends_on: [redis, pgbouncer, ssh-vault, rag-service]
    deploy:
      resources:
        limits: { cpus: "2.0", memory: "1G" }

  inserver-agent:
    build: ./services/inserver-agent
    environment:
      <<: *common-env
      AGENT_TYPE: inserver
      WORKER_CONCURRENCY: ${INSERVER_WORKERS:-3}
    networks: [internal]
    depends_on: [orchestrator]
    deploy:
      replicas: 1          # scale with: docker compose up --scale inserver-agent=3
      resources:
        limits: { cpus: "1.0", memory: "512M" }

  client-agent:
    build: ./services/client-agent
    environment:
      <<: *common-env
      AGENT_TYPE: client
      WORKER_CONCURRENCY: ${CLIENT_WORKERS:-5}
    networks: [internal]
    depends_on: [orchestrator, rag-service]
    deploy:
      replicas: 2          # scale this first for high ticket volume
      resources:
        limits: { cpus: "2.0", memory: "1G" }

  report-agent:
    build: ./services/report-agent
    environment:
      <<: *common-env
      MANAGER_WEBHOOK_URL: ${MANAGER_WEBHOOK_URL}
      SMTP_HOST: ${SMTP_HOST:-""}
    networks: [internal]
    deploy:
      replicas: 1
      resources:
        limits: { cpus: "0.5", memory: "256M" }

  rag-service:
    build: ./services/rag-service
    environment:
      <<: *common-env
      EMBEDDING_MODEL: text-embedding-3-small
      RERANK_MODEL: cross-encoder/ms-marco-MiniLM-L-6-v2
      CACHE_TTL_ACTIVE: 3600
      CACHE_TTL_STATIC: 86400
    networks: [internal]
    depends_on: [qdrant, redis]
    deploy:
      resources:
        limits: { cpus: "2.0", memory: "2G" }

  ssh-vault:
    build: ./services/ssh-vault
    environment:
      VAULT_MASTER_KEY: ${VAULT_MASTER_KEY}
      POSTGRES_DSN: postgresql+asyncpg://mas:${POSTGRES_PASSWORD}@pgbouncer:5432/masdb
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}
    networks: [internal]
    depends_on: [pgbouncer]
    # NO external port exposure
    deploy:
      resources:
        limits: { cpus: "0.5", memory: "256M" }

  scheduler:
    build: ./services/scheduler
    environment:
      <<: *common-env
      ORCHESTRATOR_URL: http://orchestrator:8001
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}
    networks: [internal]
    depends_on: [orchestrator, pgbouncer]

  llmops:
    image: langfuse/langfuse:2
    environment:
      DATABASE_URL: postgresql://mas:${POSTGRES_PASSWORD}@postgres:5432/langfuse
      NEXTAUTH_SECRET: ${LANGFUSE_NEXTAUTH_SECRET}
      NEXTAUTH_URL: http://localhost:3000
      SALT: ${LANGFUSE_SALT}
    ports: ["3000:3000"]   # internal access only in prod (behind nginx)
    networks: [internal]
    depends_on: [postgres]

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: mas
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_MULTIPLE_DATABASES: masdb,langfuse
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./infra/postgres/init.sh:/docker-entrypoint-initdb.d/init.sh
    networks: [internal]
    deploy:
      resources:
        limits: { cpus: "2.0", memory: "2G" }

  pgbouncer:
    image: edoburu/pgbouncer:1.22
    environment:
      DATABASE_URL: postgres://mas:${POSTGRES_PASSWORD}@postgres:5432/masdb
      POOL_MODE: transaction
      MAX_CLIENT_CONN: 200
      DEFAULT_POOL_SIZE: 20
    networks: [internal]
    depends_on: [postgres]

  redis:
    image: redis:7.2-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes: ["redis_data:/data"]
    networks: [internal]
    deploy:
      resources:
        limits: { cpus: "0.5", memory: "600M" }

  qdrant:
    image: qdrant/qdrant:v1.9.0
    volumes: ["qdrant_data:/qdrant/storage"]
    networks: [internal]
    deploy:
      resources:
        limits: { cpus: "1.0", memory: "1G" }

  prometheus:
    image: prom/prometheus:v2.51.0
    volumes:
      - ./infra/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prom_data:/prometheus
    networks: [internal]
    command: ["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.retention.time=30d"]

  grafana:
    image: grafana/grafana:10.4.0
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
    volumes:
      - grafana_data:/var/lib/grafana
      - ./infra/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
    ports: ["3001:3000"]
    networks: [internal]
    depends_on: [prometheus, loki]

  loki:
    image: grafana/loki:2.9.0
    volumes:
      - loki_data:/loki
      - ./infra/loki/loki-config.yaml:/etc/loki/local-config.yaml:ro
    networks: [internal]

volumes:
  pg_data:
  redis_data:
  qdrant_data:
  prom_data:
  grafana_data:
  loki_data:

networks:
  public:
  internal:
    internal: true
```

---

## 3. Environment Variables Template (.env.example)

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_RPM_LIMIT=60
ANTHROPIC_TPM_LIMIT=100000
DAILY_COST_LIMIT_USD=50

# Database
POSTGRES_PASSWORD=changeme_strong_password

# Redis
REDIS_PASSWORD=changeme_redis_password

# Vault
VAULT_MASTER_KEY=base64_encoded_32_byte_key_here

# Auth
JWT_SECRET_KEY=changeme_jwt_secret_min_32_chars
INTERNAL_API_KEY=changeme_internal_service_key

# Agents
MAX_CONCURRENT_AGENTS=10
INSERVER_WORKERS=3
CLIENT_WORKERS=5

# Reporting
MANAGER_WEBHOOK_URL=https://hooks.yourplatform.com/...
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=

# LLMOps (Langfuse)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_NEXTAUTH_SECRET=changeme_nextauth_secret
LANGFUSE_SALT=changeme_salt

# Grafana
GRAFANA_PASSWORD=changeme_grafana_password

# Web Search (pick one)
TAVILY_API_KEY=tvly-...
# SERP_API_KEY=...
```

---

## 4. Scaling Runbook

### Scenario A: High ticket volume (>200 pending tickets)

```bash
# Scale client agents
docker compose up --scale client-agent=6 -d

# Monitor queue depth in Grafana → "Agent Queue" dashboard
# Scale back when queue drains to < 20
docker compose up --scale client-agent=2 -d
```

### Scenario B: Many servers to maintain (>50 servers)

```bash
docker compose up --scale inserver-agent=4 -d
```

### Scenario C: RAG service slow (>500ms p95)

```bash
# Scale RAG (embedding is CPU-bound)
docker compose up --scale rag-service=3 -d
# Ensure qdrant is not the bottleneck — check qdrant metrics
```

### Scenario D: DB connection saturation

```
# PgBouncer config (infra/pgbouncer/pgbouncer.ini)
# Increase: default_pool_size = 30 (from 20)
# Increase: max_client_conn = 400 (from 200)
# Restart pgbouncer only — no downtime
docker compose restart pgbouncer
```

---

## 5. Health Checks

Every service exposes `GET /health` returning:
```json
{
  "status": "ok",
  "service": "client-agent",
  "version": "0.1.0",
  "dependencies": {
    "redis": "ok",
    "postgres": "ok",
    "vault": "ok",
    "qdrant": "ok"
  },
  "metrics": {
    "active_tasks": 3,
    "queue_depth": 12,
    "rate_limit_utilisation_pct": 45
  }
}
```

Docker compose healthcheck:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

---

## 6. Dockerfile Pattern (All Services)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client curl && rm -rf /var/lib/apt/lists/*

# Python deps (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code last
COPY . .

# Non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

---

## 7. Tmpfs for Ephemeral SSH Keys (if needed)

```yaml
# For services that must write a temp key file for SSH
services:
  client-agent:
    tmpfs:
      - /tmp/ssh-sessions:size=10m,mode=1700
    # Keys written here are in-memory only, gone on container restart
```
