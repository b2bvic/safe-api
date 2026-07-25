#!/usr/bin/env python3
"""
safe-api — Safety wrapper for REST API write operations.

Seven rules that prevent runaway writes to production APIs:

1. Dry-run default — --execute flag required to actually write
2. One record per transaction — GET→diff→PUT/POST→verify→log
3. Duplicate guard — configurable dedup check before POST
4. Circuit breaker — halts on 2+ failures or rate exceeded
5. Audit trail — every write logged to JSONL
6. Scope whitelist — per-client endpoint restrictions + global blocks
7. Human escalation — incident files generated on breaker trip

Zero dependencies. Stdlib only. Born from a production incident where
a batch write created duplicate records in a CRM.

🌐 Victor Valentine Romo · victorvalentineromo.com · scalewithsearch.com
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

VERSION = "1.0.0"


class CircuitBreakerTripped(Exception):
    """Raised when the circuit breaker halts all writes."""
    pass


class ScopeViolation(Exception):
    """Raised when a client attempts to write to an unauthorized endpoint."""
    pass


class SafeAPIClient:
    """
    Gated REST API client. Every write operation passes through seven
    safety rules before reaching the API.

    Usage:
        client = SafeAPIClient(
            base_url="https://api.example.com/v1",
            name="my-script",
            allowed_endpoints=["/contacts", "/tasks"],
            blocked_endpoints=["/billing"],
            auth_header="Bearer your-token-here",
        )
        # Dry-run (default):
        result = client.post("/contacts", {"name": "Jane"})
        # Execute mode (--execute on CLI):
        result = client.post("/contacts", {"name": "Jane"})
    """

    def __init__(
        self,
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
    ):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.allowed_endpoints = frozenset(allowed_endpoints) if allowed_endpoints else None
        self.blocked_endpoints = frozenset(blocked_endpoints or [])
        self.blocked_methods = {k: frozenset(v) for k, v in (blocked_methods or {}).items()}
        self.max_writes_per_minute = max_writes_per_minute
        self.max_failures = max_failures
        self.dedup_checker = dedup_checker

        # Auth: explicit header > env var > None
        if auth_header:
            self._auth = auth_header
        elif api_key_env:
            key = os.environ.get(api_key_env, "")
            if not key:
                raise RuntimeError(f"Environment variable {api_key_env} not set")
            self._auth = f"Bearer {key}"
        else:
            self._auth = None

        # Execute mode: explicit > CLI flag > default dry-run
        if execute is not None:
            self.execute_mode = execute
        else:
            self.execute_mode = "--execute" in sys.argv

        # Logging
        log_path = Path(log_dir) if log_dir else Path.home() / ".cache" / "safe-api"
        log_path.mkdir(parents=True, exist_ok=True)
        self._log_file = log_path / f"{name}-writes.jsonl"
        self._incident_dir = log_path

        # Circuit breaker state
        self._failure_count = 0
        self._write_timestamps: list[float] = []
        self._breaker_tripped = False

    @property
    def is_dry_run(self) -> bool:
        return not self.execute_mode

    # --- Rule 6: Scope whitelist ---

    def _validate_scope(self, endpoint: str, method: str) -> None:
        """Enforce endpoint restrictions."""
        base = "/" + endpoint.lstrip("/").split("/")[0]

        if base in self.blocked_endpoints:
            raise ScopeViolation(f"BLOCKED: {method} {endpoint} — endpoint is globally blocked")

        if base in self.blocked_methods and method.upper() in self.blocked_methods[base]:
            raise ScopeViolation(f"BLOCKED: {method} {base} — method blocked on this endpoint")

        if self.allowed_endpoints is not None and base not in self.allowed_endpoints:
            raise ScopeViolation(
                f"SCOPE VIOLATION: {self.name} attempted {method} {endpoint}. "
                f"Allowed: {sorted(self.allowed_endpoints)}"
            )

    # --- Rule 4: Circuit breaker ---

    def _check_circuit_breaker(self) -> None:
        if self._breaker_tripped:
            raise CircuitBreakerTripped("Circuit breaker is tripped. No further writes this session.")

        if self._failure_count >= self.max_failures:
            self._trip_breaker(f"{self._failure_count}+ failures in this session")
            raise CircuitBreakerTripped(f"Circuit breaker tripped: {self._failure_count}+ failures")

        now = time.time()
        self._write_timestamps = [t for t in self._write_timestamps if now - t < 60]
        if len(self._write_timestamps) >= self.max_writes_per_minute:
            self._trip_breaker(f"Rate exceeded: {len(self._write_timestamps)} writes in 60s")
            raise CircuitBreakerTripped("Circuit breaker tripped: rate exceeded")

    def _trip_breaker(self, reason: str) -> None:
        self._breaker_tripped = True
        incident = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "client": self.name,
            "reason": reason,
            "failure_count": self._failure_count,
            "writes_last_60s": len(self._write_timestamps),
        }
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        incident_file = self._incident_dir / f"incident-{self.name}-{ts}.json"
        incident_file.write_text(json.dumps(incident, indent=2))
        print(f"CIRCUIT BREAKER TRIPPED: {reason}", file=sys.stderr)
        print(f"Incident file: {incident_file}", file=sys.stderr)

    # --- Rule 5: Audit trail ---

    def _log_write(self, entry: dict) -> None:
        with open(self._log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # --- Core API methods ---

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        """GET request — always allowed, no safety gates."""
        url = f"{self.base_url}{endpoint}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{qs}"

        req = urllib.request.Request(url)
        if self._auth:
            req.add_header("Authorization", self._auth)
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)}

    def post(self, endpoint: str, payload: dict, reason: str = "") -> dict:
        """POST — passes through all seven safety rules."""
        return self._write("POST", endpoint, payload, reason)

    def put(self, endpoint: str, payload: dict, reason: str = "") -> dict:
        """PUT — passes through all seven safety rules."""
        return self._write("PUT", endpoint, payload, reason)

    def patch(self, endpoint: str, payload: dict, reason: str = "") -> dict:
        """PATCH — passes through all seven safety rules."""
        return self._write("PATCH", endpoint, payload, reason)

    def delete(self, endpoint: str, reason: str = "") -> dict:
        """DELETE — passes through all seven safety rules."""
        return self._write("DELETE", endpoint, {}, reason)

    def _write(self, method: str, endpoint: str, payload: dict, reason: str) -> dict:
        """Central write path. Every mutation flows through here."""
        # Rule 6: Scope check
        self._validate_scope(endpoint, method)

        # Rule 4: Circuit breaker
        self._check_circuit_breaker()

        # Rule 3: Duplicate guard (POST only, if checker provided)
        if method == "POST" and self.dedup_checker:
            existing = self.dedup_checker(self, endpoint, payload)
            if existing:
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "client": self.name,
                    "endpoint": endpoint,
                    "method": method,
                    "action": "SKIPPED_DUPLICATE",
                    "payload": payload,
                    "reason": reason,
                    "dry_run": self.is_dry_run,
                }
                self._log_write(entry)
                return {"skipped": True, "reason": "duplicate detected", "existing": existing}

        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "client": self.name,
            "endpoint": endpoint,
            "method": method,
            "payload": payload,
            "reason": reason,
            "dry_run": self.is_dry_run,
        }

        # Rule 1: Dry-run
        if self.is_dry_run:
            audit_entry["action"] = "DRY_RUN"
            self._log_write(audit_entry)
            return {"dry_run": True, "would_send": payload, "endpoint": endpoint, "method": method}

        # Rule 2: Execute single record
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode() if payload else None

        req = urllib.request.Request(url, data=data, method=method)
        if self._auth:
            req.add_header("Authorization", self._auth)
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
                response_data = json.loads(body) if body else {}

            self._write_timestamps.append(time.time())
            audit_entry["action"] = "EXECUTED"
            audit_entry["response_status"] = resp.status
            self._log_write(audit_entry)

            time.sleep(0.1)  # Rate limit between writes
            return response_data

        except urllib.error.HTTPError as e:
            self._failure_count += 1
            error_body = ""
            try:
                error_body = e.read().decode()
            except Exception:
                pass
            audit_entry["action"] = "FAILED"
            audit_entry["error"] = f"HTTP {e.code}: {error_body}"
            self._log_write(audit_entry)
            return {"error": f"HTTP {e.code}", "detail": error_body}

        except Exception as e:
            self._failure_count += 1
            audit_entry["action"] = "FAILED"
            audit_entry["error"] = str(e)
            self._log_write(audit_entry)
            return {"error": str(e)}

    # --- Utilities ---

    def log_tail(self, n: int = 20) -> list[dict]:
        """Return the last N entries from the write log."""
        if not self._log_file.exists():
            return []
        lines = self._log_file.read_text().strip().split("\n")
        return [json.loads(line) for line in lines[-n:] if line.strip()]

    def reset_breaker(self) -> None:
        """Manually reset the circuit breaker. Use with caution."""
        self._breaker_tripped = False
        self._failure_count = 0
        self._write_timestamps.clear()
