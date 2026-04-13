# TUI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `yoitsu/tui.py` from a cramped 5-panel flat layout to a tabbed dashboard with compact summary bar, job/task detail screens, DAG visualization, and filtering.

**Architecture:** Single-file rewrite of `yoitsu/tui.py`. SummaryBar replaces two 10-line panels with a 3-line strip. TabbedContent gives each data view (Events/Jobs/Tasks) full terminal height. Detail screens are pushed Textual Screens. DAG is derived from hierarchical task_id paths. Filtering is client-side substring matching.

**Tech Stack:** Python 3.11+, Textual 8.x (TabbedContent, TabPane, Screen, Input, DataTable, Static), httpx async clients (PasloeClient, TrenniClient from `yoitsu/client.py`).

**Spec:** `docs/superpowers/specs/2026-04-13-tui-refactor-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `yoitsu/tui.py` | Rewrite | All TUI code: SummaryBar, MonitorApp, JobDetailScreen, TaskDetailScreen, helpers |
| `tests/test_tui.py` | Create | Tests for pure helpers + Textual pilot integration tests |

No changes to `yoitsu/client.py` — all needed API methods already exist (`get_job`, `get_task`, `get_jobs`, `get_tasks`, `list_events`, `get_llm_stats`, `get_status`).

---

### Task 1: Pure Helper Functions — DAG Builder, DAG Renderer, Summary Formatter

These are pure functions with no Textual dependency. TDD first.

**Files:**
- Create: `tests/test_tui.py`
- Modify: `yoitsu/tui.py` (add new helpers, keep existing ones)

- [ ] **Step 1: Write failing tests for `_build_task_tree`**

Create `tests/test_tui.py`:

```python
"""Tests for TUI helper functions."""
from __future__ import annotations


def test_build_task_tree_flat():
    """Root tasks with no children produce tree with empty child lists."""
    from yoitsu.tui import _build_task_tree

    tasks = [
        {"task_id": "t1", "state": "running", "bundle": "factorio", "goal": "Do A"},
        {"task_id": "t2", "state": "pending", "bundle": "factorio", "goal": "Do B"},
    ]
    tree, roots = _build_task_tree(tasks)
    assert roots == ["t1", "t2"]
    assert tree["t1"] == []
    assert tree["t2"] == []


def test_build_task_tree_nested():
    """Child task IDs (containing /) nest under their parent."""
    from yoitsu.tui import _build_task_tree

    tasks = [
        {"task_id": "root", "state": "completed", "bundle": "f", "goal": "Root"},
        {"task_id": "root/abc", "state": "running", "bundle": "f", "goal": "Child A"},
        {"task_id": "root/def", "state": "pending", "bundle": "f", "goal": "Child B"},
        {"task_id": "root/abc/ghi", "state": "pending", "bundle": "f", "goal": "Grandchild"},
    ]
    tree, roots = _build_task_tree(tasks)
    assert roots == ["root"]
    assert sorted(tree["root"]) == ["root/abc", "root/def"]
    assert tree["root/abc"] == ["root/abc/ghi"]
    assert tree["root/def"] == []
    assert tree["root/abc/ghi"] == []


def test_build_task_tree_orphan_children():
    """Children whose parent is missing still appear in the tree."""
    from yoitsu.tui import _build_task_tree

    tasks = [
        {"task_id": "root/abc", "state": "running", "bundle": "f", "goal": "Orphan"},
    ]
    tree, roots = _build_task_tree(tasks)
    # root/abc's parent "root" is not in the task list, so root/abc becomes a root
    assert roots == ["root/abc"]
    assert tree["root/abc"] == []
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `.venv/bin/pytest tests/test_tui.py -v`
Expected: ImportError — `_build_task_tree` does not exist yet.

- [ ] **Step 3: Implement `_build_task_tree`**

Add to `yoitsu/tui.py` after the existing `_state_cell` helper (after line 94):

```python
def _build_task_tree(
    tasks: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], list[str]]:
    """Build parent→children mapping from hierarchical task_ids.

    Returns (tree, roots) where tree maps each task_id to its direct children
    and roots is the list of task_ids with no parent in the dataset.
    """
    all_ids = {t["task_id"] for t in tasks}
    tree: dict[str, list[str]] = {tid: [] for tid in all_ids}
    roots: list[str] = []

    for tid in sorted(all_ids):
        if "/" not in tid:
            roots.append(tid)
            continue
        parent = tid.rsplit("/", 1)[0]
        if parent in tree:
            tree[parent].append(tid)
        else:
            roots.append(tid)

    return tree, roots
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `.venv/bin/pytest tests/test_tui.py::test_build_task_tree_flat tests/test_tui.py::test_build_task_tree_nested tests/test_tui.py::test_build_task_tree_orphan_children -v`
Expected: 3 passed.

- [ ] **Step 5: Write failing tests for `_render_dag`**

Append to `tests/test_tui.py`:

```python
def test_render_dag_simple_tree():
    """DAG renderer shows parent, siblings, and marks current task."""
    from yoitsu.tui import _render_dag

    tasks_by_id = {
        "root": {"task_id": "root", "state": "completed"},
        "root/a": {"task_id": "root/a", "state": "completed"},
        "root/b": {"task_id": "root/b", "state": "running"},
        "root/c": {"task_id": "root/c", "state": "pending"},
    }
    tree = {"root": ["root/a", "root/b", "root/c"], "root/a": [], "root/b": [], "root/c": []}
    result = _render_dag(tree, tasks_by_id, "root/b")
    assert "root" in result
    assert "root/a" in result
    assert "root/b" in result
    assert "root/c" in result
    # Current task should be marked
    assert "<<<" in result or "<<" in result or "←" in result


