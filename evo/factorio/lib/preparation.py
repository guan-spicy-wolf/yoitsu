"""Reusable preparation building blocks for Factorio bundle.

Each function returns a WorkspaceConfig (or operates on runtime_context as a side effect).
Roles compose these in their own preparation_fn. Future plan: replace per-role
preparation_fn with a list of these building blocks.
"""
from __future__ import annotations

from palimpsest.config import WorkspaceConfig


def prepare_evo_workspace_override(*, evo_root: str, **kwargs) -> WorkspaceConfig:
    """Make the live evo_root the agent's workspace.
    
    Used by implementer-style roles that should write directly into the bundle.
    Caller is responsible for ensuring serialization (factorio bundle has a serial lock).
    
    Args:
        evo_root: Path to the evo root directory.
        
    Returns:
        WorkspaceConfig with workspace_override set to evo_root.
    """
    return WorkspaceConfig(repo="", new_branch=False, workspace_override=evo_root)