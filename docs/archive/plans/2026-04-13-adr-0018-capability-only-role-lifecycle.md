# ADR-0018 Capability-Only Role Lifecycle Implementation Plan

**Goal:** 落实 [ADR-0018](/home/holo/yoitsu/docs/adr/0018-capability-only-role-lifecycle.md)，让 capability 成为 role 的唯一 lifecycle 模型；`needs=[]` 不再表示 legacy fallback；runtime 不再识别和执行 role 私有的 preparation/publication 协议。

**Architecture:** 分三层收敛：
1. **Runtime contract 收敛**：所有 job 都走统一的 `setup -> context -> agent loop -> finalize` 生命周期，不再按 `needs` 决定是否回退到旧路径。
2. **Role contract 收敛**：role 不再用 `preparation_fn` / `publication_fn` / `publication_strategy` / `workspace_override` 定义执行模型。
3. **Migration close-out**：生产 role 全部迁到 capability 路径后，删除 legacy 字段、helper、分支和文档兼容叙述。

**Tech Stack:** `palimpsest`, `trenni`, `yoitsu-contracts`, `evo/*` role definitions, runtime tests

## Scope

本计划只覆盖 ADR-0018 的 lifecycle 收敛，不做以下决策：

- 不决定某个 role 属于 repo-authoring 还是 live-runtime authority；这属于 ADR-0019
- 不重做 `/jobs`、TUI 或 terminal projection 语义；这属于 ADR-0020
- 不重做 planner task-level publication 语义；ADR-0006 保持独立
- 不重写非 lifecycle 的 role 表达方式；`context_fn` / prompt 组织方式不是本计划主线

## Non-goals

- 不在本计划内把 Factorio bundle 的业务语义一次性重构完
- 不在本计划内引入新的通用 capability DSL
- 不在本计划内顺手修所有历史 smoke；只保留能验证 lifecycle 收敛的最小 smoke

## Cutover Strategy

本计划采用**一次性硬切换**，不设计渐进 rollout、运行时开关或长期兼容窗口。

- 本文中的 Phase 是**开发与验证顺序**，不是线上分阶段启用策略
- 在彻底完成并验证通过之前，不把 capability-only lifecycle 当成已交付状态
- 一旦进入最终切换提交，legacy lifecycle path 直接删除，不保留可回退的运行时分支
- 切换后的问题处理策略是 forward fix，而不是恢复双轨制

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Factorio roles 的 authority 划分拖延 | Task 6 及最终 close-out 受阻 | 先完成 Task 4 的简单角色迁移与 runtime 单路径收敛，把 authority 歧义 role 明确列为 blocked by ADR-0019 |
| 空 capability role 语义不清 | Task 1 容易把 `needs=[]` 重新实现成另一种 fallback | 在 Task 1 的测试里明确“空集 = 无额外 capability 需求”，而不是“未定义 role lifecycle” |
| legacy helper 仍有隐性引用 | Task 8 删除不彻底，硬切换后留下死角 | 在进入 Phase 3 前完成 role surface 盘点与零引用校验，并把相关 grep/validation 固化为可重复检查 |
| builtin capability 职责边界不清 | 迁移后仍把 legacy publication 语义偷偷包进 capability | 在 Task 5 明确 capability 的职责边界，并用测试覆盖“负责什么 / 不再负责什么” |

## Preconditions

0018 的 runtime 收敛可以先做，但以下角色的“最终迁移完成”依赖 ADR-0019 的 authority 划分：

- `evo/factorio/roles/implementer.py`
- `evo/factorio/roles/worker.py`
- `evo/factorio/roles/evaluator.py`

原因：这些 role 当前混杂 repo 修改、live runtime 影响和 evaluator 语义；不能在 authority 未定的情况下机械迁移到 capability-only。

---

## Phase 1: Make the Runtime Lifecycle Single-Path

### Task 1: 定义并测试统一 lifecycle 入口

**目标:** `runner` 不再以 `bool(needs)` 决定是否走 legacy publication/preparation 路径。所有 role 都经过同一条 lifecycle 主路径。

**Files:**
- Modify: `palimpsest/palimpsest/runner.py`
- Test: `palimpsest/tests/test_capability.py`
- Test: `palimpsest/tests/test_runner_runtime_events.py`

**Steps:**

- [ ] 1.1 先写回归测试，明确以下行为：
  - `needs=[]` 的 role 仍走统一 lifecycle，而不是 `_stage_interaction_and_publication`
  - `needs=["git_workspace"]` 的 role 继续走 capability path
  - finalize 阶段的 success/failure 决定 job terminal event，不依赖 legacy publication
- [ ] 1.2 收敛 `runner.py` 的主流程，只保留一条 lifecycle：
  - 统一使用现有 `JobContext` 进行 wiring
  - 统一执行 capability setup
  - 统一运行 interaction
  - 统一执行 capability finalize
- [ ] 1.3 删除 `needs` 作为“切换执行模型”的语义，只保留它作为 capability 集合本身
- [ ] 1.4 让空 capability 集成为合法、正常的一等路径
- [ ] 1.5 跑 `palimpsest` 相关 lifecycle/runner 测试，确保无 capability role 与有 capability role 都通过

