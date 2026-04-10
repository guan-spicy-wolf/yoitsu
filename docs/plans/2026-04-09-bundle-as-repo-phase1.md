# Bundle-as-Repo Phase 1: Hard Cutover

> **REQUIRED SUB-SKILL:** Use the executing-plans skill to implement this plan task-by-task.

**Goal:** Replace `evo_root` bind-mount with per-job bundle workspace materialized from registered git repositories. **No legacy mode, hard cutover.**

**Architecture:**
- Each bundle is a registered git repo with `source.url` and `source.selector`
- Trenni resolves selector to commit SHA, materializes workspace, mounts into container
- Palimpsest loads roles/tools/contexts from bundle root (no `factorio/` prefix)
- `bundle_source` is **required** for all jobs; `evo_sha` is ignored

**Tech Stack:** Python, Pydantic, GitPython, Podman volumes

---

## Path Contract (Single Mode)

| Entity | Path Type | Example | Purpose |
|--------|-----------|---------|---------|
| BundleSourceResolver | Host | `/tmp/yoitsu-source-factorio-abc` | Materialize on host |
| Volume mount | Host→Container | `(host, /opt/yoitsu/palimpsest/bundle, False)` | Podman bind mount |
| JobConfig.bundle_source | Container | `/opt/yoitsu/palimpsest/bundle` | Palimpsest reads in container |
| Bundle internal paths | Bundle-relative | `prompts/worker.md` | Roles in bundle repo |

**No legacy mode. No dual-mode resolution. No path rewriting at runtime.**

---

## Phase 1A: Contracts Layer

### Task 1: Add BundleSource to yoitsu-contracts

**TDD scenario:** New feature — full TDD cycle

**Files:**
- Create: `yoitsu-contracts/tests/test_bundle_source.py`
- Modify: `yoitsu-contracts/src/yoitsu_contracts/config.py`

**Step 1: Write the failing test**

```python
# yoitsu-contracts/tests/test_bundle_source.py
"""Tests for BundleSource per ADR-0015."""
import pytest
from yoitsu_contracts.config import BundleSource


def test_bundle_source_required_fields():
    source = BundleSource(
        name="factorio",
        repo_uri="git+file:///home/holo/bundles/factorio.git",
        selector="evolve",
        resolved_ref="a1b2c3d4e5f6",
        source_workspace="/opt/yoitsu/palimpsest/bundle",
    )
    assert source.name == "factorio"
    assert source.can_modify_bundle == False
    assert source.job_workspace is None


def test_bundle_source_with_job_workspace():
    source = BundleSource(
        name="factorio",
        repo_uri="git+file:///home/holo/bundles/factorio.git",
        selector="evolve",
        resolved_ref="a1b2c3d4e5f6",
        source_workspace="/opt/yoitsu/palimpsest/bundle",
        can_modify_bundle=True,
        job_workspace="/opt/yoitsu/palimpsest/workspace",
    )
    assert source.can_modify_bundle == True
```

**Step 2-4: Implement and verify**

```python
# yoitsu-contracts/src/yoitsu_contracts/config.py
from pydantic import BaseModel, Field

class BundleSource(BaseModel):
    """Bundle identity and materialization state. Per ADR-0015 §2.7.
    
    source_workspace and job_workspace are container-visible paths.
    """
    name: str = Field(min_length=1)
    repo_uri: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    resolved_ref: str = Field(min_length=1)
    source_workspace: str = Field(min_length=1)
    can_modify_bundle: bool = False
    job_workspace: str | None = None
```

**Step 5: Commit**

```bash
cd yoitsu-contracts && git add tests/test_bundle_source.py src/yoitsu_contracts/config.py
git commit -m "feat(contracts): add BundleSource per ADR-0015"
```

---

### Task 2: Add bundle_source to JobConfig, deprecate evo_sha

**TDD scenario:** Modifying tested code

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/config.py` (JobConfig)

**Step 1: Add bundle_source field**

```python
# yoitsu-contracts/src/yoitsu_contracts/config.py

