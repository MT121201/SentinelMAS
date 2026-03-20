# SentinelMAS — Operations Runbook

> Quick reference for the on-call engineer. Jump to the scenario that matches your situation.

---

## 1. How to Scale

### Scale client agents (high ticket volume)

```bash
# Check queue depth first
make ps          # see running containers
docker compose exec redis redis-cli -a $REDIS_PASSWORD LLEN mas:client_queue

# Scale up
docker compose up --scale client-agent=6 -d

# Confirm new containers are healthy
docker compose ps client-agent

# Scale back when queue drains below 20
docker compose up --scale client-agent=2 -d
```

**Rule of thumb:** 1 client-agent handles ~5 concurrent tickets. At >100 pending, scale to 4–6.

### Scale inserver agents (large server fleet)

```bash
docker compose up --scale inserver-agent=4 -d
```

**Rule of thumb:** 1 inserver-agent handles ~3 servers concurrently. Scale to fleet_size / 3.

### Scale RAG service (high search latency)

```bash
# Check p95 latency in Grafana → Agent Overview → HTTP p95 Latency
docker compose up --scale rag-service=3 -d
```

---

## 2. How to Add a Server to the Fleet

```bash
# Step 1 — Add credentials via API
curl -X POST https://your-domain/admin/servers \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "srv-gpu-12",
    "display_name": "GPU Node 12",
    "hostname": "10.0.1.112",
    "port": 22,
    "username": "ubuntu",
    "ssh_private_key": "-----BEGIN RSA PRIVATE KEY-----\n..."
  }'

# Step 2 — Verify the credential was stored
curl https://your-domain/admin/servers \
  -H "Authorization: Bearer $ADMIN_JWT"

# Step 3 — Trigger an immediate health check (optional)
curl -X POST https://your-domain/admin/servers/srv-gpu-12/check \
  -H "Authorization: Bearer $ADMIN_JWT"
```

The server will be included in the next scheduled daily health check (00:05 UTC) automatically.

---

## 3. How to Rotate Secrets

### Rotate VAULT_MASTER_KEY

```bash
# 1. Generate new key
make generate-vault-key   # prints: VAULT_MASTER_KEY=<new-base64-key>

# 2. Re-encrypt all credentials with the new key (run migration script)
docker compose exec ssh-vault python scripts/rotate_vault_key.py \
  --old-key "$OLD_VAULT_MASTER_KEY" \
  --new-key "$NEW_VAULT_MASTER_KEY"

# 3. Update secrets file
echo "$NEW_VAULT_MASTER_KEY" > secrets/vault_master_key.txt

# 4. Restart vault (will load new key from secret)
docker compose restart ssh-vault

# 5. Verify health
curl http://localhost:8100/health
```

### Rotate JWT_SECRET_KEY

```bash
# 1. Generate
make rotate-jwt-secret    # prints: JWT_SECRET_KEY=<new-key>

# 2. Update secret file
echo "$NEW_JWT_KEY" > secrets/jwt_secret_key.txt

# 3. Restart api-gateway (all existing JWTs invalidated — users re-login)
docker compose restart api-gateway
```

### Rotate INTERNAL_API_KEY

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/internal_api_key.txt
docker compose restart api-gateway orchestrator inserver-agent client-agent report-agent ssh-vault
```

### Rotate POSTGRES_PASSWORD

```bash
# 1. Generate
NEW_PW=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# 2. Change in Postgres
docker compose exec postgres psql -U mas -c "ALTER USER mas WITH PASSWORD '$NEW_PW';"

# 3. Update secret file and restart dependent services
echo "$NEW_PW" > secrets/postgres_password.txt
docker compose restart api-gateway orchestrator inserver-agent client-agent report-agent rag-service ssh-vault pgbouncer
```

---

## 4. How to Investigate a Stuck Agent

### Check the worker pool

```bash
# View active task list from orchestrator API
curl http://localhost:8001/ops/agents \
  -H "X-Internal-Key: $INTERNAL_API_KEY"
```

### Check logs for a specific task

```bash
# In Grafana → Explore → Loki → filter by trace_id
# Or from CLI:
docker compose logs orchestrator | grep "task_id=<TASK_ID>"
docker compose logs client-agent  | grep "task_id=<TASK_ID>"
```

### A task appears stuck for >15 minutes

The watchdog in `worker_pool.py` logs `STUCK TASK` at WARNING level every 60s for tasks running >900s. It does **not** auto-cancel — to manually cancel:

```bash
# 1. Find the stuck task_id from logs or /ops/agents
# 2. Mark it failed in DB
docker compose exec postgres psql -U mas masdb \
  -c "UPDATE tickets SET status='failed', resolution_summary='Manually cancelled - stuck task' WHERE id='<TICKET_ID>';"

# 3. Notify orchestrator
curl -X PUT http://localhost:8001/internal/tasks/<TASK_ID>/status \
  -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "failed", "resolution_summary": "Manually cancelled"}'
```

### Agent consuming all RPM (rate throttling)

```bash
# Check utilisation
curl http://localhost:8000/ops/cost -H "Authorization: Bearer $ADMIN_JWT"

# If daily limit hit and more capacity needed, reset counter
curl -X POST http://localhost:8000/ops/cost/reset \
  -H "Authorization: Bearer $ADMIN_JWT"

# Or increase limit in .env and restart
# DAILY_COST_LIMIT_USD=100
docker compose up -d  # picks up new env var
```

---

## 5. Database Backup & Restore

### Backup

```bash
make backup-db
# Saves to ./backups/masdb_YYYYMMDD_HHMMSS.sql
```

### Restore

```bash
docker compose exec -T postgres psql -U mas masdb < backups/masdb_20260320_080000.sql
```

### List recent backups

```bash
ls -lh backups/
```

---

## 6. Health Check All Services

```bash
# Quick check — all services at once
for svc in "8000" "8001" "8002" "8003" "8004" "8005" "8100"; do
  status=$(curl -sf "http://localhost:$svc/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "FAIL")
  echo "Port $svc: $status"
done

# Or run smoke tests (stack must be up)
pytest tests/smoke/ -v
```

---

## 7. Common Failure Modes & Recovery

| Symptom | Likely Cause | Recovery |
|---|---|---|
| `POST /tickets` returns 503 | api-gateway down or Redis unavailable | `docker compose restart api-gateway redis` |
| Tickets stuck in `queued` for >5min | Orchestrator consumer stopped | `docker compose restart orchestrator` |
| All tickets failing with vault error | ssh-vault crash or key mismatch | `docker compose logs ssh-vault`, then `docker compose restart ssh-vault` |
| RAG search returning 0 results | Qdrant down or BM25 index not built | `docker compose restart rag-service qdrant` |
| Grafana shows no metrics | Prometheus unreachable | `docker compose restart prometheus grafana` |
| Langfuse traces missing | Langfuse DB migration pending | `docker compose exec llmops npx prisma migrate deploy` |
| Agent hitting `DAILY_COST_LIMIT_USD` | Normal if high ticket volume | Increase limit in `.env` or reset: `make reset-cost` |
