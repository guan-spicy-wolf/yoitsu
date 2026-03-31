# ADR-0010: Self-Optimization Governance

- Status: Accepted
- Date: 2026-03-31
- Related: ADR-0002, ADR-0008

## Context

Palimpsest's long-horizon goal is self-improvement: the system should identify inefficiencies in its own operation and address them over time. The question is how to structure this without building a separate optimization subsystem with special privileges or code paths.

A prior attempt (palimpsest-v1) relied on single-prompt self-reflection — the agent reviewed its own event history and wrote its own memory. This proved insufficient: a single prompt cannot genuinely evaluate its own behavior, and self-authored memory has limited reliability.

The yoitsu architecture already separates observer (Trenni) from executor (Palimpsest), providing the structural prerequisite for external evaluation. The remaining design question is how optimization signals flow from observation to action.

## Decisions

### 1. Structured observation signals, not AI-generated summaries

Optimization begins with data. The system collects structured observation events mechanically — no LLM involved in signal generation.

Observation events use the `observation.*` type namespace and are emitted by Trenni and the tool gateway based on deterministic criteria:

- `observation.budget_usage` — job spent >N% of budget, with breakdown (prompt vs completion, retry overhead)
- `observation.tool_retry` — tool call failed and was retried, with failure count and pattern
- `observation.context_overflow` — job queried Pasloe for additional context beyond what preparation provided
- `observation.round_efficiency` — ratio of LLM rounds to concrete outputs (tool calls, commits, spawns)
- `observation.spawn_depth` — task recursion depth exceeded threshold

These are append-only events written to Pasloe through the normal event pipeline. They carry structured data, not natural language assessments. The set of observation types is expected to grow as the system matures.

### 2. Optimization discovery is a normal task

Periodically (via Trenni trigger rules, per ADR-0008), the system creates a review task:

```yaml
trigger:
  match:
    type: "observation.*"
    accumulate: 20
  spawn:
    goal: "review recent observation signals and propose improvements"
```

This review task is a normal task. It goes through the normal lifecycle — Trenni schedules it, a planner or reviewer role executes it, results are evaluated. The review job queries Pasloe for recent observation events, identifies recurring patterns, and produces concrete improvement proposals.

There is no special "optimization mode", no privileged access, no separate scheduler. The review task competes for resources like any other task.

### 3. Optimization execution is a normal task

Improvement proposals produced by review tasks become new tasks through normal spawn. Each proposal is a task with a goal like "reduce retry overhead in API tool" or "add caching to PR diff fetching in reviewer preparation".

These tasks are indistinguishable from externally submitted work. They go through planner (if role is unspecified, per ADR-0008), get scheduled, executed, and evaluated through the standard pipeline.

This means the system's self-improvement uses exactly the same mechanisms as its regular work. No special code paths, no optimization-specific roles (though a role may be particularly suited to certain optimization work), no privileged event types.

### 4. Signal collection is incremental; optimization is deferred

Observation event types should be defined in contracts early (Phase 1-2 of the roadmap) and emitted as the relevant code paths are built. However, optimization tasks should not be triggered until there is sufficient signal volume — the accumulation threshold in trigger rules serves as the gate.

The rationale: optimization with sparse signals produces false patterns and premature changes. The system needs months of real task execution data before self-optimization becomes valuable. Collecting signals early and acting on them late is the correct sequencing.

Phase mapping:
- **Phase 1-2**: Define `observation.*` schemas in contracts. Emit signals from tool gateway and Trenni as relevant code is written.
- **Phase 3**: Reviewer role can read observation events as additional context.
- **Phase 4**: Pasloe query capability enables aggregation over time windows.
- **Phase 5**: Trigger rules activate review tasks. The optimization loop closes.

Each phase adds a small increment. No phase requires building optimization-specific infrastructure.
