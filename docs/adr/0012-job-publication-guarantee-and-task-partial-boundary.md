# ADR-0012: 2026-03-26 Job Publication Guarantee And Task Partial Boundary

- Status: Superseded by ADR-0013
- Date: 2026-03-26
- Related: ADR-0007, ADR-0009

## Context

Yoitsu must keep `job` and `task` semantics strictly separated:

- `job` is the runtime execution unit
- `task` is the logical work unit

A boundary problem showed up in smoke testing:

- some runs reached budget exhaustion and were treated as "partial work"
- but if the resulting artifact was not successfully published, nothing
  durable or retrievable actually existed

This mixes two different questions:

- did the runtime complete its own execution/publication responsibility?
- did the logical task finish only part of its goal?

If publication fails, the runtime guarantee was not met. That is a job-level
failure, not a task-level partial result.

## Motivation

This ADR identified that ADR-0007's budget exhaustion path implicitly assumed
publication always succeeds. When publication fails, the partial result
disappears with no observable signal, which violates the job/task boundary
established in ADR-0002.

The decisions and the full state matrix are captured in ADR-0013 §7.
