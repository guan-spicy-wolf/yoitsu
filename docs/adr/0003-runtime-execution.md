# ADR-0003: Runtime Execution Architecture

- Status: Accepted
- Date: 2026-03-27
- Related: ADR-0001, ADR-0002, ADR-0004

## Context

The runtime execution model must support:

- Code-change jobs that clone a git repository, perform work, and publish
  via commit and push.
- Operational and observability jobs (monitoring, reporting, diagnostics)
  that need no source repository at all.
- A self-evolving system where the logic governing job execution can itself
  be modified by agents.

Palimpsest is the job executor. It receives a spawn payload, resolves the
role function from the `evo/` directory, and runs the job pipeline. The
`evo/` directory is versioned — spawn payloads reference a specific git sha
so that job behavior is reproducible at any point in time.

## Decisions

### 1. Workspace Is Execution Substrate, Not a Pipeline Stage

Workspace setup is not a transformation stage alongside context and
interaction. It is the execution substrate:

- Established at job start.
- Persists for the entire job duration.
- Shared by all stages.

The correct model:

```
job manifest (workspace type, tools, budget, provider)
        ↓ configures
context_fn → interaction loop → publication_fn
```

Workspace type determines what tools are available to the agent. This
resolution happens once at job start, not inside any stage.

### 2. Four Evolvable Functions

Every job executes through four functions, all defined in `evo/` and
therefore independently evolvable:

| Function          | Returns            | Role |
|-------------------|--------------------|------|
| `workspace_fn`    | — (side effect)    | Establishes the execution environment |
| `context_fn`      | `AgentContext`     | Builds agent prompt and context |
| `publication_fn`  | `git_ref \| None`  | Publishes the job result and verifies retrievability |
| `role_fn`         | `JobSpec`          | Composes the above into a complete job definition |

`workspace_fn` configures the execution substrate. `publication_fn`
performs publication after interaction and either returns a retrievable
`git_ref` or `None` when the role intentionally skips publication.

**Unified failure signaling via exceptions.** All four functions signal
failure by raising an exception. Palimpsest has one failure handler:

```
any function raises  →  agent.job.failed
```

No function returns a sentinel value for failure. Palimpsest does not need
per-function error logic.

### 3. Role Is a First-Class Runtime Citizen

A role is a function in `evo/` that returns a fully-resolved `JobSpec`. It
is not a named configuration entity that the runtime interprets — it is the
composition point that assembles workspace, context, tools, publication, and
budget into a coherent agent definition for a specific task type.

```python
# evo/roles/git_work.py
def git_work_role(repo, branch, goal, budget) -> JobSpec:
    return JobSpec(
        workspace_fn   = git_workspace(repo, branch),
        context_fn     = coder_context(goal),
        publication_fn = git_publication(),
        tools          = git_tools() | shell_tools(),
        provider       = default_code_provider(),
        budget         = budget,
    )
```

Prompt and persona are internalized into `context_fn`. The role function is
the only component that knows which context strategy, workspace type, tool
set, and publication strategy belong together for this class of task.

Role functions are the unit of system evolution.

### 4. Role Metadata and Team Composition via `@role` Decorator

Role functions carry metadata via decorator:

```python
@role(
    name="implementer",
    description="Writes code to implement a specific task",
    teams=["backend"],
    role_type="worker",          # worker | planner | evaluator
    min_cost=0.10,
    recommended_cost=0.80,
    min_capability="reasoning_medium",
)
def implementer_role(repo, branch, goal, budget) -> JobSpec:
    ...
```

Teams are derived automatically from the union of roles that declare the
same team name. No separate `TeamDefinition` files are required. A role may
belong to multiple teams.

**Metadata fields:**

- `name`: unique role identifier within a team.
- `description`: one-line capability summary exposed to the planner.
- `teams`: list of team names this role belongs to.
- `role_type`: `worker`, `planner`, or `evaluator`.
- `min_cost`: spawn is rejected if allocated budget is below this value.
- `recommended_cost`: reference for the planner when distributing a parent
  budget across child tasks. Not an enforcement value.
- `min_capability`: capability tier required from the provider (e.g.
  `"reasoning_medium"`). The runtime maps this to available providers.

**Validation rules** (enforced at evo load time; failure prevents startup):

- Each team must have exactly one `role_type="planner"`.
- Each team must have at most one `role_type="evaluator"`; if absent the
  system default evaluator is used.
- Each team must have at least one `role_type="worker"`.
- Role names must be unique within a team.

### 5. Spawn Payload vs. Runtime Execution

**Spawn payload** (declaration, stored in Pasloe event):

```json
{
  "role":   "git_work_role",
  "params": { "repo": "...", "branch": "...", "goal": "...", "budget": 0.80 },
  "sha":    "abc123"
}
```

Compact and serializable. The `sha` anchors the role function to a specific
version of evo, making job behavior reproducible and evolution auditable.

**JobSpec** (resolved execution input, constructed by Palimpsest):

Palimpsest receives the spawn payload, checks out evo at the specified sha,
calls `role(**params)`, and receives a `JobSpec`. The role function is
fully consumed at this point and does not appear in the `JobSpec`.

Trenni treats spawn payloads as opaque blobs. It has no dependency on evo.
Palimpsest is the sole consumer of role functions.

### 6. Provider Is Separate from Role

Role functions declare a capability requirement, not a specific model:

```python
min_capability = "reasoning_medium"
```

Provider selection happens at the job level. The runtime maps capability
requirements to available providers and handles pricing. This allows the
same role to run on different providers without modification, and keeps cost
calculation provider-aware without making roles provider-specific.

### 7. Publication Guarantee

