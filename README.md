# Yoitsu

Self-evolving agent system. An autonomous agent completes external tasks while discovering and improving its own capabilities by modifying an evolvable repository.

See [docs/architecture.md](docs/architecture.md) for system design principles and [docs/adr/](docs/adr/) for architecture decision records.

## Components

| Component | Path | Role |
|-----------|------|------|
| [palimpsest](https://github.com/morrejssc-hub/palimpsest) | `palimpsest/` | Agent Runtime — single-job execution engine |
| [trenni](https://github.com/morrejssc-hub/trenni) | `trenni/` | Supervisor — event-driven orchestration and job dispatch |
| [pasloe](https://github.com/morrejssc-hub/pasloe) | `pasloe/` | Event Store — append-only event log with webhook delivery |

Each component is a separate git repository. Use `scripts/setup.sh` to clone or update all of them.

## Quick Start

```bash
# 1. Clone components
./scripts/setup.sh

# 2. Set env vars
export PASLOE_API_KEY=yoitsu-test-key-2026
export OPENAI_API_KEY=<your-key>

# 3. Start the stack
uv run yoitsu up

# 4. Submit tasks
uv run yoitsu submit scripts/trenni.yaml

# 5. Monitor
uv run yoitsu status

# 6. Stop
uv run yoitsu down
```

## Configuration

`config/trenni.yaml` configures the Supervisor. Key decisions:

- `max_workers` — concurrency limit; keep low until the evo repo is stable
- `evo_repo_path` — must point to the palimpsest `evo/` directory
- `default_llm.model` — shared default; individual jobs can override