class JobConfig(BaseModel):
    # ... existing fields ...
    evo_sha: str = ""  # DEPRECATED - ignored in bundle-source mode
    bundle_source: BundleSource | None = None  # NEW per ADR-0015
    # ... rest of fields ...
```

**Step 2: Run existing tests**

Run: `cd yoitsu-contracts && pytest tests/ -v`
Expected: PASS

**Step 3: Commit**

```bash
cd yoitsu-contracts && git add src/yoitsu_contracts/config.py
git commit -m "feat(contracts): add bundle_source to JobConfig, deprecate evo_sha"
```

---

### Task 3: Add can_modify_bundle to RoleMetadata

**TDD scenario:** New feature

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/role_metadata.py`
- Modify: `yoitsu-contracts/tests/test_role_metadata.py`

**Step 1: Write test**

```python
# yoitsu-contracts/tests/test_role_metadata.py

def test_role_metadata_can_modify_bundle():
    from yoitsu_contracts.role_metadata import RoleMetadata
    
    meta = RoleMetadata(
        name="implementer",
        description="writes to bundle",
        can_modify_bundle=True,
    )
    assert meta.can_modify_bundle == True
    
    meta2 = RoleMetadata(name="worker", description="reads only")
    assert meta2.can_modify_bundle == False  # default
```

**Step 2: Implement**

```python
# yoitsu-contracts/src/yoitsu_contracts/role_metadata.py

class RoleMetadata(BaseModel):
    name: str
    description: str
    teams: list[str] = Field(default_factory=list)  # Deprecated
    role_type: str = "worker"
    min_cost: float = 0.0
    recommended_cost: float = 0.0
    max_cost: float = 10.0
    min_capability: str = ""
    can_modify_bundle: bool = False  # NEW: role declares write permission
```

**Step 3: Commit**

```bash
cd yoitsu-contracts && git add src/yoitsu_contracts/role_metadata.py tests/test_role_metadata.py
git commit -m "feat(contracts): add can_modify_bundle to RoleMetadata"
```

---

## Phase 1B: Trenni Configuration

### Task 4: Add BundleSourceConfig to trenni config

**Files:**
- Create: `trenni/tests/test_bundle_source_config.py`
- Modify: `trenni/trenni/config.py`

**Step 1: Write test**

```python
# trenni/tests/test_bundle_source_config.py

def test_bundle_source_config():
    from trenni.config import BundleSourceConfig, BundleConfig
    
    source = BundleSourceConfig.from_dict({
        "url": "git+file:///path/to/bundle.git",
        "selector": "evolve",
    })
    assert source.url == "git+file:///path/to/bundle.git"
    
    bundle = BundleConfig.from_dict({
        "source": {"url": "git+file:///test.git"},
    })
    assert bundle.source.url == "git+file:///test.git"
```

**Step 2: Implement**

```python
# trenni/trenni/config.py

@dataclass
class BundleSourceConfig:
    url: str = ""
    selector: str = "main"
    
    @classmethod
    def from_dict(cls, data: dict | None) -> "BundleSourceConfig":
        payload = data or {}
        return cls(
            url=payload.get("url", ""),
            selector=payload.get("selector", "main"),
        )


@dataclass
class BundleConfig:
    source: BundleSourceConfig = field(default_factory=BundleSourceConfig)
    runtime: BundleRuntimeConfig = field(default_factory=BundleRuntimeConfig)
    scheduling: BundleSchedulingConfig = field(default_factory=BundleSchedulingConfig)
    
    @classmethod
    def from_dict(cls, data: dict | None) -> "BundleConfig":
        payload = data or {}
        return cls(
            source=BundleSourceConfig.from_dict(payload.get("source")),
            runtime=BundleRuntimeConfig.from_dict(payload.get("runtime")),
            scheduling=BundleSchedulingConfig.from_dict(payload.get("scheduling")),
        )
```

**Step 3: Commit**

```bash
cd trenni && git add tests/test_bundle_source_config.py trenni/config.py
git commit -m "feat(trenni): add BundleSourceConfig per ADR-0015"
```

