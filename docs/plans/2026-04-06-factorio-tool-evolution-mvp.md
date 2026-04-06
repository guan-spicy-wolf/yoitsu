# Factorio Tool Evolution MVP Implementation Plan

**Goal:** yoitsu 自主演化出一个 Factorio Lua 脚本。第一次 task 重复调用 actions.place → observation.tool_repetition 信号 → optimizer 提议新增封装脚本 → implementer 写出并 commit → 第二次 task 自动使用新脚本，调用次数显著下降。

**Architecture:**
- factorio-agent 仓库本身充当 evo（workaround，Phase 2 再做 multi-bundle）
- 共享 host 上的 factorio headless server，preparation_fn 通过 RCON 批量加载 evo 脚本
- worker（team=factorio，串行锁）暴露 1 个 dispatcher tool `factorio_call_script`
- implementer（team=default，可并发）写 Lua 文件，路径白名单限定到 teams/factorio/scripts/
- 新增 2 个 observation 信号（tool_repetition / context_late_lookup），保持独立模型
- 新增 trenni 定时聚合器，查 pasloe observation 事件，达阈值 spawn optimizer

**Tech Stack:** Python, Pydantic, factorio-rcon, yoitsu-contracts, palimpsest, trenni, Lua

**Non-goals:**
- 不做 multi-bundle evo overlay（留 Phase 2）
- 不做每 job 独立 factorio 实例（共享 host 实例）
- 不做 ArtifactStore checkpoint（留 Phase 3）

---

## Task 0: 实现 observation 聚合层（trenni 定时查询 + 本地聚合）

**Files:**
- Modify: `trenni/trenni/supervisor.py`
- Modify: `trenni/trenni/config.py`
- Add: `trenni/trenni/observation_aggregator.py`
- Modify: `trenni/tests/test_observation_aggregator.py`

**Step 1: 在 TrenniConfig 加聚合器配置**

```python
# trenni/config.py
@dataclass
class TrenniConfig:
    ...
    observation_aggregation_interval: float = 300.0  # 5 分钟
    observation_window_hours: int = 24
    observation_thresholds: dict[str, float] = field(default_factory=lambda: {
        "budget_variance": 0.3,
        "preparation_failure": 0.1,
        "tool_retry": 0.2,
        "tool_repetition": 5.0,  # 绝对计数，不是比率
        "context_late_lookup": 3.0,
    })
```

**Step 2: 实现聚合器模块**

```python
# trenni/observation_aggregator.py
"""Observation event aggregator for autonomous optimization loop.

Periodically queries pasloe for observation.* events, aggregates by metric_type,
and spawns optimizer tasks when thresholds are exceeded.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import httpx
from loguru import logger


@dataclass
class AggregationResult:
    metric_type: str
    count: int
    threshold: float
    exceeded: bool
    role: str | None = None


async def aggregate_observations(
    pasloe_url: str,
    window_hours: int,
    thresholds: dict[str, float],
) -> list[AggregationResult]:
    """Query pasloe for observation.* events in window, aggregate by metric_type."""
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    
    # Query pasloe: GET /events?event_type_prefix=observation.&since=<cutoff>
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{pasloe_url}/events",
            params={
                "event_type_prefix": "observation.",
                "since": cutoff.isoformat(),
                "limit": 10000,
            },
        )
        resp.raise_for_status()
        events = resp.json()
    
    # Group by metric_type (从 event_type 提取，如 observation.tool_repetition → tool_repetition)
    counts: dict[str, int] = {}
    for evt in events:
        event_type = evt.get("event_type", "")
        if not event_type.startswith("observation."):
            continue
        metric = event_type.split(".", 1)[1] if "." in event_type else ""
        counts[metric] = counts.get(metric, 0) + 1
    
    results = []
    for metric, count in counts.items():
        threshold = thresholds.get(metric, float("inf"))
        results.append(AggregationResult(
            metric_type=metric,
            count=count,
            threshold=threshold,
            exceeded=(count >= threshold),
        ))
    
    return results
```

**Step 3: 在 supervisor 主循环加定时触发**

