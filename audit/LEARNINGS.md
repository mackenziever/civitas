# LEARNINGS — Civitas

## 2026-09-10 — P2 scale

- Load 1M tick (5 agents, spatial-hash + delta-log): ~182 s wall (~5486 Hz), p95 compute ~0.32 ms, 16 overruns, ~511 MB log.
- Rust/PyO3: contract in `native/README.md` + golden `tests/golden/spatial_seed42.json`; missing `civitas_spatial` falls back to Python without failing the run.
- `CognitiveWorker` is optional ops queue (`--cognitive-worker`); authoritative `router.decide` stays in the tick for deterministic replay.
- Viewer 3D LOD (auto/high/low) hides trails and lowers sphere segments when far from camera.
- CityMap with size N must use N×N grids where border write uses index N-1; tests with 32×32 hit IndexError on `blocked[32,:]`.

## 2026-09-10 — FreeLLMAPI + Alveare

- FreeLLMAPI primary only under Compose `--profile llm` (loopback :3001). Default CI remains LLM-off.
- Alveare replay must store **full chunk text** in `llm_trace.jsonl` (`kind=alveare_retrieval`); IDs alone are not enough if the store mutates.
- `CIVITAS_REPLAY=1` freezes upserts (HTTP 423). Agent writes flush in a **sorted batch at end of tick**.
- Hash embedder = wiring/determinism tests only; semantic quality needs real `/v1/embeddings` with fixed float precision (~6 decimals).
- CI covers the chat-completion-compatible path via stdlib mock (`tests/test_mock_llm_ci.py`) without pulling GHCR.

## 2026-09-24 — Production loop MVP

- `production/` — produce landing (`vault/08-PORTFOLIO/`) → rubric Awwwards-ish → critique in `vault/04-LEARNINGS/`.
- OPS: `POST /v1/production/run`, `GET /v1/production/recent` on Living :9300; script `scripts/run_production_loop.py`.
- Golden rubric fixture: `tests/fixtures/portfolio/golden_landing/`.
