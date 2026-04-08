# Yoitsu Status Index

- 当前系统计划：[SYSTEM-PLAN.md](SYSTEM-PLAN.md)
- 架构指南：[docs/architecture.md](docs/architecture.md)
- 活跃 ADR：[docs/adr/](docs/adr/)
- 当前任务工件：`.task/`
- 历史归档：[docs/archive/](docs/archive/)

## 2026-04-08 发现的问题

### observation_aggregator.py API key header 错误

**问题**：`trenni/trenni/observation_aggregator.py` 使用了错误的 pasloe API 认证 header
- 错误代码：`headers["Authorization"] = f"Bearer {api_key}"` 
- 正确代码：`headers["X-API-Key"] = api_key`

**影响**：导致 observation 聚合查询返回 401 Unauthorized，优化回环无法触发

**状态**：已修复代码 + 已添加测试，需要重启 trenni 服务生效

**验证路径**：
- pasloe 中已有 10 个 `observation.budget_variance` 事件
- 阈值配置 `budget_variance: 0.3` 已满足 (10 >= 0.3)
- 重启后应触发 optimizer 任务

**相关测试**：
- `trenni/tests/test_observation_aggregator.py::test_api_key_header_is_x_api_key`
- `trenni/tests/test_optimizer_output.py::TestEndToEndOptimizationLoop`
