# ADR-0011: 2026-03-26 Event Domain System, Detail Tables, And Operations CLI

- Status: Accepted, implementation pending
- Date: 2026-03-26
- Related: ADR-0004

## Context

Pasloe stores all event data in a generic JSONB `data` column on the `events`
table. The projection framework (ADR-0004) was designed to accelerate queries
by materializing event data into typed tables, but the one-projection-per-
event-type granularity is wrong: querying "all jobs for a task" or "LLM cost
over time" requires cross-type aggregation that per-type tables cannot serve
efficiently.

Meanwhile, operations tooling is scattered across ad-hoc scripts
(`monitor.py`, `submit-tasks.py`, `deploy-quadlet.sh`) with no unified
interface and no access to structured event queries.

Key observations:

- The event envelope (id, source_id, type, ts) is fixed and generic.
- Events within the same **domain** (job, task, llm, tool) share common
  queryable fields (e.g. all job events carry `job_id` and `task_id`).
- PostgreSQL can index JSONB internals via GIN/expression indexes, but SQLite
  cannot. Detail tables provide backend-agnostic acceleration.
- Each domain forms a natural bundle: a detail model (table schema), domain-
  specific API routes, and aggregation queries. These should be co-located.

## Decision

### 1. Event type naming convention

Event types follow a three-segment convention:

```
<source>.<model>.<state>
```

- **source**: the emitting component (`agent`, `supervisor`, `trigger`)
- **model**: the domain entity (`job`, `task`, `llm`, `tool`)
- **state**: the specific event (`started`, `completed`, `request`, `exec`)

For **registered models** (`job`, `task`, `llm`, `tool`), the **model**
segment determines which domain (and therefore which detail table) an event
belongs to.

Not every event type must map to a registered domain. `trigger.*` events use
the same naming convention but remain generic events with no detail table in
this phase.

Migration from current names:

| Current                    | New                            | Model  |
|----------------------------|--------------------------------|--------|
| `agent.llm.request`       | `agent.llm.request`            | llm    |
| `agent.llm.response`      | `agent.llm.response`           | llm    |
| `agent.tool.exec`         | `agent.tool.exec`              | tool   |
| `agent.tool.result`       | `agent.tool.result`            | tool   |
| `job.started`             | `agent.job.started`            | job    |
| `job.completed`           | `agent.job.completed`          | job    |
| `job.failed`              | `agent.job.failed`             | job    |
| `job.cancelled`           | `agent.job.cancelled`          | job    |
| `job.runtime.issue`       | `agent.job.runtime_issue`      | job    |
| `job.stage.transition`    | `agent.job.stage_transition`   | job    |
| `job.spawn.request`       | `agent.job.spawn_request`      | job    |
| `task.created`            | `supervisor.task.created`      | task   |
| `task.evaluating`         | `supervisor.task.evaluating`   | task   |
| `task.completed`          | `supervisor.task.completed`    | task   |
| `task.failed`             | `supervisor.task.failed`       | task   |
| `task.partial`            | `supervisor.task.partial`      | task   |
| `task.eval_failed`        | `supervisor.task.eval_failed`  | task   |
| `task.cancelled`          | `supervisor.task.cancelled`    | task   |
| `supervisor.job.launched` | `supervisor.job.launched`      | job    |
| `supervisor.job.enqueued` | `supervisor.job.enqueued`      | job    |
| `trigger.external`        | `trigger.external.received`    | external |

Four-segment types are flattened: `job.runtime.issue` →
`agent.job.runtime_issue` (underscore joins the compound state).

This ADR assumes a **fresh cutover**: there is no historical event corpus that
must remain query-compatible across old and new type names. We rename the
types in place across contracts and producers, then rebuild downstream state
from newly emitted events only. No compatibility alias period is provided.

### 2. Detail tables replace projections

Each domain has a detail table where committed events are written with their
`data` fields flattened into typed, indexed columns. One row per **event**
(no upsert, no entity snapshot, no state aggregation). Primary key is
`event_id` with a foreign key to `events.id`.

The detail table's purpose is to provide **indexed access to fields inside
event data** — the same role that PostgreSQL expression indexes or GIN indexes
fill, but portable to SQLite. It is a domain-specific acceleration layer over
the canonical event log, not a replacement for the log.

Example for the task domain:

```
detail_tasks:
  event_id      UUID PK  FK → events.id
  task_id       TEXT      indexed
  parent_id     TEXT
  goal          TEXT
  team          TEXT
  state         TEXT      indexed   -- derived from event type tail segment
  reason        TEXT
```

All fields come directly from the event's data dict, laid flat. The `state`
column is derived from the event type's tail segment (e.g.
`supervisor.task.completed` → `state = "completed"`).

For events with complex nested fields (e.g. `supervisor.job.launched` with
its `llm`, `workspace`, `publication` dicts), only the commonly queried
scalar fields are flattened. The detail row does **not** become the canonical
representation of the event. Full event fidelity remains in `events.data`.

### 3. Event domain abstraction

