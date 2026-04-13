"""Factorio bundle capabilities.

Per ADR-0018 Task 6: bundle-specific lifecycle enters capability model.
These capabilities handle Factorio runtime services (mod sync, RCON, etc.).

Status: PREPARATION for ADR-0019 authority split.
Actual migration of worker/implementer/evaluator roles blocked by ADR-0019.
"""

from .factorio_runtime import FactorioRuntimeCapability

BUNDLE_CAPABILITIES = {
    "factorio_runtime": FactorioRuntimeCapability(),
}