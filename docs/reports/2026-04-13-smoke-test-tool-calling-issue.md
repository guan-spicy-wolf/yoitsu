# 冒烟测试 Tool Calling 问题分析报告

**日期**: 2026-04-13  
**状态**: 问题已定位，部分修复完成

## 问题现象

冒烟测试任务 (`smoke-spawn-monitor.sh`) 执行时，implementer 子任务显示 `completed`，但：
1. `smoke/SMOKE.txt` 文件仍然为空
2. 目标未达成

日志显示：
```
LLM returned no tool calls; requesting idle confirmation
LLM remained idle after confirmation; ending loop
No changes detected, publication skipped
```

## 调查过程

### 1. 发现大量 optimizer 任务

最初观察到 8+ 个 optimizer 任务在运行，干扰了冒烟测试的观察。这些是系统自动触发的 pattern 分析任务（`budget_variance`, `tool_repetition:bash`）。

**解决方案**: 修改 `deploy/quadlet/trenni.dev.yaml`，提高 observation thresholds：
```yaml
observation_thresholds:
  budget_variance: 999.0  # effectively disabled
  tool_repetition: 999.0  # effectively disabled
  tool_retry: 999.0
  context_late_lookup: 999.0
```

### 2. LLM 模型配置问题

发现实际使用的模型是 `glm-5`（在 `deploy/quadlet/trenni.dev.yaml`），而不是 `kimi-k2.5`（`config/trenni.yaml`）。

部署流程使用的是 `deploy/quadlet/trenni.dev.yaml`，该文件被复制到容器的 `/etc/yoitsu/trenni.yaml`。

**历史变化**：
- `209e449` (Mar 23): 使用 `gpt-5.2-codex`
- `0eb265b` (Mar 28): 改成 `glm-5`

### 3. GLM-5 Tool Calling 格式问题

日志显示：
```
Tool bash raised: [Errno 2] No such file or directory: ''
Tool bash raised: UnifiedToolGateway.__init__.<locals>.bash_with_config() got an unexpected keyword argument 'config'
```

**原因分析**：GLM-5 通过 DashScope API 返回的 tool call 参数格式问题：
1. 有时返回空的 `command` 参数
2. 有时返回不应该存在的 `config` 参数

### 4. Bash 工具 Schema 问题

检查 `palimpsest/runtime/tools.py` 发现：

```python
@tool
def bash(command: str, workspace: str, config: ToolsConfig | None = None) -> ToolResult:
```

生成的 schema 包含 `config` 参数：
```json
{
  "type": "function",
  "function": {
    "name": "bash",
    "parameters": {
      "properties": {
        "command": {"type": "string"},
        "config": {"type": "string"}  // ← 问题！
      }
    }
  }
}
```

但 `bash_with_config` wrapper 不接受 `config` 参数：
```python
def bash_with_config(command: str, workspace: str) -> ToolResult:
    # 没有 config 参数！
```

**解决方案**: 将 `config` 加入排除列表：
```python
# palimpsest/palimpsest/runtime/tools.py
injected_args = {"workspace", "gateway", "evo_root", "evo_sha", "bundle_workspace", "bundle_sha", "runtime_context", "config"}
```

### 5. 切换到 kimi-k2.5 后仍存在问题

修改配置使用 `kimi-k2.5` 后，单独测试确认 DashScope API 的 tool calling 是工作的：

```python
response = client.chat.completions.create(
    model="kimi-k2.5",
    messages=[...],
    tools=[...],
)
# 结果：tool_calls 正确返回
# bash: {"command": "echo \"hello world\" > /tmp/test.txt"}
```

但在实际 implementer 任务中，模型仍然有时返回 "no tool calls"。

**原因推测**：
- model 收到的 context/prompt 可能让它认为不需要工具
- 或者 task 的 goal 描述方式让 model 选择直接回复而不是调用工具

## 已完成的修复

### 1. 排除 config 参数 (palimpsest)

**文件**: `palimpsest/palimpsest/runtime/tools.py`

```python
# 修改前
injected_args = {"workspace", "gateway", "evo_root", "evo_sha", "bundle_workspace", "bundle_sha", "runtime_context"}

# 修改后
injected_args = {"workspace", "gateway", "evo_root", "evo_sha", "bundle_workspace", "bundle_sha", "runtime_context", "config"}
```

### 2. 提高 optimizer 触发阈值

**文件**: `deploy/quadlet/trenni.dev.yaml`

```yaml
observation_thresholds:
  budget_variance: 999.0
  tool_repetition: 999.0
  tool_retry: 999.0
  context_late_lookup: 999.0
```

### 3. 切换到 kimi-k2.5 模型

**文件**: `deploy/quadlet/trenni.dev.yaml`

```yaml
default_llm:
  model: "kimi-k2.5"
  api_base: "https://coding.dashscope.aliyuncs.com/v1"
```

## 待解决问题

### DashScope API 模型行为不稳定

kimi-k2.5 通过 DashScope API 时，tool calling 行为不稳定：
- 单独测试：正常返回 tool_calls
- 实际任务：有时返回 "no tool calls"

**可能的解决方向**：
1. 使用更可靠的 API（直接 OpenAI、Anthropic）
2. 优化 implementer 的 prompt/context，明确指示必须使用工具
3. 添加强制 tool_choice 参数

### 配置文件分离

当前有两个配置文件：
- `config/trenni.yaml` - 开发参考配置
- `deploy/quadlet/trenni.dev.yaml` - 实际部署配置

建议统一或明确文档说明两者的用途差异。

## 监控脚本

创建了 `scripts/monitor-loop.sh` 用于实时监控任务状态：

```bash
# 使用方式
INTERVAL=15 scripts/monitor-loop.sh

# 或使用 TUI
PASLOE_API_KEY=... uv run yoitsu tui
```

## 后续建议

1. **测试其他模型**: 尝试 OpenAI 的 `gpt-4o` 或 Anthropic 的 `claude-3-5-sonnet`
2. **Prompt 优化**: 检查 `prompts/implementer.md`，确保明确指示使用 bash 工具
3. **Tool schema 验证**: 添加测试确保工具 schema 生成正确
4. **API 兼容性测试**: 对不同 API 提供者进行 tool calling 兼容性测试

## 相关文件

- `palimpsest/palimpsest/runtime/tools.py` - 工具定义和 schema 生成
- `palimpsest/palimpsest/runtime/llm.py` - LLM 调用和 tool calling 处理
- `palimpsest/palimpsest/stages/interaction.py` - 交互循环和 idle detection
- `deploy/quadlet/trenni.dev.yaml` - 部署配置
- `scripts/monitor-loop.sh` - 监控脚本
- `scripts/smoke-spawn-monitor.sh` - 冒烟测试脚本