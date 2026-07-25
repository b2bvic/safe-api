# safe-api

Safety wrapper for REST API write operations. Seven rules that prevent runaway writes to production APIs.

Born from a real production incident where a batch write created duplicate CRM records. Zero dependencies — Python stdlib only.

Built by [Victor Valentine Romo](https://victorvalentineromo.com) at [Scale With Search](https://scalewithsearch.com).

Part of a larger system: this repository proves **P09 (agency is governed)** from the [Seventeen Principles](https://victorvalentineromo.com/principles). What ships here is the capability-gate pattern itself; side effects are a permission granted per operation, never a habit the tooling drifts into.

## The Seven Rules

1. **Dry-run default** — `--execute` flag required to actually send writes
2. **One record per transaction** — no batch mutations, GET→diff→PUT/POST→verify→log
3. **Duplicate guard** — configurable dedup check before POST
4. **Circuit breaker** — halts all writes on 2+ failures or rate exceeded
5. **Audit trail** — every write logged to JSONL (including dry-runs)
6. **Scope whitelist** — per-client endpoint restrictions + global blocks
7. **Human escalation** — incident files generated on breaker trip

## Install

```python
# Copy safe_api.py into your project, or:
curl -o safe_api.py https://raw.githubusercontent.com/b2bvic/safe-api/main/safe_api.py
```

Zero pip dependencies. Uses only Python stdlib (`urllib`, `json`, `pathlib`).

## Usage

```python
from safe_api import SafeAPIClient

# Initialize with your API
client = SafeAPIClient(
    base_url="https://api.example.com/v1",
    name="my-sync-script",
    allowed_endpoints=["/contacts", "/tasks"],
    blocked_endpoints=["/billing", "/users"],
    auth_header="Bearer your-token-here",
    max_writes_per_minute=10,
)

# Dry-run mode (default) — logs intent but doesn't send
result = client.post("/contacts", {"name": "Jane Doe", "email": "jane@example.com"})
# Returns: {"dry_run": True, "would_send": {...}, "endpoint": "/contacts", "method": "POST"}

# Execute mode — pass --execute on CLI or set execute=True
# result = client.post("/contacts", {"name": "Jane Doe", "email": "jane@example.com"})
# Actually sends the request
```

### Scope Enforcement

```python
client = SafeAPIClient(
    base_url="https://api.example.com/v1",
    name="contact-updater",
    allowed_endpoints=["/contacts"],          # Only these endpoints
    blocked_endpoints=["/billing"],            # Never these
    blocked_methods={"/contacts": ["DELETE"]}, # Block specific methods
)

client.post("/contacts", {...})    # OK
client.put("/contacts/123", {...}) # OK
client.delete("/contacts/123")     # ScopeViolation!
client.post("/billing", {...})     # ScopeViolation!
client.post("/tasks", {...})       # ScopeViolation! (not in allowed list)
```

### Duplicate Guard

```python
def check_contact_exists(client, endpoint, payload):
    """Custom dedup checker — return existing record or None."""
    email = payload.get("email")
    if email:
        results = client.get(f"/contacts?email={email}")
        contacts = results.get("contacts", [])
        if contacts:
            return contacts[0]  # Duplicate found
    return None  # No duplicate

client = SafeAPIClient(
    base_url="https://api.example.com/v1",
    name="contact-importer",
    allowed_endpoints=["/contacts"],
    dedup_checker=check_contact_exists,
)
```

### Circuit Breaker

The breaker trips automatically when:
- 2+ write failures in a session (configurable via `max_failures`)
- Write rate exceeds `max_writes_per_minute`

When tripped:
- All further writes raise `CircuitBreakerTripped`
- An incident JSON file is written to the log directory
- Manual reset: `client.reset_breaker()`

### Auth Methods

```python
# Bearer token
SafeAPIClient(base_url="...", auth_header="Bearer abc123")

# API key from environment variable
SafeAPIClient(base_url="...", api_key_env="MY_API_KEY")

# Basic auth (construct the header yourself)
import base64
creds = base64.b64encode(b"user:pass").decode()
SafeAPIClient(base_url="...", auth_header=f"Basic {creds}")
```

### Audit Log

Every write (including dry-runs, duplicates, and failures) is logged to JSONL:

```json
{
  "timestamp": "2026-03-25T20:00:00+00:00",
  "client": "contact-updater",
  "endpoint": "/contacts/123",
  "method": "PUT",
  "action": "EXECUTED",
  "payload": {"name": "Jane Doe"},
  "reason": "weekly sync",
  "dry_run": false,
  "response_status": 200
}
```

```python
# View recent writes
for entry in client.log_tail(10):
    print(f"{entry['action']} {entry['method']} {entry['endpoint']}")
```

Log location: `~/.cache/safe-api/{name}-writes.jsonl` (configurable via `log_dir`).

## API

```python
SafeAPIClient(
    base_url: str,                          # API base URL
    name: str = "safe-api",                 # Client name (used in logs)
    allowed_endpoints: list[str] | None,    # Whitelist (None = allow all)
    blocked_endpoints: list[str] | None,    # Global blocks
    blocked_methods: dict | None,           # Per-endpoint method blocks
    auth_header: str | None,                # Authorization header value
    api_key_env: str | None,                # Env var name for API key
    max_writes_per_minute: int = 10,        # Rate limit
    max_failures: int = 2,                  # Circuit breaker threshold
    log_dir: str | None,                    # Log directory path
    execute: bool | None,                   # Override dry-run (None = check CLI)
    dedup_checker: Callable | None,         # Custom duplicate checker
)

# Methods
client.get(endpoint, params=None)           # Always allowed
client.post(endpoint, payload, reason="")   # Gated
client.put(endpoint, payload, reason="")    # Gated
client.patch(endpoint, payload, reason="")  # Gated
client.delete(endpoint, reason="")          # Gated
client.log_tail(n=20)                       # Read audit log
client.reset_breaker()                      # Manual breaker reset
```

## License

MIT

## How this was built

Specification and judgment: human. Implementation: AI models executing that specification under a build contract, with an adversarial audit before publish. The division of labor is the point; see [P07](https://victorvalentineromo.com/principles).
