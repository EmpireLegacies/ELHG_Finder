"""Tests for storage, dedup, and filtering."""

from datetime import datetime, timezone

import pytest

from elhg_finder.db import Database
from elhg_finder.models import Finding, Theme


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def make(external_id="a1", score=5, **kw):
    defaults = dict(
        source="reddit", external_id=external_id, url=f"https://r/{external_id}",
        title="I would pay for a bookkeeping tool", body="Really would.",
        community="r/smallbusiness", created_at=datetime.now(timezone.utc),
        score=score, num_comments=3, topic="bookkeeping", demand_score=7.5,
        signals=[("willing_to_pay", "would pay")],
    )
    defaults.update(kw)
    return Finding(**defaults)


def test_insert_then_dedupe(db):
    assert db.upsert_finding(make()) is True
    assert db.upsert_finding(make()) is False
    assert db.stats()["total_findings"] == 1


def test_repeat_sighting_keeps_higher_score(db):
    db.upsert_finding(make(demand_score=9.0))
    db.upsert_finding(make(demand_score=2.0))
    assert db.top_findings()[0]["demand_score"] == 9.0


def test_repeat_sighting_refreshes_engagement(db):
    db.upsert_finding(make(score=5))
    db.upsert_finding(make(score=500))
    assert db.top_findings()[0]["score"] == 500


def test_different_ids_are_separate(db):
    db.upsert_finding(make("a1"))
    db.upsert_finding(make("a2"))
    assert db.stats()["total_findings"] == 2


def test_same_id_different_source_is_separate(db):
    db.upsert_finding(make("x", source="reddit"))
    db.upsert_finding(make("x", source="hackernews"))
    assert db.stats()["total_findings"] == 2


def test_full_text_search(db):
    db.upsert_finding(make("a1", title="I would pay for a bookkeeping tool"))
    db.upsert_finding(make("a2", title="Looking to hire a video editor"))
    assert len(db.top_findings(search="bookkeeping")) == 1
    assert len(db.top_findings(search="editor")) == 1


def test_source_and_topic_filters(db):
    db.upsert_finding(make("a1", source="reddit", topic="bookkeeping"))
    db.upsert_finding(make("a2", source="hackernews", topic="SEO"))
    assert len(db.top_findings(source="reddit")) == 1
    assert len(db.top_findings(topic="SEO")) == 1


def test_min_score_filter(db):
    db.upsert_finding(make("a1", demand_score=9.0))
    db.upsert_finding(make("a2", demand_score=1.0))
    assert len(db.top_findings(min_score=5.0)) == 1


def test_starring(db):
    f = make()
    db.upsert_finding(f)
    db.set_flag(f.fingerprint, "starred", 1)
    assert len(db.top_findings(starred_only=True)) == 1


def test_bad_flag_rejected(db):
    with pytest.raises(ValueError):
        db.set_flag("x", "drop_table", 1)


def test_bad_distinct_column_rejected(db):
    with pytest.raises(ValueError):
        db.distinct("password")


def test_themes_roundtrip(db):
    db.save_theme(Theme(label="Etsy bookkeeping", summary="s", opportunity="o",
                        audience="a", evidence_ids=["1", "2"], demand_score=8.0))
    themes = db.latest_themes()
    assert themes[0]["label"] == "Etsy bookkeeping"
    assert themes[0]["evidence"] == ["1", "2"]


def test_clear_themes(db):
    db.save_theme(Theme(label="x", summary="", opportunity="", audience=""))
    db.clear_themes()
    assert db.latest_themes() == []


def test_run_tracking(db):
    run_id = db.start_run("manual", ["reddit"])
    db.finish_run(run_id, queries=10, found=5, new=3)
    run = db.recent_runs()[0]
    assert run["new_findings"] == 3
    assert run["finished_at"] is not None


def test_stats_top_topics_ranked(db):
    db.upsert_finding(make("a1", topic="bookkeeping", demand_score=9.0))
    db.upsert_finding(make("a2", topic="SEO", demand_score=2.0))
    assert db.stats()["top_topics"][0]["topic"] == "bookkeeping"


def test_themes_ordered_by_demand_not_insert_time(db):
    """The opportunities page must lead with the strongest theme, regardless of
    the order the analysis happened to emit them in."""
    db.save_theme(Theme(label="weak", summary="", opportunity="", audience="",
                        demand_score=3.0))
    db.save_theme(Theme(label="strong", summary="", opportunity="", audience="",
                        demand_score=14.0))
    assert [t["label"] for t in db.latest_themes()] == ["strong", "weak"]