---

### Task 5: Create BundleSourceResolver

**Files:**
- Create: `trenni/tests/test_bundle_resolver.py`
- Create: `trenni/trenni/bundle_resolver.py`

**Step 1: Write test**

```python
# trenni/tests/test_bundle_resolver.py

import subprocess
import tempfile
from pathlib import Path
from trenni.bundle_resolver import BundleSourceResolver


def test_resolve_and_materialize():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test repo
        repo = Path(tmpdir) / "bundle"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
        (repo / "test.txt").write_text("content")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
        
        resolver = BundleSourceResolver()
        sha = resolver.resolve_selector(f"git+file://{repo}", "master")
        assert len(sha) == 40
        
        workspace = resolver.materialize_source_workspace(f"git+file://{repo}", sha, "test")
        assert (Path(workspace) / "test.txt").read_text() == "content"
        
        resolver.reclaim_workspace(workspace)
        assert not Path(workspace).exists()
```

**Step 2: Implement**

```python
# trenni/trenni/bundle_resolver.py
"""Bundle source resolver - materializes workspaces from git repos."""
import subprocess
import shutil
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class BundleSourceResolver:
    """Materializes bundle workspaces from git repositories."""
    
    def resolve_selector(self, repo_uri: str, selector: str) -> str:
        """Resolve branch/tag selector to commit SHA."""
        git_uri = repo_uri.replace("git+", "")
        
        # Try branch
        result = subprocess.run(
            ["git", "ls-remote", git_uri, f"refs/heads/{selector}"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\t")[0]
        
        # Try tag
        result = subprocess.run(
            ["git", "ls-remote", git_uri, f"refs/tags/{selector}"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\t")[0]
        
        raise ValueError(f"Could not resolve selector '{selector}' for {repo_uri}")
    
    def materialize_source_workspace(self, repo_uri: str, resolved_ref: str, bundle_name: str) -> str:
        """Create RO workspace at resolved ref. Returns host path."""
        git_uri = repo_uri.replace("git+", "")
        workspace = tempfile.mkdtemp(prefix=f"yoitsu-source-{bundle_name}-")
        
        subprocess.run(["git", "clone", "--no-checkout", git_uri, workspace], capture_output=True, check=True)
        subprocess.run(["git", "-C", workspace, "checkout", resolved_ref], capture_output=True, check=True)
        
        logger.info(f"Materialized source workspace for {bundle_name} at {resolved_ref[:8]}")
        return workspace
    
    def materialize_job_workspace(self, repo_uri: str, selector: str, bundle_name: str) -> str:
        """Create RW workspace on branch. Returns host path."""
        git_uri = repo_uri.replace("git+", "")
        workspace = tempfile.mkdtemp(prefix=f"yoitsu-job-{bundle_name}-")
        
        subprocess.run(["git", "clone", git_uri, workspace], capture_output=True, check=True)
        subprocess.run(["git", "-C", workspace, "checkout", selector], capture_output=True, check=True)
        
        logger.info(f"Materialized job workspace for {bundle_name} on {selector}")
        return workspace
    
    def reclaim_workspace(self, workspace_path: str | None) -> None:
        """Reclaim workspace directory."""
        if workspace_path and Path(workspace_path).exists():
            shutil.rmtree(workspace_path, ignore_errors=True)
            logger.info(f"Reclaimed workspace: {workspace_path}")
```

**Step 3: Commit**

```bash
cd trenni && git add tests/test_bundle_resolver.py trenni/bundle_resolver.py
git commit -m "feat(trenni): add BundleSourceResolver per ADR-0015"
```

---

### Task 6: RuntimeBuilder path translation

**Files:**
- Modify: `trenni/trenni/runtime_builder.py`
- Modify: `trenni/tests/test_runtime_builder.py`

**Key change**: Host paths for volume mounts, container paths for JobConfig.

