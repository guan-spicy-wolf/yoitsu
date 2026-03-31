# ADR-0009: Preparation and Publication Functions

- Status: Accepted
- Date: 2026-03-31
- Related: ADR-0003, ADR-0007

## Context

The current `workspace` function sets up a git repository working directory before the agent loop begins. The current `publication` function handles result delivery (e.g., git push, PR creation) after the agent loop completes.

In practice, job preparation often requires more than a git checkout — dependency installation, context fetching from Pasloe, environment variable injection, file staging. Similarly, result submission may involve more than git operations — posting reviews, emitting proposal events, updating external systems.

The question is how to expand these semantics without either (a) exposing preparation internals to the agent or (b) replacing deterministic code with LLM-driven setup, which would sacrifice evolvability.

## Decisions

### 1. Rename workspace → preparation, publish → publication; broaden semantics

The `workspace` function becomes `preparation` with expanded scope: any deterministic setup required before the agent loop. This includes but is not limited to:

- Git repository checkout and branch setup
- Dependency installation
- Context fetching (Pasloe queries, PR diffs, CI status)
- Environment variable injection
- File staging

The `publication` function broadens symmetrically: any deterministic result delivery after the agent loop.

The agent sees none of this. It receives a ready environment and produces outputs; the surrounding lifecycle is invisible to it.

### 2. Role and preparation function maintain a one-to-one relationship

Each role has exactly one preparation function and exactly one publication function. There is no declarative pipeline, no step configuration, no composition DSL.

```python
def prepare_implementer(config: WorkspaceConfig) -> PreparedEnv:
    repo = git_checkout(config.repo, config.branch)
    run_in(repo, "uv sync")
    inject_env(config.env_vars)
    return PreparedEnv(workdir=repo)

def prepare_reviewer(config: WorkspaceConfig) -> PreparedEnv:
    repo = git_checkout(config.repo, config.branch)
    diff = fetch_pr_diff(config.pr_number)
    ci = fetch_ci_status(config.pr_number)
    return PreparedEnv(workdir=repo, context={"diff": diff, "ci": ci})
```

If a new role needs different preparation, it gets a new function. The function's internals may reuse shared utilities (`git_checkout`, `pasloe_query`, etc.), but composition happens in code, not configuration.

Rationale for rejecting declarative pipelines: a configuration DSL for composing preparation steps would expose internal structure that the agent doesn't need and that the system shouldn't reason about declaratively. The original motivation for using functions was to hide all detail behind a single call boundary. A pipeline of named steps recreates the complexity inside the abstraction it was meant to eliminate. Code composition is strictly more expressive, equally evolvable (git-tracked, testable), and does not require a DSL parser or step registry.

### 3. Preparation parameters flow through WorkspaceConfig

The `WorkspaceConfig` dataclass (or its successor) carries all parameters a preparation function might need. Different roles use different subsets of these parameters. Adding new preparation capabilities means adding parameters to `WorkspaceConfig` and using them in the relevant preparation function.

This keeps the interface surface narrow: Trenni assembles a config, calls the preparation function, and passes the result to the agent runtime. The config structure is the only contract between Trenni and preparation logic.

### 4. Preparation and publication functions are evolvable

Because these functions are ordinary Python code in the Palimpsest codebase, the self-evolution mechanism applies to them directly. The system can:

- Modify an existing preparation function to handle a new setup requirement
- Add a new shared utility and call it from multiple preparation functions
- Optimize a publication function's error handling or retry logic

All changes are git-committed and versioned. This is the core advantage over LLM-driven preparation: knowledge about how to set up environments accumulates in code rather than evaporating after each conversation.