A domain bundles everything for one event category into a single module:

- **Detail model** (SQLAlchemy table)
- **API routes** (FastAPI router)
- **Stats queries** (aggregation over detail table)
- **from_event / to_payload** (typed extraction + normalized domain response)

```python
# pasloe/domains/__init__.py

@dataclass
class EventDomain:
    model_name: str                       # "job", "task", "llm", "tool"
    event_types: list[str]                # all event types this domain handles
    detail_model: type[EventDetailBase]
    router: APIRouter


class EventDetailBase(DeclarativeBase):
    """Base for all detail tables."""

    @classmethod
    @abc.abstractmethod
    def from_event(cls, event_id: UUID, event_type: str, data: dict) -> Self:
        """Extract indexed detail fields from a committed event."""

    @abc.abstractmethod
    def to_payload(self) -> dict:
        """Return the normalized domain payload represented by this detail row.

        This is not required to reproduce the original event exactly.
        Canonical event payload remains in events.data.
        """
```

### 4. Domain module structure

Each domain is a single file under `pasloe/domains/`:

```
pasloe/src/pasloe/domains/
    __init__.py         — EventDomain, EventDetailBase, discover_domains()
    jobs.py             — detail_jobs table + /jobs routes + /jobs/stats
    tasks.py            — detail_tasks table + /tasks routes + /tasks/stats
    llm.py              — detail_llm table + /llm routes + /llm/stats
    tools.py            — detail_tools table + /tools routes + /tools/stats
```

A domain file contains:

```python
# pasloe/domains/tasks.py

class TaskDetail(EventDetailBase):
    __tablename__ = "detail_tasks"
    model_name = "task"

    event_id = mapped_column(ForeignKey("events.id"), primary_key=True)
    task_id  = mapped_column(String, index=True)
    parent_id = mapped_column(String, nullable=True)
    goal     = mapped_column(String, nullable=True)
    team     = mapped_column(String, nullable=True)
    state    = mapped_column(String, index=True)
    reason   = mapped_column(String, nullable=True)

    @classmethod
    def from_event(cls, event_id, event_type, data):
        state = event_type.rsplit(".", 1)[-1]  # tail segment
        return cls(
            event_id=event_id,
            task_id=data.get("task_id", ""),
            parent_id=data.get("parent_task_id"),
            goal=data.get("goal"),
            team=data.get("team"),
            state=state,
            reason=data.get("reason"),
        )

    def to_payload(self): ...


router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("")
async def list_tasks(
    task_id: str | None = None,
    state: str | None = None,
    team: str | None = None,
    ...
): ...

@router.get("/stats")
async def task_stats(since: datetime | None = None, ...):
    # SELECT state, COUNT(*) FROM detail_tasks GROUP BY state
    ...


domain = EventDomain(
    model_name="task",
    event_types=[
        "supervisor.task.created",
        "supervisor.task.evaluating",
        "supervisor.task.completed",
        "supervisor.task.failed",
        "supervisor.task.partial",
        "supervisor.task.eval_failed",
        "supervisor.task.cancelled",
    ],
    detail_model=TaskDetail,
    router=router,
)
```

### 5. App integration and write path

At startup, the app discovers all domain modules and builds a model-based
routing table for registered domains:

```python
# app.py
domains = discover_domains()  # import all .domain objects from domains/
domain_registry: dict[str, EventDomain] = {}
for d in domains:
    app.include_router(d.router)
    domain_registry[d.model_name] = d
```

The committer writes detail rows synchronously in the same transaction as
the event commit:

```python
# In commit path (replaces projection worker call):
parts = event.type.split(".", 2)
model = parts[1] if len(parts) == 3 else None
domain = domain_registry.get(model or "")
if domain:
    detail = domain.detail_model.from_event(event.id, event.type, event.data)
    session.add(detail)
# event.data is still written for all events (redundant for registered
# types, sole storage for unregistered types)
```

This removes the async projector worker entirely. The committer handles
everything in one transaction.

If detail extraction fails for a registered event type, the event log remains
the priority durability surface: the system should preserve the committed
event and surface the detail-write failure operationally, rather than block
event visibility behind a domain parsing bug.

### 6. Removal of projection framework

The following are removed:

- `pasloe/src/pasloe/projections/` — `BaseProjection`, `ProjectionRegistry`
- Projector pipeline worker (outbox `PIPELINE_PROJECTOR` path)
- `OutboxRecord` entries for projector pipeline
- `projection_registry` from app state
- Projection filter logic in `store.query_events()`

Pipeline simplifies from committer + projector + webhook to
**committer + webhook**.

The `source` field on `BaseProjection` is dropped entirely — domain routing
is by event type only (model segment), not by source.

### 7. Domain-specific API endpoints

Each registered domain exposes routes under its own prefix:

```
GET  /tasks              — query task events (task_id, state, team filters)
GET  /tasks/stats        — task event statistics + derived task metrics
GET  /jobs               — query job events (job_id, task_id, role, status)
GET  /jobs/stats         — job event statistics + derived job metrics
GET  /llm                — query LLM call events (job_id, model filters)
GET  /llm/stats          — token/cost aggregation (group by model, time range)
GET  /tools              — query tool execution events (job_id, tool_name)
GET  /tools/stats        — tool statistics (group by tool_name, success rate)
```

