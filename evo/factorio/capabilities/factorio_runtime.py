"""Factorio runtime capability.

Handles Factorio-specific runtime lifecycle:
- Mod script sync (setup)
- RCON connection management (setup)
- Cleanup (finalize)

Per ADR-0018 Task 6:
- This capability replaces the preparation logic in evo/factorio/lib/preparation.py
- Roles using this capability: worker (blocked by ADR-0019)

Status: PREPARATION - not yet integrated with runtime.
Requires ADR-0019 to determine authority model for live runtime modification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from yoitsu_contracts import FinalizeResult, EventData


class FactorioRuntimeCapability:
    """Factorio runtime service capability.
    
    Handles:
    - Mod script sync from bundle to live Factorio mod directory
    - RCON connection establishment
    - Cleanup of RCON connection
    
    Per Factorio Optimization Loop Closure MVP:
    - Worker role syncs scripts and uses RCON for in-game communication
    - Cleanup ensures RCON is properly closed
    """
    name = "factorio_runtime"
    
    def setup(self, ctx) -> list[EventData]:
        """Setup Factorio runtime environment.
        
        Effects:
        - Syncs bundle scripts to live Factorio mod
        - Reloads mod scripts
        - Connects RCON
        
        Returns:
            List of EventData for runtime to emit.
        """
        events = []
        
        # TODO: Implement after ADR-0019 authority determination
        # This is preparation for migration, not yet active
        
        events.append(EventData(type="factorio_runtime.setup_started", data={
            "bundle": ctx.bundle,
            "job_id": ctx.job_id,
        }))
        
        logger.warning(
            "FactorioRuntimeCapability.setup is not yet implemented. "
            "Requires ADR-0019 to determine authority model."
        )
        
        return events
    
    def finalize(self, ctx) -> FinalizeResult:
        """Finalize Factorio runtime.
        
        Effects:
        - Closes RCON connection
        - Logs completion
        
        Returns:
            FinalizeResult with events and success status.
        """
        events = []
        success = True
        
        # TODO: Implement after ADR-0019 authority determination
        
        events.append(EventData(type="factorio_runtime.finalize_completed", data={
            "bundle": ctx.bundle,
            "job_id": ctx.job_id,
        }))
        
        logger.warning(
            "FactorioRuntimeCapability.finalize is not yet implemented. "
            "Requires ADR-0019 to determine authority model."
        )
        
        return FinalizeResult(events=events, success=success)


# Design notes for future implementation:
#
# 1. Authority considerations (ADR-0019):
#    - Worker modifies live Factorio state (in-game via RCON)
#    - Implementer writes directly into bundle directory
#    - Evaluator validates bundle content
#    - Each may need different authority constraints
#
# 2. Setup logic (from prepare_factorio_runtime):
#    - Sync scripts: evo/factorio/scripts -> $FACTORIO_MOD_SCRIPTS_DIR
#    - Reload: /silent-command pcall(function() game.reload_script() end)
#    - RCON: connect with host/port/password from environment
#    - Store RCON in ctx.resources["rcon"]
#
# 3. Finalize logic:
#    - Close RCON connection (from ctx.resources["rcon"])
#    - No git publication (worker doesn't produce commits)
#
# 4. Integration with runtime:
#    - Add to palimpsest/runtime/capability.py BUILTIN_CAPABILITIES
#    - Or create bundle capability registration mechanism
#    - Roles can then use needs=["factorio_runtime"]