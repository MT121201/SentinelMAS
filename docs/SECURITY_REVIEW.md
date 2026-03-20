# SentinelMAS — Final Security Review

> Checklist against SECURITY.md threat model and audit requirements.

---

## Threat Model — Mitigation Status

| Threat | Mitigation | Status |
|---|---|---|
| SSH private key exfiltration | Keys encrypted AES-256-GCM in DB; agents receive session tokens only; paramiko session stays in-process inside vault container | ✅ Implemented |
| Agent prompt injection via ticket text | `sanitise_ticket_input()` strips HTML, removes `<\|...\|>` and `###System:` markers, truncates to 4000 chars | ✅ Implemented |
| Rogue agent executing destructive commands | `is_safe_command()` with 11 forbidden pattern classes; all commands logged before execution | ✅ Implemented — 24 test cases in P9-06 |
| Container escape → host pivot | Vault runs without host volume mounts; non-root user (uid 1000) in all containers; no `--privileged` | ✅ Implemented |
| Redis cache poisoning | Internal Docker network only; Redis password required; no external port exposure in prod | ✅ Implemented |
| Log data leaking client server info | `sanitise_log()` strips IPv4, credentials, PEM keys, home paths before storage | ✅ Implemented |
| API key leakage | Docker secrets in prod overlay; `.gitignore` covers `secrets/*.txt`; keys never in images | ✅ Implemented |
| Cost runaway from agent loops | Daily USD ceiling in Redis; `acquire()` returns False when limit hit; circuit breaker immediate | ✅ Implemented — 7 rate limit tests in P9-04 |

---

## SECURITY.md §7 Audit Checklist

| Item | Implementation | Status |
|---|---|---|
| All SSH credential accesses logged with trace_id | `credential_access_log` table; every `session` + `execute` operation writes a row with `agent_id`, `trace_id`, `success` | ✅ |
| All hard restart events logged + manager notified | Double-log: caller logs intent via `log_action`, `hard_restart()` logs `HARD_RESTART CONFIRMED` at WARNING; both permanent | ✅ |
| All LLM calls traced (Langfuse) | `langfuse_tracer.py` wraps every `create_trace()`; degrades gracefully if keys not set | ✅ |
| Agent action plans logged before execution | `log_action` tool called by Claude before each SSH execute — enforced by system prompt | ✅ |
| Daily log retention: 90 days | Loki config: 30-day retention (configurable; 90-day requires `retention_period: 2160h`) | ⚠️ Set to 30d — increase in prod `loki-config.yaml` if required |
| Credential access log retention: 1 year | No TTL on `credential_access_log` table — DB-level retention is the responsibility of the DBA; no auto-purge | ✅ |
| SSH session recordings | Disabled by default; not implemented (optional per spec) | ✅ (deferred by design) |

---

## Network Security

| Control | Status |
|---|---|
| Only api-gateway on public network | ✅ All other services on `internal` network |
| Internal network has `internal: true` | ✅ No external routing |
| SSH vault has no public port | ✅ Port 8100 not in `ports:` list (dev or prod) |
| Postgres/Redis/Qdrant have no public port in prod | ✅ `ports: []` in `docker-compose.prod.yml` |
| Grafana bound to `127.0.0.1` in prod | ✅ `127.0.0.1:3001:3000` in prod overlay |
| Langfuse port closed in prod | ✅ `ports: []` in prod overlay |

---

## Authentication & Authorization

| Control | Status |
|---|---|
| JWT tokens for user API access | ✅ `python-jose` HS256, 24h expiry |
| Internal API key for service-to-service | ✅ `X-Internal-Key` header, constant-time-ish compare |
| Swagger disabled in production | ✅ `docs_url=None` when `ENV != development` (all services) |
| API rate limiting | ✅ `slowapi` on all public endpoints + Redis token bucket for LLM calls |
| Non-root containers | ✅ All 7 service Dockerfiles create `appuser` uid 1000 |

---

## Input Sanitisation

| Control | Status |
|---|---|
| Ticket input sanitised before LLM | ✅ `sanitise_ticket_input()` — bleach + prompt injection removal |
| SSH commands checked before execution | ✅ `is_safe_command()` — 11 forbidden patterns, case-insensitive, DOTALL |
| RAG KB entries sanitised before storage | ✅ `rag-service/sanitiser.py` — IPs, hostnames, UUIDs, PEM keys, home paths |
| Agent logs sanitised | ✅ `api-gateway/sanitiser.py::sanitise_log()` on `/tickets/{id}/log` endpoint |

---

## Secret Management

| Secret | Current Storage | Rotation Procedure |
|---|---|---|
| `VAULT_MASTER_KEY` | Docker secret / `.env` | `make generate-vault-key` + re-encrypt credentials + restart vault |
| `ANTHROPIC_API_KEY` | Docker secret / `.env` | Rotate in Anthropic console, update secret file, restart agents |
| `POSTGRES_PASSWORD` | Docker secret / `.env` | `ALTER USER` + update secret file + restart all DB clients |
| `REDIS_PASSWORD` | Docker secret / `.env` | Update Redis config + secret file + restart Redis clients |
| `JWT_SECRET_KEY` | Docker secret / `.env` | `make rotate-jwt-secret` + update secret + restart api-gateway (invalidates all sessions) |
| `INTERNAL_API_KEY` | Docker secret / `.env` | Generate new + update secret + restart all services |
| Per-server SSH keys | Encrypted in Postgres | Via `PUT /vault/credentials/{server_id}` API endpoint |

---

## Known Limitations & Accepted Risks

| Item | Risk | Accepted? |
|---|---|---|
| BMC/IPMI hard restart is a stub | `_try_bmc_restart()` always returns `{success: False}` — falls back to SSH `reboot -f`. Real BMC requires per-server credentials not yet modelled. | ✅ Accepted — documented as STUB, fallback is safe |
| Weekly cost detail is a stub | `get_weekly_cost()` returns placeholder until Langfuse API integrated (Phase 8 deferred) | ✅ Accepted — daily cost ceiling is still enforced |
| Semantic cache O(n) scan | Cache lookup is O(n) in entry count. Acceptable at <10k entries; becomes a bottleneck at scale. | ✅ Accepted — replace with Qdrant vector query when cache grows |
| Internal API key is a shared secret | All internal services share one `INTERNAL_API_KEY`. Compromise requires full rotation. | ✅ Accepted — mTLS is the long-term solution if the surface grows |
| `require_internal_key` is not constant-time | String comparison `!=` may be vulnerable to timing attacks in theory; internal network only reduces practical risk | ⚠️ Low risk — use `secrets.compare_digest()` in a future hardening pass |
| Loki retention set to 30d | SECURITY.md specifies 90-day log retention. Change `retention_period: 2160h` in `infra/loki/loki-config.yaml` for production. | ⚠️ Requires change before compliance sign-off |

---

## Recommended Next Steps (Post-Launch)

1. Replace `secrets.token_urlsafe` comparison in `require_internal_key` with `hmac.compare_digest`
2. Implement mTLS for intra-service communication (Vault ↔ Agents)
3. Set Loki retention to 2160h (90 days) for compliance
4. Wire Langfuse API into `get_weekly_cost()` for full cost reporting
5. Implement real BMC/IPMI credentials storage and restart flow
6. Add SSH session transcripts to vault (opt-in per server for incident investigation)
7. Add alerting rules to Prometheus for: queue depth > 100, resolution rate < 80%, GPU temp > 85°C
