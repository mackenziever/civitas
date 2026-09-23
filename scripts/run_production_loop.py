#!/usr/bin/env python3
"""Run production loop once (no Living server required)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import SimConfig
from engine.tick_engine import CivitasEngine
from production.loop import run_production_loop


def main() -> int:
    p = argparse.ArgumentParser(description="Civitas production loop — landing + rubric + critique")
    p.add_argument("--agents", type=int, default=6)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--tick", type=int, default=0)
    p.add_argument("--slug", default="", help="optional portfolio folder name")
    p.add_argument("--crew-size", type=int, default=3)
    p.add_argument("--portfolio", default="vault/08-PORTFOLIO")
    p.add_argument("--learnings", default="vault/04-LEARNINGS")
    args = p.parse_args()
    cfg = SimConfig(
        num_agents=args.agents,
        total_ticks=1,
        seed=args.seed,
        log_path=str(ROOT / "data" / "production_smoke.msgpack"),
        llm_enabled=False,
        metrics_enabled=False,
    )
    engine = CivitasEngine(cfg, live_endpoint=None)
    record = run_production_loop(
        engine,
        args.tick,
        {"slug": args.slug, "crew_size": args.crew_size},
        portfolio_root=args.portfolio,
        learnings_dir=args.learnings,
    )
    print(json.dumps(record.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