**完成标志:** `runner.py` 中不再存在“如果 `needs` 为空就走另一套 job 执行模型”的主分支。

---

### Task 2: 建立统一 workspace contract

**目标:** 所有 job 都拥有单一的 execution workspace contract；runtime 不再通过 legacy preparation helper 偷偷为某些 role 建立另一套工作目录语义。

**Files:**
- Modify: `yoitsu-contracts` 中 job/workspace 相关 contract 定义
- Modify: `trenni` job dispatch / workspace materialization 路径
- Modify: `palimpsest/palimpsest/runner.py`
- Test: `trenni` / `palimpsest` workspace 相关测试

**Steps:**

- [ ] 2.1 定义统一原则：每个 job 都有一个 runtime 提供的 execution workspace
- [ ] 2.2 区分“workspace existence”和“repo publication”：
  - workspace 是 job 基本执行面
  - `git_workspace` capability 决定该 workspace 是否承载 repo publish 语义
- [ ] 2.3 让 repoless / analysis-only role 也能在统一 workspace contract 下执行
- [ ] 2.4 去掉 legacy path 对 `setup_workspace(...)` 的隐式依赖
- [ ] 2.5 回归验证：
  - analysis-only role 能在无 capability 下执行
  - repo role 能在有 `git_workspace` 时执行并进入 finalize

**完成标志:** workspace 不再是 legacy fallback 的副产品，而是所有 job 的统一基础 contract。

---

## Phase 2: Migrate Role Definitions Off Legacy Lifecycle Hooks

### Task 3: 盘点并冻结 legacy role surface

**目标:** 在删除 legacy 字段前，先把当前生产角色的使用点盘清楚，并阻止新增使用。

**Files:**
- Modify: role resolution / validation tests
- Possibly modify: `palimpsest/palimpsest/runtime/roles.py`
- Document: role migration checklist

**Steps:**

- [ ] 3.1 列出所有仍使用以下字段的生产 role：
  - `preparation_fn`
  - `publication_fn`
  - `__publication_strategy__`
  - `workspace_override`
- [ ] 3.2 给 role loader/validation 增加迁移期约束：
  - 不允许新增 legacy lifecycle 用法
  - 已知存量 role 必须显式进入迁移清单
- [ ] 3.3 为每个现存 role 标记迁移目标：
  - empty capability set
  - builtin capability
  - bundle capability
  - blocked by ADR-0019 authority split

**完成标志:** 存量 legacy role 有完整清单，且仓库不再悄悄引入新的 legacy lifecycle 用法。

---

### Task 4: 迁移不含 authority 歧义的角色

**目标:** 先迁最简单的角色，证明 capability-only lifecycle 可落地，而不是一上来卡死在 Factorio 语义混合点上。

**Files:**
- Modify: `evo/default/roles/optimizer.py`
- Modify: 其他 analysis-only / planner-like role
- Test: role resolution + runner tests

**Steps:**

- [ ] 4.1 先迁 analysis-only / planner-like role（首批清单）：
  - `evo/default/roles/optimizer.py`
  - 其他不承载 authority 歧义、可被明确归为 read-only / analysis 的 role
- [ ] 4.2 对首批清单逐个迁移：
  - 取消 role 私有 publication/preparation 生命周期钩子
  - 保留空 capability 集
- [ ] 4.3 验证空 capability role 在统一 lifecycle 下可运行、可完成、不会触发 fallback
- [ ] 4.4 梳理 planner/evaluator 中哪些属于 read-only role，可按同样方式迁移
- [ ] 4.5 为每类简单双角色补一条最小 smoke 或 integration test

**完成标志:** 至少有一类生产 role 完全不依赖 legacy lifecycle hooks，且不靠 fallback 运行。

---

### Task 5: 为 repo-authoring role 收敛到 builtin capability

**目标:** 仓库型 role 不再依赖 role 私有 publication 语义，而是显式依赖 builtin capability。

**Files:**
- Modify: `palimpsest/palimpsest/runtime/capability.py`
- Modify: repo-authoring roles
- Test: capability finalize / publication tests

**Steps:**

- [ ] 5.1 明确 `git_workspace` 的单一职责：
  - 它负责 target repo workspace 的持久化 lifecycle
  - 它不再负责解释 role 私有的 publication 策略，也不再充当 legacy publication 的包装层
- [ ] 5.2 把原先由 `publication_fn` 驱动的 repo publish 语义迁入 builtin capability
- [ ] 5.3 确认 repo role 的成功/失败来自 capability finalize 结果，而不是 role 私有配置
- [ ] 5.4 保留最小测试矩阵：
  - 有修改并成功 finalize
  - 无修改但仍属正常 terminal path
  - finalize 失败导致 job failed

**完成标志:** repo publish 语义不再由 role 私有 publication hook 定义。

---

### Task 6: 迁移 bundle-specific lifecycle 到 bundle capability

**目标:** 对需要 bundle runtime 服务的角色，生命周期语义进入 bundle capability，而不是继续留在 role hook 或共享 helper 里。