The generic `GET /events` endpoint is preserved for envelope-level queries
and unregistered event types. The generic `POST /events` remains the sole
write entry point.

Important semantic boundary: `/tasks` and `/jobs` in Pasloe are still
**historical event views**, not live entity snapshots. Derived metrics such as
"active task count" are computed from event history (for example, tasks with
no terminal event yet), not by treating detail tables as current-state rows.

### 8. Data column handling

`events.data` (JSONB) is retained:

- **Registered event types**: data is written redundantly alongside the detail
  row. This keeps webhook delivery simple (serialize `event.data` directly)
  and allows the detail table to be rebuilt by replaying events.
- **Unregistered event types**: data is the sole storage. Functionality is not
  degraded — these events are queryable through `GET /events` as before, just
  without indexed field access.

### 9. Trenni task query endpoints

Trenni gains task and job query endpoints on the control API, sourced from its
in-memory scheduler state:

```
GET  /control/tasks              — list tasks (state, team filters)
GET  /control/tasks/{task_id}    — task detail (job_order, eval state, result)
GET  /control/jobs               — list jobs (task_id, role, queue/running filters)
GET  /control/jobs/{job_id}      — job detail (condition, runtime handle, queue state)
```

This provides a live view of task state that includes information not in
pasloe events (e.g. current job_order, eval_spawned flag, in-memory
scheduling state). Pasloe's `/tasks` and `/jobs` endpoints provide historical
event views; Trenni's `/control/tasks` and `/control/jobs` provide the live
operational view.

### 10. Unified CLI

A `yoitsu` CLI replaces the scattered scripts:

```
yoitsu status              — system overview (trenni + pasloe + podman)
yoitsu tasks               — list tasks (queries trenni live state)
yoitsu tasks <id>          — task detail + job trace
yoitsu events              — recent events (queries pasloe)
yoitsu jobs                — job listing (queries pasloe /jobs)
yoitsu llm-stats           — LLM token/cost summary (queries pasloe /llm/stats)
yoitsu submit <file|goal>  — submit trigger event to pasloe
yoitsu deploy              — wraps deploy-quadlet.sh
```

Config: `~/.config/yoitsu/config.yaml` or environment variables
(`YOITSU_PASLOE_URL`, `YOITSU_TRENNI_URL`, `PASLOE_API_KEY`).

## Consequences

### Positive

- Each domain is self-contained: model, routes, stats in one file; adding a
  new domain is adding one file + one Alembic migration
- Projection framework complexity removed (async worker, outbox pipeline,
  registry); detail writes are synchronous in commit transaction
- Domain-specific APIs provide natural query and stats endpoints; no generic
  aggregation framework needed
- Event type naming becomes consistent and parseable; model segment
  provides reliable domain routing
- Detail tables work on both PostgreSQL and SQLite

### Tradeoffs

- Detail tables are redundant with `events.data` for registered types (disk
  cost; minor since detail rows are small)
- Event type rename requires coordinated migration across yoitsu-contracts,
  palimpsest, and trenni
- New event categories require a migration (acceptable — event types change
  rarely and should be deliberate)
- Pasloe domain endpoints are historical-event APIs, not live state APIs;
  operators must use Trenni control endpoints for scheduler truth

### Non-Goals

- Replacing `events.data` entirely — retained as fallback and for webhook
  delivery
- Condition-based alerting — out of scope; can be added later as a trenni
  feature emitting alert events
- Task persistence in trenni — in-memory state with event replay is
  sufficient for current scale
- Adding a trigger domain/detail table in this phase — trigger sources may
  need different modeling and remain generic for now

## Implementation Scope

**pasloe**
- `domains/`: new package with `__init__.py` (base classes, discovery),
  `jobs.py`, `tasks.py`, `llm.py`, `tools.py`
- `app.py`: discover domains, include routers, build domain registry
- `pipeline.py`: remove projector worker; committer writes detail rows
  synchronously
- `store.py`: remove projection filter logic from `query_events()`
- `projections/`: delete entire package
- `models.py`: remove projector outbox pipeline constant
- Alembic migration: create `detail_jobs`, `detail_tasks`, `detail_llm`,
  `detail_tools` tables

**yoitsu-contracts**
- `events.py`: rename all `event_type` ClassVar values to three-segment
  convention

**palimpsest**
- `emitter.py` / `event_gateway.py`: no changes (event_type comes from
  data classes)

**trenni**
- `supervisor.py`: event type string references updated
- `control_api.py`: add `GET /control/tasks`, `GET /control/tasks/{task_id}`,
  `GET /control/jobs`, `GET /control/jobs/{job_id}`

**yoitsu (new or existing CLI package)**
- CLI entry point with subcommands: status, tasks, events, jobs, llm-stats,
  submit, deploy