def test_render_dag_with_children():
    """DAG renderer shows direct children of the current task."""
    from yoitsu.tui import _render_dag

    tasks_by_id = {
        "root": {"task_id": "root", "state": "completed"},
        "root/a": {"task_id": "root/a", "state": "running"},
        "root/a/x": {"task_id": "root/a/x", "state": "pending"},
    }
    tree = {"root": ["root/a"], "root/a": ["root/a/x"], "root/a/x": []}
    result = _render_dag(tree, tasks_by_id, "root/a")
    assert "root/a/x" in result


def test_render_dag_root_task():
    """When current task is root, show it and its children."""
    from yoitsu.tui import _render_dag

    tasks_by_id = {
        "root": {"task_id": "root", "state": "running"},
        "root/a": {"task_id": "root/a", "state": "pending"},
    }
    tree = {"root": ["root/a"], "root/a": []}
    result = _render_dag(tree, tasks_by_id, "root")
    assert "root" in result
    assert "root/a" in result
```

- [ ] **Step 6: Run tests — verify new tests fail**

Run: `.venv/bin/pytest tests/test_tui.py -k "render_dag" -v`
Expected: ImportError — `_render_dag` does not exist yet.

- [ ] **Step 7: Implement `_render_dag`**

Add to `yoitsu/tui.py` after `_build_task_tree`:

```python
def _render_dag(
    tree: dict[str, list[str]],
    tasks_by_id: dict[str, dict[str, Any]],
    current_task_id: str,
) -> str:
    """Render ASCII DAG centered on current_task_id.

    Shows: parent chain → siblings (with current marked) → children of current.
    """
    lines: list[str] = []

    def _state_tag(tid: str) -> str:
        t = tasks_by_id.get(tid, {})
        st = t.get("state", "?")
        return _state_cell(st, task=True)

    # Find parent
    parent_id = current_task_id.rsplit("/", 1)[0] if "/" in current_task_id else None
    if parent_id and parent_id in tasks_by_id:
        lines.append(f"  ↑ {parent_id}  {_state_tag(parent_id)}")
    elif parent_id:
        lines.append(f"  ↑ {parent_id}  [dim](not loaded)[/dim]")

    # Siblings (children of parent, or roots if current is root)
    if parent_id and parent_id in tree:
        siblings = tree[parent_id]
    else:
        # current is a root — no siblings from parent, just show self
        siblings = [current_task_id]

    for i, sib in enumerate(siblings):
        is_last = i == len(siblings) - 1
        prefix = "└── " if is_last else "├── "
        marker = " ←" if sib == current_task_id else ""
        lines.append(f"  {prefix}{sib}  {_state_tag(sib)}{marker}")

        # Show children of the current task
        if sib == current_task_id and sib in tree:
            children = tree[sib]
            for j, child in enumerate(children):
                child_is_last = j == len(children) - 1
                indent = "    " if is_last else "│   "
                child_prefix = "└── " if child_is_last else "├── "
                lines.append(f"  {indent}{child_prefix}{child}  {_state_tag(child)}")

    return "\n".join(lines)
```

- [ ] **Step 8: Run tests — verify all pass**

Run: `.venv/bin/pytest tests/test_tui.py -v`
Expected: 6 passed.

- [ ] **Step 9: Write failing test for `_format_summary`**

Append to `tests/test_tui.py`:

```python
def test_format_summary_all_available():
    """Summary line shows trenni + podman + llm when all available."""
    from yoitsu.tui import _format_summary

    trenni = {"running_jobs": 2, "max_workers": 4, "pending_jobs": 3, "ready_queue_size": 1}
    podman = {"available": True, "running": 5, "exited": 2, "total": 7}
    llm = {"by_model": [{"model": "claude", "total_input_tokens": 120000, "total_output_tokens": 45000, "total_cost": 1.234}]}
    result = _format_summary(trenni, podman, llm)
    assert "2" in result and "4" in result  # running/max
    assert "3" in result  # pending
    assert "5" in result  # podman running
    assert "$1.23" in result or "1.234" in result  # cost


def test_format_summary_services_down():
    """Summary shows unreachable when services are down."""
    from yoitsu.tui import _format_summary

    result = _format_summary(None, {"available": False}, None)
    assert "unreachable" in result.lower() or "?" in result
