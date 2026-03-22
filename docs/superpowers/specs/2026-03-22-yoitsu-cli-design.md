# Yoitsu CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A unified `yoitsu` CLI that lets an agent (or human) start, stop, monitor, and control the full Yoitsu stack (pasloe + trenni) with JSON-first output and reliable process management.

**Architecture:** New Python package in the umbrella repo at `/home/holo/yoitsu/yoitsu/`. Uses `click` + `httpx` (already present in the ecosystem). All commands output JSON by default; plain text only for `logs`. Process lifecycle is managed via a `.pids.json` file in the repo root.

**Tech Stack:** Python 3.10+, click, httpx, uv

---

## Design Constraints

- **Agent-first output**: all commands emit JSON to stdout; exit code 0 = success, 1 = failure. No color escapes, no spinners, no interactive prompts.
- **Idempotent**: `up` when already running returns success without restarting. `down` when already stopped returns success.
- **Fast failure**: `up` validates required env vars before spawning any process.
- **No new infrastructure**: reuses pasloe's `/events/stats` and trenni's `/control/status`; no new endpoints needed.

---

## Directory Layout

```
/home/holo/yoitsu/
├── yoitsu/
│   ├── __init__.py
│   ├── cli.py           # click entry point, all subcommands
│   ├── process.py       # process start/stop/PID file management
│   └── client.py        # thin httpx wrappers for pasloe + trenni APIs
├── pyproject.toml       # entry_points: yoitsu = yoitsu.cli:main
└── .pids.json           # runtime (gitignored)
```

---

## Commands

### `yoitsu up [--config PATH]`

1. Validate env vars: `PASLOE_API_KEY`, `OPENAI_API_KEY` — fail immediately if missing.
2. Check `.pids.json`: if both processes are alive (`os.kill(pid, 0)` succeeds), return success without restarting.
3. If PID file exists but process is dead (crash residue), clean up and proceed.
4. Start pasloe: `uv run uvicorn src.pasloe.app:app ...` → append stdout+stderr to `pasloe.log`.
5. Poll `GET /events?limit=1` every 0.5s, up to 10s; fail if not ready.
6. Start trenni: `uv run trenni start -c <config>` → append to `trenni.log`.
7. Poll `GET /control/status` every 0.5s, up to 10s; fail if not ready.
8. Write `.pids.json` with PIDs and start timestamps.

**Output:**
```json
{"ok": true, "pasloe_pid": 12345, "trenni_pid": 12346}
```

### `yoitsu down`

1. Load `.pids.json`; if missing or both processes dead, return success.
2. `POST /control/stop` to trenni; wait up to 30s for process exit.
3. If trenni still alive: `SIGTERM` → wait 5s → `SIGKILL`.
4. `SIGTERM` pasloe → wait 5s → `SIGKILL`.
5. Remove `.pids.json`.

**Output:**
```json
{"ok": true, "stopped": ["trenni", "pasloe"]}
```

### `yoitsu status`

Aggregates state from both services into a single JSON blob. Checks PID liveness independently of HTTP reachability (a process can be alive but HTTP not yet ready, or vice versa on partial shutdown).

**Output:**
```json
{
  "pasloe": {
    "alive": true,
    "total_events": 1240,
    "by_type": {"task.submit": 35, "job.completed": 20, "job.failed": 5}
  },
  "trenni": {
    "alive": true,
    "running": true,
    "paused": false,
    "running_jobs": 2,
    "max_workers": 4,
    "pending_jobs": 0,
    "ready_queue_size": 1
  }
}
```

If a service is unreachable, the corresponding object contains `{"alive": false, "error": "<reason>"}`.

### `yoitsu submit <tasks.yaml>`

Reads a YAML file with a top-level `tasks` list. Each item is POSTed to `POST /events` as `type: task.submit`. Continues on individual failures.

**Tasks YAML format:**
```yaml
tasks:
  - task: "..."
    role: default
    repo: "https://github.com/..."
    init_branch: main
```

**Output:**
```json
{"submitted": 13, "failed": 0, "errors": []}
```

### `yoitsu pause` / `yoitsu resume`

Forward to `POST /control/pause` and `POST /control/resume` respectively.

**Output:**
```json
{"ok": true}
```

### `yoitsu logs [--service pasloe|trenni|all] [--lines 100]`

Reads the last N lines from `pasloe.log` and/or `trenni.log`. Output is plain text (not JSON), with a `=== pasloe ===` / `=== trenni ===` header when showing both. `--service` defaults to `all`.

---

## Process Management Details

**`.pids.json` schema:**
```json
{
  "pasloe": {"pid": 12345, "started_at": "2026-03-22T10:00:00"},
  "trenni":  {"pid": 12346, "started_at": "2026-03-22T10:00:01"}
}
```

**Liveness check:** `os.kill(pid, 0)` — raises `ProcessLookupError` if dead, `PermissionError` if alive but not owned (treat as alive).

**Log append mode:** both log files are opened with `mode="a"` so multiple `up/down` cycles accumulate history. Agent can use `yoitsu logs --lines 200` to read recent output after a failure.

**Working directories:**
- pasloe started from `<root>/pasloe/`
- trenni started from `<root>/trenni/`

**Default config path:** `<root>/config/trenni.yaml`

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `up` — env var missing | exit 1, `{"ok": false, "error": "OPENAI_API_KEY not set"}` |
| `up` — pasloe fails readiness | kill pasloe, exit 1 with reason |
| `up` — trenni fails readiness | kill trenni + pasloe, exit 1 with reason |
| `down` — trenni HTTP unreachable | skip POST, proceed to SIGTERM |
| `status` — service unreachable | include `{"alive": false, "error": "..."}`, exit 0 |
| `submit` — one task fails | continue remaining, report failures in output |

---

## Out of Scope (MVP)

- Web dashboard / TUI
- Log streaming (SSE or follow mode)
- Multi-environment support
- Process supervision / auto-restart on crash
