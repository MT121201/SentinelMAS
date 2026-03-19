# SSH Vault Service

Internal-only credential store for GPU server SSH keys.
Agents **never** receive raw key bytes — they get a short-lived session token backed by an in-process `paramiko.SSHClient`.

**Port:** `8100` | **Network:** internal only | **Auth:** `X-Internal-Key` header

---

## Why It Exists

Every agent that needs to SSH into a server calls this service instead of holding keys itself. This creates a single, audited chokepoint:

- Keys are encrypted at rest (AES-256-GCM, master key in env only)
- Every access is logged with `{agent_id, server_id, trace_id, operation}`
- Dangerous commands are rejected before reaching the server

---

## Credential Lifecycle

```mermaid
sequenceDiagram
    participant Admin
    participant Vault
    participant DB as PostgreSQL

    Admin->>Vault: POST /vault/credentials {server_id, hostname, username, ssh_key}
    Vault->>Vault: VaultCrypto.encrypt(username) → (ciphertext, nonce)
    Vault->>Vault: VaultCrypto.encrypt(ssh_key)  → (ciphertext, nonce)
    Vault->>DB: INSERT server_credentials (encrypted fields)
    Vault-->>Admin: {server_id, status: "created"}

    Admin->>Vault: PUT /vault/credentials/{server_id} (rotate key)
    Vault->>Vault: encrypt(new_key) → new ciphertext+nonce
    Vault->>DB: UPDATE server_credentials SET ssh_key_enc=..., rotated_at=now()
    Vault-->>Admin: {status: "updated"}
```

---

## SSH Session Lifecycle

```mermaid
sequenceDiagram
    participant Agent
    participant Vault
    participant DB as PostgreSQL
    participant Registry as SessionRegistry
    participant Server as GPU Server

    Agent->>Vault: POST /vault/session {server_id, agent_id, trace_id, ttl=300}
    Vault->>DB: SELECT server_credentials WHERE server_id=...
    Vault->>Vault: decrypt(username_enc, user_nonce)
    Vault->>Vault: decrypt(ssh_key_enc, key_nonce)
    Vault->>Server: paramiko.connect(hostname, pkey=decrypted_key)
    Vault->>Vault: zero out key plaintext from memory
    Vault->>Registry: store {token → SSHClient, expires_at=now+300s}
    Vault->>DB: INSERT credential_access_log (operation="connect")
    Vault-->>Agent: {session_token: "abc..."}

    Agent->>Vault: POST /vault/session/{token}/execute {command: "nvidia-smi"}
    Vault->>Vault: safety.is_safe_command("nvidia-smi") → safe=True
    Vault->>Server: SSHClient.exec_command("nvidia-smi")
    Server-->>Vault: stdout, stderr, exit_code
    Vault->>DB: INSERT credential_access_log (operation="execute")
    Vault-->>Agent: {stdout, stderr, exit_code, duration_ms}

    Agent->>Vault: DELETE /vault/session/{token}
    Vault->>Registry: SSHClient.close(), remove token
    Vault->>DB: INSERT credential_access_log (operation="close")
    Vault-->>Agent: {status: "closed"}
```

---

## Command Safety Filter

Before any command reaches the server, `safety.py` checks it against forbidden patterns:

| Pattern | Reason Blocked |
|---|---|
| `rm -rf /` or `rm -rf ~/` | Recursive delete from root |
| `mkfs.*` | Filesystem format |
| `dd ... of=/dev/` | Raw device write |
| `> /dev/sda` | Direct block device write |
| `chmod 777 /` | World-writable root |
| `:(){ :|:& };:` | Fork bomb |
| `curl ... \| bash` | Pipe URL to shell |
| `poweroff` / `shutdown` | System power-off |
| `iptables -F` | Flush all firewall rules |

If blocked: command is rejected, attempt is logged, no SSH call is made.

---

## Encryption Design

```mermaid
flowchart LR
    ENV["VAULT_MASTER_KEY\n(32-byte, base64, env only)"]
    AESGCM["AESGCM(key)\nloaded once at startup"]
    PT["plaintext field\ne.g. SSH private key"]
    NONCE["os.urandom(12)\nnew nonce per encrypt"]
    CT["ciphertext\n(stored in DB)"]
    NONCE2["nonce\n(stored in DB alongside CT)"]

    ENV --> AESGCM
    PT --> AESGCM
    NONCE --> AESGCM
    AESGCM --> CT
    AESGCM --> NONCE2
```

- One nonce per field per encrypt call — reuse would break GCM security
- Tampered ciphertext raises `cryptography.exceptions.InvalidTag`
- Master key is never logged, never returned via API, zeroed on GC (best-effort)

---

## File Structure

```
ssh-vault/
├── main.py              # FastAPI app, startup/shutdown hooks, /health
├── config.py            # Pydantic settings (env vars)
├── crypto.py            # VaultCrypto: AES-256-GCM encrypt/decrypt
├── models.py            # SQLAlchemy ORM: ServerCredential, CredentialAccessLog
├── routes.py            # All API endpoints
├── safety.py            # is_safe_command() filter
├── session_registry.py  # token → SSHClient store with TTL eviction
├── requirements.txt
├── Dockerfile
├── dev_note.md          # Function-level reference for Claude
└── tests/
    ├── test_crypto.py          # 8 encrypt/decrypt cases
    ├── test_safety.py          # 20 allow/block cases
    └── test_session_registry.py # 11 lifecycle cases
```

---

## Running Tests

```bash
# From repo root
pytest services/ssh-vault/tests/ -v

# Or via Make
make test-service SERVICE=ssh-vault
```

---

## API Reference

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/vault/credentials` | Register new server credential |
| `PUT` | `/vault/credentials/{server_id}` | Update or rotate credential |
| `DELETE` | `/vault/credentials/{server_id}` | Deactivate credential |
| `POST` | `/vault/session` | Open SSH session → token |
| `POST` | `/vault/session/{token}/execute` | Run command on session |
| `DELETE` | `/vault/session/{token}` | Close session |
| `GET` | `/health` | Service health + active session count |

All endpoints require header: `X-Internal-Key: <INTERNAL_API_KEY>`
