#!/usr/bin/env bash
# smoke-planner.sh — Factorio planner 端到端冒烟测试
#
# 测试目标：验证 planner 角色能够正确加载 factorio/prompts/planner.md，
# 并通过 spawn 工具拆解任务、启动 evaluator 子任务（analysis-only，无需 Factorio 连接）。
#
# 用法:
#   ./scripts/smoke-planner.sh                          # 只提交任务
#   ./scripts/smoke-planner.sh --fresh                  # 清空数据 + 重部署 + 测试
#   ./scripts/smoke-planner.sh --fresh --rebuild-image  # 重建 job 镜像 + 清空 + 重部署 + 测试
#
# 前置条件:
#   PASLOE_API_KEY  已设置（或在 trenni.env 中）
#   TASK_TIMEOUT    等待超时秒数（默认 300）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

export BUNDLE="factorio"
export ROLE="planner"
export BUDGET="${BUDGET:-0.80}"
export TASK_TIMEOUT="${TASK_TIMEOUT:-300}"
export TAIL_ENABLED="${TAIL_ENABLED:-0}"

# Planner 专用 goal：纯分析任务，evaluator 无需 Factorio 游戏连接
export GOAL='Analyze the factorio bundle and report its current state.

Spawn a single evaluator job with the following goal:
"List all Lua scripts in scripts/ directory (relative to bundle root). For each file, print its filename and first line. If the directory is empty or does not exist, report that clearly."

Do not spawn any implementer or worker jobs. After the evaluator finishes, summarize its findings.'

# 不传 REPO/BRANCH，planner 作为 bundle 任务不操作外部仓库
export REPO=""
export BRANCH=""
export ROOT_REPO_CONTEXT="0"

# ── Bundle 控制平面引导 ───────────────────────────────────────────────
# 每次 Pasloe 清空后需要重新提交 bundle.control_plane.switched 事件，
# 否则 Trenni 会拒绝启动 factorio bundle 的 job。
# 从本地 bare clone 读取当前 evolve 分支的 HEAD SHA。
_bootstrap_bundle() {
  local pasloe_url="${PASLOE_URL:-http://127.0.0.1:8000}"
  local bundle_bare="$HOME/trenni/bundles/factorio.git"
  local api_key="${PASLOE_API_KEY:-}"

  if [[ -z "$api_key" ]]; then
    local env_file="$HOME/.config/containers/systemd/yoitsu/trenni.env"
    [[ -f "$env_file" ]] && api_key="$(sed -n 's/^PASLOE_API_KEY=//p' "$env_file" | tail -n1)"
  fi

  if [[ ! -d "$bundle_bare" ]]; then
    echo "[smoke-planner] WARN: bundle bare clone not found at $bundle_bare, skipping bootstrap" >&2
    return 0
  fi

  local sha
  sha="$(git -C "$bundle_bare" rev-parse "origin/evolve" 2>/dev/null \
       || git -C "$bundle_bare" rev-parse evolve 2>/dev/null \
       || git -C "$bundle_bare" rev-parse HEAD)"

  # Check if already bootstrapped with the CURRENT sha (order=desc → latest event first)
  existing="$(rtk proxy curl -sf -H "X-API-Key: $api_key" \
    "${pasloe_url}/events?limit=200&order=desc" 2>/dev/null \
    | python3 -c "
import sys, json
events = json.loads(sys.stdin.read())
for e in events:
    if e.get('type') == 'bundle.control_plane.switched' and e.get('data', {}).get('bundle') == 'factorio':
        print(e['data']['sha'])
        break
" 2>/dev/null || true)"

  if [[ "$existing" == "$sha" ]]; then
    echo "[smoke-planner] factorio control plane already bootstrapped (sha=${existing::12})" >&2
    return 0
  fi

  echo "[smoke-planner] bootstrapping factorio control plane (sha=${sha::12}, was=${existing::12})" >&2

  rtk proxy curl -sf -X POST "${pasloe_url}/events" \
    -H "X-API-Key: $api_key" \
    -H "Content-Type: application/json" \
    -d "{
      \"source_id\": \"smoke-planner\",
      \"type\": \"bundle.control_plane.switched\",
      \"data\": {
        \"bundle\": \"factorio\",
        \"sha\": \"$sha\",
        \"switched_by\": \"smoke-planner\",
        \"reason\": \"bootstrap after pasloe data reset\"
      }
    }" >/dev/null

  echo "[smoke-planner] bootstrap event submitted, waiting for Trenni to pick up..." >&2
  sleep 5
}

# Bootstrap runs AFTER smoke-spawn-monitor.sh's --fresh reset (if applicable)
# For --fresh: handle reset ourselves, then bootstrap, then submit via smoke-spawn-monitor.sh (no --fresh)
if [[ "$*" == *--fresh* ]]; then
  # Parse args to extract flags
  FRESH_MODE=1
  REBUILD_MODE=0
  for arg in "$@"; do
    [[ "$arg" == "--rebuild-image" ]] && REBUILD_MODE=1
  done

  echo "[smoke-planner] fresh reset mode"
  bash "$SCRIPT_DIR/cleanup-test-data.sh" --skip-backup
  if [[ "$REBUILD_MODE" == "1" ]]; then
    echo "[smoke-planner] rebuilding job image"
    bash "$SCRIPT_DIR/build-job-image.sh"
  fi
  echo "[smoke-planner] redeploying quadlet services"
  bash "$SCRIPT_DIR/deploy-quadlet.sh" --skip-build

  # Wait for services
  echo "[smoke-planner] waiting for services"
  for i in {1..30}; do
    if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1 && \
       curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1; then
      echo "[smoke-planner] services ready"
      break
    fi
    sleep 2
  done

  # Bootstrap AFTER reset
  _bootstrap_bundle

  # Submit task via smoke-spawn-monitor.sh (without --fresh)
  exec bash "$SCRIPT_DIR/smoke-spawn-monitor.sh"
fi

# Non-fresh case: bootstrap first, then run smoke test
_bootstrap_bundle
exec bash "$SCRIPT_DIR/smoke-spawn-monitor.sh" "$@"