```

- [ ] **Step 10: Run — verify fail**

Run: `.venv/bin/pytest tests/test_tui.py -k "format_summary" -v`
Expected: ImportError.

- [ ] **Step 11: Implement `_format_summary`**

Add to `yoitsu/tui.py` after `_render_dag`:

```python
def _format_summary(
    trenni: dict[str, Any] | None,
    podman: dict[str, Any],
    llm: dict[str, Any] | None,
) -> str:
    """Format compact 2-line summary for SummaryBar."""
    parts_line1: list[str] = []
    parts_line2: list[str] = []

    # Trenni
    if trenni:
        parts_line1.append(
            f"[b]Trenni[/b] [green]{trenni.get('running_jobs', '?')}[/green]"
            f"/[dim]{trenni.get('max_workers', '?')}[/dim] running  "
            f"[yellow]{trenni.get('pending_jobs', '?')}[/yellow] pending  "
            f"ready {trenni.get('ready_queue_size', '?')}"
        )
        tasks_map = trenni.get("tasks") or {}
        if isinstance(tasks_map, dict):
            parts_line2.append(f"tasks: {len(tasks_map)}")
    else:
        parts_line1.append("[red]Trenni unreachable[/red]")

    # Podman
    if podman.get("available"):
        parts_line1.append(
            f"[b]Podman[/b] [green]{podman['running']}[/green]▶ "
            f"[dim]{podman['exited']}[/dim]✗"
        )
    else:
        parts_line1.append("[b]Podman[/b] [dim]n/a[/dim]")

    # LLM
    if llm:
        by_model = llm.get("by_model", [])
        total_input = sum(r.get("total_input_tokens", 0) or 0 for r in by_model)
        total_output = sum(r.get("total_output_tokens", 0) or 0 for r in by_model)
        total_cost = sum(r.get("total_cost", 0.0) or 0.0 for r in by_model)
        parts_line1.append(f"[bold yellow]${total_cost:.2f}[/bold yellow]")
        parts_line2.append(f"in {total_input:,.0f}  out {total_output:,.0f}")
    else:
        parts_line1.append("[red]LLM ?[/red]")

    line1 = "  │  ".join(parts_line1)
    line2 = "  │  ".join(parts_line2) if parts_line2 else ""
    return f"{line1}\n{line2}" if line2 else line1
```

- [ ] **Step 12: Run all tests — verify pass**

Run: `.venv/bin/pytest tests/test_tui.py -v`
Expected: 8 passed.

- [ ] **Step 13: Commit**

```bash
git add tests/test_tui.py yoitsu/tui.py
git commit -m "feat(tui): add DAG builder, DAG renderer, and summary formatter helpers"
```

---

### Task 2: SummaryBar Widget + Tabbed Layout

Replace the two 10-line panels and flat table layout with a compact SummaryBar + TabbedContent.

**Files:**
- Modify: `yoitsu/tui.py` (rewrite widgets and MonitorApp.compose/CSS/refresh)

- [ ] **Step 1: Delete StatusPanel and LlmPanel classes**

Remove the `StatusPanel` class (lines 99-114) and `LlmPanel` class (lines 117-132) from `yoitsu/tui.py`. They are fully replaced by SummaryBar.

- [ ] **Step 2: Add SummaryBar widget**

Replace the deleted classes with:

```python
class SummaryBar(Static):
    """Compact 2-3 line summary strip replacing StatusPanel + LlmPanel."""

    DEFAULT_CSS = """
    SummaryBar {
        height: auto;
        max-height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }
    """

    content: reactive[str] = reactive("loading…", layout=True)

    def render(self) -> str:
        return self.content
```

- [ ] **Step 3: Add TabbedContent import**

Update imports at top of `yoitsu/tui.py`:

```python
from textual.widgets import DataTable, Footer, Header, Input, Label, Static, TabbedContent, TabPane
```

Remove `Horizontal` from the containers import (no longer needed):

```python
from textual.containers import Vertical
```

(Or remove the containers import entirely if `Horizontal` was the only import.)

- [ ] **Step 4: Rewrite MonitorApp.CSS**

Replace the CSS class attribute:

```python
    CSS = """
    Screen {
        layout: vertical;
    }
    #summary {
        height: auto;
        max-height: 3;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    DataTable {
        height: 1fr;
    }
    """
```

- [ ] **Step 5: Rewrite `compose()` method**

Replace the `compose` method:

```python
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SummaryBar(id="summary")
        with TabbedContent(id="tabs", initial="tab-events"):
            with TabPane("Events", id="tab-events"):
                yield DataTable(id="events-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Jobs", id="tab-jobs"):
                yield DataTable(id="jobs-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Tasks", id="tab-tasks"):
                yield DataTable(id="tasks-table", cursor_type="row", zebra_stripes=True)
        yield Footer()
```

- [ ] **Step 6: Update keybindings**

Replace the `BINDINGS` class attribute:

```python
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_events", "Events"),
        Binding("2", "tab_jobs", "Jobs"),
        Binding("3", "tab_tasks", "Tasks"),
        Binding("slash", "filter", "Filter"),
    ]
