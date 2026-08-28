"""Pipeline tests using a fake source — no network."""

from datetime import datetime, timezone

import pytest

from elhg_finder.config import Config
from elhg_finder.db import Database
from elhg_finder.models import Finding
from elhg_finder.pipeline import run_crawl
from elhg_finder.sources import REGISTRY
from elhg_finder.sources.base import Source, SourceError


class FakeSource(Source):
    name = "fake"
    payload: list[Finding] = []
    explode: bool = False

    def available(self):
        return True

    def search(self, topics, since_days):
        if self.explode:
            raise SourceError("fake: simulated API failure")
        yield from self.payload


@pytest.fixture
def wired(tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "fake", FakeSource)
    config = Config(sources=["fake"], db_path=str(tmp_path / "t.db"))
    return config, Database(config.db_path)


def _post(external_id, title, **kw):
    return Finding(source="fake", external_id=external_id, url="u", title=title,
                   created_at=datetime.now(timezone.utc), score=20,
                   num_comments=5, **kw)


def test_stores_scored_findings(wired):
    config, db = wired
    FakeSource.payload = [_post("1", "I would pay for a bookkeeping tool")]
    FakeSource.explode = False
    result = run_crawl(config, db, ["fake"])
    assert result.new == 1
    assert db.top_findings()[0]["demand_score"] > 0


def test_drops_findings_with_no_signal(wired):
    config, db = wired
    FakeSource.payload = [_post("1", "Nice weather in Ohio today")]
    FakeSource.explode = False
    result = run_crawl(config, db, ["fake"])
    assert result.new == 0
    assert db.stats()["total_findings"] == 0


def test_respects_min_score_threshold(wired):
    config, db = wired
    config.min_score_to_store = 99.0
    FakeSource.payload = [_post("1", "I would pay for a bookkeeping tool")]
    FakeSource.explode = False
    assert run_crawl(config, db, ["fake"]).new == 0


def test_second_run_finds_nothing_new(wired):
    config, db = wired
    FakeSource.payload = [_post("1", "I would pay for a bookkeeping tool")]
    FakeSource.explode = False
    run_crawl(config, db, ["fake"])
    assert run_crawl(config, db, ["fake"]).new == 0


def test_source_failure_is_recorded_not_raised(wired):
    config, db = wired
    FakeSource.payload = []
    FakeSource.explode = True
    result = run_crawl(config, db, ["fake"])
    assert result.errors and "simulated" in result.errors[0]


def test_run_is_logged(wired):
    config, db = wired
    FakeSource.payload = [_post("1", "I would pay for X")]
    FakeSource.explode = False
    run_crawl(config, db, ["fake"], mode="test")
    assert db.recent_runs()[0]["mode"] == "test"


def test_unknown_source_name_rejected(wired):
    config, db = wired
    with pytest.raises(ValueError, match="unknown source"):
        run_crawl(config, db, ["nonexistent"])


class BrokenSource(FakeSource):
    """Every query fails — the outage case."""
    name = "broken"

    def search(self, topics, since_days):
        self.queries_run = 12
        self.record_error(SourceError("broken: HTTP 403"))
        return iter([])


def test_total_failure_is_not_reported_as_empty_market(tmp_path, monkeypatch):
    """A crawl where nothing connected must not look like a quiet market."""
    from elhg_finder.pipeline import describe
    monkeypatch.setitem(REGISTRY, "broken", BrokenSource)
    config = Config(sources=["broken"], db_path=str(tmp_path / "t.db"))
    db = Database(config.db_path)
    result = run_crawl(config, db, ["broken"])

    assert result.new == 0
    assert result.errors, "a total outage must surface errors"
    assert any("connection or credential problem" in e for e in result.errors)
    assert "failed" in describe(result).lower()
    db.close()


def test_per_query_errors_reach_the_run_log(tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "broken", BrokenSource)
    config = Config(sources=["broken"], db_path=str(tmp_path / "t.db"))
    db = Database(config.db_path)
    run_crawl(config, db, ["broken"])
    assert "403" in db.recent_runs()[0]["errors"]
    db.close()


def test_query_count_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "broken", BrokenSource)
    config = Config(sources=["broken"], db_path=str(tmp_path / "t.db"))
    db = Database(config.db_path)
    result = run_crawl(config, db, ["broken"])
    assert result.queries == 12
    assert db.recent_runs()[0]["queries_run"] == 12
    db.close()
