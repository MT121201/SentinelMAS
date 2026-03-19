# dev_note — ssh-vault

## Purpose
AES-256-GCM encrypted SSH credential store. Agents never receive raw SSH keys — they get short-lived paramiko sessions via a token.

## Files
> Phase 0 scaffold — no code files yet. Built in Phase 1C.

Planned files (from TODO.md P1-11 to P1-17):
- `main.py` — FastAPI app, internal network only (no public port)
- `crypto.py` — `VaultCrypto` class: AES-256-GCM encrypt/decrypt using VAULT_MASTER_KEY
- `models.py` — SQLAlchemy ORM: `ServerCredential`, `CredentialAccessLog`
- `routes.py` — credential CRUD + session create/execute/close endpoints
- `session_registry.py` — in-process `{token: paramiko.SSHClient}` dict with TTL eviction
- `safety.py` — `is_safe_command()` filter (FORBIDDEN_PATTERNS list)

## Cross-Service Contracts
- Called by: `inserver-agent`, `client-agent` (SSH session creation + command execution)
- Writes: `server_credentials`, `credential_access_log` tables in Postgres
- Listens on: port 8100 (internal only — no public exposure)
- Master key: injected via `VAULT_MASTER_KEY` env var, never written to disk

## Key Design Rules
- Raw SSH key bytes NEVER leave this service
- Every credential access logged: {timestamp, agent_id, server_id, operation, trace_id}
- Session TTL: 300 seconds; evicted by asyncio background task
- `safety.py` rejects any command matching FORBIDDEN_PATTERNS before execution

## Known Gaps / Deferred
- Phase 0: directory scaffold only
