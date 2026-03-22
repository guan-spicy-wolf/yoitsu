"""Tests for PID file management and liveness checks."""
from __future__ import annotations
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import yoitsu.process as proc


class TestIsAlive:
    def test_alive_process_returns_true(self):
        assert proc.is_alive(os.getpid()) is True

    def test_dead_process_returns_false(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            assert proc.is_alive(99999999) is False

    def test_permission_error_treated_as_alive(self):
        with patch("os.kill", side_effect=PermissionError):
            assert proc.is_alive(1) is True


class TestPidFile:
    def test_write_and_read_pids(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.write_pids(pasloe_pid=100, trenni_pid=200)
        data = proc.read_pids()
        assert data["pasloe"]["pid"] == 100
        assert data["trenni"]["pid"] == 200

    def test_read_pids_returns_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        assert proc.read_pids() is None

    def test_clear_pids_removes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.write_pids(pasloe_pid=1, trenni_pid=2)
        proc.clear_pids()
        assert proc.read_pids() is None

    def test_clear_pids_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.clear_pids()  # file doesn't exist — should not raise