```

Add the tab-switching action methods after `action_refresh`:

```python
    def action_tab_events(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-events"

    def action_tab_jobs(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-jobs"

    def action_tab_tasks(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-tasks"
```

- [ ] **Step 7: Rewrite `_refresh_status` and `_refresh_llm` into `_refresh_summary`**

Delete `_refresh_status` and `_refresh_llm` methods. Replace with a single method:

```python
    async def _refresh_summary(self) -> None:
        assert self._trenni is not None and self._pasloe is not None
        trenni_st, podman_info, llm_stats = await asyncio.gather(
            self._trenni.get_status(),
            asyncio.get_running_loop().run_in_executor(None, _podman_summary),
            self._pasloe.get_llm_stats(),
            return_exceptions=True,
        )
        # If any returned an exception, treat as None/unavailable
        if isinstance(trenni_st, BaseException):
            trenni_st = None
        if isinstance(podman_info, BaseException):
            podman_info = {"available": False}
        if isinstance(llm_stats, BaseException):
            llm_stats = None

        bar: SummaryBar = self.query_one("#summary", SummaryBar)
        bar.content = _format_summary(trenni_st, podman_info, llm_stats)
```

- [ ] **Step 8: Update `_do_refresh` to call `_refresh_summary`**

Replace the `_do_refresh` method:

```python
    async def _do_refresh(self) -> None:
        try:
            await asyncio.gather(
                self._refresh_summary(),
                self._refresh_events(),
                self._refresh_jobs(),
                self._refresh_tasks(),
                return_exceptions=True,
            )
        except Exception:
            pass
```

- [ ] **Step 9: Remove row limits in `_refresh_jobs` and `_refresh_tasks`**

In `_refresh_jobs`, change `for j in jobs[:50]:` to `for j in jobs:`.

In `_refresh_tasks`, change `for t in tasks[:50]:` to `for t in tasks:`.

In `_refresh_events`, change `list_events(limit=40)` to `list_events(limit=100)`.

- [ ] **Step 10: Run the app to verify layout**

Run: `.venv/bin/python -m yoitsu tui --interval 10`

Verify:
- Summary bar shows compact Trenni/Podman/LLM info (or "unreachable")
- Three tabs are visible: Events, Jobs, Tasks
- Pressing 1/2/3 switches tabs
- Each tab's table fills the remaining height
- q quits

- [ ] **Step 11: Run existing tests to check for regressions**

Run: `.venv/bin/pytest tests/ -v`
Expected: All existing tests pass. No tests reference StatusPanel/LlmPanel directly.

- [ ] **Step 12: Commit**

```bash
git add yoitsu/tui.py
git commit -m "feat(tui): replace flat layout with compact summary bar + tabbed data views"
```

---

### Task 3: Filtering

Add per-tab filtering via `/` key with substring matching.

**Files:**
- Modify: `yoitsu/tui.py`
- Modify: `tests/test_tui.py`

- [ ] **Step 1: Write failing test for `_matches_filter`**

Append to `tests/test_tui.py`:

```python
def test_matches_filter_case_insensitive():
    from yoitsu.tui import _matches_filter

    row = ("12:00:00", "agent.job.completed", "palimpsest", "job:abc", "done")
    assert _matches_filter(row, "completed")
    assert _matches_filter(row, "COMPLETED")
    assert _matches_filter(row, "pali")
    assert not _matches_filter(row, "nonexistent")


def test_matches_filter_empty_passes_all():
    from yoitsu.tui import _matches_filter

    row = ("a", "b", "c")
    assert _matches_filter(row, "")
```

- [ ] **Step 2: Run — verify fail**

Run: `.venv/bin/pytest tests/test_tui.py -k "matches_filter" -v`
Expected: ImportError.

- [ ] **Step 3: Implement `_matches_filter`**

Add to `yoitsu/tui.py` helpers section:

```python
def _matches_filter(row: tuple[str, ...], query: str) -> bool:
    """Return True if any cell in row contains query (case-insensitive)."""
    if not query:
        return True
    q = query.lower()
    return any(q in str(cell).lower() for cell in row)
```

- [ ] **Step 4: Run — verify pass**

Run: `.venv/bin/pytest tests/test_tui.py -k "matches_filter" -v`
Expected: 2 passed.

- [ ] **Step 5: Add data caching to MonitorApp**

In `MonitorApp.__init__`, add after existing attributes:

```python
        self._events_data: list[tuple[str, ...]] = []
        self._jobs_data: list[tuple[str, ...]] = []
        self._tasks_data: list[tuple[str, ...]] = []
        self._jobs_raw: list[dict[str, Any]] = []
        self._tasks_raw: list[dict[str, Any]] = []
        self._filter_text: dict[str, str] = {"tab-events": "", "tab-jobs": "", "tab-tasks": ""}
```

`_jobs_raw` and `_tasks_raw` store the original API dicts (needed for detail screen navigation to resolve row → job_id/task_id).

- [ ] **Step 6: Update `_refresh_events` to cache and filter**

Rewrite `_refresh_events`:

```python
    async def _refresh_events(self) -> None:
        assert self._pasloe is not None
        events = await self._pasloe.list_events(limit=100)
        table: DataTable = self.query_one("#events-table", DataTable)
        table.clear()
        if not events:
            self._events_data = []
            return
        self._events_data = []
        query = self._filter_text.get("tab-events", "")
        for event in events:
            data = event.get("data") or {}
            row = (
                _event_ts(event.get("ts")),
                _shorten(event.get("type"), 30),
                _shorten(event.get("source_id"), 18),
                _event_refs(data),
                _event_detail(event),
            )
            self._events_data.append(row)
            if _matches_filter(row, query):
                table.add_row(*row)
```

- [ ] **Step 7: Update `_refresh_jobs` to cache and filter**

Rewrite `_refresh_jobs`:

```python
    async def _refresh_jobs(self) -> None:
        assert self._trenni is not None
        jobs = await self._trenni.get_jobs()
        table: DataTable = self.query_one("#jobs-table", DataTable)
        table.clear()
        if not jobs:
            self._jobs_data = []
            self._jobs_raw = []
            return
        self._jobs_data = []
        self._jobs_raw = list(jobs)
        query = self._filter_text.get("tab-jobs", "")
        for j in jobs:
            state = str(j.get("state") or "")
            row = (
                _shorten(j.get("job_id"), 16),
                _state_cell(state),
                _shorten(j.get("bundle"), 16),
                _shorten(j.get("role"), 12),
                _shorten(j.get("task_id"), 16),
            )
            self._jobs_data.append(row)
            if _matches_filter(row, query):
                table.add_row(*row, key=j.get("job_id", ""))
```

- [ ] **Step 8: Update `_refresh_tasks` to cache and filter**

Rewrite `_refresh_tasks`:

```python
    async def _refresh_tasks(self) -> None:
        assert self._trenni is not None
        tasks = await self._trenni.get_tasks()
        table: DataTable = self.query_one("#tasks-table", DataTable)
        table.clear()
        if not tasks:
            self._tasks_data = []
            self._tasks_raw = []
            return
        self._tasks_data = []
        self._tasks_raw = list(tasks)
        query = self._filter_text.get("tab-tasks", "")
        for t in tasks:
            state = str(t.get("state") or "")
            row = (
                _shorten(t.get("task_id"), 16),
                _state_cell(state, task=True),
                _shorten(t.get("bundle"), 16),
                _shorten(t.get("goal"), 60),
            )
            self._tasks_data.append(row)
            if _matches_filter(row, query):
                table.add_row(*row, key=t.get("task_id", ""))
```

- [ ] **Step 9: Add filter Input widget to each TabPane**

Update `compose()` — add an `Input` widget inside each `TabPane`, above the DataTable:

```python
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SummaryBar(id="summary")
        with TabbedContent(id="tabs", initial="tab-events"):
            with TabPane("Events", id="tab-events"):
                yield Input(placeholder="filter…", id="filter-events", classes="filter-input hidden")
                yield DataTable(id="events-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Jobs", id="tab-jobs"):
                yield Input(placeholder="filter…", id="filter-jobs", classes="filter-input hidden")
                yield DataTable(id="jobs-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Tasks", id="tab-tasks"):
                yield Input(placeholder="filter…", id="filter-tasks", classes="filter-input hidden")
                yield DataTable(id="tasks-table", cursor_type="row", zebra_stripes=True)
        yield Footer()
```

Add CSS for the filter input:

```python
    .filter-input {
        dock: top;
        height: 1;
        display: block;
    }
    .filter-input.hidden {
        display: none;
    }
```

- [ ] **Step 10: Implement `action_filter` to toggle filter input**

Add the filter action method:

```python
    def action_filter(self) -> None:
        """Toggle the filter input for the active tab."""
        tabs = self.query_one("#tabs", TabbedContent)
        active = tabs.active
        filter_id = f"filter-{active.replace('tab-', '')}"
        filter_input = self.query_one(f"#{filter_id}", Input)
        if filter_input.has_class("hidden"):
            filter_input.remove_class("hidden")
            filter_input.focus()
        else:
            filter_input.add_class("hidden")
            filter_input.value = ""
            self._filter_text[active] = ""
            self.run_worker(self._apply_filter(active), exclusive=False, exit_on_error=False)
```

- [ ] **Step 11: Handle filter Input changes and Escape**

Add event handlers:

```python
    def on_input_changed(self, event: Input.Changed) -> None:
        """Update filter when user types."""
        input_widget = event.input
        # Map input id to tab id
        tab_id = input_widget.id.replace("filter-", "tab-") if input_widget.id else ""
        self._filter_text[tab_id] = event.value
        self.run_worker(self._apply_filter(tab_id), exclusive=False, exit_on_error=False)

    def on_key(self, event) -> None:
        """Handle Escape to clear filter."""
        if event.key == "escape":
            tabs = self.query_one("#tabs", TabbedContent)
            active = tabs.active
            filter_id = f"filter-{active.replace('tab-', '')}"
            try:
                filter_input = self.query_one(f"#{filter_id}", Input)
                if not filter_input.has_class("hidden"):
                    filter_input.add_class("hidden")
                    filter_input.value = ""
                    self._filter_text[active] = ""
                    self.run_worker(self._apply_filter(active), exclusive=False, exit_on_error=False)
                    event.prevent_default()
            except Exception:
                pass
```

- [ ] **Step 12: Implement `_apply_filter` method**

```python
    async def _apply_filter(self, tab_id: str) -> None:
        """Re-filter the table for the given tab using cached data."""
        query = self._filter_text.get(tab_id, "")
        if tab_id == "tab-events":
            table: DataTable = self.query_one("#events-table", DataTable)
            table.clear()
            for row in self._events_data:
                if _matches_filter(row, query):
                    table.add_row(*row)
        elif tab_id == "tab-jobs":
            table = self.query_one("#jobs-table", DataTable)
            table.clear()
            for i, row in enumerate(self._jobs_data):
                if _matches_filter(row, query):
                    job_id = self._jobs_raw[i].get("job_id", "") if i < len(self._jobs_raw) else ""
                    table.add_row(*row, key=job_id)
        elif tab_id == "tab-tasks":
            table = self.query_one("#tasks-table", DataTable)
            table.clear()
            for i, row in enumerate(self._tasks_data):
                if _matches_filter(row, query):
                    task_id = self._tasks_raw[i].get("task_id", "") if i < len(self._tasks_raw) else ""
                    table.add_row(*row, key=task_id)
```

- [ ] **Step 13: Manual test**

Run: `.venv/bin/python -m yoitsu tui`

Verify:
- Press `/` — filter input appears at top of active tab
- Type text — table rows narrow to matches
- Press Escape — filter clears, all rows return, input hides
- Switch tabs — each tab has independent filter state

- [ ] **Step 14: Run all tests**

Run: `.venv/bin/pytest tests/ -v`
Expected: All pass.

- [ ] **Step 15: Commit**

```bash
git add yoitsu/tui.py tests/test_tui.py
git commit -m "feat(tui): add per-tab filtering with / key and substring matching"
```

---

### Task 4: Job Detail Screen

Push a detail screen when pressing Enter on a job row.

**Files:**
- Modify: `yoitsu/tui.py`

- [ ] **Step 1: Add Screen import**

Ensure this import exists at top:

```python
from textual.screen import Screen
```

- [ ] **Step 2: Create JobDetailScreen class**

Add after the `SummaryBar` class, before `MonitorApp`:

```python
class JobDetailScreen(Screen):
    """Detail view for a single job."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("r", "refresh_detail", "Refresh"),
    ]

    CSS = """
    JobDetailScreen {
        layout: vertical;
    }
    #job-meta {
        height: auto;
        max-height: 12;
        padding: 1 2;
        border-bottom: solid $primary;
    }
    #job-events-label {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
    }
    #job-events {
        height: 1fr;
    }
    """

    def __init__(self, job_id: str, pasloe: "PasloeClient", trenni: "TrenniClient") -> None:
        super().__init__()
        self._job_id = job_id
        self._pasloe = pasloe
        self._trenni = trenni

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(f"[b]Job:[/b] {self._job_id}\nloading…", id="job-meta")
        yield Label(" Job Events", id="job-events-label")
        yield DataTable(id="job-events", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#job-events", DataTable)
        table.add_columns("ts", "type", "detail")
        self.run_worker(self._load(), exclusive=False, exit_on_error=False)

    async def action_refresh_detail(self) -> None:
        await self._load()

    async def _load(self) -> None:
        meta_widget: Static = self.query_one("#job-meta", Static)
        table: DataTable = self.query_one("#job-events", DataTable)

        job = await self._trenni.get_job(self._job_id)
        if not job:
            meta_widget.update(f"[red]Job {self._job_id} not found[/red]")
            return

        state = str(job.get("state", ""))
        lines = [
            f"[b]Job:[/b] {job.get('job_id', '')}  {_state_cell(state)}",
            f"[b]Role:[/b] {job.get('role', '')}  [b]Bundle:[/b] {job.get('bundle', '')}",
            f"[b]Task:[/b] {job.get('task_id', '')}",
            f"[b]Parent:[/b] {job.get('parent_job_id', '') or '-'}",
        ]
        cond = job.get("condition")
        if cond:
            lines.append(f"[b]Condition:[/b] {_shorten(str(cond), 80)}")

        ctx = job.get("job_context", {})
        if ctx.get("join"):
            j = ctx["join"]
            lines.append(f"[b]Join:[/b] parent_task={j.get('parent_task_id', '')}  children={len(j.get('child_task_ids', []))}")
        if ctx.get("eval"):
            e = ctx["eval"]
            lines.append(f"[b]Eval:[/b] task={e.get('task_id', '')}  deliverables={len(e.get('deliverables', []))}")

        meta_widget.update("\n".join(lines))

        # Load events for this job
        table.clear()
        events = await self._pasloe.list_events(limit=100)
        if events:
            for ev in events:
                data = ev.get("data") or {}
                if data.get("job_id") == self._job_id:
                    table.add_row(
                        _event_ts(ev.get("ts")),
                        _shorten(ev.get("type"), 30),
                        _event_detail(ev),
                    )
```

- [ ] **Step 3: Wire Enter key on jobs table to push JobDetailScreen**

Add to `MonitorApp`:

```python
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter on a table row."""
        table = event.data_table
        if table.id == "jobs-table":
            row_key = str(event.row_key.value)
            if row_key and self._pasloe and self._trenni:
                self.push_screen(JobDetailScreen(row_key, self._pasloe, self._trenni))
        elif table.id == "tasks-table":
            row_key = str(event.row_key.value)
            if row_key and self._pasloe and self._trenni:
                # Will be implemented in Task 5
                pass
