"""Produce static landing artifacts from a small agent crew (rule-based, no LLM)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from engine.tick_engine import CivitasEngine


@dataclass
class CrewMember:
    agent_id: str
    name: str
    job: str
    skills: list[str]
    focus: str | None


@dataclass
class ProductionArtifact:
    slug: str
    artifact_dir: str
    lead_agent_id: str
    crew: list[CrewMember]
    files: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "artifact_dir": self.artifact_dir,
            "lead_agent_id": self.lead_agent_id,
            "crew": [
                {
                    "agent_id": c.agent_id,
                    "name": c.name,
                    "job": c.job,
                    "skills": c.skills,
                    "focus": c.focus,
                }
                for c in self.crew
            ],
            "files": self.files,
        }


def _skill_rank(skills: list[str]) -> int:
    web = {"layout", "motion", "interaction", "webgl"}
    return len(web.intersection(set(skills)))


def select_crew(engine: CivitasEngine, *, crew_size: int = 3) -> list[CrewMember]:
    """Pick lead + crew by web-design skills and study focus."""
    rows: list[tuple[int, str, CrewMember]] = []
    for agent in engine.agents:
        r = agent.r
        improve = getattr(agent.cog, "improve", None)
        focus = getattr(improve, "focus", None) if improve else None
        progress = sum(r.study_progress.values())
        rank = _skill_rank(list(r.skills)) * 10 + progress
        if focus == "study":
            rank += 2
        member = CrewMember(
            agent_id=r.agent_id,
            name=r.persona.display_name,
            job=r.job,
            skills=list(r.skills),
            focus=focus,
        )
        rows.append((rank, r.agent_id, member))
    rows.sort(key=lambda x: (-x[0], x[1]))
    size = max(1, min(crew_size, len(rows)))
    return [m for _, _, m in rows[:size]]


def _slug_from(seed: int, tick: int, lead_id: str, custom: str = "") -> str:
    if custom:
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in custom.strip())[:48]
        return safe.strip("-") or "landing"
    raw = f"{seed}:{tick}:{lead_id}"
    return "run-" + hashlib.sha256(raw.encode()).hexdigest()[:10]


def _render_html(lead: CrewMember, crew: Sequence[CrewMember], city_tagline: str) -> str:
    crew_lines = "\n".join(
        f'          <li><strong>{m.name}</strong> — {m.job} ({", ".join(m.skills[:4])})</li>'
        for m in crew
    )
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Civitas Studio — {lead.name}</title>
  <link rel="stylesheet" href="styles.css"/>
</head>
<body>
  <header class="hero">
    <p class="eyebrow">Civitas Web Design City</p>
    <h1>{lead.name} &amp; crew</h1>
    <p class="lede">{city_tagline}</p>
    <a class="cta" href="#work">Vedi il lavoro</a>
  </header>
  <main id="work">
    <section class="panel">
      <h2>Motion &amp; layout intent</h2>
      <p>Landing prodotta dal production loop locale: tipografia curata, transizioni CSS e struttura semantica verso l'ambizione Awwwards — zero API cloud.</p>
    </section>
    <section class="panel crew">
      <h2>Crew</h2>
      <ul>
{crew_lines}
      </ul>
    </section>
  </main>
  <footer>
    <small>Artifact statico · tick engine Civitas · PII-safe</small>
  </footer>
</body>
</html>
"""


def _render_css(lead: CrewMember) -> str:
    accent = hashlib.sha256(lead.agent_id.encode()).hexdigest()[:6]
    return f""":root {{
  --ink: #0e141c;
  --paper: #f4f0ea;
  --accent: #{accent};
  --muted: #6a7a8c;
  --radius: 14px;
}}

* {{ box-sizing: border-box; }}

body {{
  margin: 0;
  font-family: "Segoe UI", system-ui, sans-serif;
  line-height: 1.55;
  color: var(--ink);
  background: linear-gradient(160deg, var(--paper) 0%, #dfe8f2 100%);
}}

.hero {{
  padding: clamp(2rem, 8vw, 5rem) clamp(1rem, 6vw, 4rem);
  max-width: 960px;
  margin: 0 auto;
}}

.eyebrow {{
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-size: 0.72rem;
  color: var(--muted);
}}

h1 {{
  font-size: clamp(2rem, 5vw, 3.2rem);
  margin: 0.4rem 0 1rem;
}}

.lede {{
  max-width: 42ch;
  font-size: 1.05rem;
}}

.cta {{
  display: inline-block;
  margin-top: 1.25rem;
  padding: 0.75rem 1.4rem;
  border-radius: var(--radius);
  background: var(--accent);
  color: #fff;
  text-decoration: none;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}}

.cta:hover {{
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}}

main {{
  display: grid;
  gap: 1.25rem;
  max-width: 960px;
  margin: 0 auto 3rem;
  padding: 0 clamp(1rem, 6vw, 4rem);
}}

.panel {{
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(14, 20, 28, 0.08);
  border-radius: var(--radius);
  padding: 1.25rem 1.5rem;
}}

.crew ul {{
  margin: 0;
  padding-left: 1.2rem;
}}

footer {{
  text-align: center;
  padding: 2rem 1rem 3rem;
  color: var(--muted);
  font-size: 0.85rem;
}}

@media (prefers-reduced-motion: reduce) {{
  .cta {{ transition: none; }}
  .cta:hover {{ transform: none; }}
}}
"""


def produce_landing(
    engine: CivitasEngine,
    *,
    tick: int,
    portfolio_root: str | Path = "vault/08-PORTFOLIO",
    slug: str = "",
    crew_size: int = 3,
    city_tagline: str = "Una landing scoreabile verso Awwwards, generata dal loop di produzione Civitas.",
) -> ProductionArtifact:
    """Write index.html + styles.css under portfolio_root/{slug}/."""
    crew = select_crew(engine, crew_size=crew_size)
    if not crew:
        raise ValueError("no agents available for crew")
    lead = crew[0]
    run_slug = _slug_from(engine.cfg.seed, tick, lead.agent_id, slug)
    root = Path(portfolio_root) / run_slug
    root.mkdir(parents=True, exist_ok=True)
    html = _render_html(lead, crew, city_tagline)
    css = _render_css(lead)
    (root / "index.html").write_text(html, encoding="utf-8")
    (root / "styles.css").write_text(css, encoding="utf-8")
    return ProductionArtifact(
        slug=run_slug,
        artifact_dir=str(root),
        lead_agent_id=lead.agent_id,
        crew=list(crew),
        files=["index.html", "styles.css"],
    )
