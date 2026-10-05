# Dry-run REST API write wrapper: safe-api

Safe-api wraps REST API writes with configurable dry-run, scope, and breaker controls for operators who connect hosted-model workflows to APIs.
It helps callers inspect intended writes and retain an agent API audit trail before enabling execution.

[Project page](https://scalewithsearch.com/code/safe-api)

## Install

Use Python 3.11 or newer and Git. The runtime uses only the Python standard library.

```bash
git clone https://github.com/b2bvic/safe-api.git
cd safe-api
```

Import `SafeAPIClient` from `safe_api.py`, or copy the module into your reviewed application.

## Quick start

Run a dry-run example with local logs and no duplicate callback:

```bash
python3 - <<'PYTHON'
import tempfile
from safe_api import SafeAPIClient

with tempfile.TemporaryDirectory() as logs:
    client = SafeAPIClient(
        base_url="https://api.example.com/v1",
        allowed_endpoints=["/contacts"],
        log_dir=logs,
        execute=False,
    )
    print(client.post("/contacts", {"name": "Example"}, reason="synthetic demo"))
    print(client.log_tail())
PYTHON
```

This example records the intended POST without sending an HTTP request.

## How it works

Each write checks API write scope controls, the in-memory API circuit breaker, and an optional duplicate callback before choosing dry-run or execution.
`post`, `put`, `patch`, and `delete` share that write path.
Execution makes one urllib request call per method call. The caller must define record boundaries and validate payloads.
Accepted dry runs, duplicate skips, and successful or failed requests produce JSONL log entries.
The breaker checks configured failure and successful-write rate thresholds before the next write attempt.
A trip writes an incident JSON file. `reset_breaker()` clears that client instance’s breaker state.

These are patterns a team can adopt after it implements human approval and destination verification in its own service.
`execute=False` forces dry-run mode. `execute=True`, or a process `--execute` flag when no override exists, selects execution.
An execution setting does not prove human approval.

| Option | Boundary |
|---|---|
| `allowed_endpoints` | Restrict writes by the first path segment. `[]` denies every write; `None` permits unblocked endpoints. |
| `blocked_endpoints` | Block configured first path segments, including paths with queries. |
| `blocked_methods` | Block configured uppercase methods on those segments. |
| `dedup_checker` | Optional caller-defined check for POST duplicates. |
| `max_failures` | Trip the breaker before a write after the failure threshold. |
| `max_writes_per_minute` | Limit successful writes recorded by this client instance. |
| `auth_header` or `api_key_env` | Supply authentication without putting a real token in shared examples. |
| `log_dir` | Select the local JSONL and incident directory. |

Run the mocked-network regression suite:

```bash
python3 -m unittest discover -s tests -v
```

## Limits

- This wrapper supplies configured controls. Callers must enforce authorization, idempotency, payload validation, and remote outcome verification.
- It does not implement a GET, diff, write, and verify transaction or roll back remote writes.
- `get()` is not scope-gated. A caller-defined duplicate callback can perform reads even during dry runs.
- Write paths reject encoded path segments, traversal, fragments, repeated slashes, backslashes, and control characters.
- Allowed and blocked scopes use the first path segment. Configure the allowlist explicitly.
- Requests use urllib’s redirect behavior. The wrapper does not enforce destination scope after redirects.
- Breaker state is in memory and belongs to one client instance. It does not coordinate processes or survive a restart.
- Logs can contain payloads and server errors. Scope rejections and pre-request exceptions are not all logged.
- There is no log redaction, rotation, locking, or durable approval record. Protect logs in your integration.

## Related repositories

- [agent-oversight](https://github.com/b2bvic/agent-oversight): orchestration cluster and action boundaries.
- [skills](https://github.com/b2bvic/skills): local artifact checks that do not authorize actions.
- [session-ledger](https://github.com/b2bvic/session-ledger): transcript record archive.
- [observer-protocol](https://github.com/b2bvic/observer-protocol): local draft review status.

## License

[MIT](LICENSE).
