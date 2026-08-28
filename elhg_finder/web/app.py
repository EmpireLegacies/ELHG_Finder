"""FastAPI dashboard: browse findings, read themes, trigger crawls."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..analyze import analyze_themes
from ..config import Config
from ..db import Database
from ..pipeline import describe, run_crawl
from ..signals import distinct_intents

HERE = Path(__file__).parent


def create_app(config_path: str = "config.yaml") -> FastAPI:
    config = Config.load(config_path)
    db = Database(config.db_path)

    app = FastAPI(title="ELHG Finder")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=str(HERE / "templates"))

    # Surfaced in the UI so a background crawl isn't a silent no-op.
    state = {"running": False, "last": ""}

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        source: str = "",
        topic: str = "",
        q: str = "",
        days: int = 0,
        starred: int = 0,
        limit: int = 60,
    ):
        rows = db.top_findings(
            limit=limit, source=source or None, topic=topic or None,
            search=q or None, since_days=days or None, starred_only=bool(starred),
        )
        for r in rows:
            r["signal_list"] = distinct_intents(json.loads(r.get("signals") or "[]"))
        return templates.TemplateResponse(request=request, name="index.html", context={
            "rows": rows,
            "stats": db.stats(),
            "sources": db.distinct("source"),
            "topics": db.distinct("topic"),
            "filters": {"source": source, "topic": topic, "q": q,
                        "days": days, "starred": starred, "limit": limit},
            "state": state,
        })

    @app.get("/themes", response_class=HTMLResponse)
    def themes(request: Request):
        return templates.TemplateResponse(request=request, name="themes.html", context={
            "themes": db.latest_themes(50),
            "stats": db.stats(),
            "state": state,
        })

    @app.post("/crawl")
    def crawl(background: BackgroundTasks):
        def job():
            state["running"] = True
            try:
                result = run_crawl(config, db, None, None, "dashboard")
                state["last"] = describe(result)
                if result.errors:
                    state["last"] += f" — {result.errors[0]}"
            except Exception as exc:
                state["last"] = f"failed: {exc}"
            finally:
                state["running"] = False

        if not state["running"]:
            background.add_task(job)
        return RedirectResponse("/", status_code=303)

    @app.post("/analyze")
    def analyze(background: BackgroundTasks):
        def job():
            state["running"] = True
            try:
                found = analyze_themes(config, db)
                state["last"] = f"{len(found)} themes identified"
            except Exception as exc:
                state["last"] = f"analysis failed: {exc}"
            finally:
                state["running"] = False

        if not state["running"]:
            background.add_task(job)
        return RedirectResponse("/themes", status_code=303)

    @app.post("/star/{fingerprint}")
    def star(fingerprint: str, value: int = Form(1)):
        db.set_flag(fingerprint, "starred", value)
        return RedirectResponse("/", status_code=303)

    @app.get("/api/findings")
    def api_findings(limit: int = 100, source: str = "", q: str = ""):
        return db.top_findings(limit=limit, source=source or None, search=q or None)

    @app.get("/api/themes")
    def api_themes():
        return db.latest_themes(50)

    @app.get("/api/stats")
    def api_stats():
        return {**db.stats(), "running": state["running"], "last": state["last"]}

    return app
