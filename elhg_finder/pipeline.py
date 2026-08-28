"""Crawl orchestration: fetch from every source, score, dedup, store."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .db import Database
from .models import Finding
from .scoring import score_finding
from .sources import SourceError, build_sources


@dataclass
class RunResult:
    queries: int = 0
    seen: int = 0
    stored: int = 0
    new: int = 0
    errors: list[str] = field(default_factory=list)
    per_source: dict[str, int] = field(default_factory=dict)


def run_crawl(
    config: Config,
    db: Database,
    sources: list[str] | None = None,
    since_days: int | None = None,
    mode: str = "manual",
    progress=None,
) -> RunResult:
    """Run one full pass over the configured sources.

    Findings below ``min_score_to_store`` are dropped rather than stored, which
    keeps the database made of things worth reading. A source that fails is
    recorded and skipped; one dead API never takes down the run.
    """
    since = since_days if since_days is not None else config.backfill_days
    active = build_sources(config, sources)
    result = RunResult()

    if not active:
        result.errors.append(
            "No sources available. Missing: " + ", ".join(config.missing_credentials())
        )
        return result

    run_id = db.start_run(mode, [s.name for s in active])

    for source in active:
        count = 0
        try:
            for finding in source.search(config.topics, since):
                result.seen += 1
                score_finding(finding)
                if finding.demand_score < config.min_score_to_store:
                    continue
                if not finding.signals:
                    continue
                is_new = db.upsert_finding(finding)
                result.stored += 1
                count += 1
                if is_new:
                    result.new += 1
                if progress:
                    progress(source.name, finding)
        except SourceError as exc:
            result.errors.append(str(exc))
        except Exception as exc:  # a broken adapter shouldn't kill the crawl
            result.errors.append(f"{source.name}: unexpected error: {exc}")
        finally:
            result.per_source[source.name] = count
            result.queries += source.queries_run
            # Per-query failures the adapter skipped past. Capped so a total
            # outage doesn't write a thousand identical lines into the run log.
            result.errors.extend(source.errors[:5])
            if source.errors and count == 0 and source.queries_run:
                result.errors.append(
                    f"{source.name}: every query failed ({source.queries_run} attempted) "
                    f"— this is a connection or credential problem, not an empty market."
                )
            source.close()

    db.finish_run(run_id, result.queries, result.stored, result.new,
                  "; ".join(result.errors))
    return result


def describe(result: RunResult) -> str:
    """One-line human summary, honest about the difference between
    'found nothing' and 'never connected'."""
    if result.queries and not result.seen and result.errors:
        return "Crawl failed — no source returned data. Check credentials and network."
    if not result.seen:
        return "Crawl completed but matched nothing. Try broadening topics."
    return (f"{result.new} new, {result.stored} kept, {result.seen} seen "
            f"across {result.queries} queries.")
