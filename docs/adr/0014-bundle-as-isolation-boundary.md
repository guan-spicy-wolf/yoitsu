## 0014: Bundle 作为一等隔离边界（取代 Team 与全局层）

状态：Accepted（2026-04-07，Bundle MVP 已落地并生产验证）
取代：归档的 ADR-0011（"Team as First-Class Isolation Boundary"）
相关：ADR-0012（Factorio 任务源，术语需按本 ADR 修正）

## 1. 现状与存在的问题

ADR-0011 以来，系统用 "team" 作为角色/工具/上下文/调度的隔离边界，同时保留一个全局 `evo/roles`、`evo/tools`、`evo/contexts` 层作为公共回落。这个两层结构存在若干长期痛点：

- **语义混淆**：同一个名字的角色既可能来自 team 目录也可能来自全局层，测试与生产行为取决于文件布局而非显式声明。
- **隔离漏洞**：任何 bundle 都能隐式继承全局角色与工具，导致"默认路径"带来的耦合逐渐扩散，破坏了 ADR-0011 想要的硬边界。
- **术语与范畴错配**：实际投入使用的场景（factorio、multi-role evolution 等）已经不是传统意义上的"多团队协作"而是"一套独立的角色/工具/提示/调度策略"的捆绑，"team" 一词携带了不必要的组织学含义。
- **优化闭环需要稳定锚点**：自优化与观测事件聚合（Factorio Tool Evolution MVP、observation aggregator）需要一个统一的稳定标签来划分样本、预算、并发与生成物，team + 全局回落使样本归属不明确。

## 2. 做出的决策与原因

**决策**：将隔离边界重命名为 `bundle`，并把架构从"全局 + bundle 两层"简化为**纯 bundle 解析，无全局回落，无 team 层**。所有角色、工具、上下文、提示、调度约束都属于某个 bundle，且必须显式声明 bundle。

具体架构约束如下：

1. **目录结构唯一化**：`evo/<bundle>/{roles,tools,contexts,prompts,lib,scripts,evolved}/`。不存在 `evo/roles/` 等全局目录。`RoleManager` 的 `list_definitions/get_definition/resolve` 只扫描 `evo/<bundle>/roles/`，空或缺失的 bundle 返回空注册表而不是回落到全局（见 `palimpsest/palimpsest/runtime/roles.py` 的 `RoleManager`）。
2. **Bundle 必须显式**：bundle 是 envelope 级字段，不是业务参数；`params` dict 中出现 `role` 或 `bundle` 会被 schema 拒绝。解析侧（`RoleManager`、`resolve_context_functions`、`resolve_tool_functions`）不做任何"缺失即回落"的语义——空/缺失 bundle 返回空注册表，强制调用方显式声明所属 bundle。
3. **Trenni 配置与调度以 bundle 为单位**：`trenni/trenni/config.py` 中 `BundleConfig = BundleRuntimeConfig + BundleSchedulingConfig`，`TrenniConfig.bundles: dict[str, BundleConfig]` 取代原 `teams`。运行时字段包括 `image`、`pod_name`（使用 `_UNSET` sentinel 区分"未设置继承默认"/"显式 None 不加入 pod"/"显式字符串"三态）、`env_allowlist`、`extra_networks`。调度字段只有 `max_concurrent_jobs`。
4. **调度器 per-bundle 并发计数**：`SupervisorState.running_jobs_by_bundle` + `increment_bundle_running/decrement_bundle_running`；`BundleLaunchCondition(bundle, max_concurrent)` 在 `Scheduler` 发射前检查"实际在跑 + 本轮已虚拟占用"的并发，防止同 bundle 的多个 pending 任务在一个 tick 内被同时提升导致越限。`max_concurrent_jobs <= 0` 视为无上限。
5. **Runtime 合并语义**：`RuntimeSpecBuilder` 将 bundle 的 `image` 与 `pod_name` **覆盖**默认值；`env_allowlist` 采用**整表替换**而不是与默认列表合并——bundle 要想继承默认就必须把默认值显式列出。该选择优先考虑"bundle 完全自描述其运行时环境"，避免默认 allowlist 在不相关 bundle 中泄漏。
6. **Spawn 链上 bundle 必须传播**：spawn 链要求 bundle 作为一等字段持续传播；跨 bundle spawn 不属于本 ADR 的设计目标。观测事件（`ObservationToolRepetitionEvent`、`ObservationContextLateLookupEvent` 等）亦带 bundle 字段，使 observation aggregator 能按 bundle 做单维度归因。
7. **跨进程元数据统一**：`yoitsu-contracts` 的 `RoleMetadataReader` 接受 `bundle` 参数；trenni/palimpsest/contracts 三仓库使用同一套 bundle 语义，消除早期 team/global 混合期中各仓行为漂移的问题。