```python
# supervisor.py
class Supervisor:
    def __init__(self, config: TrenniConfig):
        ...
        self._last_aggregation = 0.0
    
    async def run(self):
        while True:
            ...
            # 定时聚合 observation
            now = time.time()
            if now - self._last_aggregation >= self.config.observation_aggregation_interval:
                await self._aggregate_and_spawn_optimizer()
                self._last_aggregation = now
            
            await asyncio.sleep(self.config.poll_interval)
    
    async def _aggregate_and_spawn_optimizer(self):
        from trenni.observation_aggregator import aggregate_observations
        results = await aggregate_observations(
            self.config.pasloe_url,
            self.config.observation_window_hours,
            self.config.observation_thresholds,
        )
        for r in results:
            if r.exceeded:
                logger.info(f"Observation threshold exceeded: {r.metric_type} ({r.count} >= {r.threshold})")
                # 直接 spawn optimizer task（不走 pasloe ObservationThresholdEvent）
                trigger_data = {
                    "trigger_type": "observation_threshold",
                    "goal": f"Analyze {r.metric_type} pattern ({r.count} occurrences in {self.config.observation_window_hours}h)",
                    "role": "optimizer",
                    "team": "default",
                    "budget": 0.5,
                    "params": {
                        "metric_type": r.metric_type,
                        "observation_count": r.count,
                        "window_hours": self.config.observation_window_hours,
                    },
                }
                await self._process_trigger(SimpleNamespace(
                    id=f"obs-agg-{r.metric_type}-{int(time.time())}",
                    source_id="observation_aggregator",
                    event_type="trigger",
                    data=trigger_data,
                ))
```

**Step 4: 单元测试**

```python
# tests/test_observation_aggregator.py
import pytest
from trenni.observation_aggregator import aggregate_observations

@pytest.mark.asyncio
async def test_aggregate_below_threshold(mock_pasloe_server):
    # mock_pasloe_server 返回 3 个 observation.tool_repetition 事件
    results = await aggregate_observations(
        mock_pasloe_server.url, window_hours=24, thresholds={"tool_repetition": 5.0}
    )
    assert len(results) == 1
    assert results[0].metric_type == "tool_repetition"
    assert results[0].count == 3
    assert not results[0].exceeded

@pytest.mark.asyncio
async def test_aggregate_exceeds_threshold(mock_pasloe_server):
    # 返回 6 个事件
    results = await aggregate_observations(
        mock_pasloe_server.url, window_hours=24, thresholds={"tool_repetition": 5.0}
    )
    assert results[0].exceeded
```

**Verification:**
```bash
cd trenni && uv run pytest tests/test_observation_aggregator.py -v
```

---

## Task 1: 扩展 observation 信号合约（新增 2 个独立模型）

**Files:**
- Modify: `yoitsu-contracts/src/yoitsu_contracts/observation.py`
- Modify: `yoitsu-contracts/tests/test_observation_events.py`

**Step 1: 添加常量和模型**

```python
# observation.py
OBSERVATION_TOOL_REPETITION = "observation.tool_repetition"
OBSERVATION_CONTEXT_LATE_LOOKUP = "observation.context_late_lookup"

class ToolRepetitionData(BaseModel):
    """Emitted when a tool was called many times with similar args in one job."""
    job_id: str
    task_id: str
    role: str
    team: str
    tool_name: str
    call_count: int
    arg_pattern: str  # 字符串摘要，如 "grid_5x2"
    similarity: float  # 0.0-1.0

class ContextLateLookupData(BaseModel):
    """Emitted when a job repeatedly queried data that could be in context."""
    job_id: str
    task_id: str
    role: str
    tool_name: str
    call_count: int
    query_kind: str  # 字符串摘要
```

**Step 2: 单元测试**

```python
# tests/test_observation_events.py
def test_tool_repetition_flat_fields():
    data = ToolRepetitionData(
        job_id="j1", task_id="t1", role="worker", team="factorio",
        tool_name="factorio_call_script", call_count=10,
        arg_pattern="grid_5x2", similarity=0.85,
    )
    assert data.call_count == 10
    # 验证所有字段都是 primitive（无嵌套 dict/list）
    for k, v in data.model_dump().items():
        assert not isinstance(v, (dict, list))
```

**Verification:**
```bash
cd yoitsu-contracts && uv run pytest tests/test_observation_events.py::test_tool_repetition_flat_fields -v
```

---

## Task 2: 在 interaction loop 出口扫描并 emit 新信号

