# ADR-0005: 2026-03-25 Supervisor Intake/Execution Phase Split And Cursor Semantics

- Status: Accepted, implementation pending
- Date: 2026-03-25
- Related: ADR-0002, ADR-0004

## Context

Trenni supervisor currently polls events, advances cursor, and then processes
each event. Even after fixing mark-before-process dedupe, cursor advancement is
still ahead of actual handling work in the poll path.

Failure mode:

- poll returns events and next cursor
- supervisor advances cursor immediately
- handling of an event fails before enqueue/side effects complete
- process restarts from advanced cursor and can skip unhandled events

This is a boundary-definition bug. Cursor progression should represent intake
progress (accepted by scheduler), not downstream execution completion.

We also need a clean separation between:

- intake: transforming committed events into scheduler state transitions
- execution: launching/monitoring runtime jobs

## Decision

Supervisor architecture is split into two phases:

1. Intake phase (deterministic control plane)
   - consume committed Pasloe events
   - validate, dedupe, and apply scheduler mutations
   - persist intake-safe progress marker
2. Execution phase (runtime side effects)
   - drain ready queue
   - launch and monitor containers
   - emit runtime lifecycle events

Cursor semantics are redefined:

- cursor advances only after intake phase succeeds for an event batch
- execution failures do not roll back intake cursor
- replay reconstructs pending/ready/running using intake-derived state and
  launch/terminal events

Operationally, this implies explicit middle lifecycle signals between trigger
and execution (for example queue admission), so replay and observability can
distinguish:

- received
- enqueued
- launched
- terminal

## Consequences

### Positive

- removes crash window where advanced cursor can hide unprocessed work
- makes replay boundaries explicit and auditable
- decouples scheduler correctness from runtime jitter

### Tradeoffs

- requires supervisor refactor around intake commit boundaries
- adds intermediate lifecycle event volume
- needs extra tests for crash/restart and duplicate delivery paths

### Non-Goals

- introducing global backpressure in this phase
- changing Task semantic quality gates (Dual Gate remains separate work)

## Implementation Notes

Planned implementation scope:

1. move cursor advancement from pre-handle poll path to post-intake commit point
2. introduce explicit enqueue lifecycle event(s) for replay-safe boundaries
3. refactor supervisor loop so intake and execution have separate failure domains
4. add restart regression tests proving no event loss across cursor persistence