```

- [ ] **Step 4: Manual test**

Run: `.venv/bin/python -m yoitsu tui`

Verify:
- Press `2` to go to Jobs tab
- Navigate to a job row, press Enter
- JobDetailScreen appears with job metadata and filtered events
- Press Escape or `q` to go back to main dashboard

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/pytest tests/ -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add yoitsu/tui.py
git commit -m "feat(tui): add job detail screen with metadata and event history"
```

---

### Task 5: Task Detail Screen with DAG

Push a detail screen when pressing Enter on a task row, showing metadata, DAG, and associated jobs.

**Files:**
- Modify: `yoitsu/tui.py`
- Modify: `tests/test_tui.py`

- [ ] **Step 1: Create TaskDetailScreen class**

Add after `JobDetailScreen`:

```python
class TaskDetailScreen(Screen):
    """Detail view for a single task with DAG visualization."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("r", "refresh_detail", "Refresh"),
    ]

    CSS = """
    TaskDetailScreen {
        layout: vertical;
    }
    #task-meta {
        height: auto;
        max-height: 8;
        padding: 1 2;
        border-bottom: solid $primary;
    }
    #task-dag {
        height: auto;
        max-height: 15;
        padding: 0 2;
        border-bottom: solid $accent;
    }
    #task-jobs-label {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
    }
    #task-jobs {
        height: 1fr;
    }
    #task-result {
        height: auto;
        max-height: 6;
        padding: 0 2;
        border-top: solid $primary;
    }
    """

    def __init__(self, task_id: str, pasloe: "PasloeClient", trenni: "TrenniClient") -> None:
        super().__init__()
        self._task_id = task_id
        self._pasloe = pasloe
        self._trenni = trenni

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(f"[b]Task:[/b] {self._task_id}\nloading…", id="task-meta")
        yield Static("loading DAG…", id="task-dag")
        yield Label(" Jobs for this Task", id="task-jobs-label")
        yield DataTable(id="task-jobs", cursor_type="row", zebra_stripes=True)
        yield Static("", id="task-result")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#task-jobs", DataTable)
        table.add_columns("job_id", "state", "role")
        self.run_worker(self._load(), exclusive=False, exit_on_error=False)

    async def action_refresh_detail(self) -> None:
        await self._load()

    async def _load(self) -> None:
        meta_widget: Static = self.query_one("#task-meta", Static)
        dag_widget: Static = self.query_one("#task-dag", Static)
        table: DataTable = self.query_one("#task-jobs", DataTable)
        result_widget: Static = self.query_one("#task-result", Static)

        task_detail, all_tasks, task_jobs = await asyncio.gather(
            self._trenni.get_task(self._task_id),
            self._trenni.get_tasks(),
            self._trenni.get_jobs(task_id=self._task_id),
            return_exceptions=True,
        )

        # Task metadata
        if isinstance(task_detail, BaseException) or not task_detail:
            meta_widget.update(f"[red]Task {self._task_id} not found[/red]")
            return

        state = str(task_detail.get("state", ""))
        lines = [
            f"[b]Task:[/b] {task_detail.get('task_id', '')}  {_state_cell(state, task=True)}",
            f"[b]Bundle:[/b] {task_detail.get('bundle', '')}",
            f"[b]Goal:[/b] {task_detail.get('goal', '')}",
        ]
        if task_detail.get("eval_spawned"):
            lines.append(f"[b]Eval job:[/b] {task_detail.get('eval_job_id', '')}")
        meta_widget.update("\n".join(lines))

        # DAG
        if isinstance(all_tasks, BaseException) or not all_tasks:
            dag_widget.update("[dim]DAG unavailable[/dim]")
        else:
            tasks_by_id = {t["task_id"]: t for t in all_tasks}
            tree, _roots = _build_task_tree(all_tasks)
            dag_text = _render_dag(tree, tasks_by_id, self._task_id)
            dag_widget.update(f"[b]DAG[/b]\n{dag_text}")
            # Store for navigation
            self._all_tasks = all_tasks

        # Jobs
        table.clear()
        if not isinstance(task_jobs, BaseException) and task_jobs:
            for j in task_jobs:
                job_state = str(j.get("state", ""))
                table.add_row(
                    _shorten(j.get("job_id"), 24),
                    _state_cell(job_state),
                    j.get("role", ""),
                    key=j.get("job_id", ""),
                )

        # Result
        result = task_detail.get("result")
        if result:
            r_lines = []
            sem = result.get("semantic", {})
            if sem.get("verdict"):
                r_lines.append(f"[b]Verdict:[/b] {sem['verdict']}  {_shorten(sem.get('summary', ''), 60)}")
            trace = result.get("trace", [])
            if trace:
                r_lines.append(f"[b]Trace:[/b] {len(trace)} entries")
                for entry in trace[:5]:
                    r_lines.append(
                        f"  {entry.get('role', '?')}: {entry.get('outcome', '?')} — {_shorten(entry.get('summary', ''), 50)}"
                    )
            result_widget.update("\n".join(r_lines) if r_lines else "")
        else:
            result_widget.update("")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a job in this task → push job detail."""
        row_key = str(event.row_key.value)
        if row_key:
            self.app.push_screen(JobDetailScreen(row_key, self._pasloe, self._trenni))
```

