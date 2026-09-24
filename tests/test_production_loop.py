"""Production loop: rubric determinism, artifact write, OPS busy lock."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from config import SimConfig
from engine.tick_engine import CivitasEngine
from living_server.app import STATE, create_app
from production.loop import ProductionEngine, run_production_loop
from production.rubric import RUBRIC_DIMENSIONS, score_landing
from starlette.testclient import TestClient

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "portfolio" / "golden_landing"
GOLDEN_TOTAL = 90.0  # pinned at fixture introduction; update if rubric weights change


def _engine(tmp_path, agents=4, seed=11):
    return CivitasEngine(
        SimConfig(
            num_agents=agents,
            total_ticks=1,
            seed=seed,
            log_path=str(tmp_path / "prod.msgpack"),
            llm_enabled=False,
            metrics_enabled=False,
        ),
        live_endpoint=None,
    )


def test_rubric_golden_fixture_is_deterministic():
    a = score_landing(FIXTURE)
    b = score_landing(FIXTURE)
    assert a.as_dict() == b.as_dict()
    assert set(RUBRIC_DIMENSIONS) == set(a.notes.keys())
    assert a.total == GOLDEN_TOTAL


def test_production_loop_writes_artifact_and_critique(tmp_path):
    engine = _engine(tmp_path)
    portfolio = tmp_path / "portfolio"
    learnings = tmp_path / "learnings"
    record = run_production_loop(
        engine,
        99,
        {"slug": "test-landing", "crew_size": 2},
        portfolio_root=str(portfolio),
        learnings_dir=str(learnings),
        data_dir=str(tmp_path / "data"),
    )
    art_dir = Path(record.artifact["artifact_dir"])
    assert (art_dir / "index.html").is_file()
    assert (art_dir / "styles.css").is_file()
    assert record.score["total"] > 0
    assert Path(record.critique_path).is_file()
    assert record.artifact["slug"] == "test-landing"


def test_production_ops_busy_returns_409(tmp_path):
    engine = _engine(tmp_path)
    STATE.engine = engine
    STATE.tick = 7
    STATE.production_engine = ProductionEngine(
        portfolio_root=str(tmp_path / "p"),
        learnings_dir=str(tmp_path / "l"),
        data_dir=str(tmp_path / "d"),
    )
    hold = threading.Event()
    results: list = []

    def slow_run():
        acquired = STATE.production_engine._lock.acquire(blocking=False)
        if acquired:
            try:
                hold.wait(timeout=5)
            finally:
                STATE.production_engine._lock.release()

    t = threading.Thread(target=slow_run)
    t.start()
    try:
        client = TestClient(create_app(engine))
        r = client.post("/v1/production/run", json={"slug": "busy-test"})
        results.append(r.status_code)
    finally:
        hold.set()
        t.join(timeout=2)
    assert 409 in results


def test_production_run_endpoint_ok(tmp_path):
    engine = _engine(tmp_path)
    STATE.engine = engine
    STATE.tick = 3
    STATE.production_engine = ProductionEngine(
        portfolio_root=str(tmp_path / "p"),
        learnings_dir=str(tmp_path / "l"),
        data_dir=str(tmp_path / "d"),
    )
    client = TestClient(create_app(engine))
    r = client.post("/v1/production/run", json={"slug": "ops-demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["run"]["artifact"]["slug"] == "ops-demo"
    recent = client.get("/v1/production/recent")
    assert recent.status_code == 200
    assert len(recent.json()["runs"]) >= 1