**Files:**
- Modify/Create: bundle `capabilities/`
- Modify: bundle roles currently using preparation helpers
- Test: bundle integration tests

**Steps:**

- [ ] 6.1 识别哪些 preparation/finalization 逻辑其实是 bundle capability，而不是 role 差异
- [ ] 6.2 把共享 lifecycle 行为从 role helper 中抽到 capability
- [ ] 6.3 对存在 authority 歧义的 role，先标记为 blocked by ADR-0019，不机械迁移
- [ ] 6.4 authority 明确后，再把剩余角色迁到 capability-only

**完成标志:** “共享 runtime 服务”不再躲在 role helper / lib 里，而是进入 capability。

---

## Phase Gate: Phase 2 -> Phase 3

进入 Phase 3（删除 legacy contract 与 dead code）前，必须同时满足：

1. 所有生产 role 已迁移，或已明确标记为 blocked by ADR-0019
2. Task 9 的 V1-V4 验收项对应的前置验证已经通过
3. 不再存在已知 open bug 依赖 legacy lifecycle path 才能规避
4. role surface 盘点已经确认 legacy 字段只剩待删除引用，而不是仍在承载生产语义

不满足以上条件时，不进入硬切换清理阶段。

---

## Phase 3: Remove Legacy Contract and Dead Code

### Task 7: 删除 role-level lifecycle contract

**目标:** 一旦存量角色迁完，删除 legacy surface，而不是永远保留兼容。

**Files:**
- Modify: `palimpsest/palimpsest/runtime/roles.py`
- Modify: `yoitsu-contracts` role/job spec definitions
- Delete/Archive: legacy tests and helpers

**Steps:**

- [ ] 7.1 从 role/job spec 中删除或禁用以下 lifecycle 字段：
  - `preparation_fn`
  - `publication_fn`
- [ ] 7.2 删除与 `publication_strategy`、`branch_prefix`、`workspace_override` 相关的 role/runtime 合同
- [ ] 7.3 让 role validation 对 legacy lifecycle 字段直接报错，而不是 fallback
- [ ] 7.4 清理与 legacy contract 一起存在的 dead tests / fixtures

**完成标志:** 代码层面已无法定义一个靠 legacy lifecycle hooks 运行的 role。

---

### Task 8: 删除 legacy execution helpers

**目标:** legacy helper 与 branch 不只是不再调用，而是从系统中清除，避免概念回流。

**Files:**
- Modify/Delete: `palimpsest/palimpsest/stages/publication.py`
- Modify/Delete: legacy workspace/preparation helpers
- Modify: runtime docs and comments

**Steps:**

- [ ] 8.1 删除 `_stage_interaction_and_publication` 及其调用链
- [ ] 8.2 删除只服务于 role-level publication/preparation 的 helper
- [ ] 8.3 清理引用 legacy contract 的注释、docstring、兼容分支说明
- [ ] 8.4 把“无 legacy path / 无 legacy lifecycle 字段”的检查固化为可重复运行的 validation 或 CI 检查，而不是一次性手工 grep

**完成标志:** runtime 中不再保留“旧路径虽然不用了但还能走”的隐藏入口。

---

## Phase 4: Validate and Close Out

### Task 9: 建立最小验收矩阵

**目标:** 用最少但足够硬的验证，确认 0018 真的完成，而不是只做了代码搬运。

**Validation matrix:**

- [ ] V1 空 capability role：可执行、可完成、无 fallback
- [ ] V2 builtin capability role：setup/finalize 均经过统一 lifecycle
- [ ] V3 repo role：通过 `git_workspace` capability 完成持久化语义
- [ ] V4 bundle runtime role：在 authority 明确后，通过 bundle capability 完成 lifecycle
- [ ] V5 grep/validation：生产 role 中不再出现 `preparation_fn` / `publication_fn` / `__publication_strategy__`
- [ ] V6 runtime code：不存在按 `needs` 选择 legacy path 的执行分支

**完成标志:** 0018 的完成判断可由上述矩阵直接验证，不再靠“理解代码的人觉得已经差不多”。

---

## Sequencing

建议执行顺序：

1. Task 1-2：先把 runtime lifecycle 收敛成单路径
2. Task 3-5：先迁简单角色和 builtin capability
3. Task 6：处理 bundle capability；authority 不清的角色等待 ADR-0019
4. Task 7-8：删除 legacy contract 和 dead code
5. Task 9：做最小验收与收尾

## Completion Criteria

ADR-0018 视为完成，当且仅当：

1. runtime 不再按 `needs` 在 capability path 与 legacy path 之间二选一
2. 生产 role 不再通过 role-level lifecycle hooks 定义执行模型
3. builtin / bundle capability 承担全部 setup/finalize 责任
4. legacy lifecycle contract 在代码层面已不可用，而不是“约定上不要再用”
5. 空 capability role 作为统一 lifecycle 的正常特例稳定工作

## Deferred Follow-ups

以下事项不阻塞 0018 完成，但完成后应分别处理：

- ADR-0019：authority-aware role split 与 smoke 重分层
- ADR-0020：job terminal projection / `/jobs` 可观测性收敛
- role 非 lifecycle surface 的进一步声明式化