- [ ] **Step 2: Wire Enter on tasks table in MonitorApp**

Update the `elif table.id == "tasks-table"` branch in `on_data_table_row_selected`:

```python
        elif table.id == "tasks-table":
            row_key = str(event.row_key.value)
            if row_key and self._pasloe and self._trenni:
                self.push_screen(TaskDetailScreen(row_key, self._pasloe, self._trenni))
```

- [ ] **Step 3: Manual test**

Run: `.venv/bin/python -m yoitsu tui`

Verify:
- Press `3` to go to Tasks tab
- Navigate to a task row, press Enter
- TaskDetailScreen shows: metadata, DAG tree, jobs list, result (if any)
- From the jobs table in TaskDetailScreen, press Enter on a job → JobDetailScreen opens
- Escape chains back through the screen stack

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest tests/ -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/tui.py
git commit -m "feat(tui): add task detail screen with DAG visualization and job list"
```

---

### Task 6: Cross-Navigation Between Detail Screens

Add navigation from JobDetailScreen → TaskDetailScreen, and between task DAG nodes.

**Files:**
- Modify: `yoitsu/tui.py`

- [ ] **Step 1: Add task navigation from JobDetailScreen**

Add a keybinding and handler to `JobDetailScreen` for navigating to the associated task:

Add to `JobDetailScreen.BINDINGS`:
```python
        Binding("t", "go_task", "Go to Task"),
