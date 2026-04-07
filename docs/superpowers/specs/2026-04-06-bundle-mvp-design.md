# Bundle MVP Design

**Status:** Approved, ready for implementation planning
**Date:** 2026-04-06
**Supersedes:** `docs/plans/2026-04-06-evo-team-isolation.md` (Phase 1.5),
`docs/plans/2026-04-06-multi-bundle-evo-phase2.md` (old multi-repo Phase 2 vision)

## Background

The current evo/trenni split leaks task-domain knowledge into trenni infrastructure.
Concrete symptoms observed on 2026-04-06:

- `supervisor.py:1480-1511` categorizes roles into `planner` / `evaluator` / `worker`
  buckets and enforces a fixed topology (exactly one planner, at most one evaluator,
  at least one worker). Factorio's actual role set (worker, implementer, optimizer,
  planner, evaluator) does not fit this mold cleanly — `implementer.py` and
  `worker.py` both declare `role_type="worker"`, so categorization is ambiguous.
- `_DEFAULT_TEAM_DEFINITION` lacks a `worker_roles` field, and production config has
  no team definitions, so the system runs on an incomplete hardcoded fallback.
- Tasks submitted without a `role` go through planner-driven decomposition; the
  planner routes execution subtasks to `implementer` (whose workspace has no git
  remote) instead of `worker`, causing publication to fail and the system to retry
  indefinitely. On 2026-04-06 this burned 15 subtask attempts on a single
  iron-chest placement task with zero successful executions.
- The `evo/roles/` global layer is dead weight: every role that matters is
  team-specific, and the fallback path silently masks configuration errors.

Each time a task domain has needed a new role topology, trenni has been modified
to accommodate it. This is not sustainable — role topology belongs to the task
domain, not to the generic harness.

## Goal

Move all task-domain concerns (role catalog, topology, routing, publication
strategy) into a **bundle**: a self-contained subtree under `evo/<bundle>/`
that owns its own roles and is consumed by trenni through a minimal behavioral
contract.

Trenni becomes a generic harness: given `(bundle, role, payload)`, load the
named role from the named bundle and run it. No categorization, no topology
validation, no automatic routing.

## Non-Goals

- **Multi-repo bundle distribution.** Bundle is a logical unit; whether each
  bundle is its own git repo is a physical packaging question deferred to a
  later phase. MVP keeps everything inside the existing `evo/` repo.
- **Manifest files (bundle.yaml / pyproject per bundle).** Pure directory
  convention is sufficient. Code > config.
- **Automatic role routing.** Task submissions must specify `role` explicitly.
  Missing `role` is a hard 400.
- **Enforced planner/evaluator topology.** Bundles freely choose which roles
  to include. Self-evolution topology is per-bundle business; trenni provides
  templates as guidance, not constraints.
- **Centralized publication declaration.** Publication strategy remains an
  attribute of the role file itself (`worker_publication`, `implementer_publication`).
- **Adapting `2026-04-04-autonomous-review-loop-output-closure.md`.** That plan
  assumes the current supervisor consumption path; bundle MVP will break its
  assumptions. Re-adapting it is a follow-up, not in this scope.
- **Backwards compatibility.** Direct replacement. No deprecation window, no
  data migration, no config shims.

## Architecture

### Bundle = self-contained subtree

A bundle is a directory under `evo/<bundle>/` with this layout:

```
evo/
└── factorio/                      (the bundle, top-level under evo)
    ├── __init__.py
    ├── roles/                     (role catalog — files named by role)
    │   ├── worker.py              (RCON execution, skip publication)
    │   ├── implementer.py         (writes Lua, git publication + allowlist)
    │   ├── optimizer.py
    │   ├── planner.py
    │   └── evaluator.py
    ├── tools/                     (factorio_call_script.py, ...)
    ├── contexts/                  (factorio_scripts.py, ...)
    ├── prompts/                   (optimizer.md, ...)
    ├── lib/                       (rcon.py, bridge.py — human-reviewed infra)
    └── evolved/                   (agent write surface)
        └── scripts/               (Lua scripts produced by implementer)
```

