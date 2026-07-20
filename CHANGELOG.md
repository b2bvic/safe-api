# Changelog

## 1.0.0 - 2026-07-20

- Add deterministic contract tests backed by a loopback HTTP server.
- Add read-only GitHub Actions CI across Python 3.11, 3.12, and 3.13.
- Encode GET query parameters with `urllib.parse.urlencode`.
- Write the incident artifact as soon as the configured failure threshold is reached.
- Document the exact guardrail boundary and non-guarantees.
