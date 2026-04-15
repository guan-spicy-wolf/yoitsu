"""Join context provider for continuation planners.

Per ADR-0006: Renders child task results for planner join mode.

The authoritative source is the child task terminal event emitted by Trenni
(`supervisor.task.completed|failed|partial|cancelled|eval_failed`). Those
events already contain normalized semantic verdicts and execution traces, so
the continuation planner can reason over task outcomes rather than guessing
from raw job events.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yoitsu_contracts.config import EventStoreConfig, JobConfig


_TERMINAL_TASK_EVENT_TYPES = (
    "supervisor.task.completed",
    "supervisor.task.failed",
    "supervisor.task.partial",
    "supervisor.task.cancelled",
    "supervisor.task.eval_failed",
)

_TERMINAL_JOB_EVENT_TYPES = (
    "agent.job.completed",
    "agent.job.failed",
    "agent.job.cancelled",
    "supervisor.job.failed",
)


def join_context(
    *,
    job_config: JobConfig,
    eventstore: EventStoreConfig,
    **_,
) -> str:
    """Render join context with child task results.

    Args:
        job_config: JobConfig with join.child_task_ids
        eventstore: EventStoreConfig for querying pasloe

    Returns:
        Markdown-formatted join context with child task results.
    """
    join_cfg = getattr(job_config, "join", None)
    if join_cfg is None:
        join_cfg = getattr(getattr(job_config, "context", None), "join", None)
    if not join_cfg or not join_cfg.child_task_ids:
        return ""

    # Query pasloe for child task events
    base_url = eventstore.url or os.environ.get("PASLOE_URL", "http://127.0.0.1:8000")
    api_key_env = eventstore.api_key_env or "PASLOE_API_KEY"
    api_key = os.environ.get(api_key_env, "")

    results = _fetch_child_results(base_url, api_key, join_cfg.child_task_ids)

    if not results:
        return "## Child Tasks\nNo child task results available."

    parts = ["## Child Tasks\n\n"]

    for task_id in join_cfg.child_task_ids:
        result = results.get(task_id)
        if not result:
            parts.append(f"### {task_id} `unknown` ? unknown\n")
            parts.append("**Summary:**\nNo terminal result found for this child task.\n\n")
            continue

        status = result.get("status", "unknown")
        status_icon = _status_icon(status)
        role = result.get("role", "unknown")
        summary = result.get("summary", "")

        parts.append(f"### {task_id} `{role}` {status_icon} {status}\n")
        verdict = str(result.get("verdict", "")).strip()
        if verdict:
            parts.append(f"**Semantic verdict:** `{verdict}`\n")
        if summary:
            summary_text = _truncate(str(summary), 800)
            if len(str(summary)) > 800:
                summary_text += "\n... (truncated)"
            parts.append(f"**Summary:**\n{summary_text}\n")

        git_ref = result.get("git_ref")
        if git_ref:
            parts.append(f"**Git ref:** `{git_ref}`\n")

        criteria_results = result.get("criteria_results") or []
        if criteria_results:
            parts.append("**Criteria:**\n")
            for item in criteria_results[:5]:
                criterion = _truncate(str(item.get("criterion", "")).strip(), 140) or "(unnamed)"
                outcome = _truncate(str(item.get("result", "unknown")).strip(), 24) or "unknown"
                evidence = _truncate(str(item.get("evidence", "")).strip(), 220)
                if evidence:
                    parts.append(f"- [{outcome}] {criterion}: {evidence}\n")
                else:
                    parts.append(f"- [{outcome}] {criterion}\n")

        trace = result.get("trace") or []
        if trace:
            parts.append("**Trace:**\n")
            for entry in trace[:4]:
                trace_role = _truncate(str(entry.get("role", "unknown")).strip(), 40) or "unknown"
                trace_outcome = _truncate(str(entry.get("outcome", "unknown")).strip(), 24) or "unknown"
                trace_summary = _truncate(str(entry.get("summary", "")).strip(), 180)
                trace_git_ref = _truncate(str(entry.get("git_ref", "")).strip(), 120)
                line = f"- `{trace_role}` {trace_outcome}"
                if trace_summary:
                    line += f": {trace_summary}"
                if trace_git_ref:
                    line += f" (`{trace_git_ref}`)"
                parts.append(line + "\n")

        parts.append("\n")

    if join_cfg.parent_summary:
        parts.append("---\n\n")
        parts.append("## Original Goal\n\n")
        parts.append(join_cfg.parent_summary)

    return "".join(parts)


def _fetch_child_results(
    base_url: str,
    api_key: str,
    child_task_ids: list[str],
) -> dict[str, dict]:
    """Query Pasloe for child task terminal results."""
    results = _fetch_child_task_results(base_url, api_key, child_task_ids)

    missing = [task_id for task_id in child_task_ids if task_id not in results]
    if missing:
        results.update(_fetch_child_job_results(base_url, api_key, missing))
    return results


def _fetch_child_task_results(
    base_url: str,
    api_key: str,
    child_task_ids: list[str],
) -> dict[str, dict]:
    results: dict[str, dict] = {}
    headers = _request_headers(api_key)
    wanted = set(child_task_ids)

    for event_type in _TERMINAL_TASK_EVENT_TYPES:
        try:
            events = _fetch_events(base_url, headers, event_type=event_type, limit=200)
        except Exception:
            continue
        for event in events:
            data = event.get("data", {})
            task_id = str(data.get("task_id", "")).strip()
            if task_id not in wanted or task_id in results:
                continue
            results[task_id] = _task_result_from_event(event_type, data)
            if len(results) == len(wanted):
                return results

    return results


def _fetch_child_job_results(
    base_url: str,
    api_key: str,
    child_task_ids: list[str],
) -> dict[str, dict]:
    """Fallback for older/missing task terminal events.

    Job events are less authoritative than task events, but still better than
    leaving the join planner blind when a child result exists.
    """
    results: dict[str, dict] = {}
    headers = _request_headers(api_key)
    wanted = set(child_task_ids)

    for event_type in _TERMINAL_JOB_EVENT_TYPES:
        try:
            events = _fetch_events(base_url, headers, event_type=event_type, limit=200)
        except Exception:
            continue
        for event in events:
            data = event.get("data", {})
            task_id = str(data.get("task_id", "")).strip()
            if task_id not in wanted or task_id in results:
                continue
            results[task_id] = _job_result_from_event(event_type, data)
            if len(results) == len(wanted):
                return results

    return results


def _request_headers(api_key: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _fetch_events(
    base_url: str,
    headers: dict[str, str],
    *,
    event_type: str,
    limit: int,
) -> list[dict]:
    url = f"{base_url}/events?limit={limit}&order=desc&type={event_type}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def _task_result_from_event(event_type: str, data: dict) -> dict:
    result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
    semantic = result.get("semantic", {}) if isinstance(result.get("semantic"), dict) else {}
    trace = result.get("trace", []) if isinstance(result.get("trace"), list) else []

    summary = (
        str(data.get("summary") or "").strip()
        or str(data.get("reason") or "").strip()
        or str(semantic.get("summary") or "").strip()
    )
    git_ref = _latest_trace_git_ref(trace)
    role = _latest_trace_role(trace)
    verdict = str(semantic.get("verdict", "")).strip() or "unknown"
    criteria_results = [item for item in semantic.get("criteria_results", []) if isinstance(item, dict)]

    return {
        "status": _status_from_task_event_type(event_type),
        "role": role,
        "summary": summary,
        "git_ref": git_ref,
        "verdict": verdict,
        "criteria_results": criteria_results,
        "trace": [item for item in trace if isinstance(item, dict)],
    }


def _job_result_from_event(event_type: str, data: dict) -> dict:
    job_id = str(data.get("job_id", "")).strip()
    summary = (
        str(data.get("summary") or "").strip()
        or str(data.get("error") or "").strip()
        or str(data.get("reason") or "").strip()
    )

    return {
        "status": _status_from_job_event_type(event_type),
        "role": _extract_role(job_id),
        "summary": summary,
        "git_ref": str(data.get("git_ref") or "").strip(),
        "verdict": "",
        "criteria_results": [],
        "trace": [],
    }


def _status_from_task_event_type(event_type: str) -> str:
    return event_type.rsplit(".", 1)[-1]


def _status_from_job_event_type(event_type: str) -> str:
    mapping = {
        "agent.job.completed": "completed",
        "agent.job.failed": "failed",
        "agent.job.cancelled": "cancelled",
        "supervisor.job.failed": "failed",
    }
    return mapping.get(event_type, "unknown")


def _latest_trace_git_ref(trace: list[dict]) -> str:
    for entry in reversed(trace):
        git_ref = str(entry.get("git_ref", "")).strip()
        if git_ref:
            return git_ref
    return ""


def _latest_trace_role(trace: list[dict]) -> str:
    for entry in reversed(trace):
        role = str(entry.get("role", "")).strip()
        if role:
            return role
    return "unknown"


def _status_icon(status: str) -> str:
    return {
        "completed": "✓",
        "failed": "✗",
        "partial": "~",
        "cancelled": "-",
        "eval_failed": "!",
    }.get(status, "?")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def _extract_role(job_id: str) -> str:
    """Extract role from job_id pattern.

    Job IDs follow patterns like:
    - 069dfabc-root-cxyz-evaluator
    - 069dfabc/eval-evaluator
    The last segment after the final '-' or '/' is typically the role.
    """
    # Handle both dash and slash separators
    segments = job_id.replace("/", "-").split("-")
    for seg in reversed(segments):
        if seg in ("evaluator", "implementer", "optimizer", "worker", "planner", "reviewer"):
            return seg
    return segments[-1] if segments else "unknown"


# Mark as context provider for palimpsest resolve_context_functions
join_context.__is_context__ = True
join_context.__section_type__ = "join_context"
