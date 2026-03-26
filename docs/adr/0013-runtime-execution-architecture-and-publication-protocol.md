# ADR-0013: 2026-03-26 Runtime Execution Architecture And Publication Protocol

- Status: Proposed
- Date: 2026-03-26
- Supersedes: ADR-0012, ADR-0003, ADR-0010 (role and team model)
- Related: ADR-0006, ADR-0007, ADR-0009

## Context

Smoke testing exposed three concrete gaps:

- branch and commit naming used the job_id as content, not the task goal
- partial results that failed publication silently disappeared with no signal
- spawn and eval paths were not exercised because task scope was too large

ADR-0012 established the publication guarantee boundary but did not provide
a design that makes it implementable. ADR-0003 proposed workspace/publication
decoupling but stalled because workspace was not correctly categorised.

The root cause across all three gaps is that publication is not a first-class
operation with explicit success/failure semantics, and workspace is conflated
with the pipeline stage model.

## Decisions

### 1. Workspace is execution substrate, not a pipeline stage

The existing model treats workspace setup as a stage alongside context and
interaction. This is a category error.

Workspace is the execution substrate — it is established at job start, persists
for the entire job, and is shared by all stages. It is not a transformation
with an output that flows into the next stage.

The correct model:

```
job manifest (workspace type, tools, budget, provider)
        ↓ configures
context_fn → interaction loop → publication_fn
```

Workspace type determines what tools are available to the agent. This
resolution happens once at job start, not inside any stage.

### 2. Four evolvable functions

Every job is executed through four functions, all defined in evo and therefore
independently evolvable:

| function | returns | role |
|----------|---------|------|
| `workspace_fn` | — | establishes execution environment (side effect) |
| `context_fn` | `AgentContext` | builds agent prompt and context |
| `publication_fn` | — | publishes artifact and confirms retrievability (side effect) |
| `role_fn` | `JobSpec` | composes the above into a complete job definition |

`workspace_fn` and `publication_fn` are symmetric bookends. Their value is
entirely in their side effects; they have no meaningful return value.

`context_fn` and `role_fn` return content that palimpsest consumes directly.

**Unified failure signaling via exceptions.** All four functions signal failure
by raising an exception. Palimpsest has one failure handler:

```
any function raises  →  agent.job.failed
```

No function returns a sentinel value for failure. Palimpsest does not need
per-function error logic.

### 3. Role is a first-class runtime citizen

Role is a function in evo that returns a fully-resolved `JobSpec`. It is not
a named configuration entity that the runtime interprets — it is the
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

### 4. Spawn payload and runtime execution are distinct layers

**Spawn payload** (declaration, stored in pasloe event):

```json
{
  "role_fn": "git_work_role",
  "params":  { "repo": "...", "branch": "...", "goal": "...", "budget": 18 },
  "sha":     "abc123"
}
```

Compact and serializable. The sha anchors the role function to a specific
version of evo, making job behavior reproducible and evolution auditable.

**JobSpec** (resolved execution input, constructed by palimpsest):

Palimpsest receives the spawn payload, checks out evo at the specified sha,
calls `role_fn(**params)`, and receives a `JobSpec`. The role function is
fully consumed at this point and does not appear in the JobSpec.

Trenni treats spawn payloads as opaque blobs. It has no dependency on evo.
Palimpsest is the sole consumer of role functions.

### 5. Budget model

Budget is unified under a single dimension: **cost** (USD).

- **Iteration count** is not an independent budget dimension. Exceeding a
  threshold (declared by the role) adds a penalty to the cost accumulator
  per additional iteration. This creates a soft economic pressure without
  a hard cut, preserving the agent's ability to complete work.

  ```
  effective_cost = token_cost + max(0, n - threshold) × penalty_per_iter
  ```

- **Context window** is not a separate budget dimension. Token consumption
  is already captured in cost.

Each role declares two budget values:

- `min_cost`: below this the role cannot operate meaningfully; spawn fails
  if the allocated budget is below this value
- `recommended_cost`: the typical budget for a task of this type; used by
  plan as a reference when distributing budget across spawned children

Budget allocation is the plan agent's responsibility. The plan has the full
picture: total remaining task budget, number of children to spawn, estimated
complexity per child. The role does not allocate; it only constrains.

