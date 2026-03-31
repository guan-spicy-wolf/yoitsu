# ADR-0008: Task Creation and Ingestion

- Status: Accepted
- Date: 2026-03-31
- Related: ADR-0002, ADR-0007

## Context

Tasks currently enter the system through two paths: external trigger events and agent-initiated spawn requests. Both paths require the caller to supply enough information to launch a job directly — including a specific role. This creates two problems:

1. **Spawn burden on agents**: An agent executing a job must know which roles exist and what parameters each role requires in order to spawn sub-tasks. This leaks orchestration concerns into the runtime.

2. **External event ingestion**: Phase 2 of the roadmap introduces external triggers (CI failures, GitHub issues). These need a mechanism to become tasks without a dedicated adapter per event type. The question is where this translation logic lives — Pasloe or Trenni.

## Decisions

### 1. Spawn requests may omit role; Trenni defaults to planner

A spawn request is no longer required to carry a fully specified role. If `role` is absent, Trenni assigns `planner` as the first job's role.

The planner job receives only the goal (and any other task-level fields like budget), reads whatever context it needs, then spawns concrete sub-tasks with explicit roles.

This means:

- Agents can spawn sub-tasks by stating **what** needs to be done, without specifying **how**
- Planner becomes the universal entry point for underspecified work
- Fully specified spawn requests (with role) continue to work as before — no breaking change
- Planner jobs should have a small, fixed budget defined in the role itself, since they only plan and spawn

### 2. External event → task translation lives in Trenni, not Pasloe

Pasloe remains a domain-agnostic event store. It does not interpret event semantics or generate spawn events.

Trenni gains a **trigger evaluator** module that processes new events from its existing Pasloe poll loop. Triggers are declarative rules in Trenni's configuration:

```yaml
triggers:
  - name: "ci_failure"
    match:
      type: "github.ci.completed"
      data.conclusion: "failure"
    spawn:
      goal: "investigate and fix CI failure: {{data.summary}}"

  - name: "optimization_review"
    match:
      type: "observation.*"
      accumulate: 20
    spawn:
      goal: "review recent observation signals and propose improvements"
```

When a trigger matches, Trenni creates a normal task — identical to a manually submitted one. No special code path.

Rationale for rejecting the Pasloe alternative: if Pasloe wraps non-spawn events into spawn events, it needs to understand task semantics (goal construction, deduplication, spawn schema). This makes Pasloe a second orchestrator, duplicating concerns that belong in Trenni. Keeping Pasloe dumb preserves a clean failure domain boundary — Pasloe failures affect durability, Trenni failures affect scheduling, and they never entangle.

### 3. Trigger rules are evaluated against the existing poll cursor

No new communication channel is needed. Trenni already polls Pasloe for events via cursor-based pagination. The trigger evaluator runs as an additional step in this loop:

1. Poll new events from Pasloe (existing behavior)
2. Route task/job events to supervisor state machine (existing behavior)
3. Evaluate remaining events against trigger rules (new behavior)
4. Matched triggers create tasks through the normal task creation path

This keeps the architecture change minimal — one new module in Trenni, no changes to Pasloe, no new APIs.
