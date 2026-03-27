"""Yoitsu monitor TUI — real-time dashboard for the running stack."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Label, Static

from .client import PasloeClient, TrenniClient


# ── helpers ──────────────────────────────────────────────────────────────────

def _podman_summary() -> dict[str, Any]:
    """Return podman container counts; safe if podman not available."""
    import subprocess
    try:
        out = subprocess.run(
            ["podman", "ps", "-a", "--format", "{{.State}}"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return {"available": False}
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        running = sum(1 for s in lines if s.lower().startswith("running"))
        exited = sum(1 for s in lines if s.lower().startswith("exited"))
        return {"available": True, "running": running, "exited": exited, "total": len(lines)}
    except Exception:
        return {"available": False}


def _shorten(s: str | None, n: int) -> str:
    if not s:
        return ""
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ── widgets ──────────────────────────────────────────────────────────────────

class StatusPanel(Static):
    """Left top panel: Trenni + Podman."""

    DEFAULT_CSS = """
    StatusPanel {
        border: round $primary;
        padding: 0 1;
        height: 10;
        width: 1fr;
    }
    """

    content: reactive[str] = reactive("loading…", layout=True)

    def render(self) -> str:  # type: ignore[override]
        return self.content


class LlmPanel(Static):
    """Right top panel: LLM usage stats."""

    DEFAULT_CSS = """
    LlmPanel {
        border: round $accent;
        padding: 0 1;
        height: 10;
        width: 1fr;
    }
    """

    content: reactive[str] = reactive("loading…", layout=True)

    def render(self) -> str:  # type: ignore[override]
        return self.content


# ── main app ─────────────────────────────────────────────────────────────────

class MonitorApp(App[None]):
    """Yoitsu real-time monitor."""

    TITLE = "Yoitsu Monitor"
    CSS = """
    Screen {
        layout: vertical;
    }
    #top-row {
        height: 10;
    }
    #jobs-label, #tasks-label {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
    }
    #jobs-table {
        height: 1fr;
        border: none;
    }
    #tasks-table {
        height: 1fr;
        border: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        pasloe_url: str,
        trenni_url: str,
        api_key: str,
        interval: int = 5,
    ) -> None:
        super().__init__()
        self._pasloe_url = pasloe_url
        self._trenni_url = trenni_url
        self._api_key = api_key
        self._interval = interval
        self._pasloe: PasloeClient | None = None
        self._trenni: TrenniClient | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top-row"):
            yield StatusPanel(id="status-panel")
            yield LlmPanel(id="llm-panel")
        yield Label(" Active Jobs", id="jobs-label")
        yield DataTable(id="jobs-table", cursor_type="row", zebra_stripes=True)
        yield Label(" Active Tasks", id="tasks-label")
        yield DataTable(id="tasks-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._pasloe = PasloeClient(url=self._pasloe_url, api_key=self._api_key)
        self._trenni = TrenniClient(url=self._trenni_url)

        jobs_table: DataTable = self.query_one("#jobs-table", DataTable)
        jobs_table.add_columns("job_id", "state", "team", "role", "summary")

        tasks_table: DataTable = self.query_one("#tasks-table", DataTable)
        tasks_table.add_columns("task_id", "state", "team", "goal")

        self.set_interval(self._interval, self._do_refresh)
        self.run_worker(self._do_refresh(), exclusive=False, exit_on_error=False)

    async def on_unmount(self) -> None:
        if self._pasloe:
            await self._pasloe.aclose()
        if self._trenni:
            await self._trenni.aclose()

    async def action_refresh(self) -> None:
        await self._do_refresh()

    async def _do_refresh(self) -> None:
        try:
            await asyncio.gather(
                self._refresh_status(),
                self._refresh_llm(),
                self._refresh_jobs(),
                self._refresh_tasks(),
                return_exceptions=True,
            )
        except Exception:
            pass

    # ── status panel ─────────────────────────────────────────────────────────

    async def _refresh_status(self) -> None:
        assert self._trenni is not None
        st = await self._trenni.get_status()
        lines: list[str] = []
        if st:
            lines.append(
                f"[b]Trenni[/b]  jobs [green]{st.get('running_jobs', '?')}"
                f"[/green]/[dim]{st.get('max_workers', '?')}[/dim]  "
                f"pending [yellow]{st.get('pending_jobs', '?')}[/yellow]  "
                f"ready {st.get('ready_queue_size', '?')}"
            )
            tasks_map: dict = st.get("tasks", {}) or {}
            lines.append(f"        tasks in memory: {len(tasks_map)}")
        else:
            lines.append("[red]Trenni  unreachable[/red]")

        ps = await asyncio.get_running_loop().run_in_executor(None, _podman_summary)
        if ps.get("available"):
            lines.append(
                f"\n[b]Podman[/b]  running [green]{ps['running']}[/green]  "
                f"exited [dim]{ps['exited']}[/dim]  "
                f"total {ps['total']}"
            )
        else:
            lines.append("\n[b]Podman[/b]  [dim]not available[/dim]")

        panel: StatusPanel = self.query_one("#status-panel", StatusPanel)
        panel.content = "\n".join(lines)

    # ── llm panel ────────────────────────────────────────────────────────────

    async def _refresh_llm(self) -> None:
        assert self._pasloe is not None
        stats = await self._pasloe.get_llm_stats()
        panel: LlmPanel = self.query_one("#llm-panel", LlmPanel)
        if not stats:
            panel.content = "[red]LLM stats  unreachable[/red]"
            return

        lines = ["[b]LLM Usage[/b]"]
        by_model = stats.get("by_model", [])
        total_input = total_output = total_cost = 0.0
        for row in by_model:
            model = _shorten(row.get("model", ""), 24)
            inp = row.get("total_input_tokens", 0) or 0
            out = row.get("total_output_tokens", 0) or 0
            cost = row.get("total_cost", 0.0) or 0.0
            total_input += inp
            total_output += out
            total_cost += cost
            lines.append(
                f"  [dim]{model}[/dim]  in {inp:,}  out {out:,}  "
                f"[yellow]${cost:.3f}[/yellow]"
            )
        if by_model:
            lines.append(
                f"\n  [b]total[/b]  in {total_input:,.0f}  out {total_output:,.0f}  "
                f"[bold yellow]${total_cost:.3f}[/bold yellow]"
            )
        else:
            lines.append("  [dim](no data yet)[/dim]")
        panel.content = "\n".join(lines)

    # ── jobs table ────────────────────────────────────────────────────────────

    async def _refresh_jobs(self) -> None:
        assert self._pasloe is not None
        jobs = await self._pasloe.list_jobs(limit=50)
        table: DataTable = self.query_one("#jobs-table", DataTable)
        table.clear()
        if not jobs:
            return
        for j in jobs:
            state = j.get("state", "")
            style = (
                "green" if state == "completed"
                else "red" if state in ("failed", "eval_failed")
                else "yellow" if state == "running"
                else ""
            )
            state_cell = f"[{style}]{state}[/{style}]" if style else state
            table.add_row(
                _shorten(j.get("job_id"), 16),
                state_cell,
                _shorten(j.get("team"), 16),
                _shorten(j.get("role"), 12),
                _shorten(j.get("summary"), 48),
            )

    # ── tasks table ──────────────────────────────────────────────────────────

    async def _refresh_tasks(self) -> None:
        assert self._pasloe is not None
        tasks = await self._pasloe.list_tasks(limit=30)
        table: DataTable = self.query_one("#tasks-table", DataTable)
        table.clear()
        if not tasks:
            return
        for t in tasks:
            state = t.get("state", "")
            style = (
                "green" if state == "completed"
                else "red" if state in ("failed", "cancelled", "eval_failed")
                else "yellow" if state == "running"
                else ""
            )
            state_cell = f"[{style}]{state}[/{style}]" if style else state
            table.add_row(
                _shorten(t.get("task_id"), 16),
                state_cell,
                _shorten(t.get("team"), 16),
                _shorten(t.get("goal"), 60),
            )


# ── entry point ──────────────────────────────────────────────────────────────

def run_tui(pasloe_url: str, trenni_url: str, api_key: str, interval: int = 5) -> None:
    app = MonitorApp(
        pasloe_url=pasloe_url,
        trenni_url=trenni_url,
        api_key=api_key,
        interval=interval,
    )
    app.run()
