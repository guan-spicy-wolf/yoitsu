# Yoitsu Next Plan

日期：2026-04-03
状态：代码简化阶段已完成，进入下一执行阶段
范围：`yoitsu` / `yoitsu-contracts` / `trenni` / `palimpsest` / `pasloe`

## 1. 已完成前置

代码简化阶段已经完成，当前主链路已满足：

- canonical contract 已统一
- legacy 输入与 fallback 已清除
- 事件面已收紧
- 主链路字段搬运已明显收敛
- 三套运行环境已加载同一份 source contracts

下一步不再继续做“为了简化而简化”的改造，而是转向把架构文档里已经确定的能力真正闭环。

## 2. 总目标

下一阶段只做四类事：

1. 运行时硬化
2. 自观察闭环落地
3. 外部协作入口落地
4. Artifact Runtime 接管验证

## 3. 执行顺序

按下面顺序推进：

1. 先做 `Runtime Hardening`
2. 再做 `Observation Loop Closure`
3. 再做 `GitHub / External Trigger Integration`
4. 最后做 `Artifact Runtime Adoption`

原因：

- 运行时硬化会影响后续所有能力
- 自优化闭环依赖稳定的 observation 和查询面
- 外部触发和 reviewer 能力建立在前两者之上
- Artifact Runtime 是架构最终形态，但落地成本和影响面最大，应最后进入

## 4. Phase 1: Runtime Hardening ✅

已完成：

- ✅ Trenni intake / execution 分相隔离已清晰
  - intake 失败不影响已运行的 job
  - execution 失败有明确的 cleanup 机制
- ✅ Budget 不变量已补齐
  - budget >= 0 验证 (ge=0.0 constraint)
  - join job budget 继承规则已固定
  - replay budget 一致性已修复
- ✅ 回归测试已补齐
  - replay 测试使用 canonical 字段
  - intake/execution 失败场景有覆盖

## 5. Phase 2: Observation Loop Closure

目标：把 ADR-0010 里“结构化信号 -> Review Task -> Proposal -> 优化 Task”的闭环真正打通。

动作：

- 补齐并审视 `observation.*` 发射面，确保信号足够稳定
- 为 `Pasloe` 增加时间窗口与聚合查询接口，供 Review Task 读取
- 让 reviewer / review task 能直接消费 observation 聚合结果
- 激活基于阈值累积的 review trigger
- 为闭环建立 smoke test：
  - observation 累积
  - trigger 触发 review task
  - review task 读取聚合上下文

完成标志：

- review task 不再只是概念存在，而是真能由 observation 驱动产生
- system health 的核心代理指标是预算预测精度，而不是人工读日志

建议工单：

`observation-loop-closure`

## 6. Phase 3: GitHub / External Trigger Integration

目标：把系统从“手工提交任务”扩展为“能接外部协作事件并回写协作结果”。

动作：

- 实现统一 GitHub client，供 tools 与 context 共用
- 落地 PR 查询、评论读取、PR 创建后的后续动作接口
- 接入外部 trigger：
  - CI/CD failure
  - 带特定标签的 issue / PR 事件
- 落地 reviewer role 的 GitHub 上下文输入
- 评估自动 merge / approval 的安全边界，但默认先只做只读 + PR/评论写入

完成标志：

- 任务来源不再只有手工 YAML / raw goal
- reviewer 能基于真实 GitHub 上下文输出结构化审阅结果

建议工单：

`github-client-and-external-trigger-ingestion`

## 7. Phase 4: Artifact Runtime Adoption

目标：让 `Artifact Store` 从“contracts 与 backend 已存在”走到“runtime 主链路真的消费它”。

动作：

- 在 `Palimpsest` preparation 中接入 artifact copy-in / materialization
- 在 publication 中产出真实 `ArtifactBinding`
- 为非 Git 任务建立最小 smoke 路径
- 对 `blob/tree` 的 runtime 流转补齐端到端验证
- 用一个明确的非 Git 任务场景验证：
  - 报告/日志任务
  - 或 Factorio / 大文件状态类任务

完成标志：

- `git_ref` 退化为兼容收据，而不是唯一交付通道
- 非 Git 原生任务可以在不依赖 Git 的情况下完成输入物化与结果固化

建议工单：

`artifact-runtime-adoption`

## 8. 约束

- 不回退到兼容层思路
- 不为临时方便重新引入多套协议字段
- 不把实现细节再堆回主文档
- 新计划优先体现为代码、测试与 smoke path，不体现为文档扩写

## 9. 验收方式

每个 phase 完成时都应同时满足：

- 代码路径闭环
- 受影响测试通过
- 至少一条最小 smoke path 通过
- 当前行为能由代码与测试直接表达，而不是依赖额外说明
