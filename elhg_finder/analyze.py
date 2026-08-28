"""Turn a pile of findings into named market opportunities, using Claude.

The scoring pass tells you which individual posts matter. This pass answers the
question you actually care about: what do fifty of them, taken together, say
somebody would buy?
"""

from __future__ import annotations

import json
import textwrap

from .config import Config
from .db import Database
from .signals import distinct_intents
from .models import Theme

SYSTEM = """You are a market research analyst helping a solo operator find a \
product to build and sell — a digital product, an information product, a \
course, a template, or a productized service they can run from home.

You will receive real questions and posts scraped from Reddit, Hacker News, \
Stack Exchange, Quora and similar Q&A sites. Each was matched because its \
phrasing signals demand: someone said they'd pay, wanted to hire, wished a \
tool existed, or asked how to learn something.

Identify the recurring DEMANDS across these posts. For each one:

- label: a short, concrete name for the demand (5-8 words)
- summary: what people are actually struggling with, in plain language, \
citing the pattern you saw across posts
- opportunity: the specific product that could be sold against it. Be concrete \
— "a $49 spreadsheet template pack for X" beats "a solution for X". Say what \
format, roughly what price, and who would buy it.
- audience: who these people are
- confidence: high | medium | low, based on how many independent posts support \
it and how clearly they signal willingness to pay
- evidence: the id numbers of the posts supporting it

Rules:
- Ground every theme in the posts provided. Do not invent demand that isn't there.
- Prefer specific over broad. "Bookkeeping for Etsy sellers" beats "bookkeeping".
- Favor demands where the asker revealed money intent or where the question \
went unanswered.
- If the evidence for something is thin, say so with low confidence rather than \
dressing it up.
- Note explicitly when a theme looks saturated with existing products.

Return ONLY a JSON array of theme objects. No prose before or after."""


def _format_findings(rows: list[dict], limit: int) -> str:
    lines = []
    for i, r in enumerate(rows[:limit], start=1):
        signals = ", ".join(distinct_intents(json.loads(r.get("signals") or "[]")))
        body = textwrap.shorten(r.get("body") or "", width=500, placeholder=" …")
        lines.append(
            f"[{i}] ({r['source']} · {r.get('community','')} · score {r['demand_score']} "
            f"· signals: {signals})\n"
            f"TITLE: {r['title']}\n"
            f"BODY: {body}\n"
        )
    return "\n".join(lines)


def analyze_themes(
    config: Config,
    db: Database,
    limit: int | None = None,
    replace: bool = True,
) -> list[Theme]:
    """Cluster the top findings into themes and store them.

    Raises RuntimeError with an actionable message if the API key is missing,
    rather than failing deep inside the SDK.
    """
    if not config.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set — the theme analysis needs it. "
            "Everything else in the tool works without it."
        )

    import anthropic

    rows = db.findings_for_analysis(limit=limit or config.analysis_batch)
    if not rows:
        return []

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    payload = _format_findings(rows, limit or config.analysis_batch)

    message = client.messages.create(
        model=config.analysis_model,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Here are {min(len(rows), limit or config.analysis_batch)} demand "
                f"signals collected from public Q&A sites. Identify the recurring "
                f"demands and the products that could be sold against them.\n\n{payload}"
            ),
        }],
    )

    raw = "".join(b.text for b in message.content if b.type == "text").strip()
    themes = _parse_themes(raw, rows)

    if replace:
        db.clear_themes()
    for theme in themes:
        db.save_theme(theme)
    return themes


def _parse_themes(raw: str, rows: list[dict]) -> list[Theme]:
    """Parse the model's JSON, tolerating a stray code fence."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise RuntimeError(f"analysis did not return JSON:\n{raw[:400]}")

    data = json.loads(text[start:end + 1])
    themes: list[Theme] = []
    for item in data:
        evidence = [str(e) for e in item.get("evidence", [])]
        # Average the demand score of the cited posts, so a theme built on
        # strong evidence sorts above one built on weak evidence.
        scores = []
        for ref in evidence:
            try:
                idx = int(str(ref).strip("[]")) - 1
                if 0 <= idx < len(rows):
                    scores.append(rows[idx]["demand_score"])
            except (ValueError, TypeError):
                continue
        themes.append(Theme(
            label=item.get("label", "untitled"),
            summary=item.get("summary", ""),
            opportunity=item.get("opportunity", ""),
            audience=item.get("audience", ""),
            confidence=item.get("confidence", "medium"),
            evidence_ids=evidence,
            demand_score=round(sum(scores) / len(scores), 2) if scores else 0.0,
        ))
    themes.sort(key=lambda t: t.demand_score, reverse=True)
    return themes
