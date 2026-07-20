# Design decisions

## Dry run is the default

The common failure is unintended execution, so mutation methods preview unless execute mode is explicit. This is a client-side control, not an authorization boundary. Production APIs still need their own permissions.

## Every mutation uses one central path

`post`, `put`, `patch`, and `delete` all call `_write`. Scope checks, breaker checks, duplicate handling, receipts, and transport behavior therefore share one implementation.

The library sends one HTTP mutation request per method call. It cannot infer whether a caller placed one record or 10,000 records inside the payload.

## Duplicate identity is supplied by the caller

An email address, external ID, compound business key, and idempotency key have different semantics. A configurable callback makes the decision visible instead of guessing inside a generic HTTP wrapper.

## Breaker state is process-local

The wrapper is intended for bounded scripts, so counters stay in memory and incident evidence goes to disk. Coordinated workers need a shared rate limiter and breaker store.

## Scope is checked by base endpoint

`/contacts/123` maps to `/contacts`. This keeps configuration compact but cannot express every API's nested-resource policy. Use API-side scopes and a narrower client when path semantics are more complex.

## Receipts favor inspectability

JSONL is append-friendly and easy to inspect with standard tools. Payload logging can expose sensitive data, so callers must protect the directory and avoid secrets in payloads. This version does not redact fields or encrypt logs.
