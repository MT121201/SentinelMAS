# SECURITY — GPU-MAS

## 1. Threat Model

| Threat | Mitigation |
|---|---|
| SSH private key exfiltration | Keys encrypted at rest; agents never receive key bytes; in-process paramiko only |
| Agent prompt injection via ticket text | Input sanitisation; LLM output parsed as structured data, not executed as shell directly |
| Rogue agent executing destructive commands | Pre-execution command safety filter; forbidden pattern list; all commands logged before exec |
| Container escape → host pivot | Vault container runs without host volume mounts; no `--privileged` flag |
| Redis cache poisoning | Internal network only; Redis requires password; no external exposure |
| Log data leaking client server info | Log sanitiser strips IPs/paths; client file content never reaches logging layer |
| API key leakage | Keys in Docker secrets / env vars; never in images; never in git |
| Cost runaway from agent loops | Daily USD ceiling in Redis; circuit breaker cuts LLM calls when limit hit |

---

## 2. SSH Vault Service

### 2.1 Database Schema

```sql
-- services/ssh-vault/migrations/001_initial.sql

CREATE TABLE server_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id       VARCHAR(64) UNIQUE NOT NULL,       -- logical name
    display_name    VARCHAR(128) NOT NULL,
    hostname        TEXT NOT NULL,                     -- plaintext OK (not secret)
    port            INTEGER NOT NULL DEFAULT 22,
    username_enc    BYTEA NOT NULL,                    -- AES-256-GCM encrypted
    ssh_key_enc     BYTEA NOT NULL,                    -- AES-256-GCM encrypted
    sudo_pass_enc   BYTEA,                             -- optional, encrypted
    key_nonce       BYTEA NOT NULL,                    -- GCM nonce for ssh_key
    user_nonce      BYTEA NOT NULL,                    -- GCM nonce for username
    sudo_nonce      BYTEA,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    rotated_at      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE TABLE credential_access_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id       VARCHAR(64) NOT NULL,
    agent_id        VARCHAR(64) NOT NULL,
    trace_id        VARCHAR(64) NOT NULL,
    operation       VARCHAR(32) NOT NULL,              -- 'connect','execute','close'
    accessed_at     TIMESTAMPTZ DEFAULT NOW(),
    success         BOOLEAN NOT NULL
);

-- Index for audit queries
CREATE INDEX idx_access_log_server ON credential_access_log(server_id, accessed_at DESC);
CREATE INDEX idx_access_log_trace  ON credential_access_log(trace_id);
```

### 2.2 Encryption Implementation

```python
# services/ssh-vault/crypto.py
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os, base64

class VaultCrypto:
    """
    AES-256-GCM encryption for vault fields.
    Master key loaded ONCE at startup from environment — never re-read.
    """

    def __init__(self):
        key_b64 = os.environ["VAULT_MASTER_KEY"]  # 32-byte key, base64-encoded
        self._key = base64.b64decode(key_b64)
        assert len(self._key) == 32, "VAULT_MASTER_KEY must be 32 bytes"
        self._aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """Returns (ciphertext, nonce). Nonce is 12 bytes, randomly generated."""
        nonce = os.urandom(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode(), None)
        return ct, nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        pt = self._aesgcm.decrypt(nonce, ciphertext, None)
        return pt.decode()

    def __del__(self):
        # Attempt to zero key material (best-effort in CPython)
        import ctypes
        if hasattr(self, '_key'):
            buf = (ctypes.c_char * len(self._key)).from_buffer(bytearray(self._key))
            ctypes.memset(buf, 0, len(self._key))
```

### 2.3 Session API (Internal Only)

```
POST /vault/session
  Body: {server_id, agent_id, trace_id, ttl_seconds}
  Auth: Internal API key (X-Internal-Key header)
  Returns: {session_token}  ← opaque token, redeemed in-process

# The vault service holds the active paramiko.SSHClient in a session registry
# Agents redeem session_token via gRPC or internal HTTP to run commands
# Session auto-closes after ttl_seconds or explicit /vault/session/{token}/close
```

**No SSH key material ever leaves the vault service process.**

---

## 3. Secret Management

### 3.1 Secret Inventory