```python
# trenni/trenni/runtime_builder.py

CONTAINER_BUNDLE_PATH = "/opt/yoitsu/palimpsest/bundle"
CONTAINER_WORKSPACE_PATH = "/opt/yoitsu/palimpsest/workspace"


class RuntimeSpecBuilder:
    def __init__(self, config: TrenniConfig, defaults: RuntimeDefaults) -> None:
        self.config = config
        self.defaults = defaults
        self._host_workspaces: dict[str, dict[str, str | None]] = {}
    
    def get_host_workspaces(self, job_id: str) -> dict[str, str | None] | None:
        return self._host_workspaces.get(job_id)
    
    def clear_host_workspaces(self, job_id: str) -> None:
        self._host_workspaces.pop(job_id, None)
    
    def build(
        self,
        *,
        job_id: str,
        # ... existing params ...
        bundle_source: BundleSource | None = None,
        host_source_workspace: str | None = None,
        host_job_workspace: str | None = None,
    ) -> JobRuntimeSpec:
        
        volume_mounts: list[tuple[str, str, bool]] = []
        
        if bundle_source and host_source_workspace:
            volume_mounts.append((host_source_workspace, CONTAINER_BUNDLE_PATH, False))
            if bundle_source.can_modify_bundle and host_job_workspace:
                volume_mounts.append((host_job_workspace, CONTAINER_WORKSPACE_PATH, True))
            
            self._host_workspaces[job_id] = {
                "source_workspace": host_source_workspace,
                "job_workspace": host_job_workspace,
            }
        
        # Build JobConfig with container paths
        job_config_dict = {
            "job_id": job_id,
            # ... other fields ...
            "bundle_source": bundle_source.model_dump(mode="json") if bundle_source else None,
        }
        
        # ... rest of build logic ...
```

**Commit:**

```bash
cd trenni && git add tests/test_runtime_builder.py trenni/runtime_builder.py
git commit -m "feat(trenni): path translation - host for mounts, container for JobConfig"
```

---

### Task 7: Supervisor bundle resolution with cleanup

**Files:**
- Modify: `trenni/trenni/supervisor.py`
- Modify: `trenni/trenni/state.py`
- Modify: `trenni/trenni/spawn_handler.py`

**Step 1: Add can_modify_bundle to SpawnedJob**

```python
# trenni/trenni/state.py

@dataclass
class SpawnedJob:
    # ... existing fields ...
    can_modify_bundle: bool = False
    
    # Update to_enqueued_data, to_launched_data, from_enqueued_data
```

**Step 2: Read can_modify_bundle from RoleMetadata in Supervisor**

```python
# trenni/trenni/supervisor.py

# In _process_trigger (~line 470), when creating root_job:

# Read can_modify_bundle from role metadata
can_modify_bundle = False
if bundle and bundle in self.config.bundles:
    # Need to load role metadata from bundle
    # For Phase 1, check role name (simpler)
    if role == "implementer":
        can_modify_bundle = True

root_job = SpawnedJob(
    # ... existing fields ...
    can_modify_bundle=can_modify_bundle,
)
```

```python
# trenni/trenni/spawn_handler.py

# In expand(), when creating child SpawnedJob (~line 143):

can_modify_bundle = role == "implementer"  # Same rule as supervisor

jobs.append(SpawnedJob(
    # ... existing fields ...
    can_modify_bundle=can_modify_bundle,
))
```

**Step 3: Bundle resolution in _launch_from_spawned with exception cleanup**

