# Factorio Optimization Loop Closure - Smoke Test Runbook

**Date:** 2026-04-08
**Plan:** docs/plans/2026-04-07-factorio-optimization-loop-closure.md
**Status:** Code implementation complete (Task 1-4). Smoke test pending live Factorio server.

## Implementation Summary

### Commits

**Main repo:**
- `7e98419` config: serialize factorio bundle (max_concurrent_jobs=1) ahead of workspace_override rollout
- `37cde0e` feat(factorio): add bundle-specific optimizer role with evidence-aware prompt
- `670969e` feat(factorio): implementer writes to live bundle
- `ca0bb64` fix(factorio): simplify import path in implementer role
- `3e9c205` feat(factorio): worker preparation reloads bundle scripts into live mod

**Trenni:**
- `0d356fb` feat(trenni): route optimizer spawn by observation bundle and pass evidence

**Palimpsest:**
- `94a5141` feat(palimpsest): honor workspace_override in preparation/finalization

**Contracts:**
- `e456dda` feat(contracts): add WorkspaceConfig.workspace_override

### Key Changes

1. **Task 1:** Observation aggregator extracts evidence (latest 5 events), supervisor routes optimizer by bundle
2. **Task 2:** Factorio-specific optimizer role with evidence-aware prompt
3. **Task 3:** workspace_override mechanism for implementer to write directly to live bundle
4. **Task 4:** Worker preparation syncs bundle scripts to mod and triggers reload

## Smoke Test (Task 5)

**Prerequisites:**
- [ ] Factorio headless server running and accessible
- [ ] `FACTORIO_MOD_SCRIPTS_DIR` environment variable configured
- [ ] `FACTORIO_RCON_HOST`, `FACTORIO_RCON_PORT`, `FACTORIO_RCON_PASSWORD` set
- [ ] Trenni supervisor running
- [ ] Pasloe event store running

### Step 5.1: Prepare Task Input

```json
{
  "goal": "用挖矿机挖 50 个铁矿",
  "bundle": "factorio",
  "role": "worker"
}
```

### Step 5.2: First Round Execution

**Expected behavior:**
- Worker explores repeatedly using `find_ore_basic` or similar script
- Total steps: ~10-15
- `observation.tool_repetition` event emitted
- Aggregator triggers optimizer spawn with `bundle="factorio"`
- Optimizer outputs `improve_tool` proposal
- Implementer creates new script in `factorio/scripts/`

**Record results:**

| Metric | Expected | Actual |
|--------|----------|--------|
| Total steps | 10-15 | _TBD_ |
| tool_repetition triggered | Yes | _TBD_ |
| arg_pattern | find_ore_basic | _TBD_ |
| optimizer spawn bundle | factorio | _TBD_ |
| ReviewProposal action_type | improve_tool | _TBD_ |
| New script created | Yes | _TBD_ |

### Step 5.3: Verify New Script

```bash
ls -la evo/factorio/scripts/
```

**Expected:** New `.lua` file present, content resembles radius scan or resource detection.

### Step 5.4: Second Round Execution

Trigger same task again. Worker preparation should:
1. Sync bundle scripts to mod directory
2. Issue `/silent-command pcall(function() game.reload_script() end)`
3. Connect RCON
4. New script should be available

**Record results:**

| Metric | First Round | Second Round |
|--------|-------------|--------------|
| Total steps | _TBD_ | _TBD_ |
| Scripts used | find_ore_basic (repeated) | _TBD_ (should use new script) |

**Target:** Second round steps significantly lower (1-2 vs 10-15).

### Step 5.5: Runbook Archive

After completion, archive:
- First round trajectory
- Second round trajectory
- New script content
- Step comparison

## Environment Variables Required

```bash
export FACTORIO_MOD_SCRIPTS_DIR=/path/to/factorio/mod/scripts
export FACTORIO_RCON_HOST=localhost
export FACTORIO_RCON_PORT=27015
export FACTORIO_RCON_PASSWORD=your_password
```

## Notes

- The `game.reload_script()` command may not fully reload scripts with `require` caching
- Fallback: restart Factorio server between rounds
- If `factorio_call_script` mod has script whitelist, ensure new scripts are allowed

## Success Criteria

- [ ] Two rounds execute without manual intervention
- [ ] Step count reduction observed
- [ ] New script appears in bundle
- [ ] Evidence correctly routed to factorio optimizer