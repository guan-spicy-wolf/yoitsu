# ADR-0004: Budget System

- Status: Accepted
- Date: 2026-03-27
- Related: ADR-0002, ADR-0003

## Context

The budget system has evolved incrementally across several earlier decisions
without a unified design. Several gaps remained:

- Budget was a loose collection of independent limits with no explicit model
  of how they relate or which takes precedence.
- `max_iterations` was changed from a hard cut to a penalty threshold, but
  the behavioral contract and the wall-time dimension were not resolved.
- Budget was declared on roles and global config, but the entity that should
  own budget allocation is the task — the same role executing different tasks
  should consume different budgets.
- Provider cost tracking silently failed when pricing was unavailable,
  creating invisible degraded operation.

## Goal

The budget system exists to serve one goal:

> Guide agents to decompose work into bounded, independently verifiable
> chunks rather than attempting to complete arbitrarily large tasks in a
> single job.

Economic pressure (cost accumulation) is the primary mechanism. Hard limits
are system-level backstops that protect against bugs and failures, not tools
for guiding agent behavior.

## Decisions

### 1. Budget Is Task-Bound; Role Provides Constraints Only

Budget allocation follows the Kubernetes requests/limits pattern:

**Role declares constraints** (scheduling hints and floor):

```python
@role(
    min_cost=0.05,          # spawn rejected below this
    recommended_cost=0.60,  # planner's reference for allocation
)
```

**Task receives allocated budget at spawn time** (enforcement bound):

```python
spawn(tasks=[{
    "role": "implementer",
    "goal": "...",
    "budget": 0.80,         # planner decides based on remaining task budget
}])
```

**Root tasks receive allocated budget at trigger time**:

```json
{
  "team": "backend",
  "goal": "Implement feature X",
  "budget": 1.50
}
```

Budget is carried by the task object itself at every level:

- Root task: `TriggerData.budget`
- Child task: `SpawnTaskData.budget`

`recommended_cost` is a reference for the planner when distributing a
parent budget across child tasks. It is not an enforcement value. The same
role executing a trivial fix and a complex refactor should receive different
budgets — only the plan has the context to make that decision.

`min_cost` is enforced at spawn time: if the allocated budget is below
`min_cost`, the spawn is rejected with an explicit error. This prevents the
planner from allocating an amount too small for the role to operate
meaningfully.

### 2. Cost Is the Primary Budget Dimension

Cost (USD) is the unified accumulator. All other dimensions either
contribute to it or act as independent backstops.

**Cost tracking states:**

- `active`: provider pricing is known; cost accumulates per token consumed.
- `degraded`: pricing unavailable for the configured model; token-cost
  accumulation is disabled, but iteration-penalty accumulation remains
  active if configured. The operator is warned at job start and the state
  is recorded in job metadata/events (`JobStartedData` and
  `JobCompletedData`).

Degraded mode is not silent. If `max_total_cost > 0` is configured but
provider pricing is unavailable, the system logs a warning and continues
in degraded mode. In degraded mode:

- Provider token pricing contributes `0` to cost.
- Iteration penalty still contributes to effective cost if configured.
- Hard backstops (`max_iterations_hard`, timeout) remain active.

The operator knows they are not getting full provider-aware cost tracking,
but the system does not silently lose all soft-pressure behavior.

### 3. Iterations Use a Penalty Model, Not a Hard Cut

`max_iterations` is the **penalty threshold**, not a hard ceiling. Each
iteration beyond the threshold adds a configurable penalty to the
accumulated cost:

```
effective_cost = token_cost + max(0, n − max_iterations) × iteration_penalty_cost
```

When `effective_cost` exceeds the allocated budget, `budget_exhausted()`
returns `"cost"` and the interaction loop exits. The agent is never
forcibly interrupted mid-iteration — it reaches a natural decision point
between LLM calls.

`iteration_penalty_cost` defaults to 0. When 0, iterations have no economic
effect and `max_iterations` has no effect on cost accumulation. Both fields
must be configured for the penalty model to be active.

The rationale: a well-decomposed task completes well within the threshold.
An agent running over the threshold is paying an increasing premium to
continue — economic pressure toward concluding or declaring partial work,
not an abrupt cut.

### 4. Hard Iteration Ceiling as System Backstop

A separate field `max_iterations_hard` provides an absolute ceiling that the
runtime enforces regardless of cost state. It exists to protect against
infinite loops, broken tool calls that always succeed, and configurations
where cost tracking is unavailable and `max_iterations` has no effect.

```
max_iterations_hard >> max_iterations  (typically 3–5x)
```

