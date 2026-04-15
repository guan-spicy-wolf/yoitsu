import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "palimpsest"))
sys.path.insert(0, str(ROOT / "yoitsu-contracts" / "src"))

from yoitsu_contracts.config import EventStoreConfig, JobConfig, JobContextConfig, JoinContextConfig

from evo.factorio.contexts.join_context import join_context
from evo.factorio.roles.planner import planner


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _job_config(*child_task_ids: str) -> JobConfig:
    return JobConfig(
        job_id="job-join",
        goal="Parent goal",
        role="planner",
        context=JobContextConfig(
            join=JoinContextConfig(
                parent_task_id="root-task",
                parent_summary="Parent goal",
                child_task_ids=list(child_task_ids),
            )
        ),
    )


def test_factorio_planner_switches_context_by_mode():
    assert (ROOT / "evo/factorio/prompts/planner.md").is_file()
    assert (ROOT / "evo/factorio/prompts/planner-join.md").is_file()

    initial = planner()
    initial_context = initial.context_fn(goal="plan work")
    assert initial_context["system"] == "prompts/planner.md"
    assert initial_context["sections"] == []
    assert initial.tools == ["spawn"]

    continuation = planner(mode="join")
    join_context_spec = continuation.context_fn(goal="plan work")
    assert join_context_spec["system"] == "prompts/planner-join.md"
    assert join_context_spec["sections"] == [{"type": "join_context"}]
    assert continuation.tools == ["spawn"]


def test_factorio_join_context_is_registered_provider():
    assert join_context.__is_context__ is True
    assert join_context.__section_type__ == "join_context"


def test_factorio_join_context_prefers_task_terminal_events(monkeypatch):
    payloads = {
        "supervisor.task.completed": [
            {
                "data": {
                    "task_id": "root-task/a1",
                    "summary": "Child task completed",
                    "result": {
                        "semantic": {
                            "verdict": "pass",
                            "summary": "Semantic pass",
                            "criteria_results": [
                                {
                                    "criterion": "All scripts enumerated",
                                    "result": "pass",
                                    "evidence": "Reported every Lua file",
                                }
                            ],
                        },
                        "trace": [
                            {
                                "job_id": "root-task-root-ca1-implementer",
                                "role": "implementer",
                                "outcome": "success",
                                "summary": "Enumerated scripts",
                                "git_ref": "branch:abc123",
                            }
                        ],
                    },
                }
            }
        ]
    }

    def fake_urlopen(req, timeout=10):
        url = req.full_url
        event_type = url.split("type=", 1)[1]
        return _FakeResponse(payloads.get(event_type, []))

    monkeypatch.setattr("evo.factorio.contexts.join_context.urllib.request.urlopen", fake_urlopen)

    text = join_context(
        job_config=_job_config("root-task/a1"),
        eventstore=EventStoreConfig(url="http://pasloe.test", api_key_env="PASLOE_API_KEY"),
    )

    assert "root-task/a1 `implementer` ✓ completed" in text
    assert "**Semantic verdict:** `pass`" in text
    assert "All scripts enumerated" in text
    assert "branch:abc123" in text
    assert "Parent goal" in text


def test_factorio_join_context_falls_back_to_job_terminal_events(monkeypatch):
    payloads = {
        "agent.job.failed": [
            {
                "data": {
                    "task_id": "root-task/b2",
                    "job_id": "root-task-root-cb2-evaluator",
                    "error": "Eval failed",
                }
            }
        ]
    }

    def fake_urlopen(req, timeout=10):
        url = req.full_url
        event_type = url.split("type=", 1)[1]
        return _FakeResponse(payloads.get(event_type, []))

    monkeypatch.setattr("evo.factorio.contexts.join_context.urllib.request.urlopen", fake_urlopen)

    text = join_context(
        job_config=_job_config("root-task/b2"),
        eventstore=EventStoreConfig(url="http://pasloe.test", api_key_env="PASLOE_API_KEY"),
    )

    assert "root-task/b2 `evaluator` ✗ failed" in text
    assert "Eval failed" in text