### 6. Provider is separate from role

Role functions declare a capability requirement, not a specific model:

```python
min_capability = "reasoning_medium"
```

Provider selection happens at the job level. The runtime maps capability
requirements to available providers and handles pricing. This allows the
same role to run on different providers without modification, and keeps
cost calculation provider-aware without making roles provider-specific.

### 7. Publication guarantee (supersedes ADR-0012, narrows ADR-0007)

`publication_fn` is responsible for pushing the artifact and confirming it
is retrievable. If publication fails for any reason, `publication_fn` raises,
and palimpsest emits `agent.job.failed`.

ADR-0007 established that budget exhaustion exits through
`agent.job.completed(code="budget_exhausted")`, assuming publication always
succeeds. This ADR adds the conditional: publication success is required
for that path to be valid. The full state matrix:

| budget exhausted | publication succeeded | outcome |
|------------------|-----------------------|---------|
| no  | yes | `agent.job.completed` → `task.completed` (via eval) |
| yes | yes | `agent.job.completed(code="budget_exhausted")` → `task.partial` |
| no  | no  | `agent.job.failed` |
| yes | no  | `agent.job.failed` |

There is no `job.partial` state. `task.partial` cannot be derived from an
unpublished local-only result.

Palimpsest signals budget exhaustion to trenni via `code: "budget_exhausted"`
in the `agent.job.completed` event. Trenni derives the task-level state from
this field. This event routing mechanism is unchanged from ADR-0007.

### 8. Branch and commit naming

Branches are named from the task goal, not the job_id:

```
{agent-namespace}/task/{task_id_short}/{goal-slug}
```

Commit messages describe what was accomplished. The job_id and task_id
appear in the commit body for traceability, not as the primary message.

This is enforced by `publication_fn` in evo, not by the runtime.

## Consequences

### Positive

- Publication failure has an unambiguous, observable signal
- Role functions are independently testable, versioned, and evolvable
- Spawn payload is compact and reproducible at any future point in time
- Budget is a single dimension with a clear allocation protocol
- Trenni has zero dependency on evo or role internals
- Branch and commit history is human-readable

### Tradeoffs

- Palimpsest must be able to checkout and execute evo at an arbitrary sha;
  this requires a defined evo access protocol
- Role functions must be deterministic given the same inputs at the same sha
- All four functions must handle their own internal errors and surface them
  as exceptions; silent failures are not permitted

### 9. Role metadata and team composition (supersedes ADR-0010 role/team model)

Role functions carry metadata via decorator, replacing `RoleDefinition`
dataclasses and separate `TeamDefinition` files from ADR-0010:

```python
@role(
    name="implementer",
    description="Writes code to implement a specific task",
    teams=["backend"],
    role_type="worker",       # worker | planner | evaluator
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

**Validation rules** (enforced at evo load time, failure prevents startup):

- Each team must have exactly one `role_type="planner"`
- Each team must have at most one `role_type="evaluator"`; if absent the
  system default evaluator is used
- Each team must have at least one `role_type="worker"`
- Role names must be unique within a team

**`available_roles` context provider** filters by the current team and
exposes only `role_type="worker"` roles to the planner. Planner and
evaluator roles are excluded — the planner selects spawn targets from
workers only.

**Trigger routing** is unchanged from ADR-0010: a trigger specifies a team
name; trenni finds the `role_type="planner"` role in that team and launches
the initial planning job.

**Planner spawn interface** remains minimal. The planner specifies only what
it knows: role name, goal, budget, and eval_spec. Inherited params (repo,
sha, team) are resolved by palimpsest from parent job context:

```python
spawn(tasks=[{
    "role": "implementer",
    "goal": "Implement OAuth2 login endpoint",
    "budget": 0.60,
    "eval_spec": { "deliverables": [...], "criteria": [...] }
}])
```

The `prompt`, `contexts`, and `tools` fields from ADR-0010's `RoleDefinition`
are replaced by the role function body and its choice of `context_fn`.

### Non-Goals

- Dynamic tool sets that change mid-loop (deferred)
- Evolvable loop termination conditions (deferred)
- artifact_sink and event_only publication strategies (ADR-0003 deferred
  items; will be implemented as additional publication_fn variants)
- Multi-provider routing within a single job
