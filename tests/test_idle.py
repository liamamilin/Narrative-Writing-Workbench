"""Idle auto-shutdown tests (workbench/idle.py)."""

from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.idle import IdleTracker, install, timeout_from_env


def test_check_fires_only_after_timeout():
    fired = []
    tr = IdleTracker(0.05, shutdown=lambda: fired.append(1))
    assert tr.check() is False and fired == []
    time.sleep(0.08)
    assert tr.check() is True and fired == [1]


def test_touch_resets_window():
    fired = []
    tr = IdleTracker(0.2, shutdown=lambda: fired.append(1))
    for _ in range(5):
        time.sleep(0.06)
        tr.touch()
        assert tr.check() is False
    assert fired == []


def test_install_touches_on_request():
    app = FastAPI()
    tr = IdleTracker(3600, shutdown=lambda: (_ for _ in ()).throw(
        AssertionError("should not fire")))
    install(app, tr, poll_seconds=3600)   # thread polls far in the future

    @app.get("/ping")
    def ping():
        return {"ok": True}

    tr._last = time.monotonic() - 9999
    TestClient(app).get("/ping")
    assert tr.idle_seconds() < 5          # middleware reset the clock


def test_timeout_from_env(monkeypatch):
    monkeypatch.delenv("WORKBENCH_IDLE_TIMEOUT", raising=False)
    assert timeout_from_env() == 30 * 60
    monkeypatch.setenv("WORKBENCH_IDLE_TIMEOUT", "5")
    assert timeout_from_env() == 5 * 60
    monkeypatch.setenv("WORKBENCH_IDLE_TIMEOUT", "0")
    assert timeout_from_env() == 0
    monkeypatch.setenv("WORKBENCH_IDLE_TIMEOUT", "-1")
    assert timeout_from_env() == 0
    monkeypatch.setenv("WORKBENCH_IDLE_TIMEOUT", "abc")
    assert timeout_from_env() == 30 * 60