```

Add method to `JobDetailScreen`:
```python
    async def action_go_task(self) -> None:
        """Navigate to the task this job belongs to."""
        job = await self._trenni.get_job(self._job_id)
        if job and job.get("task_id"):
            self.app.push_screen(
                TaskDetailScreen(job["task_id"], self._pasloe, self._trenni)
            )
```

- [ ] **Step 2: Add DAG node navigation in TaskDetailScreen**

Add a keybinding for navigating to parent task:

Add to `TaskDetailScreen.BINDINGS`:
```python
        Binding("p", "go_parent", "Parent Task"),
```

Add method to `TaskDetailScreen`:
```python
    async def action_go_parent(self) -> None:
        """Navigate to parent task in the DAG."""
        if "/" in self._task_id:
            parent_id = self._task_id.rsplit("/", 1)[0]
            self.app.push_screen(
                TaskDetailScreen(parent_id, self._pasloe, self._trenni)
            )
```

- [ ] **Step 3: Manual test**

Run: `.venv/bin/python -m yoitsu tui`

Test the navigation chain:
1. Jobs tab → Enter on job → JobDetailScreen
2. Press `t` → TaskDetailScreen for that job's task
3. Press `p` → parent task's TaskDetailScreen
4. Escape, Escape, Escape → back to main dashboard
5. Tasks tab → Enter on task → TaskDetailScreen → Enter on job → JobDetailScreen

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest tests/ -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/tui.py
git commit -m "feat(tui): add cross-navigation between job and task detail screens"
```