Key properties:

- **No global layer.** `evo/roles/`, `evo/tools/`, `evo/contexts/`, `evo/prompts/`
  cease to exist. Loaders only look under `evo/<bundle>/`. Missing role is a hard
  error, not a silent fallback.
- **No `teams/` wrapper.** Bundle name is the first-level directory under `evo/`.
  Python import path is `factorio.lib.rcon`, not `teams.factorio.lib.rcon`.
- **`evolved/` is the only agent-writable subtree.** Implementer's path allowlist
  is tightened to `evo/<bundle>/evolved/**`.
- **Role catalog is discovered by filename.** `evo/<bundle>/roles/*.py` is the
  entire catalog. The filename (minus `.py`) is the canonical role name. No
  manifest, no registration.

### Worker vs Implementer: both kept

These two roles have similar prompts but different publication strategies, and
the separation is load-bearing:

- **worker.py** — executes in-game operations via RCON. `publication=skip`.
  Never produces git commits. Workspace is ephemeral scratch.
- **implementer.py** — writes Lua scripts into `evolved/scripts/`. Uses
  `git_publication` with a path allowlist. All file changes must pass
  allowlist validation before commit. Workspace requires a real git remote.

The ideal workflow is: worker drafts scripts during or after execution, but
scripts must pass human review before landing in the mod. Separate roles allow
publication policy to diverge even when the underlying prompt is similar.
This is an intentional instance of the principle "similar prompt + different
publication = different role."

The earlier instinct to delete one as "duplication" was based on a
misreading. Both stay. The only deletion in this area is the *global*
`evo/roles/worker.py`, which is genuinely legacy.

### Trenni contract

Trenni reads exactly one thing from a bundle: **the set of role files under
`evo/<bundle>/roles/`**. Everything else (tools, contexts, prompts, lib) is
indirect — consumed by role code at runtime, not inspected by trenni.

Task submission API:
```
{bundle: <name>, role: <name>, payload: ...}
```
Both `bundle` and `role` are required. Missing either is a 400. Trenni does
not infer a default, does not run a planner, does not categorize.

Subtask spawning: role code that wants to decompose or chain work submits
new tasks with explicit `(bundle, role)` through the same API. Trenni treats
them identically to externally submitted tasks.

## Changes

### Deletions

- `evo/roles/`, `evo/tools/`, `evo/contexts/`, `evo/prompts/` (global layer)
- `supervisor.py:1480-1511` role categorization block
- `_DEFAULT_TEAM_DEFINITION` and all references to `worker_roles`,
  `planner_role`, `eval_role` fields on team definitions
- `RoleManager` global fallback path
- `docs/plans/2026-04-06-evo-team-isolation.md` → moved to `docs/archive/`
- `docs/plans/2026-04-06-multi-bundle-evo-phase2.md` → moved to `docs/archive/`

### Renames

- Directory: `evo/teams/factorio/` → `evo/factorio/`
- Python imports: `teams.factorio.*` → `factorio.*` (repo-wide)
- Vocabulary: `team` → `bundle` in API field names, config keys, error
  messages, logs, documentation. `config/trenni.yaml` `teams:` section
  becomes `bundles:`.

### New behavior

- `RoleManager(bundle=...)`, `ToolLoader(bundle=...)`, `ContextLoader(bundle=...)`
  only search `evo/<bundle>/<kind>/`. Missing → raise.
- Task submission requires `role` field. Missing → 400.
- Supervisor execution path: resolve `(bundle, role)` → load role file →
  run. No categorization, no topology validation.

### Unchanged

- Publication strategies (`worker_publication`, `implementer_publication`)
  remain as attributes of role files.
- SHA pinning, evo materialization (`_materialize_evo_root`), and sys.path
  injection mechanisms.
- `evolved/` conventions and implementer allowlist semantics (just rooted at
  `evo/<bundle>/evolved/` instead of `evo/teams/<team>/evolved/`).
