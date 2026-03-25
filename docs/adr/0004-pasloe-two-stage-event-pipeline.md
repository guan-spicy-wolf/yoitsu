# ADR-0004: 2026-03-25 Pasloe Two-Stage Event Pipeline And PostgreSQL Default

- Status: Accepted and implemented
- Date: 2026-03-25
- Related: ADR-0001, ADR-0002

## Context

Pasloe previously handled ingest, visibility, projection, and webhook delivery in
the same write path. Under concurrent multi-source delivery, the old SQLite-first
path showed lock contention (`database is locked`) and made delivery reliability
depend on synchronous side effects.

This caused two problems:

- producer success and downstream side-effect success were coupled
- transient DB or webhook pressure could delay or lose operationally critical
  event visibility

Yoitsu needs a clear event visibility contract:

- producers need a fast, durable `accepted` acknowledgement
- consumers and business logic should only read `committed` events
- background fan-out must be crash-recoverable and retryable

## Decision

Pasloe is now a two-stage architecture:

1. `ingest log` is the durability boundary.
   - `POST /events` persists ingress rows first and returns `accepted`.
   - optional `idempotency_key` is enforced per source for safe producer retries.
2. `read models` are driven asynchronously from committed events.
   - a `committer` pipeline moves ingress rows into committed `events`.
   - projection and webhook work is represented in `outbox_events`.
   - `projector` and `webhook` workers consume outbox via lease + retry.
3. Event visibility semantics are fixed:
   - producers only depend on `accepted`
   - business consumers only read `committed`
4. Deployment default is PostgreSQL.
   - Pasloe runtime config and local Quadlet deployment now default to Postgres.

## Consequences

### Positive

- removes synchronous coupling between producer acknowledgement and side effects
- supports concurrent multi-source ingest with stronger write concurrency
- enables crash recovery through lease expiration and retry scheduling
- creates explicit operational signals (`ingress_pending`, `outbox_pending`,
  oldest uncommitted age)

### Tradeoffs

- introduces worker complexity (committer/projector/webhook pipelines)
- requires queue health monitoring rather than only API health
- increases schema and migration surface

### Non-Goals

- global backpressure and rate shaping in this phase
- exactly-once webhook semantics across external systems
- schema-aware event validation inside Pasloe

## Implementation Notes

Implemented in Pasloe and integrated in Yoitsu local deployment:

- new ingest/outbox tables with lease/retry fields
- worker runtime for committer/projector/webhook
- committed-only query surface for `/events`
- Quadlet Postgres service and Pasloe dependency wiring
