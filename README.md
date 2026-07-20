# safe-api

A zero-dependency Python wrapper that puts dry runs, scope checks, duplicate checks, circuit breaking, incident artifacts, and JSONL receipts around REST API mutations.

It is designed for small automation scripts where an accidental loop, broad endpoint, or repeated failure could write bad state faster than a human can intervene.

## Seven guardrails

1. **Dry-run default:** mutation methods log intent and return without sending unless execute mode is explicit.
2. **One mutation request per method call:** all writes pass through one central `_write` path.
3. **Duplicate callback:** callers can refuse a POST after an application-specific lookup.
4. **Circuit breaker:** successful-write rate and session failures can stop further mutations.
5. **Audit receipt:** dry runs, duplicate refusals, executed writes, and failures append to JSONL.
6. **Scope controls:** allowlisted base endpoints, blocked base endpoints, and blocked methods are checked before a write.
7. **Incident artifact:** a breaker trip writes a local JSON file with the reason and session counters.

## Verify it

```bash
python3 -m py_compile safe_api.py tests/test_safe_api.py
python3 -m unittest discover -s tests -v
```

The tests use a loopback HTTP server and a temporary log directory. No external API or credentials are required. They cover dry-run behavior, scope and duplicate refusals, a real local POST, query encoding, rate and failure breaker trips, incident files, and audit receipts.

## Install

Copy `safe_api.py` into a project, or download the version you reviewed:

```bash
curl -O https://raw.githubusercontent.com/b2bvic/safe-api/main/safe_api.py
```

Requires Python 3.11 or newer. Runtime dependencies are Python standard library only.

## Example

```python
from safe_api import SafeAPIClient

client = SafeAPIClient(
    base_url="https://api.example.com/v1",
    name="contact-sync",
    allowed_endpoints=["/contacts"],
    blocked_methods={"/contacts": ["DELETE"]},
    auth_header="Bearer token-from-your-secret-store",
    max_writes_per_minute=10,
)

# Default: records intent without sending.
preview = client.post(
    "/contacts",
    {"name": "Jane Doe"},
    reason="approved import fixture",
)

# Execute mode must be explicit in code or supplied by --execute.
executing_client = SafeAPIClient(
    base_url="https://api.example.com/v1",
    name="contact-sync",
    allowed_endpoints=["/contacts"],
    execute=True,
)
```

## Duplicate guard

Duplicate identity is domain-specific, so the library does not guess. Supply a callback that returns the existing record when the proposed POST would duplicate it:

```python
def existing_contact(client, endpoint, payload):
    email = payload.get("email")
    if not email:
        return None
    response = client.get("/contacts", {"email": email})
    matches = response.get("contacts", [])
    return matches[0] if matches else None

client = SafeAPIClient(
    base_url="https://api.example.com/v1",
    allowed_endpoints=["/contacts"],
    dedup_checker=existing_contact,
)
```

## Circuit breaker

The client trips when either threshold is reached:

- `max_failures` failed mutation requests in the current process
- `max_writes_per_minute` successful mutation requests in the trailing 60 seconds before another attempt

A trip blocks later mutations with `CircuitBreakerTripped` and writes `incident-{name}-{timestamp}.json`. `reset_breaker()` clears in-memory counters. It does not undo remote writes.

## Audit log

The default path is `~/.cache/safe-api/{name}-writes.jsonl`. Use `log_dir` to place receipts elsewhere and `log_tail()` to read them.

Payloads are logged as provided. Do not put credentials in payloads, and configure a protected log directory when payloads contain personal or confidential data. Authorization headers are not written to the audit entry.

## API

```python
SafeAPIClient(
    base_url: str,
    name: str = "safe-api",
    allowed_endpoints: list[str] | None = None,
    blocked_endpoints: list[str] | None = None,
    blocked_methods: dict[str, list[str]] | None = None,
    auth_header: str | None = None,
    api_key_env: str | None = None,
    max_writes_per_minute: int = 10,
    max_failures: int = 2,
    log_dir: str | None = None,
    execute: bool | None = None,
    dedup_checker: Callable | None = None,
)
```

Mutation methods are `post`, `put`, `patch`, and `delete`. `get` is ungated and intended for lookups. Scope matching uses the first endpoint path segment, such as `/contacts` for `/contacts/123`.

## Non-guarantees

- The wrapper does not infer whether a payload contains one record or a batch.
- It does not diff or verify remote state after a successful response.
- It does not coordinate rate or breaker state across processes.
- It does not make retries idempotent or supply idempotency keys.
- It does not encrypt or redact audit payloads.
- It cannot replace API-side authorization, validation, or transactional controls.

See [design decisions](docs/DECISIONS.md) for the boundary behind each guardrail.

## License

MIT

Built by [Victor Valentine Romo](https://victorvalentineromo.com).
