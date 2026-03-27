# ADR-0005: CLI Task Observability

- Status: Accepted
- Date: 2026-03-27
- Related: ADR-0001, ADR-0002

## Context

During the first end-to-end smoke run (planner → spawn → implementer × N →
eval → terminal), the only way to observe task progress was to write ad-hoc
`curl | python3` scripts against the Pasloe event API. The existing CLI
commands fall short in two ways:

- `yoitsu tasks <task_id>` dumps raw JSON. It shows Trenni's live in-memory
  state for the task but does not reconstruct the full chain (spawn tree,
  eval verdicts, branch outcomes) from events.
- There is no blocking "wait until done" primitive. Smoke scripts must poll
  manually and implement their own timeout logic.
- `yoitsu events` is a snapshot. There is no way to stream new events as they
  arrive, which makes live debugging require repeated manual invocations.

The root cause is that useful task state is split across two systems:

- **Trenni** holds live in-memory state (current job states, queue depth).
  It is authoritative while jobs are running but has no history after a
  restart.
- **Pasloe** holds the durable event log. It is the only source of truth for
  completed work, eval results, and the spawn tree structure.

Reconstructing a meaningful chain view requires joining both.

## Decisions

### 1. `yoitsu tasks chain <task_id>` — Human-readable chain view

A new command that reconstructs the full task chain from Pasloe events and
overlays live state from Trenni where available. Output is human-readable
text, not JSON.

**Data sources:**

1. Pasloe `GET /events?task_id=<id>` (all ancestor and descendant task IDs,
   see §4) to collect all lifecycle events.
2. Trenni `GET /tasks/<id>` (live state) — optional, degraded gracefully if
   Trenni is unreachable.

**Output format** (one line per task, indented by depth):

```
069c633f53417da0          pending      planner    069c633f53417da0-root
  069c633f53417da0/fv7o   completed ✓  implementer  palimpsest/job/…:f0e1f05d
  069c633f53417da0/g6gw   completed ✓  implementer  palimpsest/job/…:9809a3ea
```

Columns: task_id (shortened), terminal state + verdict icon, role of the
primary job, and git_ref from eval result if available.

**Verdict icons:**

| Condition                                   | Icon |
|---------------------------------------------|------|
| `supervisor.task.completed` + verdict=pass  | ✓    |
| `supervisor.task.completed` + verdict≠pass  | ~    |
| `supervisor.task.completed` + no eval       | ✓    |
| `supervisor.task.partial`                   | ~    |
| `supervisor.task.failed`                    | ✗    |
| `supervisor.task.cancelled`                 | –    |
| Not yet terminal                            | …    |

**Reconstruction algorithm:**

1. Fetch all Pasloe events for the root task_id and all its descendants
   (see §4 for how descendants are identified).
2. For each task_id seen in events, determine:
   - The primary job role from the first `supervisor.job.launched` event for
     that task.
   - The terminal state from the latest `supervisor.task.*` terminal event.
   - The eval verdict and git_ref from the `result` field of the terminal
     event, if present.
3. Print tasks in depth-first order (root first, then children sorted by
   task_id).

---

### 2. `yoitsu tasks wait <task_id>` — Block until terminal state

A new command that polls until the specified task (root or child) reaches a
terminal state, then exits with a meaningful exit code.

**Options:**

| Flag              | Default | Meaning                                 |
|-------------------|---------|-----------------------------------------|
| `--timeout SECS`  | 600     | Abort with exit code 2 after N seconds  |
| `--interval SECS` | 5       | Poll interval                           |
| `--quiet`         | false   | Suppress progress output                |

**Exit codes:**

| Code | Condition                                          |
|------|----------------------------------------------------|
| 0    | `supervisor.task.completed`                        |
| 1    | `supervisor.task.failed`, `.partial`, `.cancelled` |
| 2    | Timeout elapsed before terminal state              |

**Progress output** (unless `--quiet`): one line per poll interval showing
elapsed time and the last known state of each task in the chain (same format
as `tasks chain`). On terminal, print the full chain view once and exit.

**Data source:** Pasloe `GET /events?task_id=<id>` polled at the configured
interval. Trenni is not required.

---

### 3. `yoitsu events tail [--task <task_id>]` — Streaming event poll

A new command that continuously polls Pasloe for new events using cursor
pagination and prints each new event as it arrives.

**Options:**

| Flag              | Default | Meaning                                 |
|-------------------|---------|-----------------------------------------|
| `--task TASK_ID`  | —       | Filter to events matching this task     |
| `--source SOURCE` | —       | Filter by source_id                     |
| `--type TYPE`     | —       | Filter by event type                    |
| `--interval SECS` | 2       | Poll interval                           |

**Output format** (one line per event):

```
15:42:01 [trenni-supervisor] supervisor.job.launched  job=069c…-root  task=069c…  role=planner
15:42:03 [palimpsest-agent] agent.job.started         job=069c…-root  task=069c…
```

Runs until interrupted (Ctrl-C). Does not exit on its own.

**Cursor management:** Uses `GET /events?order=asc&cursor=<last_seen_id>`.
On the first call, starts from the current tail of the event log (not from
the beginning), unless `--task` is specified in which case it fetches all
historical events for that task first, then follows.

---

### 4. Descendant task ID enumeration (shared algorithm)

Commands in §1 and §2 need to fetch events for a task and all its
descendants. Task IDs form a prefix hierarchy: children of `abc123` have
IDs `abc123/<suffix>`, grandchildren `abc123/<suffix>/<suffix2>`, etc.

The enumeration strategy:

1. Start with the root task_id.
2. Fetch `GET /events?source=trenni-supervisor&type=supervisor.task.created`
   (no task_id filter — this is the full task creation log).
3. Collect all task_ids from those events whose `task_id` starts with
   `<root_task_id>/`.
4. Include the root itself. This gives the complete subtree.

This is a single Pasloe query and does not require Trenni.

---

### 5. `yoitsu status` alive detection fix

The existing `yoitsu status` command reports `alive=false` even when Trenni
is running. The Trenni client's `check_ready` method must use the same health
endpoint and authentication that the container health check uses. Verify
against `GET /health` (unauthenticated) rather than a status endpoint that
may require auth or return a different schema.

This is a bug fix, not a new feature, but it is included here because it
affects the usefulness of the monitoring commands that depend on knowing
whether Trenni is reachable.

## Non-decisions

- **Push/webhook from Trenni**: Not in scope. Trenni does not push events;
  all observability is pull-based against Pasloe. A future ADR may add a
  webhook or SSE endpoint to Pasloe.
- **Persisting wait state across restarts**: `tasks wait` holds no durable
  state. If the process is killed, the caller must re-run it. This is
  acceptable for CLI use.
- **JSON output mode**: All three new commands output human-readable text.
  `yoitsu tasks <task_id>` already provides the raw JSON for
  machine-consumption. The new commands are observability tools, not data
  pipeline components.