**Files:**
- Add: `palimpsest/palimpsest/runtime/tool_pattern.py`
- Modify: `palimpsest/palimpsest/stages/interaction.py`
- Add: `palimpsest/tests/test_tool_pattern.py`

**Step 1: 实现检测纯函数**

```python
# runtime/tool_pattern.py
from dataclasses import dataclass
import json

@dataclass
class ToolCallRecord:
    name: str
    args_json: str

@dataclass
class RepetitionFinding:
    tool_name: str
    call_count: int
    arg_pattern: str
    similarity: float

def detect_repetition(
    history: list[ToolCallRecord],
    *,
    min_count: int = 5,
    similarity_threshold: float = 0.7,
) -> list[RepetitionFinding]:
    """Find tools called >= min_count with high arg similarity.
    
    For dispatcher tools (like factorio_call_script), extracts nested script_name
    from args and groups by that instead of tool name.
    """
    # Group by (tool_name, script_name_if_dispatcher)
    groups: dict[tuple[str, str], list[dict]] = {}
    for rec in history:
        try:
            args = json.loads(rec.args_json)
        except:
            args = {}
        
        # 如果 args 有 "name" 字段（dispatcher 的 script_name），用它分组
        script_name = args.get("name", "")
        key = (rec.name, script_name) if script_name else (rec.name, "")
        groups.setdefault(key, []).append(args)
    
    findings = []
    for (tool_name, script_name), args_list in groups.items():
        if len(args_list) < min_count:
            continue
        
        # 计算参数结构相似度（key-set overlap）
        if not args_list:
            continue
        key_sets = [set(a.keys()) for a in args_list]
        avg_similarity = sum(
            len(k1 & k2) / max(len(k1 | k2), 1)
            for i, k1 in enumerate(key_sets)
            for k2 in key_sets[i+1:]
        ) / max(len(key_sets) * (len(key_sets) - 1) / 2, 1)
        
        if avg_similarity >= similarity_threshold:
            # arg_pattern: 如果是 dispatcher，用 script_name；否则用 tool_name
            pattern = script_name if script_name else tool_name
            findings.append(RepetitionFinding(
                tool_name=f"{tool_name}({script_name})" if script_name else tool_name,
                call_count=len(args_list),
                arg_pattern=pattern,
                similarity=avg_similarity,
            ))
    
    return findings
```

**Step 2: 在 interaction.py 出口调用**

```python
# stages/interaction.py
def run_interaction_loop(...):
    tool_call_history: list[ToolCallRecord] = []
    
    while not done:
        ...
        if tool_calls:
            for tc in tool_calls:
                result = execute_tool(tc.name, tc.args)
                tool_call_history.append(ToolCallRecord(
                    name=tc.name,
                    args_json=json.dumps(tc.args, sort_keys=True),
                ))
    
    # Loop 结束，扫描 pattern
    from palimpsest.runtime.tool_pattern import detect_repetition
    repetitions = detect_repetition(tool_call_history)
    for r in repetitions:
        gateway.emit_observation(
            event_type="observation.tool_repetition",
            data={
                "job_id": job_id,
                "task_id": task_id,
                "role": role_name,
                "team": team,
                "tool_name": r.tool_name,
                "call_count": r.call_count,
                "arg_pattern": r.arg_pattern,
                "similarity": r.similarity,
            },
        )
```

**Step 3: 单元测试**

```python
# tests/test_tool_pattern.py
def test_detect_repetition_dispatcher_groups_by_script_name():
    history = [
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 0, "y": 0}'),
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 1, "y": 0}'),
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 2, "y": 0}'),
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 3, "y": 0}'),
        ToolCallRecord("factorio_call_script", '{"name": "actions.place", "x": 4, "y": 0}'),
    ]
    findings = detect_repetition(history, min_count=5, similarity_threshold=0.7)
    assert len(findings) == 1
    assert findings[0].tool_name == "factorio_call_script(actions.place)"
    assert findings[0].call_count == 5
    assert findings[0].arg_pattern == "actions.place"
```

**Verification:**
```bash
cd palimpsest && uv run pytest tests/test_tool_pattern.py -v
```

---

由于 token 限制，剩余 Task 3-9 分成下一个输出块。现在 commit 前 3 个 task 的 plan 片段。