"""Planner role: analyzes tasks and spawns child jobs.

Per ADR-0019: output_authority="analysis" — read-only, spawns children but no direct output.
Per ADR-0018: uses capability-only lifecycle (needs=[]).
Uses spawn tool to create implementer/evaluator/optimizer child jobs.
"""
from __future__ import annotations

from palimpsest.runtime.roles import JobSpec, context_spec, role


@role(
    name="planner",
    description="Factorio bundle planner (analyzes tasks and spawns child roles)",
    role_type="planner",
    min_cost=0.1,
    recommended_cost=0.3,
    max_cost=0.5,
    needs=[],  # ADR-0018: analysis role, no capability needs
    output_authority="analysis",  # ADR-0019: read-only, spawns children
)
def planner(**params) -> JobSpec:
    """Factorio planner role definition.

    Per ADR-0018/0019:
    - output_authority="analysis": read-only role, spawns children
    - needs=[]: no capability setup/finalize
    - Runner provides ephemeral workspace (cwd irrelevant for planner)
    - Uses spawn tool to create child jobs:
      - implementer: for code changes (output_authority="live_runtime")
      - evaluator: for review (output_authority="analysis")
      - optimizer: for tool evolution (output_authority="analysis")
      - worker: for in-game execution (output_authority="live_runtime", needs=["factorio_runtime"])
    - No git publication (spawn decisions in summary)
    """
    return JobSpec(
        context_fn=context_spec(
            system="factorio/prompts/planner.md",
            sections=[],  # Planner doesn't need script listing
        ),
        tools=["spawn"],  # Spawn tool for child job creation
    )
