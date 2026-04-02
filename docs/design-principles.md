# Design Principles

Date: 2026-04-02
Source: Extracted from current code, ADRs, and code conventions

## Architectural Principles

### 1. Pasloe is authoritative; durable output is currently git-based

Pasloe events are the authoritative system record for task and job
lifecycle. Workspace directories, process memory, and Trenni's in-memory
records are all derived or ephemeral. For git-backed jobs, physical output
is currently persisted through git publication and surfaced as `git_ref`.
ADR-0013 artifact contracts have landed in `yoitsu-contracts`; backend and
runtime wiring are still pending.

### 2. Job and task are strictly separated

A job is a runtime execution unit (one Palimpsest run). A task is a logical
work objective. A job completing does not mean its task is complete. Trenni
owns task state; Palimpsest has no task awareness. This separation is load-
bearing -- it enables evaluation, partial completion, and spawn-based
decomposition.

### 3. Spawn is the only orchestration primitive

There are no pre-defined DAGs, no workflow definitions, no pipeline
configurations. The planner agent decides decomposition at runtime by
calling spawn(). Trenni mechanically expands spawn requests. This keeps
orchestration logic in the evolvable layer (planner prompt/context) rather
than in infrastructure.

### 4. The control plane is deterministic and non-evolvable

Trenni's state machine, condition evaluation, spawn expansion, and
eval/join triggering are hardcoded. They do not consume evo/ code and are
not targets for self-optimization. This provides a stable foundation that
continues to work correctly even when evo/ changes introduce bugs.

The trust boundary is:
- Trenni (non-evolvable) decides WHAT to run
- Palimpsest (consumes evo) decides HOW to run it

Task decomposition DECISIONS (which roles, what budget, how many children)
belong to the planner role, not to Trenni. Trenni only executes the
mechanics.

### 5. Four stages are a dependency chain, not a design choice

Preparation -> context -> interaction -> publication is causally fixed
within any job. You cannot interact without context, cannot build context
without a workspace, cannot publish without having interacted. The stage
ordering is not configurable because it cannot be otherwise.

Variation between task types lives in stage IMPLEMENTATIONS (different
preparation_fn, different publication_fn), not in stage TOPOLOGY.

### 6. Every job is a single attempt

A job is short-lived, disposable, and allowed to fail honestly. It does not
retry at the task level, does not hold long-term state, and does not make
scheduling decisions. Honest failure (job.failed) is a legitimate output
that feeds back to the control plane.

### 7. Workspace is a private copy, never the truth

Jobs work on private git clones or repoless scratch directories. The
workspace is disposable after the job completes. If the container crashes,
the workspace is lost -- and that is acceptable because the durable record
lives in Pasloe and, when publication runs, in git.

### 8. Evolution happens in evo/, nowhere else

All evolvable logic lives in the evo/ directory: roles, prompts, context
providers, tools, preparation functions, publication functions. The runtime
skeleton (Palimpsest's four-stage pipeline), the scheduler (Trenni), and
the event store (Pasloe) are not evolution targets.

Self-optimization tasks modify evo/ through normal git operations, the same
way any other code change happens.

### 9. Publication is git-first today; artifact store is planned

The current runtime publishes productive git-backed work by commit + push
and records `git_ref` in the completion event. Planner/evaluator roles
usually skip publication. ADR-0013 artifact contracts (`ArtifactRef`,
`ArtifactBinding`, `JobCompletedData.artifact_bindings`) have landed;
backend implementation and runtime wiring are pending.

### 10. Budget is signal, not enforcement

Budget is the planner's prediction of expected cost. The runtime does not
enforce cost-based termination. Actual spend is uncapped so that
budget_variance captures true deviation. System backstops
(max_iterations_hard, job_timeout) protect against bugs, not overspending.

Budget prediction accuracy is a proxy for system modeling fidelity and is
the primary optimization signal (ADR-0010).

## Code Conventions

### Event naming

```
<source>.<model>.<state>
```

source: agent | supervisor | trigger
model: job | task | llm | tool
state: started | completed | failed | request | exec | etc.

### Task ID hierarchy

Prefix-nested, deterministic from inputs:
```
018f4e3ab2c17d3e              # root (UUIDv7 prefix)
018f4e3ab2c17d3e/3afw         # child (base32 hash)
018f4e3ab2c17d3e/3afw/b2er    # grandchild
```

### Failure signaling

All pipeline functions signal failure by raising exceptions. No sentinel
return values, no error codes in return types. Palimpsest has one failure
handler: any exception -> agent.job.failed.

### Publication guarantee

publication_fn must either return a retrievable `git_ref` for branch
publication or intentionally skip publication. Publication failure is never
silent: if branch publication raises, the job fails.