```python
# trenni/trenni/supervisor.py

CONTAINER_BUNDLE_PATH = "/opt/yoitsu/palimpsest/bundle"
CONTAINER_WORKSPACE_PATH = "/opt/yoitsu/palimpsest/workspace"


class Supervisor:
    def __init__(self, config: TrenniConfig) -> None:
        # ... existing init ...
        self._bundle_workspaces: dict[str, dict] = {}
    
    async def _launch_from_spawned(self, job: SpawnedJob) -> None:
        bundle_source = None
        host_source = None
        host_job = None
        resolver = None
        
        if job.bundle and job.bundle in self.config.bundles:
            bundle_cfg = self.config.bundles[job.bundle]
            if bundle_cfg.source.url:
                from .bundle_resolver import BundleSourceResolver
                from yoitsu_contracts.config import BundleSource
                
                resolver = BundleSourceResolver()
                
                try:
                    resolved_ref = resolver.resolve_selector(
                        bundle_cfg.source.url,
                        bundle_cfg.source.selector
                    )
                    host_source = resolver.materialize_source_workspace(
                        bundle_cfg.source.url, resolved_ref, job.bundle
                    )
                    
                    if job.can_modify_bundle:
                        host_job = resolver.materialize_job_workspace(
                            bundle_cfg.source.url, bundle_cfg.source.selector, job.bundle
                        )
                    
                    bundle_source = BundleSource(
                        name=job.bundle,
                        repo_uri=bundle_cfg.source.url,
                        selector=bundle_cfg.source.selector,
                        resolved_ref=resolved_ref,
                        source_workspace=CONTAINER_BUNDLE_PATH,
                        can_modify_bundle=job.can_modify_bundle,
                        job_workspace=CONTAINER_WORKSPACE_PATH if host_job else None,
                    )
                except Exception as e:
                    logger.error(f"Bundle resolution failed: {e}")
                    if resolver:
                        resolver.reclaim_workspace(host_source)
                        resolver.reclaim_workspace(host_job)
                    raise
        
        try:
            await self._launch(
                # ... existing params ...
                bundle_source=bundle_source,
                host_source_workspace=host_source,
                host_job_workspace=host_job,
            )
        except Exception:
            if resolver:
                resolver.reclaim_workspace(host_source)
                resolver.reclaim_workspace(host_job)
            raise
```

**Step 4: Cleanup after job completion**

```python
# In _handle_job_done:

workspaces = self.runtime_builder.get_host_workspaces(job_id)
if workspaces:
    resolver = BundleSourceResolver()
    resolver.reclaim_workspace(workspaces.get("source_workspace"))
    resolver.reclaim_workspace(workspaces.get("job_workspace"))
    self.runtime_builder.clear_host_workspaces(job_id)
```

**Commit:**

```bash
cd trenni && git add trenni/state.py trenni/supervisor.py trenni/spawn_handler.py
git commit -m "feat(trenni): bundle resolution with exception-safe cleanup"
```

---

## Phase 1C: Palimpsest Bundle-Root Loading

### Task 8: Update all loaders for bundle-root mode

**Files:**
- Modify: `palimpsest/palimpsest/runtime/roles.py`
- Modify: `palimpsest/palimpsest/runtime/tools.py`
- Modify: `palimpsest/palimpsest/runtime/contexts.py`

**Step 1: RoleManager - bundle="" means root**

```python
# palimpsest/palimpsest/runtime/roles.py

def __init__(self, evo_root: str | Path, bundle: str = "") -> None:
    super().__init__(evo_root)
    self._bundle = bundle
    # bundle="" means evo_root is bundle root, roles at evo_root/roles/
    # bundle="factorio" (not used in hard cutover) would be evo_root/factorio/roles/
    if bundle:
        self._bundle_roles_dir = self._root / bundle / "roles"
    else:
        self._bundle_roles_dir = self._root / "roles"
```

**Step 2: Tool loader - same pattern**

```python
# palimpsest/palimpsest/runtime/tools.py

def resolve_tool_functions(evo_root: Path, bundle: str, requested: list[str]) -> dict[str, Callable]:
    if bundle:
        bundle_tools_dir = evo_root / bundle / "tools"
    else:
        bundle_tools_dir = evo_root / "tools"
    # ... scan bundle_tools_dir ...
```

**Step 3: Context loader - same pattern**

```python
# palimpsest/palimpsest/runtime/contexts.py

def resolve_context_functions(evo_root: str | Path, requested: list[str], bundle: str = "") -> dict[str, Callable]:
    if bundle:
        bundle_dir = Path(evo_root) / bundle / "contexts"
    else:
        bundle_dir = Path(evo_root) / "contexts"
    # ... scan bundle_dir ...
```

