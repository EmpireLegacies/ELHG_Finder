"""Command line interface."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .analyze import analyze_themes
from .config import Config
from .db import Database
from .pipeline import describe, run_crawl
from .signals import distinct_intents

app = typer.Typer(add_completion=False, help="Find marketable demand in public Q&A sites.")
console = Console()


def _load(config_path: str) -> tuple[Config, Database]:
    config = Config.load(config_path)
    return config, Database(config.db_path)


@app.command()
def crawl(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    sources: str = typer.Option("", "--sources", "-s", help="Comma-separated subset."),
    days: int = typer.Option(0, "--days", "-d", help="How far back. 0 = config default."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
):
    """Run one crawl across the configured sources."""
    config, db = _load(config_path)
    names = [s.strip() for s in sources.split(",") if s.strip()] or None

    missing = config.missing_credentials()
    if missing and not quiet:
        console.print(f"[yellow]Skipping sources missing credentials:[/] {', '.join(missing)}")

    def progress(source_name: str, finding):
        if not quiet and finding.demand_score >= 8:
            console.print(
                f"  [green]{finding.demand_score:5.1f}[/] [dim]{source_name}[/] "
                f"{finding.title[:90]}"
            )

    with console.status("[bold]Crawling…[/]"):
        result = run_crawl(config, db, names, days or None, "manual", progress)

    console.print()
    console.print(describe(result))
    for name, n in result.per_source.items():
        console.print(f"  [dim]{name}:[/] {n}")
    for err in result.errors:
        console.print(f"  [red]![/] {err}")
    db.close()


@app.command()
def top(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    limit: int = typer.Option(25, "--limit", "-n"),
    source: str = typer.Option("", "--source", "-s"),
    search: str = typer.Option("", "--search"),
    days: int = typer.Option(0, "--days", "-d", help="Only findings first seen in N days."),
):
    """Show the highest-demand findings."""
    config, db = _load(config_path)
    rows = db.top_findings(
        limit=limit, source=source or None, search=search or None,
        since_days=days or None,
    )
    if not rows:
        console.print("[yellow]Nothing stored yet. Run:[/] elhg crawl")
        db.close()
        raise typer.Exit()

    table = Table(show_lines=False, header_style="bold")
    table.add_column("Score", justify="right", style="green", width=6)
    table.add_column("Source", width=13)
    table.add_column("Signals", width=22)
    table.add_column("Title", overflow="fold")
    for r in rows:
        signals = ", ".join(distinct_intents(json.loads(r.get("signals") or "[]")))
        table.add_row(f"{r['demand_score']:.1f}", r["source"], signals[:22], r["title"][:100])
    console.print(table)
    db.close()


@app.command()
def analyze(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    limit: int = typer.Option(0, "--limit", "-n"),
):
    """Cluster stored findings into market opportunities using Claude."""
    config, db = _load(config_path)
    try:
        with console.status("[bold]Analyzing demand themes…[/]"):
            themes = analyze_themes(config, db, limit or None)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        db.close()
        raise typer.Exit(code=1)

    if not themes:
        console.print("[yellow]No findings to analyze yet. Run a crawl first.[/]")
        db.close()
        raise typer.Exit()

    for t in themes:
        console.print()
        console.rule(f"[bold]{t.label}[/]  [dim]({t.confidence}, {t.demand_score})[/]")
        console.print(f"[bold]What's happening:[/] {t.summary}")
        console.print(f"[bold green]Opportunity:[/] {t.opportunity}")
        console.print(f"[bold]Audience:[/] {t.audience}")
    console.print()
    console.print(f"[dim]{len(themes)} themes saved. View them at:[/] elhg serve")
    db.close()


@app.command()
def stats(config_path: str = typer.Option("config.yaml", "--config", "-c")):
    """Summarize what's in the database."""
    config, db = _load(config_path)
    s = db.stats()
    console.print(f"[bold]Findings:[/] {s['total_findings']}  "
                  f"([green]{s['new_last_7d']}[/] in last 7 days)")
    console.print(f"[bold]Themes:[/] {s['themes']}")
    console.print(f"[bold]By source:[/] " +
                  ", ".join(f"{k}={v}" for k, v in s["by_source"].items()))
    if s["top_topics"]:
        table = Table(title="Strongest topics", header_style="bold")
        table.add_column("Topic")
        table.add_column("Findings", justify="right")
        table.add_column("Avg demand", justify="right")
        for t in s["top_topics"]:
            table.add_row(t["topic"], str(t["n"]), str(t["avg"]))
        console.print(table)

    runs = db.recent_runs(5)
    if runs:
        console.print("\n[bold]Recent runs[/]")
        for r in runs:
            console.print(f"  [dim]{r['started_at'][:19]}[/] {r['mode']:8} "
                          f"new={r['new_findings']}  {r['errors'][:60]}")
    db.close()


@app.command()
def export(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    out: str = typer.Option("data/exports/findings.csv", "--out", "-o"),
    limit: int = typer.Option(5000, "--limit", "-n"),
):
    """Export findings to CSV."""
    config, db = _load(config_path)
    rows = db.top_findings(limit=limit)
    if not rows:
        console.print("[yellow]Nothing to export.[/]")
        db.close()
        raise typer.Exit()

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["demand_score", "source", "community", "title", "url",
              "created_at", "score", "num_comments", "topic", "signals", "body"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    console.print(f"[green]Wrote[/] {len(rows)} rows to {path}")
    db.close()


@app.command()
def schedule(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    analyze_after: bool = typer.Option(True, "--analyze/--no-analyze"),
):
    """Run crawls on the configured cron schedule, in the foreground."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    config, db = _load(config_path)

    def job():
        console.print("[dim]Scheduled crawl starting…[/]")
        result = run_crawl(config, db, None, None, "scheduled")
        console.print(describe(result))
        if analyze_after and config.anthropic_api_key and result.new:
            try:
                themes = analyze_themes(config, db)
                console.print(f"[green]Analysis done[/] themes={len(themes)}")
            except RuntimeError as exc:
                console.print(f"[red]Analysis skipped:[/] {exc}")

    scheduler = BlockingScheduler()
    scheduler.add_job(job, CronTrigger.from_crontab(config.schedule_cron))
    console.print(f"[bold]Scheduled[/] '{config.schedule_cron}'. Ctrl-C to stop.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")
    finally:
        db.close()


@app.command()
def serve(
    config_path: str = typer.Option("config.yaml", "--config", "-c"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port", "-p"),
):
    """Start the dashboard."""
    import uvicorn
    from .web.app import create_app

    console.print(f"[bold green]Dashboard:[/] http://{host}:{port}")
    uvicorn.run(create_app(config_path), host=host, port=port, log_level="warning")


@app.command()
def init(config_path: str = typer.Option("config.yaml", "--config", "-c")):
    """Write a starter config.yaml you can edit."""
    path = Path(config_path)
    if path.exists():
        console.print(f"[yellow]{path} already exists — leaving it alone.[/]")
        raise typer.Exit()
    example = Path("config.example.yaml")
    if not example.exists():
        console.print("[red]config.example.yaml is missing from the repo.[/]")
        raise typer.Exit(code=1)
    path.write_text(example.read_text())
    console.print(f"[green]Created[/] {path} — edit the topics list, then run: elhg crawl")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