---

### Task 7: Integration Test + Cleanup

Write a Textual pilot integration test for the main app and clean up any dead code.

**Files:**
- Modify: `tests/test_tui.py`
- Modify: `yoitsu/tui.py`

- [ ] **Step 1: Write integration test with mocked clients**

Append to `tests/test_tui.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_trenni():
    client = AsyncMock()
    client.get_status = AsyncMock(return_value={
        "running_jobs": 1, "max_workers": 4, "pending_jobs": 2,
        "ready_queue_size": 0, "tasks": {"t1": {}}
    })
    client.get_jobs = AsyncMock(return_value=[
        {"job_id": "j1", "state": "running", "bundle": "factorio", "role": "worker", "task_id": "t1"},
        {"job_id": "j2", "state": "completed", "bundle": "factorio", "role": "evaluator", "task_id": "t1"},
    ])
    client.get_tasks = AsyncMock(return_value=[
        {"task_id": "t1", "state": "running", "bundle": "factorio", "goal": "Build things"},
    ])
    client.get_job = AsyncMock(return_value={
        "job_id": "j1", "state": "running", "bundle": "factorio", "role": "worker",
        "task_id": "t1", "parent_job_id": "", "condition": None, "job_context": {},
    })
    client.get_task = AsyncMock(return_value={
        "task_id": "t1", "state": "running", "bundle": "factorio",
        "goal": "Build things", "eval_spawned": False, "eval_job_id": "",
        "job_order": ["j1"], "result": None,
    })
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def mock_pasloe():
    client = AsyncMock()
    client.get_llm_stats = AsyncMock(return_value={
        "by_model": [{"model": "claude", "total_input_tokens": 1000, "total_output_tokens": 500, "total_cost": 0.05}]
    })
    client.list_events = AsyncMock(return_value=[
        {"ts": "2026-04-13T12:00:00Z", "type": "agent.job.started", "source_id": "palimpsest",
         "data": {"job_id": "j1", "task_id": "t1", "workspace_path": "/tmp"}},
    ])
    client.aclose = AsyncMock()
    return client


async def test_monitor_app_renders_tabs(mock_trenni, mock_pasloe):
    """App should render with summary bar and three tabs."""
    from yoitsu.tui import MonitorApp

    app = MonitorApp(pasloe_url="http://test", trenni_url="http://test", api_key="test")
    # Inject mocked clients
    async with app.run_test(size=(120, 40)) as pilot:
        app._pasloe = mock_pasloe
        app._trenni = mock_trenni
        with patch("yoitsu.tui._podman_summary", return_value={"available": True, "running": 3, "exited": 1, "total": 4}):
            await app._do_refresh()

        # Check summary bar has content
        from textual.widgets import TabbedContent
        tabs = app.query_one("#tabs", TabbedContent)
        assert tabs.active == "tab-events"

        # Switch to jobs tab
        await pilot.press("2")
        assert tabs.active == "tab-jobs"

        # Switch to tasks tab
        await pilot.press("3")
        assert tabs.active == "tab-tasks"
```

- [ ] **Step 2: Run integration test**

Run: `.venv/bin/pytest tests/test_tui.py::test_monitor_app_renders_tabs -v`
Expected: PASS (the app mounts, renders, tab switching works).

If the test fails due to timing or Textual internals, adjust — e.g., add `await pilot.pause()` after key presses.

- [ ] **Step 3: Clean up dead code in `yoitsu/tui.py`**

Remove any leftover references:
- Remove `Horizontal` import if still present
- Remove `#top-row`, `#events-label`, `#jobs-label`, `#tasks-label` CSS selectors (replaced by TabbedContent)
- Remove `Label` from imports if no longer used
- Ensure no references to deleted `StatusPanel` / `LlmPanel` remain

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All pass.

- [ ] **Step 5: Manual smoke test**

Run: `.venv/bin/python -m yoitsu tui`

Walk through the complete feature set:
1. Summary bar shows compact status
2. Tab switching with 1/2/3
3. `/` filter works per tab, Escape clears
4. Enter on job → detail screen with events
5. Enter on task → detail screen with DAG + jobs
6. `t` from job detail → task detail
7. `p` from task detail → parent task
8. Escape chains back through screens
9. `r` refreshes in any context
10. `q` quits from main, pops from detail

- [ ] **Step 6: Commit**

```bash
git add tests/test_tui.py yoitsu/tui.py
git commit -m "test(tui): add integration test with mocked clients; clean up dead code"
```