**Commit:**

```bash
cd palimpsest && git add palimpsest/runtime/roles.py palimpsest/runtime/tools.py palimpsest/runtime/contexts.py
git commit -m "fix(palimpsest): all loaders use bundle-root mode (bundle='' = root)"
```

---

### Task 9: Update runner - require bundle_source, pass bundle=""

**Files:**
- Modify: `palimpsest/palimpsest/runner.py`
- Modify: `palimpsest/palimpsest/stages/context.py`

**Step 1: run_job hard cutover**

```python
# palimpsest/palimpsest/runner.py

def run_job(config: JobConfig) -> None:
    """Execute the four-stage pipeline.
    
    Per ADR-0015: bundle_source is required. evo_sha is ignored.
    """
    if not config.bundle_source:
        raise ValueError("bundle_source is required per ADR-0015")
    
    evo_path = Path(config.bundle_source.source_workspace)
    resolved_evo_sha = config.bundle_source.resolved_ref
    
    # Add bundle root to sys.path for imports
    evo_path_str = str(evo_path)
    if evo_path_str not in sys.path:
        sys.path.insert(0, evo_path_str)
    
    # Bundle-root mode: load from root, bundle=""
    resolver = RoleManager(evo_path, bundle="")
    spec = resolver.resolve(config.role, **dict(config.role_params or {}))
    
    _run_job_from_spec(
        config, spec, evo_path,
        resolved_evo_sha=resolved_evo_sha,
    )
```

**Step 2: Pass bundle="" to all loaders**

```python
# In _run_job_from_spec:

def _run_job_from_spec(config: JobConfig, spec: JobSpec, evo_path: Path, *, resolved_evo_sha: str | None = None):
    # ... setup ...
    
    # Context - bundle="" for bundle-root mode
    context_spec = spec.context_fn(
        workspace=workspace,
        job_id=job_id,
        goal=config.goal,
        job_config=config,
        evo_root=str(evo_path),
        **role_params,
    )
    context = build_context(
        job_id, workspace, config.goal, context_spec, config, gateway,
        evo_root=evo_path,
        bundle="",  # Bundle-root mode
    )
    
    # Tools - bundle="" for bundle-root mode
    tools = _setup_tools(config, spec, evo_path, evo_sha, gateway, bundle="")
    
    # ...
```

**Step 3: build_context accepts bundle parameter**

```python
# palimpsest/palimpsest/stages/context.py

def build_context(
    job_id: str,
    workspace_path: str,
    task: str,
    context_spec: dict,
    job_config: JobConfig,
    gateway: EventGateway,
    evo_root: Path | None = None,
    bundle: str = "",
) -> dict:
    # ...
    registry = {}
    if evo_root:
        registry = resolve_context_functions(evo_root, section_types, bundle=bundle)
    # ...
```

**Commit:**

```bash
cd palimpsest && git add palimpsest/runner.py palimpsest/stages/context.py
git commit -m "feat(palimpsest): hard cutover to bundle_source, pass bundle='' to loaders"
```

---

## Phase 1D: Bundle Internal Path Migration

### Task 10: Migrate Factorio bundle to bundle-root paths

**Files:**
- Modify: `evo/factorio/lib/preparation.py`
- Modify: `evo/factorio/contexts/factorio_scripts.py`
- Modify: `evo/factorio/roles/worker.py`
- Modify: `evo/factorio/roles/implementer.py`
- Modify: `evo/factorio/roles/evaluator.py`

**Step 1: Fix imports**

```python
# evo/factorio/lib/preparation.py
# OLD: from factorio.lib.rcon import RCONClient
# NEW: from lib.rcon import RCONClient
from lib.rcon import RCONClient
```

**Step 2: Fix paths in preparation.py**

```python
# evo/factorio/lib/preparation.py
# OLD: src = Path(evo_root) / "factorio" / "scripts"
# NEW: src = Path(evo_root) / "scripts"
src = Path(evo_root) / "scripts"
```