| Secret | Storage | Rotation |
|---|---|---|
| `VAULT_MASTER_KEY` | Docker secret / env var | Manual, quarterly |
| `ANTHROPIC_API_KEY` | Docker secret / env var | Manual, on compromise |
| `POSTGRES_PASSWORD` | Docker secret / env var | Manual, quarterly |
| `REDIS_PASSWORD` | Docker secret / env var | Manual, quarterly |
| `JWT_SECRET_KEY` | Docker secret / env var | Manual, monthly |
| `INTERNAL_API_KEY` | Docker secret / env var | Manual, monthly |
| Per-server SSH keys | Vault DB (encrypted) | Per-server policy |

### 3.2 Docker Secrets (Production)

```yaml
# docker-compose.prod.yml excerpt
secrets:
  vault_master_key:
    file: ./secrets/vault_master_key.txt
  anthropic_api_key:
    file: ./secrets/anthropic_api_key.txt

services:
  ssh-vault:
    secrets:
      - vault_master_key
    environment:
      VAULT_MASTER_KEY_FILE: /run/secrets/vault_master_key
```

### 3.3 .gitignore Required Entries

```
.env
.env.*
secrets/
*.pem
*.key
*.p12
```

---

## 4. Network Security

```yaml
# All services on internal Docker network — only API gateway exposed
networks:
  internal:
    driver: bridge
    internal: true   # no external routing
  public:
    driver: bridge

services:
  api-gateway:
    networks: [public, internal]  # only service on both
  agent-orchestrator:
    networks: [internal]
  ssh-vault:
    networks: [internal]
  postgres:
    networks: [internal]
  redis:
    networks: [internal]
```

---

## 5. Input Sanitisation

### 5.1 Ticket Input

```python
import bleach, re

def sanitise_ticket_input(text: str) -> str:
    # Remove HTML
    text = bleach.clean(text, tags=[], strip=True)
    # Limit length
    text = text[:4000]
    # Remove potential prompt injection markers
    text = re.sub(r'<\|.*?\|>', '', text)
    text = re.sub(r'###\s*(System|Assistant|Human):', '', text, flags=re.IGNORECASE)
    return text.strip()
```

### 5.2 SSH Command Safety Filter

```python
import re

FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+[/~]",
    r"mkfs\b",
    r"\bdd\b.*of=/dev/",
    r">\s*/dev/sd[a-z]",
    r"chmod\s+[0-7]*7[0-7]*\s+/",
    r":\(\)\{.*\}",          # fork bomb
    r"curl\s+.*\|\s*(bash|sh)",  # pipe to shell
    r"wget\s+.*-O\s*-\s*\|",
]

def is_safe_command(cmd: str) -> tuple[bool, str]:
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return False, f"Forbidden pattern detected: {pattern}"
    return True, "ok"
```

### 5.3 Log Sanitiser

```python
import re

SANITISE_PATTERNS = [
    (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[IP_REDACTED]'),           # IPv4
    (r'(?i)(password|passwd|secret|key)\s*[:=]\s*\S+', r'\1=[REDACTED]'),
    (r'-----BEGIN [A-Z ]+-----[\s\S]+?-----END [A-Z ]+-----', '[KEY_REDACTED]'),
    (r'/home/\w+', '/home/[USER]'),
    (r'/root', '/[ROOT]'),
]

def sanitise_log(text: str) -> str:
    for pattern, replacement in SANITISE_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text
```

---

## 6. Auth Design (FastAPI)

```python
# services/api-gateway/auth.py

from fastapi.security import HTTPBearer, APIKeyHeader
from jose import jwt, JWTError

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

bearer_scheme = HTTPBearer()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_current_user(token: str = Depends(bearer_scheme)) -> dict:
    try:
        payload = jwt.decode(token.credentials, settings.JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_api_key(key: str = Depends(api_key_header)) -> str:
    if key not in settings.VALID_API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key
```

---

## 7. Audit & Compliance Checklist

- [ ] All SSH credential accesses logged with trace_id
- [ ] All hard restart events logged + manager notified
- [ ] All LLM calls traced (Langfuse) — including prompt content
- [ ] Agent action plans logged before execution
- [ ] Daily log retention: 90 days (configurable)
- [ ] Credential access log retention: 1 year
- [ ] SSH session recordings (optional): paramiko transcript — disabled by default, enable on investigation
