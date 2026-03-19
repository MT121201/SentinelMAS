# dev_note — ssh-vault

## Purpose
AES-256-GCM encrypted SSH credential store. Agents never receive raw SSH keys — they get short-lived paramiko sessions via a token.

## Files

### config.py
- `Settings` — pydantic-settings config; reads VAULT_MASTER_KEY, POSTGRES_DSN, INTERNAL_API_KEY, SESSION_TTL_SECONDS

### crypto.py
- `VaultCrypto` — AES-256-GCM encrypt/decrypt
  - `encrypt(plaintext: str) -> tuple[bytes, bytes]` — returns (ciphertext, nonce); nonce is 12-byte random per call
  - `decrypt(ciphertext: bytes, nonce: bytes) -> str` — raises `InvalidTag` if tampered
  - `__del__()` — best-effort zero of key material

### models.py
- `ServerCredential` — ORM model for `server_credentials` table
- `CredentialAccessLog` — ORM model for `credential_access_log` table

### safety.py
- `is_safe_command(command: str) -> SafetyResult` — checks against FORBIDDEN_PATTERNS; returns `SafetyResult(safe, reason)`
- `FORBIDDEN_PATTERNS` — list of (regex, description) tuples; update here to add new rules
- `SafetyResult` — NamedTuple with `.safe: bool` and `.reason: str`

### session_registry.py
- `SessionRegistry` — in-process token → paramiko.SSHClient store
  - `create(server_id, agent_id, trace_id, client, ttl) -> str` — registers client, returns opaque token
  - `execute(token, command, timeout) -> dict` — runs command; dict has {stdout, stderr, exit_code, duration_ms}; safety-checked before exec
  - `close(token) -> None` — closes SSHClient, removes from registry
  - `start() / stop()` — manage background TTL eviction asyncio task
- `get_registry() -> SessionRegistry` — returns module-level singleton
- `registry` — module-level singleton; set to `SessionRegistry(...)` in `main.py` startup

### routes.py
- `router` — APIRouter with all vault endpoints
- `require_internal_key` — FastAPI dependency; validates X-Internal-Key header
- `add_credential(body, db)` — `POST /vault/credentials`
- `update_credential(server_id, body, db)` — `PUT /vault/credentials/{server_id}`
- `deactivate_credential(server_id, db)` — `DELETE /vault/credentials/{server_id}`
- `create_session(body, db)` — `POST /vault/session`; decrypts key in-memory, opens paramiko, returns token
- `execute_command(token, body, db)` — `POST /vault/session/{token}/execute`
- `close_session(token)` — `DELETE /vault/session/{token}`
- `_audit(db, ...)` — internal helper; writes CredentialAccessLog (fire-and-forget)

### main.py
- FastAPI app entry point, port 8100
- `startup()` — initialises SessionRegistry singleton, starts eviction loop
- `shutdown()` — stops registry, closes all sessions
- `GET /health` — checks Postgres connectivity, returns active_sessions count

## Cross-Service Contracts
- Called by: `inserver-agent`, `client-agent` via HTTP on internal network
- Auth: `X-Internal-Key` header required on ALL endpoints
- Writes: `server_credentials`, `credential_access_log` tables in Postgres
- Listens on: port 8100 (no public exposure)
- Build context: root (needs `services/shared/` → PYTHONPATH=/app)

## Key Design Rules
- Raw SSH key bytes NEVER leave this service
- Every credential access logged: {timestamp, agent_id, server_id, operation, trace_id}
- Session TTL: 300s default; evicted by asyncio background task every 30s
- `safety.py` rejects any command matching FORBIDDEN_PATTERNS BEFORE calling exec_command

## Known Gaps / Deferred
- `create_session` assumes RSA keys only — add Ed25519 support when needed (`paramiko.Ed25519Key`)
- paramiko key zero-out after connect is best-effort (CPython GC, not guaranteed)