- `factorio-tool-evolution-mvp.md` main line (Task 9 smoke verified) — bundle
  MVP is its infrastructure upgrade, not a replacement.

## Factorio bundle migration

After the structural changes, `evo/factorio/roles/` contains:

- `worker.py` — RCON execution (from current `teams/factorio/roles/worker.py`,
  which is already the RCON executor)
- `implementer.py` — Lua script author (from current
  `teams/factorio/roles/implementer.py`)
- `optimizer.py`, `planner.py`, `evaluator.py` — as today

Tonight's iron-chest task becomes:
```
{bundle: factorio, role: worker, payload: "place iron-chest at (0,0), (2,0), (4,0)"}
```
Zero decomposition, zero implementer misrouting, zero publication failure.

## Known Breakage

`docs/plans/2026-04-04-autonomous-review-loop-output-closure.md` assumes the
existing supervisor consumption path in `_handle_job_done` and a specific
shape for spawning follow-up tasks. Bundle MVP changes the task submission
contract (explicit `role` required) and removes the categorization logic it
implicitly relies on.

This plan is **retained, not archived**, because the goal (closing the
optimizer → follow-up task loop) remains valid. A follow-up task after
bundle MVP lands will re-adapt its consumption logic to the new API:
ReviewProposal parsing stays the same, but the spawn path must explicitly
specify `(bundle, role)` for each follow-up task.

## Implementation tasks (outline)

Detailed plan will be produced by `writing-plans` skill. Outline only:

1. **Archive conflicting plans** — move Phase 1.5 and old Phase 2 docs to
   `docs/archive/`.
2. **Delete global evo layer** — remove `evo/roles/`, `evo/tools/`,
   `evo/contexts/`, `evo/prompts/`. Grep-verify no references remain.
3. **Flatten bundle layout** — move `evo/teams/factorio/` to `evo/factorio/`,
   delete `evo/teams/` wrapper.
4. **Repo-wide rename** — `teams.factorio.` → `factorio.` (Python imports);
   `teams/factorio/` → `factorio/` (path literals in configs, docs, tools);
   `team` → `bundle` (API field names, config keys, messages, logs).
5. **Loader refactor** — `RoleManager` / `ToolLoader` / `ContextLoader`
   accept `bundle`, search `evo/<bundle>/<kind>/` only, no fallback.
6. **Supervisor simplification** — delete `supervisor.py:1480-1511` role
   categorization, delete `_DEFAULT_TEAM_DEFINITION`, remove all references
   to `worker_roles` / `planner_role` / `eval_role`.
7. **API change** — task submission requires `role` field. Missing → 400.
   Update CLI, API handlers, and any submission helpers.
8. **Smoke verification** —
   (a) `(bundle=factorio, role=worker)` runs the ping script via RCON (Task 9 equivalent).
   (b) `(bundle=factorio, role=implementer)` writes a Lua script and commits it
   through `implementer_publication` to `evo/factorio/evolved/scripts/`.
   (c) Iron-chest placement task succeeds end-to-end.

## Success criteria

- Submitting `{bundle: factorio, role: worker, payload: ...}` runs worker
  directly without decomposition or misrouting.
- Submitting a task without `role` returns 400 immediately.
- `supervisor.py` contains zero references to `planner_role`, `worker_roles`,
  `eval_role`, or `_DEFAULT_TEAM_DEFINITION`.
- `evo/roles/`, `evo/tools/`, `evo/contexts/`, `evo/prompts/`, and `evo/teams/`
  do not exist.
- `grep -r "teams\.factorio\|teams/factorio" yoitsu palimpsest trenni` returns
  zero hits in code (documentation archive references allowed).
- Factorio smoke test (Task 9) still passes under the new layout.
- An implementer-produced Lua script lands in `evo/factorio/evolved/scripts/`
  on a publication branch, and an attempt to write outside `evolved/` is
  rejected by the allowlist.
