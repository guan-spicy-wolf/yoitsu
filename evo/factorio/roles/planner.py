"""Planner role: analyzes tasks and spawns child jobs.

Per ADR-0019: output_authority="analysis" — read-only, spawns children but no direct output.
Per ADR-0018: uses capability-only lifecycle (needs=[]).
Uses spawn tool to create implementer/evaluator/optimizer child jobs.

Per ADR-0006: In join mode (after children complete), uses join_context to
decide whether goal is achieved or needs follow-up work.
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

    Per ADR-0006:
    - In join mode (mode="join" in role_params), uses join_context to assess child results
    - Uses planner-join.md prompt with join_context section
    """
    mode = params.get("mode", "")

    if mode == "join":
        # Join mode: continuation planner after children complete
        # Uses join_context section to receive child task results
        return JobSpec(
            context_fn=context_spec(
                system="prompts/planner-join.md",
                sections=[{"type": "join_context"}],
            ),
            tools=["spawn"],  # Can spawn follow-up tasks if needed
        )
    else:
        # Initial planning mode
        return JobSpec(
            context_fn=context_spec(
                system="prompts/planner.md",
                sections=[],  # Planner doesn't need script listing
            ),
            tools=["spawn"],  # Spawn tool for child job creation
        )
