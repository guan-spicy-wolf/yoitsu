# ADR 0002: Task Orchestration Decoupling from Job Infrastructure

## Status
Accepted

## Context
In the previous architecture, the Yoitsu system conflated the lifecycle of a `Job` (the runtime execution unit) with a `Task` (the logical/business objective). `Palimpsest`, acting as the executing agent, was responsible for evaluating and declaring both Job completion and semantic Task status (e.g. `success`, `in_progress`). This design created several structural issues:
1. **Inversion of Authority**: The runner container had the power to dictate the architectural flow (Task termination) rather than just executing work.
2. **Event Ambiguity**: A single `TaskUpdatedData` event was overloaded to represent progression, spawn intents, wait semantics, user interventions, and completion states. This made replay state-building unreliable.
3. **Observability Gaps**: We had no explicit `task.created`, `task.completed`, or `task.failed` events to track the system's operational hierarchy objectively.
4. **Poor State Reconstruction**: Restoring the `Supervisor` state after bounds required inferring complex business rules out of low-level LLM interactions.

## Decision
We decided to completely sever the connection between the execution environment (Palimpsest) and the task tracking system (Trenni). Trenni is now the sole authority for evaluating Task conditions structurally.

1. **Contracts and Events redesign**: 
   - Deprecated `TaskSubmitData` and `TaskUpdatedData`.
   - Introduced `TriggerData` (`trigger.*`) reflecting external user actions or scheduled automation intents. 
   - Introduced Task Lifecycle events: `task.created`, `task.completed`, `task.failed`, `task.cancelled`.
2. **Structural Orchestration in Trenni**:
   - Re-defined a `TaskRecord` as a simple intent holding a `goal` and state transitions. No metadata about LLM contexts or Docker repositories is embedded.
   - Evaluates a Task's status through **Structural Termination**: If a Task has no active Jobs, and no pending jobs are associated with it, Trenni evaluates it as complete/failed based on the final results of its child jobs.
   - Evaluates cascade cancellations: Failing a core task cancels pending related jobs in the supervisor queue.
3. **Palimpsest Stripping**:
   - Removed all `task_status` awareness from `palimpsest`. The `task_complete` tool only dictates *end of current interaction loop* to the execution core. Any reporting/summary serves to inform Trenni what the Job accomplished, not what the business outcome of the arbitrary Task is.

## Consequences

### Positive
- **Determinism**: The state of Yoitsu tasks can be linearly and deterministically replayed through an explicit ledger of `task.created/completed`.
- **Modularity**: We can swap out `Palimpsest` for any other executor. Executors no longer possess the burden of resolving complex workflow topologies. 
- **Simpler Tools**: The LLM interaction loop focuses purely on task-specific problem-solving. It just exits when it believes it has resolved its objective.

### Negative
- We have temporarily removed the capacity for Jobs to spontaneously "Fork" a new sub-goal without it being mapped to a strict structural dependency layout in the supervisor. To remedy this, a `Spawn` primitive remains to allow an LLM to request new sibling tools, but this requires further enhancements.
- Determining exactly *why* a Task failed logically if its component Jobs succeeded but delivered incomplete results relies purely on external validation now.