The hard ceiling is a system-level guarantee. It is not meant to trigger
during normal operation. If it triggers, it indicates either a bug in the
agent, a misconfigured budget, or degraded cost tracking that should have
been noticed earlier.

### 5. Job Timeout as Wide System Backstop

Job timeout remains in the runtime as a wall-clock backstop. It is not part
of the planning budget model and should be configured far above normal job
durations.

Its purpose is operational safety:

- Kill pathological jobs that stop making progress but also fail to hit
  other ceilings.
- Protect the runtime from unexpected deadlocks or provider hangs.
- Provide an operator-controlled final stop even when cost/backstop logic
  is misconfigured.

Like `max_iterations_hard`, this timeout is not meant to trigger during
normal operation. It is a coarse safety guarantee, not a decomposition
guidance mechanism.

### 6. Wall Time Policy Applies Per Tool Call, Not Per Job

Job-level wall time is the sum of all tool call durations plus LLM
round-trip times. The risk is not a job running "too long" in aggregate —
it is a single tool call hanging indefinitely (network timeout, subprocess
block, filesystem deadlock).

Each tool call is subject to a configurable `tool_timeout_seconds`. If a
tool call exceeds this limit, the runtime raises a `ToolTimeoutError`,
which surfaces to the agent as a failed tool call. The agent can decide
whether to retry, abandon, or declare partial work.

Enforcement depends on the tool execution path:

- Subprocess/callout tools can be hard-timed out directly.
- In-process Python evo tools require a stronger isolation boundary or
  cooperative timeout mechanism to guarantee interruption.

Until evo tool isolation is strengthened, `tool_timeout_seconds` is only a
hard guarantee for timeout-capable tool paths.

### 7. Budget Exhaustion Terminal Path

The interaction loop checks `budget_exhausted()` before each LLM call. When
exhausted:

```
budget_exhausted() → "cost" | "max_iterations_hard" | "input_tokens" | "output_tokens"
    ↓
job exits cleanly, publication attempted
    ↓
publication succeeded → agent.job.completed(code="budget_exhausted") → task.partial
publication failed   → agent.job.failed
```

The budget dimension that triggered exhaustion is recorded in
`JobCompletedData.budget_dim` for observability.

The `task.partial` state and routing are described in ADR-0002. The
publication guarantee is described in ADR-0003.

### 8. Deferred: fn-ization and Agent-Initiated Suspension

Two mechanisms were considered for handling long-running operations:

**fn-ization** (non-agent code jobs): would introduce executor-type jobs
that run code without an LLM. Deferred because spawn is currently the
exclusive right of agents — allowing code jobs to spawn would introduce a
path to pre-defined orchestration graphs, eroding the system's autonomous
character. The existing spawn mechanism already handles task decomposition.

**Agent-initiated suspension**: agents declare long-running operations in
advance and request job suspension. Deferred pending a clear design for the
resume mechanism and context preservation across suspension boundaries.

Neither mechanism is required to make the budget system correct. Both
remain open for future ADRs.

### 9. Deferred: Barrier Function

A non-linear penalty that approaches infinity near the budget limit was
considered. This would create stronger convergence pressure near exhaustion
without a hard cut. Deferred because it requires the agent to have
continuous cost visibility in its context (not just a near-exhaustion
warning), and because the linear penalty model should be evaluated in
practice first. The existing `LoopWarning` mechanism provides a
point-in-time signal that can be tuned independently.

## Consequences

### Positive

- Budget allocation is owned by the entity with the most context (the plan),
  not by the role definition.
- Cost tracking degradation is visible, not silent.
- Iterations have a coherent role: soft pressure mechanism and backstop, not
  both at once.
- Tool timeout is the right granularity for operational hangs, while job
  timeout remains a wide safety backstop.
- The system goal (decompose into verifiable chunks) is explicit, making
  future budget design decisions easier to evaluate.

### Tradeoffs

- `max_iterations_hard` is a new field that operators must be aware of; the
  two-field iteration model (`max_iterations` as threshold,
  `max_iterations_hard` as ceiling) requires documentation.
- Degraded mode warning at job start adds noise when pricing tables are
  incomplete; pricing tables must be maintained.
- Tool timeout enforcement is asymmetric until evo tool isolation improves.

### Non-Goals

- Dynamic budget reallocation mid-job.
- Per-tool-call cost attribution.
- Cross-job budget pooling at the task level.
- Per-budget-dimension distinction in the partial terminal signal (all
  budget types collapse to `code="budget_exhausted"`; the triggering
  dimension is in `budget_dim`).