**Step 3: Fix paths in factorio_scripts.py**

```python
# evo/factorio/contexts/factorio_scripts.py
# OLD: scripts_dir = Path(evo_root) / "factorio" / "scripts"
# NEW: scripts_dir = Path(evo_root) / "scripts"
scripts_dir = Path(evo_root) / "scripts"
```

**Step 4: Fix prompt paths in roles**

```python
# evo/factorio/roles/worker.py
# OLD: system="factorio/prompts/worker.md"
# NEW: system="prompts/worker.md"

# evo/factorio/roles/implementer.py
# OLD: system="factorio/prompts/implementer.md"
# NEW: system="prompts/implementer.md"

# evo/factorio/roles/evaluator.py
# OLD: system="factorio/prompts/evaluator.md"
# NEW: system="prompts/evaluator.md"
```

**Commit:**

```bash
cd evo/factorio && git add lib/preparation.py contexts/factorio_scripts.py roles/*.py
git commit -m "refactor(factorio): migrate to bundle-root paths per ADR-0015"
```

---

### Task 11: Update implementer preparation for bundle_workspace

**Files:**
- Modify: `evo/factorio/lib/preparation.py`
- Modify: `palimpsest/palimpsest/runner.py`

**Step 1: Update prepare_evo_workspace_override**

```python
# evo/factorio/lib/preparation.py

def prepare_evo_workspace_override(
    *,
    bundle_workspace: str,  # Required: writable workspace
    **kwargs
) -> WorkspaceConfig:
    """Use writable bundle workspace for implementer.
    
    Per ADR-0015: bundle_workspace is the RW mount for modifications.
    No evo_root fallback - hard cutover.
    """
    return WorkspaceConfig(repo="", new_branch=False, workspace_override=bundle_workspace)
```

**Step 2: Pass bundle_workspace from runner**

```python
# palimpsest/palimpsest/runner.py
# In _run_job_from_spec, when calling preparation_fn:

prep_params = {
    "goal": config.goal,
    "repo": config.workspace.repo,
    "init_branch": config.workspace.init_branch,
    **role_params,
}

prep_sig = inspect.signature(spec.preparation_fn)

if "runtime_context" in prep_sig.parameters:
    prep_params["runtime_context"] = runtime_context

if "evo_root" in prep_sig.parameters:
    prep_params["evo_root"] = str(evo_path)

# NEW: pass bundle_workspace for implementer roles
if "bundle_workspace" in prep_sig.parameters:
    if config.bundle_source and config.bundle_source.job_workspace:
        prep_params["bundle_workspace"] = config.bundle_source.job_workspace
    else:
        raise ValueError("bundle_workspace required for this role but not available")

workspace_cfg = spec.preparation_fn(**prep_params)
```

**Commit:**

```bash
cd palimpsest && git add palimpsest/runner.py
cd evo/factorio && git add lib/preparation.py
git commit -m "feat: implementer uses bundle_workspace for writes"
```

---

### Task 12: Add can_modify_bundle to factorio roles

**Files:**
- Modify: `evo/factorio/roles/implementer.py`

**Step 1: Add can_modify_bundle=True to implementer**

```python
# evo/factorio/roles/implementer.py

@role(
    name="implementer",
    description="Factorio bundle implementer (writes lua)",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.5,
    can_modify_bundle=True,  # NEW: implementer needs write permission
)
def implementer(**params) -> JobSpec:
    # ...
```

**Commit:**

```bash
cd evo/factorio && git add roles/implementer.py
git commit -m "feat(factorio): implementer declares can_modify_bundle=True"
```

---

## Phase 1E: Hallucination Gate

### Task 13: Add hallucination gate to publication

**Files:**
- Modify: `palimpsest/tests/test_publication.py`
- Modify: `palimpsest/palimpsest/stages/publication.py`

