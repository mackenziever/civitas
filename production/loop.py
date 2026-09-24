"""Orchestrate produce → score → critique → record."""
from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from production.critique import enqueue_alveare_lesson, write_critique
from production.producer import produce_landing
from production.rubric import score_landing
from production.store import ProductionRecord, ProductionStore

if TYPE_CHECKING:
    from engine.tick_engine import CivitasEngine


class ProductionEngine:
    def __init__(
        self,
        *,
        portfolio_root: str = "vault/08-PORTFOLIO",
        learnings_dir: str = "vault/04-LEARNINGS",
        data_dir: str = "data/production",
    ):
        self.portfolio_root = portfolio_root
        self.learnings_dir = learnings_dir
        self.store = ProductionStore(data_dir)
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def run(
        self,
        engine: CivitasEngine,
        tick: int,
        options: dict[str, Any] | None = None,
    ) -> tuple[ProductionRecord | None, str | None]:
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            return None, "busy"
        try:
            return self._run_unlocked(engine, tick, options or {}), None
        finally:
            self._lock.release()

    def _run_unlocked(
        self,
        engine: CivitasEngine,
        tick: int,
        options: dict[str, Any],
    ) -> ProductionRecord:
        slug = str(options.get("slug") or "")
        crew_size = int(options.get("crew_size") or 3)
        tagline = str(
            options.get("tagline")
            or "Una landing scoreabile verso Awwwards, generata dal loop di produzione Civitas."
        )
        artifact = produce_landing(
            engine,
            tick=tick,
            portfolio_root=self.portfolio_root,
            slug=slug,
            crew_size=crew_size,
            city_tagline=tagline,
        )
        rubric = score_landing(artifact.artifact_dir)
        critique_path = write_critique(artifact, rubric, tick=tick, learnings_dir=self.learnings_dir)
        alveare = enqueue_alveare_lesson(
            engine,
            artifact=artifact,
            score=rubric,
            tick=tick,
            critique_path=critique_path,
        )
        enacted_at = datetime.now(timezone.utc).isoformat()
        raw_id = f"{tick}:{artifact.slug}:{uuid.uuid4().hex[:8]}"
        run_id = "prod_" + hashlib.sha256(raw_id.encode()).hexdigest()[:12]
        record = ProductionRecord(
            run_id=run_id,
            tick=tick,
            enacted_at=enacted_at,
            artifact=artifact.as_dict(),
            score=rubric.as_dict(),
            critique_path=critique_path,
            alveare=alveare,
        )
        self.store.append(record)
        return record

    def recent(self, limit: int = 20) -> list[ProductionRecord]:
        return self.store.recent(limit)


def run_production_loop(
    engine: CivitasEngine,
    tick: int,
    options: dict[str, Any] | None = None,
    *,
    portfolio_root: str = "vault/08-PORTFOLIO",
    learnings_dir: str = "vault/04-LEARNINGS",
    data_dir: str = "data/production",
) -> ProductionRecord:
    """Stateless helper (no lock) for scripts/tests."""
    pe = ProductionEngine(
        portfolio_root=portfolio_root,
        learnings_dir=learnings_dir,
        data_dir=data_dir,
    )
    return pe._run_unlocked(engine, tick, options or {})
