"""SQLite storage. One file, no server, safe to copy around."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Finding, Theme

SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    fingerprint   TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT,
    author        TEXT,
    community     TEXT,
    created_at    TEXT,
    score         INTEGER DEFAULT 0,
    num_comments  INTEGER DEFAULT 0,
    is_answered   INTEGER DEFAULT 1,
    topic         TEXT,
    query         TEXT,
    signals       TEXT,
    demand_score  REAL DEFAULT 0,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    reviewed      INTEGER DEFAULT 0,
    starred       INTEGER DEFAULT 0,
    notes         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_findings_score   ON findings(demand_score DESC);
CREATE INDEX IF NOT EXISTS idx_findings_source  ON findings(source);
CREATE INDEX IF NOT EXISTS idx_findings_topic   ON findings(topic);
CREATE INDEX IF NOT EXISTS idx_findings_created ON findings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_seen    ON findings(first_seen DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS findings_fts USING fts5(
    title, body, content='findings', content_rowid='rowid'
);

CREATE TABLE IF NOT EXISTS themes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT NOT NULL,
    summary       TEXT,
    opportunity   TEXT,
    audience      TEXT,
    confidence    TEXT,
    demand_score  REAL DEFAULT 0,
    evidence      TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_themes_created ON themes(created_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    mode          TEXT,
    sources       TEXT,
    queries_run   INTEGER DEFAULT 0,
    found         INTEGER DEFAULT 0,
    new_findings  INTEGER DEFAULT 0,
    errors        TEXT DEFAULT ''
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- findings

    def upsert_finding(self, f: Finding) -> bool:
        """Store a finding. Returns True if it was new to the database.

        A repeat sighting keeps the higher demand score and refreshes engagement
        counts, since a thread that grew from 2 to 200 comments matters more.
        """
        now = _now()
        cur = self.conn.execute(
            "SELECT demand_score FROM findings WHERE fingerprint = ?", (f.fingerprint,)
        )
        row = cur.fetchone()
        created = f.created_at.isoformat() if f.created_at else None
        signals = json.dumps(f.signals)

        if row is None:
            self.conn.execute(
                """INSERT INTO findings
                   (fingerprint, source, external_id, url, title, body, author,
                    community, created_at, score, num_comments, is_answered,
                    topic, query, signals, demand_score, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f.fingerprint, f.source, f.external_id, f.url, f.title, f.body,
                 f.author, f.community, created, f.score, f.num_comments,
                 int(f.is_answered), f.topic, f.query, signals, f.demand_score,
                 now, now),
            )
            rowid = self.conn.execute(
                "SELECT rowid FROM findings WHERE fingerprint = ?", (f.fingerprint,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO findings_fts(rowid, title, body) VALUES (?,?,?)",
                (rowid, f.title, f.body),
            )
            self.conn.commit()
            return True

        self.conn.execute(
            """UPDATE findings
               SET last_seen = ?, score = ?, num_comments = ?,
                   demand_score = MAX(demand_score, ?), is_answered = ?
               WHERE fingerprint = ?""",
            (now, f.score, f.num_comments, f.demand_score, int(f.is_answered),
             f.fingerprint),
        )
        self.conn.commit()
        return False

    def top_findings(
        self,
        limit: int = 100,
        source: str | None = None,
        topic: str | None = None,
        min_score: float = 0.0,
        since_days: int | None = None,
        search: str | None = None,
        starred_only: bool = False,
    ) -> list[dict]:
        sql = "SELECT * FROM findings WHERE demand_score >= ?"
        params: list = [min_score]
        if source:
            sql += " AND source = ?"
            params.append(source)
        if topic:
            sql += " AND topic = ?"
            params.append(topic)
        if starred_only:
            sql += " AND starred = 1"
        if since_days is not None:
            sql += " AND first_seen >= datetime('now', ?)"
            params.append(f"-{int(since_days)} days")
        if search:
            sql += (" AND rowid IN (SELECT rowid FROM findings_fts "
                    "WHERE findings_fts MATCH ?)")
            params.append(search)
        sql += " ORDER BY demand_score DESC, score DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params)]

    def findings_for_analysis(self, limit: int = 400, min_score: float = 3.0) -> list[dict]:
        """Highest-signal findings, for the AI theme pass."""
        return self.top_findings(limit=limit, min_score=min_score)

    def set_flag(self, fingerprint: str, field: str, value: int) -> None:
        if field not in {"reviewed", "starred"}:
            raise ValueError(f"unknown flag: {field}")
        self.conn.execute(
            f"UPDATE findings SET {field} = ? WHERE fingerprint = ?", (value, fingerprint)
        )
        self.conn.commit()

    def set_notes(self, fingerprint: str, notes: str) -> None:
        self.conn.execute(
            "UPDATE findings SET notes = ? WHERE fingerprint = ?", (notes, fingerprint)
        )
        self.conn.commit()

    # ------------------------------------------------------------------ themes

    def save_theme(self, t: Theme) -> int:
        cur = self.conn.execute(
            """INSERT INTO themes
               (label, summary, opportunity, audience, confidence, demand_score,
                evidence, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (t.label, t.summary, t.opportunity, t.audience, t.confidence,
             t.demand_score, json.dumps(t.evidence_ids), _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def latest_themes(self, limit: int = 30) -> list[dict]:
        """Strongest opportunity first — that is the only order worth reading."""
        rows = self.conn.execute(
            "SELECT * FROM themes ORDER BY demand_score DESC, created_at DESC LIMIT ?",
            (limit,),
        )
        out = []
        for r in rows:
            d = dict(r)
            d["evidence"] = json.loads(d.get("evidence") or "[]")
            out.append(d)
        return out

    def clear_themes(self) -> None:
        self.conn.execute("DELETE FROM themes")
        self.conn.commit()

    # -------------------------------------------------------------------- runs

    def start_run(self, mode: str, sources: list[str]) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, mode, sources) VALUES (?,?,?)",
            (_now(), mode, ",".join(sources)),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, queries: int, found: int,
                   new: int, errors: str = "") -> None:
        self.conn.execute(
            """UPDATE runs SET finished_at = ?, queries_run = ?, found = ?,
                   new_findings = ?, errors = ? WHERE id = ?""",
            (_now(), queries, found, new, errors, run_id),
        )
        self.conn.commit()

    def recent_runs(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]

    # ------------------------------------------------------------------- stats

    def stats(self) -> dict:
        c = self.conn
        total = c.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        by_source = {r[0]: r[1] for r in c.execute(
            "SELECT source, COUNT(*) FROM findings GROUP BY source")}
        top_topics = [dict(topic=r[0], n=r[1], avg=round(r[2] or 0, 2))
                      for r in c.execute(
                          """SELECT topic, COUNT(*) n, AVG(demand_score) a
                             FROM findings WHERE topic != ''
                             GROUP BY topic ORDER BY a DESC, n DESC LIMIT 15""")]
        new_7d = c.execute(
            "SELECT COUNT(*) FROM findings WHERE first_seen >= datetime('now','-7 days')"
        ).fetchone()[0]
        themes = c.execute("SELECT COUNT(*) FROM themes").fetchone()[0]
        return {
            "total_findings": total,
            "by_source": by_source,
            "top_topics": top_topics,
            "new_last_7d": new_7d,
            "themes": themes,
        }

    def distinct(self, column: str) -> list[str]:
        if column not in {"source", "topic", "community"}:
            raise ValueError(f"unsupported column: {column}")
        return [r[0] for r in self.conn.execute(
            f"SELECT DISTINCT {column} FROM findings WHERE {column} != '' ORDER BY 1")]
