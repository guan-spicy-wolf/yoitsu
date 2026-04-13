"""Default optimizer role: analyzes observation patterns and outputs ReviewProposal.

Per ADR-0010 Autonomous Review Loop:
- Analyzes observation events (budget_variance, tool_retry, etc.)
- Outputs structured ReviewProposal JSON for optimization tasks
- No git workspace needed (analysis-only role)

Per ADR-0018 Capability-Only Role Lifecycle:
- needs=[] means no extra capability requirements
- No preparation_fn or publication_fn (unified lifecycle)
- Output goes via summary field in interaction result
"""
from __future__ import annotations

from typing import Any

from palimpsest.runtime.roles import JobSpec, context_spec, role


@role(
    name="optimizer",
    description="Analyzes observation patterns and outputs optimization proposals",
    role_type="optimizer",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.0,
    needs=[],  # ADR-0018: Explicit empty capability (analysis-only)
)
def optimizer(**params) -> JobSpec:
    """Default optimizer role definition.
    
    Per ADR-0010:
    - Receives observation context via role_params
    - Analyzes patterns and thresholds
    - Outputs ReviewProposal JSON in summary field
    - No capability needed (analysis-only role)
    
    Expected role_params:
        metric_type: The observation metric that triggered this analysis
        observation_count: Number of observations in window
        window_hours: Time window for observations
    """
    return JobSpec(
        context_fn=context_spec(
            system="default/prompts/optimizer.md",
            sections=[],  # No additional sections needed
        ),
        tools=[],  # No special tools needed, just LLM analysis
    )