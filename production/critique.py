"""Critique step: vault learning + Alveare-friendly lesson (PII-safe)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from production.producer import ProductionArtifact
from production.rubric import RubricScore
from security.pii import PIISanitizer

if TYPE_CHECKING:
    from engine.tick_engine import CivitasEngine


def _band(total: float) -> str:
    if total >= 85:
        return "distinction"
    if total >= 70:
        return "strong"
    if total >= 55:
        return "developing"
    return "needs_work"


def _weakest_dimension(score: RubricScore) -> str:
    dims = {
        "layout": score.layout,
        "motion_interaction": score.motion_interaction,
        "typography_color": score.typography_color,
        "originality": score.originality,
        "craft": score.craft,
    }
    return min(dims, key=dims.get)


def write_critique(
    artifact: ProductionArtifact,
    score: RubricScore,
    *,
    tick: int,
    learnings_dir: str | Path = "vault/04-LEARNINGS",
) -> str:
    """Write markdown critique; return path."""
    root = Path(learnings_dir)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = root / f"{stamp}-production-{artifact.slug}.md"
    weak = _weakest_dimension(score)
    weak_notes = score.notes.get(weak, [])
    body = f"""---
tags: [production, portfolio, awwwards, critique]
slug: {artifact.slug}
lead_agent: {artifact.lead_agent_id}
tick: {tick}
score_total: {score.total}
band: {_band(score.total)}
---

# Critique — {artifact.slug}

**Lead:** `{artifact.lead_agent_id}` · **Tick:** {tick} · **Totale rubric:** {score.total}/100 ({_band(score.total)})

## Punteggi

| Dimensione | /20 |
|------------|-----|
| Layout | {score.layout} |
| Motion / interaction | {score.motion_interaction} |
| Typography / color | {score.typography_color} |
| Originality | {score.originality} |
| Craft | {score.craft} |

## Focus prossimo sprint

Dimensione più debole: **{weak}**.
"""
    if weak_notes:
        body += "\nNote:\n" + "\n".join(f"- {n}" for n in weak_notes[:5])
    body += f"""

## Artifact

- Path: `{artifact.artifact_dir}`
- Files: {", ".join(artifact.files)}

Lezione Alveare-safe: migliorare {weak} sulla landing `{artifact.slug}` — target Awwwards craft senza API a pagamento.
"""
    path.write_text(PIISanitizer.sanitize_text(body, max_len=8000), encoding="utf-8")
    return str(path)


def enqueue_alveare_lesson(
    engine: CivitasEngine | None,
    *,
    artifact: ProductionArtifact,
    score: RubricScore,
    tick: int,
    critique_path: str,
) -> dict[str, Any]:
    if engine is None:
        return {"enqueued": False, "reason": "no_engine"}
    batch = getattr(engine, "alveare_batch", None)
    if batch is None:
        return {"enqueued": False, "reason": "no_alveare_batch"}
    weak = _weakest_dimension(score)
    text = PIISanitizer.sanitize_text(
        f"[production] slug={artifact.slug} score={score.total}/100 "
        f"weakest={weak} lead={artifact.lead_agent_id} critique={critique_path}",
        max_len=400,
    )
    batch.enqueue(
        agent_id=artifact.lead_agent_id,
        tick=tick,
        text=text,
        source="production",
        tags=["production", "portfolio", "critique", weak],
    )
    return {"enqueued": True}
