"""HTTP + WebSocket Living City server (Starlette/uvicorn)."""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from living_server.day_loop import run_day_loop
from metrics.collector import GLOBAL_COLLECTOR
from production.loop import ProductionEngine

_VIEWER_DIR = Path(__file__).resolve().parents[1] / "viewer"
_LIVE_HTML = _VIEWER_DIR / "living_city_live.html"


class LivingState:
    def __init__(self):
        self.engine = None
        self.tick = 0
        self.started_at = time.time()
        self.stop_event: asyncio.Event | None = None
        self.loop_task: asyncio.Task | None = None
        self.subscribers: list[WebSocket] = []
        self.last_cognitive: list[dict] = []
        self.loop_result: dict | None = None
        self.production_engine = ProductionEngine()


STATE = LivingState()


def _ping(url: str, timeout: float = 2.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw": body[:200]}
            return {"ok": True, "status": resp.status, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def health(_request: Request):
    eng = STATE.engine
    freellm_base = os.getenv("CIVITAS_LLM_API_BASE", "http://127.0.0.1:3001/v1")
    # Prefer FreeLLM host derived from env (Docker: http://freellmapi:3001/v1)
    freellm_root = freellm_base.rstrip("/").rsplit("/v1", 1)[0]
    freellm = _ping(freellm_root + "/api/ping")
    if not freellm.get("ok"):
        freellm = _ping("http://127.0.0.1:3001/api/ping")
    alveare_url = os.getenv("CIVITAS_ALVEARE_URL", "http://127.0.0.1:9200")
    alveare = _ping(alveare_url.rstrip("/") + "/health") if alveare_url else {"ok": False}
    hermes = _ping("http://127.0.0.1:8081/health")
    # host.docker.internal for Hermes on host (optional)
    if not hermes.get("ok"):
        hermes = _ping("http://host.docker.internal:8081/health")
    llm_base = freellm_base
    if eng is not None:
        llm_base = eng.cfg.llm_api_base
    llm_root = llm_base.rstrip("/").rsplit("/v1", 1)[0]
    # FreeLLM has /api/ping; llama.cpp/Hermes has /health
    llm_endpoint = _ping(llm_root + "/api/ping")
    if not llm_endpoint.get("ok"):
        llm_endpoint = _ping(llm_root + "/health")
    payload: dict[str, Any] = {
        "ok": True,
        "service": "living_city",
        "living": True,
        "uptime_s": round(time.time() - STATE.started_at, 3),
        "tick": STATE.tick,
        "freellm": freellm,
        "alveare": alveare,
        "hermes": hermes,
        "llm_endpoint": llm_endpoint,
        "llm_api_base": llm_base,
        "ws_clients": len(STATE.subscribers),
    }
    if eng is not None:
        payload["agents"] = len(eng.agents)
        payload["llm"] = dict(eng.router.stats)
        payload["llm_enabled"] = eng.cfg.llm_enabled
        if eng.paperclip_board is not None:
            payload.update(eng.paperclip_board.stats())
        growth = getattr(eng, "city_growth", None)
        if growth is not None:
            snap = growth.snapshot()
            payload["city_built"] = len(snap.get("built") or [])
            payload["city_metrics"] = snap.get("metrics")
        payload["web_search_enabled"] = bool(getattr(eng.cfg, "web_search_enabled", False))
        if getattr(eng, "web_search", None) is not None:
            payload["web_search"] = dict(eng.web_search.stats)
        mayor = getattr(eng, "mayor", None)
        payload["mayor_enabled"] = mayor is not None
        if mayor is not None:
            payload["mayor"] = dict(mayor.stats)
        research = getattr(eng, "research", None)
        if research is not None:
            payload["research"] = dict(research.stats)
            payload["research_rates"] = research.stats_summary()
        construction = getattr(eng, "construction", None)
        if construction is not None:
            cs = construction.snapshot()
            payload["construction"] = cs.get("stats")
            payload["agent_builds"] = len(cs.get("completed_pois") or [])
        rooms = getattr(eng, "rooms", None)
        if rooms is not None:
            rs = rooms.snapshot()
            payload["rooms"] = rs.get("stats")
            payload["room_count"] = len(rs.get("rooms") or {})
        # Telemetria end-to-end (consiglio esterno, 2026-09-11, "5.
        # Telemetry"): tassi LLM + latenza tick + conflitti di rilocazione,
        # cosi' un degrado si vede da /health invece che da un report utente.
        payload["llm_rates"] = eng.router.stats_summary()
        tick_s = GLOBAL_COLLECTOR.summary("civitas_tick_seconds")
        payload["tick_duration_ms"] = {
            "count": tick_s["count"],
            "mean": round(tick_s["mean"] * 1000, 3),
            "p95": round(tick_s["p95"] * 1000, 3),
            "last": round(tick_s["last"] * 1000, 3),
        }
        payload["building_relocation_conflicts"] = GLOBAL_COLLECTOR.get_counter(
            "civitas_building_relocation_conflicts_total"
        )
        # `alveare` sopra e' gia' la risposta del /health remoto del servizio
        # Alveare (knowledge/server.py), che spreadda AlveareStore.stats() —
        # last_query_ms/last_chunks_scanned sono gia' li' dentro (item 2/5).
        astats = (alveare.get("data") or {}) if isinstance(alveare, dict) else {}
        if astats.get("last_query_ms") is not None:
            payload["alveare_rag"] = {
                "last_query_ms": astats.get("last_query_ms"),
                "last_chunks_scanned": astats.get("last_chunks_scanned"),
            }
    return JSONResponse(payload)


async def agents_list(_request: Request):
    if STATE.engine is None:
        return JSONResponse({"ok": False, "error": "engine_not_ready"}, status_code=503)
    return JSONResponse({"ok": True, "agents": STATE.engine.agi_os_snapshots()})


async def agent_one(request: Request):
    if STATE.engine is None:
        return JSONResponse({"ok": False, "error": "engine_not_ready"}, status_code=503)
    aid = request.path_params["agent_id"]
    one = STATE.engine.agi_os_one(aid)
    if one is None:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    return JSONResponse({"ok": True, "agent": one})


async def thoughts(_request: Request):
    return JSONResponse({"ok": True, "cognitive": STATE.last_cognitive[-50:]})


async def production_run(request: Request):
    if STATE.engine is None:
        return JSONResponse({"ok": False, "error": "engine_not_ready"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid_body"}, status_code=400)
    record, err = STATE.production_engine.run(STATE.engine, STATE.tick, body)
    if err == "busy":
        return JSONResponse({"ok": False, "error": "busy"}, status_code=409)
    assert record is not None
    return JSONResponse({"ok": True, "run": record.as_dict()})


async def production_recent(request: Request):
    limit = 20
    try:
        q = request.query_params.get("limit")
        if q is not None:
            limit = int(q)
    except (TypeError, ValueError):
        limit = 20
    rows = STATE.production_engine.recent(limit)
    return JSONResponse(
        {
            "ok": True,
            "runs": [r.as_dict() for r in rows],
            "busy": STATE.production_engine.busy,
        }
    )


async def city_state(_request: Request):
    if STATE.engine is None:
        return JSONResponse({"ok": False, "error": "engine_not_ready"}, status_code=503)
    growth = getattr(STATE.engine, "city_growth", None)
    construction = getattr(STATE.engine, "construction", None)
    rooms = getattr(STATE.engine, "rooms", None)
    pois = {k: list(v) for k, v in STATE.engine.city.pois.items()}
    snap = STATE.engine.city.snapshot()
    payload = {
        "ok": True,
        "pois": pois,
        "blocked": [list(c) for c in snap.blocked_cells],
        "grid_w": snap.width,
        "grid_h": snap.height,
        "wilderness_margin": getattr(snap, "wilderness_margin", 0) or getattr(STATE.engine.city, "margin", 0),
        "growth": None,
        "construction": None,
        "rooms": None,
    }
    if growth is not None:
        payload["growth"] = growth.snapshot()
    if construction is not None:
        payload["construction"] = construction.snapshot()
    if rooms is not None:
        payload["rooms"] = rooms.snapshot()
    return JSONResponse(payload)


PANEL_HTML = """<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8"/><title>Living City — Ops Console</title>
<style>
*{box-sizing:border-box}
body{font-family:ui-monospace,Consolas,"Cascadia Mono",monospace;background:#0b0f14;color:#c8d2dc;margin:0;padding:1rem 1.2rem 1.5rem;font-size:13px;line-height:1.45}
h1{font-size:1.05rem;letter-spacing:.06em;font-weight:600;margin:0 0 .75rem;color:#e8eef4}
h2{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:#7a8a9c;margin:0 0 .45rem;font-weight:600}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:.55rem .85rem;margin-bottom:.9rem;padding-bottom:.75rem;border-bottom:1px solid #1c2733}
.meta{color:#8b9bb0;font-size:.8rem}
.chips{display:flex;flex-wrap:wrap;gap:.4rem}
.chip{border:1px solid #2a3544;padding:.15rem .45rem;font-size:.72rem;letter-spacing:.04em;color:#9aabbc;background:#10161e}
.chip.ok{border-color:#2d5a3d;color:#8dca9a;background:#0e1a14}
.chip.bad{border-color:#5a2d2d;color:#d09898;background:#1a1010}
.chip.warn{border-color:#5a4a2d;color:#cbb87a;background:#18140e}
.layout{display:grid;grid-template-columns:1fr 280px;gap:1rem}
@media(max-width:900px){.layout{grid-template-columns:1fr}}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.55rem}
.cell{border:1px solid #1e2a38;padding:.55rem .65rem;background:#0e141c}
.cell strong{color:#e2eaf2;font-weight:600}
.muted{color:#7a8a9c;font-size:.78rem}
.thought{margin-top:.35rem;color:#9eb6c9;font-size:.8rem}
.feed{border:1px solid #1e2a38;background:#0e141c;max-height:70vh;overflow:auto;padding:.4rem .5rem}
.ev{padding:.35rem 0;border-bottom:1px solid #16202a;font-size:.75rem}
.ev:last-child{border-bottom:0}
.ev .t{color:#6a7a8c}
.ev .k{color:#a8c4a0}
.empty{color:#5a6a7c;font-size:.78rem;padding:.4rem 0}
</style></head><body>
<h1>LIVING CITY — OPS</h1>
<div class="bar">
  <span class="meta" id="meta">connecting…</span>
  <span class="chips" id="chips"></span>
  <a class="chip" href="/live" style="text-decoration:none;color:#9fd3ff">OPEN 3D LIVE</a>
</div>
<div class="layout">
  <section>
    <h2>Agents</h2>
    <div class="grid" id="grid"><div class="empty">waiting for agents…</div></div>
  </section>
  <section>
    <h2>Cognitive</h2>
    <div class="feed" id="feed"><div class="empty">no events yet</div></div>
  </section>
</div>
<script>
(function(){
  const POLL_MS = 2000;
  let tick = 0, agentsN = 0, wsOk = false, pollTimer = null, healthTimer = null;
  let cognitive = [];
  const esc = s => String(s==null?'':s).replace(/[&<>"']/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));

  function chip(name, ok){
    const cls = ok === true ? 'ok' : ok === false ? 'bad' : 'warn';
    const lab = ok === true ? 'up' : ok === false ? 'down' : '?';
    return `<span class="chip ${cls}">${esc(name)} ${lab}</span>`;
  }

  function renderMeta(){
    const src = wsOk ? 'ws' : 'poll';
    document.getElementById('meta').textContent =
      `tick=${tick}  agents=${agentsN}  transport=${src}`;
  }

  function renderChips(h){
    const el = document.getElementById('chips');
    if(!h){ el.innerHTML = chip('freellm',null)+chip('alveare',null)+chip('hermes',null); return; }
    el.innerHTML =
      chip('freellm', !!(h.freellm&&h.freellm.ok)) +
      chip('alveare', !!(h.alveare&&h.alveare.ok)) +
      chip('hermes', !!(h.hermes&&h.hermes.ok)) +
      `<span class="chip">city ${esc(h.city_built!=null?h.city_built:0)}</span>` +
      `<span class="chip">ws_clients ${esc(h.ws_clients!=null?h.ws_clients:'—')}</span>`;
  }

  function renderAgents(list){
    const g = document.getElementById('grid');
    if(!list || !list.length){ g.innerHTML = '<div class="empty">no agents</div>'; return; }
    g.innerHTML = '';
    list.forEach(x=>{
      const d = document.createElement('div');
      d.className = 'cell';
      d.innerHTML =
        `<strong>${esc(x.name)}</strong> <span class="muted">${esc(x.os_id)}</span><br/>` +
        `<span class="muted">${esc(x.job)} · ${esc(x.course)} · focus=${esc(x.focus)}</span>` +
        `<div class="thought">${esc((x.thought||'').slice(0,160))}</div>`;
      g.appendChild(d);
    });
  }

  function renderFeed(){
    const f = document.getElementById('feed');
    const rows = cognitive.slice(-40).reverse();
    if(!rows.length){ f.innerHTML = '<div class="empty">no events yet</div>'; return; }
    f.innerHTML = rows.map(e=>{
      const typ = e.type || e.event || 'event';
      const who = e.agent_id || e.agent || e.name || '';
      const detail = e.thought || e.choice || e.summary || e.result || JSON.stringify(e).slice(0,120);
      return `<div class="ev"><span class="t">t${esc(e.tick!=null?e.tick:'?')}</span> ` +
        `<span class="k">${esc(typ)}</span> ${esc(who)} — ${esc(String(detail).slice(0,140))}</div>`;
    }).join('');
  }

  function mergeCognitive(batch){
    if(!batch || !batch.length) return;
    const key = e => `${e.tick||''}|${e.type||''}|${e.agent_id||e.agent||''}|${(e.thought||e.choice||'').slice(0,40)}`;
    const seen = new Set(cognitive.map(key));
    batch.forEach(e=>{
      const k = key(e);
      if(!seen.has(k)){ seen.add(k); cognitive.push(e); }
    });
    if(cognitive.length > 200) cognitive = cognitive.slice(-200);
    renderFeed();
  }

  async function fetchHealth(){
    try{
      const h = await fetch('/health').then(r=>r.json());
      if(typeof h.tick === 'number') tick = h.tick;
      if(typeof h.agents === 'number') agentsN = h.agents;
      renderChips(h);
      renderMeta();
      return h;
    }catch(_){ renderChips(null); return null; }
  }

  async function fetchAgents(){
    try{
      const a = await fetch('/v1/agents').then(r=>r.json());
      if(a && a.ok && a.agents){
        agentsN = a.agents.length;
        renderAgents(a.agents);
        renderMeta();
      }
    }catch(_){}
  }

  async function fetchThoughts(){
    try{
      const t = await fetch('/v1/thoughts').then(r=>r.json());
      if(t && t.ok && t.cognitive) mergeCognitive(t.cognitive);
    }catch(_){}
  }

  async function pollOnce(){
    await fetchHealth();
    await fetchAgents();
    if(!wsOk) await fetchThoughts();
  }

  function startPoll(){
    if(pollTimer) return;
    pollTimer = setInterval(pollOnce, POLL_MS);
  }

  function connectWs(){
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    let ws;
    try{ ws = new WebSocket(`${proto}://${location.host}/ws/city`); }
    catch(_){ wsOk = false; startPoll(); return; }

    ws.onopen = ()=>{
      wsOk = true;
      renderMeta();
      fetchThoughts();
      fetchAgents();
    };
    ws.onmessage = (ev)=>{
      let msg;
      try{ msg = JSON.parse(ev.data); }catch(_){ return; }
      if(msg.type === 'tick' || msg.type === 'ping'){
        if(typeof msg.tick === 'number') tick = msg.tick;
        renderMeta();
      }
      if(msg.cognitive && msg.cognitive.length) mergeCognitive(msg.cognitive);
      if(msg.snapshots && msg.snapshots.length){
        /* optional: snapshots may include agent fields — refresh agents lightly */
        fetchAgents();
      }
    };
    ws.onerror = ()=>{ wsOk = false; renderMeta(); };
    ws.onclose = ()=>{
      wsOk = false;
      renderMeta();
      startPoll();
      setTimeout(connectWs, 4000);
    };
  }

  renderChips(null);
  renderMeta();
  pollOnce();
  startPoll();
  healthTimer = setInterval(fetchHealth, 5000);
  connectWs();
})();
</script></body></html>"""


async def panel(_request: Request):
    return HTMLResponse(PANEL_HTML)


async def ws_city(websocket: WebSocket):
    await websocket.accept()
    STATE.subscribers.append(websocket)
    try:
        while True:
            # keep-alive; client may send ping text
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "tick": STATE.tick})
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in STATE.subscribers:
            STATE.subscribers.remove(websocket)


async def _broadcast(payload: dict):
    dead = []
    for ws in list(STATE.subscribers):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in STATE.subscribers:
            STATE.subscribers.remove(ws)


async def _on_tick(tick: int, events: list):
    STATE.tick = tick
    cognitive = [
        e
        for e in events
        if e.get("type")
        in (
            "reflection",
            "career_decision",
            "study_decision",
            "social_decision",
            "exam_result",
            "job_change",
            "city_build",
            "build_propose",
            "build_contribute",
            "build_decision",
            "build_reject",
            "room_decision",
            "room_apply",
            "room_reject",
            "relocate_proposed",
            "relocate_completed",
            "relocate_failed",
            "conversation",
            "research_decision",
        )
    ]
    if cognitive:
        STATE.last_cognitive.extend(cognitive)
        STATE.last_cognitive = STATE.last_cognitive[-200:]
    snaps = [e for e in events if e.get("type") == "snapshot"]
    await _broadcast(
        {
            "type": "tick",
            "tick": tick,
            "snapshots": snaps,  # all agents for live 3D
            "cognitive": cognitive,
        }
    )


async def live_city(_request: Request):
    if _LIVE_HTML.is_file():
        return FileResponse(
            _LIVE_HTML,
            media_type="text/html; charset=utf-8",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )
    return HTMLResponse("<p>viewer/living_city_live.html missing</p>", status_code=404)


def create_app(engine=None) -> Starlette:
    if engine is not None:
        STATE.engine = engine
    routes = [
        Route("/health", health),
        Route("/v1/agents", agents_list),
        Route("/v1/agents/{agent_id}", agent_one),
        Route("/v1/thoughts", thoughts),
        Route("/v1/production/run", production_run, methods=["POST"]),
        Route("/v1/production/recent", production_recent),
        Route("/v1/city", city_state),
        Route("/live", live_city),
        Route("/", panel),
        WebSocketRoute("/ws/city", ws_city),
    ]
    if _VIEWER_DIR.is_dir():
        routes.append(Mount("/viewer", app=StaticFiles(directory=str(_VIEWER_DIR)), name="viewer"))
    app = Starlette(routes=routes)
    return app


async def run_living(
    engine,
    *,
    host: str = "127.0.0.1",
    port: int = 9300,
    realtime: bool = True,
    max_ticks: int | None = None,
    checkpoint_path: str | None = None,
):
    import uvicorn

    STATE.engine = engine
    STATE.stop_event = asyncio.Event()
    app = create_app(engine)

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    async def _loop():
        STATE.loop_result = await run_day_loop(
            engine,
            stop_event=STATE.stop_event,
            realtime=realtime,
            on_tick=_on_tick,
            max_ticks=max_ticks,
            checkpoint_path=checkpoint_path,
        )
        STATE.stop_event.set()
        server.should_exit = True

    STATE.loop_task = asyncio.create_task(_loop())
    await server.serve()
    if STATE.loop_task and not STATE.loop_task.done():
        STATE.stop_event.set()
        await STATE.loop_task
    return STATE.loop_result
