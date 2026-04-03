# Yoitsu Code Simplification Plan

日期：2026-04-03
状态：第一步已完成，进入第二步
范围：`yoitsu` / `yoitsu-contracts` / `trenni` / `palimpsest`

## 1. 当前状态

第一步 `spawn-contract-cutover-without-compatibility` 已通过。

已完成结果：

- `Spawn / Trigger / CLI / runtime / tests` 已统一到 canonical contract
- 只认：`goal / role / budget / repo / init_branch / team / params / eval_spec / sha`
- 已移除并拒绝 legacy 输入：`prompt / task / repo_url / branch / context / params.repo / params.branch / params.init_branch`
- `goal` 与 `role` 已收紧为必填并 fail-fast
- `params` 只允许 role 内部参数，不再承载任务语义
- `yoitsu` / `trenni` / `palimpsest` 三套环境已实际加载同一份 source `yoitsu-contracts`

## 2. 下一目标

下一步只做两件事：

1. `Event Surface Pruning`
2. `Runtime Object Collapse`

建议工单名：

`event-surface-pruning-and-runtime-object-collapse`

## 3. Phase A: Event Surface Pruning

目标：把事件面压到“真实、最小、稳定”。

动作：

- 收紧 `SupervisorJobLaunchedData`
- 收紧 `SupervisorJobEnqueuedData`
- 清理 replay、control API、CLI、tests 中仍依赖旧事件外形的代码
- 删除不被消费、只增加搬运成本的冗余字段
- 统一关键事件的命名和字段语义，避免同一事实在不同事件里重复换名

完成标志：

- 启动/入队事件只保留当前运行时真正需要和真正消费的字段
- replay 与 live path 消费的是同一套事件形状
- CLI/控制面不再依赖 ad hoc dict 字段猜测

## 4. Phase B: Runtime Object Collapse

目标：减少核心链路中的重复对象和字段搬运。

动作：

- 审视并压缩这几个对象之间的重复：
  - `TaskRecord`
  - `SpawnedJob`
  - `SpawnDefaults`
  - `JobConfig`
  - `SupervisorJobLaunchedData`
  - `SupervisorJobEnqueuedData`
- 明确唯一的“任务语义 -> 运行时规格”转换边界
- 尽量把重复赋值收敛到一个 builder / translator，而不是散落在 `supervisor`、`spawn_handler`、`runtime_builder` 多处
- 清理只为中转存在、但不增加表达力的字段

完成标志：

- `goal / role / repo / init_branch / team / evo_sha / budget` 不再跨多个对象重复散射搬运
- `Supervisor` 主链路里的字段转换层级显著变浅
- `runtime_builder` 成为清晰、单一的运行时规格出口

## 5. 约束

- 不回退到兼容写法
- 不为了保留历史 payload 而新增 fallback
- 不扩写说明性文档，能在代码里表达的就留在代码里
- 归档历史讨论，不把历史重新带回主路径

## 6. 验收标准

完成这一步后，应满足：

- 关键 supervisor 事件的字段数量下降，但信息密度更高
- replay / enqueue / launch / runtime build 的主链路对象更少
- 搜索主代码路径时，明显减少重复字段搬运与重复赋值
- 三仓受影响测试通过
- 最小运行时校验通过：导入的 contracts、事件 schema、runtime path 保持一致

## 7. 执行顺序

按下面顺序推进：

1. 先改事件模型
2. 再改事件消费者与 replay
3. 再折叠运行时对象边界
4. 最后统一测试和最小运行时验证
