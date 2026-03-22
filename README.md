# Yoitsu

Orchestration workspace for the self-evolving agent system.

## Components

| Component | Path | Role |
|-----------|------|------|
| [palimpsest](https://github.com/morrejssc-hub/palimpsest) | `palimpsest/` | Agent Runtime — executes tasks via LLM + tools |
| [trenni](https://github.com/morrejssc-hub/trenni) | `trenni/` | Supervisor — polls Pasloe, schedules jobs, manages concurrency |
| [pasloe](https://github.com/morrejssc-hub/pasloe) | `pasloe/` | Event Store — append-only event log, webhook delivery |

Each component is a separate git repository cloned here for local development.

## Directory Structure

```
yoitsu/
├── config/
│   └── trenni.yaml          # Trenni supervisor config
├── scripts/
│   ├── start.sh             # Start Pasloe + Trenni
│   ├── submit-tasks.py      # Submit a batch of tasks
│   └── monitor.py           # Monitor job progress
├── docs/
│   └── superpowers/
│       ├── specs/           # Design specs
│       └── plans/           # Implementation plans
└── README.md
```

## Quick Start

```bash
# 1. Set env vars
export OPENAI_API_KEY=<dashscope key>

# 2. Start services
./scripts/start.sh

# 3. Submit tasks
python3 scripts/submit-tasks.py

# 4. Monitor
python3 scripts/monitor.py --hours 5
```

## Config

`config/trenni.yaml` — Trenni supervisor config. Key fields:

- `pasloe_url` — Pasloe event store endpoint
- `max_workers` — concurrent job limit
- `default_llm.model` — LLM model (currently `kimi-k2.5` via dashscope)
- `evo_repo_path` — path to palimpsest evo directory
- `work_dir` — job working directory (excluded from git)

## Known Issues

- Trenni HTTP status API (`/status`) not implemented — `submit-tasks.py` and `monitor.py` will warn but continue
- Old evo files (`evo/tools/file_ops.py`, `evo/contexts/*_provider.py`) use a deprecated API — harmless ERRORs in job logs