```python
# palimpsest/palimpsest/stages/publication.py

def publish_results(...) -> tuple[str | None, list[ArtifactBinding]]:
    # ... existing setup ...
    
    repo.git.add("-A")
    
    # Hallucination gate
    result = subprocess.run(
        ["git", "-C", workspace_path, "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if result.returncode == 0:
        raise PublicationGuardrailViolation([
            "Hallucination gate: no staged changes after git add -A",
            "Agent must modify files before publication.",
        ])
    
    # ... rest unchanged ...
```

**Commit:**

```bash
cd palimpsest && git add tests/test_publication.py palimpsest/stages/publication.py
git commit -m "feat(palimpsest): add hallucination gate per ADR-0015"
```

---

## Phase 1F: Finalization

### Task 14: Skip cleanup for bundle workspaces

**Files:**
- Modify: `palimpsest/palimpsest/stages/finalization.py`
- Modify: `palimpsest/palimpsest/runner.py`

```python
# palimpsest/palimpsest/stages/finalization.py

def finalize_workspace_after_job(
    workspace_path: str,
    gateway: EventGateway | None = None,
    *,
    is_bundle_workspace: bool = False,
) -> str | None:
    """Cleanup for sandbox jobs.
    
    Per ADR-0015: Trenni-managed bundle workspaces are not cleaned by Palimpsest.
    """
    if is_bundle_workspace:
        logger.info(f"Skipping cleanup for Trenni-managed workspace: {workspace_path}")
        return None
    
    # ... existing cleanup logic ...
```

```python
# palimpsest/palimpsest/runner.py
# In finally block:

finally:
    if 'runtime_context' in locals():
        runtime_context.cleanup()
    if workspace:
        finalize_workspace_after_job(
            workspace,
            gateway=gateway,
            is_bundle_workspace=bool(config.bundle_source),
        )
    gateway.close()
```

**Commit:**

```bash
cd palimpsest && git add palimpsest/stages/finalization.py palimpsest/runner.py
git commit -m "fix(palimpsest): skip cleanup for bundle workspaces"
```

---

## Phase 1G: Create Factorio Bundle Repo

### Task 15: Initialize factorio-bundle.git repository

**Steps:**

```bash
# Create bundle repo
mkdir -p /home/holo/bundles
cd /home/holo/bundles
git init factorio-bundle.git
cd factorio-bundle.git

# Copy content from evo/factorio (after Task 10 migration)
cp -r /home/holo/yoitsu/evo/factorio/roles .
cp -r /home/holo/yoitsu/evo/factorio/tools .
cp -r /home/holo/yoitsu/evo/factorio/contexts .
cp -r /home/holo/yoitsu/evo/factorio/prompts .
cp -r /home/holo/yoitsu/evo/factorio/scripts .
cp -r /home/holo/yoitsu/evo/factorio/lib .

git add -A
git commit -m "Initial factorio bundle per ADR-0015"
git checkout -b evolve
```

### Task 16: Update trenni.yaml

```yaml
# trenni.yaml
bundles:
  factorio:
    source:
      url: "git+file:///home/holo/bundles/factorio-bundle.git"
      selector: evolve
    runtime:
      image: "localhost/yoitsu-palimpsest-job:dev"
    scheduling:
      max_concurrent_jobs: 1
```

---

## Verification

```bash
cd /home/holo/yoitsu
pytest yoitsu-contracts/tests/ -v
pytest trenni/tests/ -v
pytest palimpsest/tests/ -v
```

---

## Success Criteria

Phase 1 complete when:

1. ✅ BundleSource with container paths in contracts
2. ✅ RoleMetadata.can_modify_bundle drives write permission
3. ✅ BundleSourceResolver materializes workspaces
4. ✅ RuntimeBuilder: host paths for mounts, container for JobConfig
5. ✅ Supervisor: exception-safe workspace cleanup
6. ✅ Palimpsest: bundle="" for all loaders
7. ✅ Bundle internal paths: `prompts/`, `scripts/` (no `factorio/` prefix)
8. ✅ Implementer uses `bundle_workspace` for writes
9. ✅ Hallucination gate blocks empty publication
10. ✅ Factorio bundle repo created and registered
11. ✅ All tests pass