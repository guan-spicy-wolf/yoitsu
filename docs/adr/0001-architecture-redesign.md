# ADR-0001: 2026-03-24 Architecture Redesign

- Status: Accepted and implemented
- Date: 2026-03-24
- Supersedes: the earlier ADR set for unified spawn, Yoitsu CLI, Quadlet runtime, Git auth cleanup, and spawn payload normalization

## Context

The previous stack had accumulated five related design decisions across several ADRs, but the code still had structural drift:

- `job` and `task` semantics were mixed together
- `spawn` was fan-out oriented and did not model conditional join jobs cleanly
- Palimpsest and Trenni duplicated event and config contracts
- Trenni still concentrated scheduler, replay, checkpoint, and spawn logic in one supervisor module
- old evo dead code remained in the runtime-facing repo

Keeping those decisions split across multiple documents no longer matched the actual architecture.

## Decision

### 1. Separate Job Result From Task State

- `job.completed` and `job.failed` only describe execution outcome.
- `task.updated` describes logical work state.
- a job may succeed while the task stays `in_progress`.

### 2. Make Conditional Spawn The Only Orchestration Primitive

- the runtime only emits `job.spawn.request`
- Trenni expands it into child jobs plus a join job
- queue admission is controlled by typed condition trees over task state

### 3. Formalize Three Layers

- Scheduler: queueing, condition evaluation, replay, checkpoint
- Isolation backend: env injection and process or container lifecycle
- Runtime: one job pipeline with tools and event emission

### 4. Move Shared Contracts Into `yoitsu-contracts`

The shared repo defines:

- typed event models
- `JobConfig`
- condition serialization
- Pasloe clients
- environment helpers

Palimpsest and Trenni consume these contracts directly instead of maintaining divergent copies.

### 5. Split Trenni Internals

Trenni now has explicit modules for:

- `state`
- `scheduler`
- `spawn_handler`
- `replay`
- `checkpoint`
- `isolation`

`supervisor.py` remains the entry point and control-plane facade.

### 6. Remove Evo Dead Code

The runtime-facing evo repo keeps only the decorator-based context and tool loading model. The obsolete class-based provider files and unused YAML defaults are removed.

## Consequences

### Positive

- the job and task lifecycle is now understandable from events alone
- condition-based join behavior no longer depends on implicit supervisor special cases
- Palimpsest and Trenni share real contracts instead of best-effort dict parsing
- replay and checkpoint behavior have stable state structures to target

### Tradeoffs

- more files and types exist in the scheduler path
- join behavior now depends on `task.updated` being emitted consistently
- the umbrella repo must keep `yoitsu-contracts` in sync with the component repos

## Notes

Some long-range items from older ADRs remain intentionally out of scope for this redesign:

- hard-gate rollback for self-evolution
- soft-gate metric comparisons
- changed-file policy enforcement by the supervisor

Those remain roadmap work, not part of the current implemented baseline.
