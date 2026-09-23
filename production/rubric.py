"""Rule-based Awwwards-ish rubric for static landing pages (deterministic)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

RUBRIC_DIMENSIONS: tuple[str, ...] = (
    "layout",
    "motion_interaction",
    "typography_color",
    "originality",
    "craft",
)

_SEMANTIC_TAGS = ("header", "main", "section", "footer", "nav", "article")
_BOILERPLATE = re.compile(
    r"\b(lorem ipsum|welcome to our website|under construction)\b", re.I
)


@dataclass
class RubricScore:
    layout: float
    motion_interaction: float
    typography_color: float
    originality: float
    craft: float
    total: float
    notes: dict[str, list[str]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_pair(artifact_dir: Path) -> tuple[str, str]:
    html_path = artifact_dir / "index.html"
    css_path = artifact_dir / "styles.css"
    html = html_path.read_text(encoding="utf-8", errors="replace") if html_path.is_file() else ""
    css = css_path.read_text(encoding="utf-8", errors="replace") if css_path.is_file() else ""
    return html, css


def _score_layout(html: str, css: str) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 0.0
    if re.search(r"<!doctype\s+html>", html, re.I):
        score += 2.0
    else:
        notes.append("missing doctype")
    if re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.I):
        score += 4.0
    else:
        notes.append("no viewport meta")
    semantic_hits = sum(1 for tag in _SEMANTIC_TAGS if re.search(rf"<{tag}\b", html, re.I))
    score += min(8.0, semantic_hits * 2.0)
    if semantic_hits < 3:
        notes.append("few semantic landmarks")
    if re.search(r"\b(display\s*:\s*(flex|grid)|grid-template|flex-direction)\b", css, re.I):
        score += 4.0
    else:
        notes.append("layout mostly block-level")
    if re.search(r"\bmax-width\s*:\s*\d", css, re.I):
        score += 2.0
    return min(20.0, score), notes


def _score_motion(css: str, html: str) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 0.0
    if re.search(r"\btransition\s*:", css, re.I):
        score += 6.0
    else:
        notes.append("no CSS transitions")
    if re.search(r"\banimation\s*:", css, re.I) or re.search(r"@keyframes\b", css, re.I):
        score += 4.0
    if re.search(r":hover\b", css, re.I):
        score += 4.0
    else:
        notes.append("no hover states")
    if re.search(r"prefers-reduced-motion", css, re.I):
        score += 3.0
    if re.search(r"\b(button|a\.cta|role=[\"']button[\"'])", html, re.I):
        score += 3.0
    return min(20.0, score), notes


def _score_typography_color(css: str) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 0.0
    if re.search(r"font-family\s*:", css, re.I):
        score += 5.0
    else:
        notes.append("generic system fonts only")
    if re.search(r"line-height\s*:", css, re.I):
        score += 3.0
    if re.search(r"--[a-z0-9_-]+\s*:", css, re.I):
        score += 4.0
    else:
        notes.append("no CSS custom properties for palette")
    colors = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    if len(set(colors)) >= 3:
        score += 4.0
    elif colors:
        score += 2.0
        notes.append("limited color palette")
    else:
        notes.append("no hex colors detected")
    if re.search(r"\b(h1|h2|h3)\b", css, re.I) or re.search(r"font-size\s*:\s*clamp", css, re.I):
        score += 4.0
    return min(20.0, score), notes


def _score_originality(html: str, css: str) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 8.0
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) >= 120:
        score += 4.0
    else:
        notes.append("copy is thin")
    if _BOILERPLATE.search(text):
        score -= 6.0
        notes.append("boilerplate phrasing detected")
    custom_props = len(re.findall(r"--[a-z0-9_-]+\s*:", css, re.I))
    score += min(4.0, custom_props * 0.8)
    title = re.search(r"<title>([^<]+)</title>", html, re.I)
    if title and len(title.group(1).strip()) > 12:
        score += 4.0
    return max(0.0, min(20.0, score)), notes


def _score_craft(html: str, css: str) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 0.0
    if re.search(r'<html[^>]+lang=["\'][a-z]{2}', html, re.I):
        score += 3.0
    else:
        notes.append("missing lang on html")
    if re.search(r"\balt\s*=\s*[\"'][^\"']+[\"']", html, re.I):
        score += 3.0
    inline_styles = len(re.findall(r"\sstyle\s*=", html, re.I))
    if inline_styles == 0:
        score += 4.0
    elif inline_styles <= 2:
        score += 2.0
    else:
        notes.append("heavy inline styles")
    if css.strip() and html.strip():
        score += 4.0
    if len(css.splitlines()) >= 20:
        score += 3.0
    else:
        notes.append("stylesheet is minimal")
    if not re.search(r"<script\b", html, re.I):
        score += 3.0  # craft bonus for CSS-first MVP
    return min(20.0, score), notes


def score_landing(artifact_dir: str | Path) -> RubricScore:
    """Score index.html + styles.css under artifact_dir (0–100 total)."""
    root = Path(artifact_dir)
    html, css = _read_pair(root)
    layout, n_layout = _score_layout(html, css)
    motion, n_motion = _score_motion(css, html)
    typo, n_typo = _score_typography_color(css)
    orig, n_orig = _score_originality(html, css)
    craft, n_craft = _score_craft(html, css)
    total = round(layout + motion + typo + orig + craft, 2)
    return RubricScore(
        layout=round(layout, 2),
        motion_interaction=round(motion, 2),
        typography_color=round(typo, 2),
        originality=round(orig, 2),
        craft=round(craft, 2),
        total=total,
        notes={
            "layout": n_layout,
            "motion_interaction": n_motion,
            "typography_color": n_typo,
            "originality": n_orig,
            "craft": n_craft,
        },
    )
