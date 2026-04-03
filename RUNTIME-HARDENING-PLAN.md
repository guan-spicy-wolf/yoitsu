# Runtime Hardening Plan

日期：2026-04-03
状态：待执行
范围：`trenni` / `palimpsest` / `yoitsu-contracts`

## 目标

把当前已简化的主链路变成足够稳定的执行面。

## 任务分解

### Task 1: Intake / Execution 分相隔离

**当前状态分析**:

- `supervisor.py` 混合了 intake (事件接收、spawn expansion) 和 execution (launch、cleanup) 逻辑
- intake 失败和 execution 失败的边界不够清晰

**动作**:
- 明确 intake path 只做事件验证和 spawn planning
- execution path 只做 runtime 操作
- 分离错误处理：intake 错误不影响已运行的 job，execution 错误有明确的 cleanup

### Task 2: Tool 子进程隔离与硬超时

**当前状态分析**:

- `palimpsest/runtime/tools.py` 中 `_normalize_spawn_task` 直接在进程内执行 git 操作
- 其他 builtin tools 也在进程内执行，没有隔离边界

**动作**:
- 评估当前 builtin tools 的风险等级
- 为高风险工具（如 spawn、git 操作）增加超时机制
- 为纯 Python 计算类工具增加硬超时

### Task 3: Budget 不变量补齐

**当前状态分析**:

- root task: TriggerData.budget 默认为 0.0，没有强制要求
- join job: spawn_handler 中 join job 使用 parent_job.budget，规则已固定
- replay: 刚修复了 budget 丢失问题

**动作**:
- root task budget 显式要求：可选，但如果有必须 > 0
- join job budget 继承规则已在代码中固定，验证即可
- replay budget 一致性：已修复，验证即可

### Task 4: 补齐回归测试

**当前状态**:

- supervisor.py 有测试但覆盖率不高
- replay 路径测试不完整
- cleanup 路径测试不完整

**动作**:
- 补齐 intake 失败场景测试
- 补齐 execution 失败场景测试
- 补齐 replay 路径测试
- 补齐 cleanup 路径测试

## 执行顺序

1. 先分析当前 intake/execution 边界
2. 再补齐 budget 不变量验证
3. 再补齐回归测试
4. 最后评估 tool 隔离需求

## 验收标准

- intake 失败与 execution 失败边界清晰且可测试
- budget 不再因入口、继承、重放路径发生漂移
- supervisor / replay / launch / cleanup 有足够的回归测试