**原因**：

- **可预测性**：删除全局回落后，"这个角色从哪里来"只有一个答案，测试 fixture 与生产行为同构。
- **隔离强度**：bundle 成为真正的硬边界，让 ADR-0012 所需的 factorio 级长状态隔离不再依赖"大家约定不往全局层写东西"。
- **优化闭环基础**：observation 事件、预算、并发、生成物（`evolved/`）全部对齐到 bundle 维度，自优化循环能拿到干净的单一维度样本。
- **术语对齐**：bundle 更准确地描述"一整套即插即用的角色/工具/上下文/提示/调度"这一捆绑单位，避免沿用 "team" 导致的语义误导。

## 3. 期望达到的结果

- `evo/factorio` 成为首个完整 bundle 样例：其下同时提供 `roles/`（implementer、worker）、`tools/`（factorio_call_script）、`contexts/`（factorio_scripts、github_context）；不再依赖任何全局目录即可完成任务生命周期。
- Trenni 在重启后通过事件回放正确重建 `running_jobs_by_bundle`，bundle 并发限制与持久化状态一致。
- 所有测试以 bundle-only 语义书写（`test_state.py`、`test_scheduler.py`、palimpsest `test_roles.py` / `test_evo_tools.py` / `test_context.py` 等），对"空 bundle 返回空注册表"有断言，防止全局回落回潮。
- github_context 等早期挂在全局层的 provider 已迁入 `evo/factorio/contexts/`，不再有"临时放全局以后再搬"的中间态。

## 4. 容易混淆的概念

- **Bundle ≠ 团队 ≠ 项目**：bundle 是执行隔离单位，一个组织可以让多个 bundle 服务同一个"团队"，也可以让同一个 bundle 跑多个项目。
- **`env_allowlist` 替换而非合并**：新增一个环境变量时，要把默认 allowlist 的条目一并写进 bundle，否则会"静默丢失"默认允许项。这是刻意选择：宁可让 bundle 显式声明全部，也不要默认值跨 bundle 潜行。
- **`pod_name` 三态**：`_UNSET`（继承默认 pod）、`None`（显式不加入任何 pod）、字符串（显式 pod 名）。YAML 中"不写这个键"和"写 `pod_name: null`"语义不同。
- **"default" 不代表全局回落**：`default` 只是一个普通 bundle 名，若存在就必须以 `evo/default/` 的形式自备角色、工具等，不会从任何地方"捡"全局文件。是否、在哪些入口保留"未显式指定时使用内部默认 bundle"的兼容行为，属于实现层过渡细节，不是本 ADR 的决策范围。
- **bundle 参数不能写进 params**：spawn payload 里 `params.bundle` 会被 schema 拒绝；bundle 是 envelope 级字段，不是业务参数。

## 5. 对之前 ADR 或文档的修正说明

- **ADR-0011（已归档）**：被本 ADR 取代。"team as first-class isolation boundary" 中的 team 一律读作 bundle，"两层解析（team + global）"的描述作废，现行架构只有 bundle 一层。
- **ADR-0012（Factorio 任务源）**：其中"Factorio Team"、"`evo/teams/factorio/`"、"Team 最高并发度 = 1" 等表述按本 ADR 修正为"Factorio bundle"、"`evo/factorio/`"、"bundle `max_concurrent_jobs = 1`"。`BundleLaunchCondition` 提供 ADR-0012 所要求的"全局序列化执行锁"的实现基础。factorio bundle 的 `extra_networks: [factorio-net]` 以及独占 `call_script` 工具的要求仍然有效，只是承载它们的配置路径改为 `trenni` 配置中的 `bundles.factorio`。
- **ADR-0010（自优化治理）**：observation 事件现在带 bundle 字段，自优化闭环的样本聚合与生成物（`evolved/`）归属按 bundle 切分。原文若暗示"全局角色池"需理解为"各 bundle 自有角色池"。
