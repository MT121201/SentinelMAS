# dev_note — alembic (database schema)

## Purpose
Single Alembic migration chain for the shared `masdb` PostgreSQL database.
All services read/write this DB via `services/shared/db.py`.
Run migrations: `make migrate` (calls `alembic upgrade head` inside the api-gateway container).

## Migration Chain

```
None → 001 → 002 → 003 → 004 → 005 → 006 (head)
```

---

## Tables

### `server_credentials` (migration 001)
Owner: `ssh-vault`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | gen_random_uuid() |
| `server_id` | VARCHAR(64) UNIQUE | logical name e.g. "gpu-node-01" |
| `display_name` | VARCHAR(128) | human label |
| `hostname` | TEXT | IP or hostname — plaintext OK |
| `port` | INTEGER | default 22 |
| `username_enc` | BYTEA | AES-256-GCM ciphertext |
| `ssh_key_enc` | BYTEA | AES-256-GCM ciphertext |
| `sudo_pass_enc` | BYTEA nullable | AES-256-GCM ciphertext |
| `key_nonce` | BYTEA | GCM nonce for ssh_key |
| `user_nonce` | BYTEA | GCM nonce for username |
| `sudo_nonce` | BYTEA nullable | GCM nonce for sudo_pass |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |
| `rotated_at` | TIMESTAMPTZ nullable | set on key rotation |
| `is_active` | BOOLEAN | soft-delete flag |

---

### `credential_access_log` (migration 002)
Owner: `ssh-vault`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `server_id` | VARCHAR(64) | FK-style reference (no hard FK for perf) |
| `agent_id` | VARCHAR(64) | which agent accessed |
| `trace_id` | VARCHAR(64) | Langfuse trace correlation |
| `operation` | VARCHAR(32) | `connect` \| `execute` \| `close` |
| `accessed_at` | TIMESTAMPTZ | |
| `success` | BOOLEAN | |

Indexes: `(server_id, accessed_at DESC)`, `(trace_id)`

---

### `tickets` (migration 003)
Owner: `api-gateway` (writes), `client-agent` (updates status/resolution)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | returned to user as ticket_id |
| `server_id` | VARCHAR(64) | target server |
| `description` | TEXT | sanitised ticket text |
| `severity` | VARCHAR(16) | `LOW` \| `MEDIUM` \| `HIGH` \| `CRITICAL` |
| `status` | VARCHAR(32) | state machine below |
| `agent_id` | VARCHAR(64) nullable | assigned agent |
| `trace_id` | VARCHAR(64) nullable | Langfuse trace |
| `resolution_summary` | TEXT nullable | user-facing result |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

Status state machine: `queued → assigned → thinking → executing → verifying → done | failed | escalated`

Indexes: `(status, created_at)`, `(server_id)`, `(trace_id)`

---

### `daily_health_snapshots` (migration 004)
Owner: `inserver-agent` (writes), `report-agent` (reads)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `server_id` | VARCHAR(64) | |
| `date` | DATE | one row per server per day |
| `metrics_json` | JSONB | `{gpu_util, disk_used_pct, mem_used_pct, services_ok, services_down, blacklisted, issues}` |
| `status` | VARCHAR(16) | `ok` \| `warn` \| `critical` |
| `created_at` | TIMESTAMPTZ | |

Unique constraint: `(server_id, date)` — one snapshot per server per day.
Index: `(server_id, date)`

---

### `rag_kb_entries` (migration 005)
Owner: `rag-service` (writes + reads)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `error_pattern` | TEXT | sanitised error description |
| `fix_steps` | TEXT | sanitised fix instructions |
| `tags` | TEXT[] | GIN-indexed array |
| `confidence` | FLOAT | default 1.0 |
| `embedding_id` | VARCHAR(128) nullable | Qdrant point ID |
| `bm25_doc_id` | INTEGER nullable | position in BM25 index |
| `source` | VARCHAR(64) | `agent_resolution` \| `manual` \| `import` |
| `created_at` | TIMESTAMPTZ | |

Indexes: `tags` (GIN), `source`

---

### `apscheduler_jobs` (migration 006)
Owner: `scheduler` service (managed automatically by APScheduler)

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(191) PK | APScheduler job ID |
| `next_run_time` | FLOAT nullable | unix timestamp; indexed |
| `job_state` | BYTEA | pickled job state |

Index: `(next_run_time)` — APScheduler queries this to find the next job to run.
**Do not write to this table manually** — APScheduler manages it entirely.

---

## Adding a New Migration

```bash
# Generate a new migration file
alembic revision -m "describe_what_you_are_adding"
# Edit the generated file in alembic/versions/
# Then update this dev_note with the new table or column changes
```

Naming convention: `NNN_short_description.py` where NNN is the next integer.
Always set `down_revision` to the previous revision ID.
