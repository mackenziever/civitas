"""JSONL persistence for production runs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List


@dataclass
class ProductionRecord:
    run_id: str
    tick: int
    enacted_at: str
    artifact: dict[str, Any]
    score: dict[str, Any]
    critique_path: str
    alveare: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ProductionRecord:
        return cls(
            run_id=str(raw["run_id"]),
            tick=int(raw.get("tick") or 0),
            enacted_at=str(raw.get("enacted_at") or ""),
            artifact=dict(raw.get("artifact") or {}),
            score=dict(raw.get("score") or {}),
            critique_path=str(raw.get("critique_path") or ""),
            alveare=dict(raw.get("alveare") or {}),
        )


class ProductionStore:
    def __init__(self, data_dir: str | Path = "data/production"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "runs.jsonl"

    def append(self, record: ProductionRecord) -> None:
        line = json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()

    def recent(self, limit: int = 20) -> List[ProductionRecord]:
        if not self.path.is_file():
            return []
        limit = max(1, min(200, int(limit)))
        lines: list[str] = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    lines.append(line)
        return [ProductionRecord.from_dict(json.loads(line)) for line in lines[-limit:]]