`publication_fn` performs publication and must confirm the artifact is
retrievable before returning a `git_ref`. If publication fails for any
reason, Palimpsest raises an exception and emits `agent.job.failed`.

Publication failure is never silent. The full state matrix (from ADR-0002):

| Budget exhausted | Publication succeeded | Outcome |
|------------------|-----------------------|---------|
| no  | yes | `agent.job.completed` → `task.completed` (via eval) |
| yes | yes | `agent.job.completed(code="budget_exhausted")` → `task.partial` |
| no  | no  | `agent.job.failed` |
| yes | no  | `agent.job.failed` |

There is no `job.partial` state. `task.partial` cannot be derived from an
unpublished local-only result.

Palimpsest signals budget exhaustion to Trenni via `code: "budget_exhausted"`
in the `agent.job.completed` event. Trenni derives the task-level state from
this field. This routing is unchanged from the budget exhaustion design in
ADR-0002.

### 8. Branch and Commit Naming

Branches are named from the task goal, not the job_id:

```
{agent-namespace}/job/{task_id_short}/{goal-slug}
```

Commit messages describe what was accomplished. The job_id and task_id
appear in the commit body for traceability, not as the primary message.

This convention is enforced by `publication_fn` in evo, not by the runtime.

### 9. Trigger Routing via Team

A trigger specifies a team:

```json
{ "team": "backend", "goal": "Implement OAuth2 login" }
```

Trenni resolves the `role_type="planner"` role in that team and launches
the initial planning job with it. The team name propagates through the task
hierarchy so child tasks inherit team context. If no team is specified, a
system default team is used.

### 10. `available_roles` Context Provider

A context provider renders the roles available to the planner, scoped to
the current team. It exposes only `role_type="worker"` roles — planner and
evaluator roles are excluded. The planner sees capability summaries (name,
description), not internal prompt or context configuration.

### 11. Planner Job Model

The planner:

- Receives the high-level goal and available worker roles as context.
- Explores the codebase with read-only tools to understand scope.
- Calls `spawn` with child tasks, each specifying role, goal, budget, and
  eval_spec.
- Does not write code or produce file artifacts.
- Exits via idle detection.

Planner spawn interface:

```python
spawn(tasks=[{
    "role": "implementer",
    "goal": "Implement OAuth2 login endpoint",
    "budget": 0.60,
    "eval_spec": {
        "deliverables": ["POST /auth/login endpoint", "token refresh flow"],
        "criteria": ["tests pass", "no hardcoded secrets"]
    }
}])
```

Inherited params (repo, evo sha, team) are resolved by Trenni during spawn
expansion, not by Palimpsest. Trenni fills them from parent job context
before child jobs are created.

### 12. Eval Job Workspace Setup

Eval jobs come in two forms:

**Leaf eval** (evaluating a task with a repo): checks out the actual git
output of the work it evaluates.

- Trenni extracts the `git_ref` from the last completed job in the task's
  job trace.
- Eval job workspace config: `repo=same, init_branch=work_branch, new_branch=False`.
- Eval job starts with the exact workspace state the work jobs produced.

Git is the ground truth for what was actually produced. Agent-submitted
events may contain hallucinations.

**Root eval** (evaluating a repoless parent task): has no repo to check out.
Its input comes entirely from event context:

- Child eval verdicts (via `eval_context` and `join_context` providers).
- Job execution traces (via `job_trace` provider).
- Structural verdict snapshot.
- Workspace is a scratch directory (repoless degradation).

Multi-repo work naturally decomposes into separate spawned tasks, each with
its own repo and leaf eval. Root eval synthesizes child eval verdicts without
needing direct repo access.

### 13. Repoless Pipeline Degradation

When `repo=""`, the existing four-stage pipeline degrades gracefully:

- **Workspace setup**: creates an empty temp directory as scratch space;
  skips git clone.
- **Context and interaction**: unchanged; context providers and tools work
  against the scratch directory.
- **Publication**: skipped entirely; `git_ref` returns `None`.

No second pipeline is introduced. Meta jobs (planner, root eval) use this
path. The distinction is purely in workspace config.

### 14. Eval-Specific Context Providers

**`eval_context`**: renders goal, deliverables, criteria, structural verdict,
and child task eval results for the evaluator.

**`job_trace`**: renders the execution history of the task being evaluated —
per job: job_id, role, status, summary, git_ref.

The existing `join_context` provider handles child task terminal state
rendering and is reused by the evaluator context.

## Consequences

### Positive

- Publication failure has an unambiguous, observable signal (`agent.job.failed`).
- Role functions are independently testable, versioned, and evolvable.
- Spawn payload is compact and reproducible at any future point in time.
- Trenni has zero dependency on evo or role internals.
- Team composition is evolvable — agents can modify team structure without
  touching runtime code.
- Eval jobs verify against git ground truth, not agent self-reports.
- Branch and commit history is human-readable.

### Tradeoffs

- Palimpsest must be able to check out and execute evo at an arbitrary sha;
  this requires a defined evo access protocol.
- Role functions must be deterministic given the same inputs at the same sha.
- All four functions must handle their own internal errors and surface them
  as exceptions; silent failures are not permitted.
- `available_roles` context provider must load and render role definitions
  at job startup; cache-worthy if role count grows.
- Eval workspace checkout adds one git clone operation per eval job.

### Non-Goals

- Dynamic tool sets that change mid-loop.
- Evolvable loop termination conditions.
- `artifact_sink` and `event_only` publication strategies (deferred; will
  be implemented as additional `publication_fn` variants).
- Multi-provider routing within a single job.
- Dynamic team composition during task execution.
- Cross-team role sharing within a single task tree.
- Role capability negotiation (planner picks from a fixed list).
- Arbitrary multi-repo code mutation within a single job.
