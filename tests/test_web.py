"""Dashboard smoke tests — these catch startup-time failures like a missing
template dependency, which no unit test would surface."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from elhg_finder.db import Database
from elhg_finder.models import Finding, Theme
from elhg_finder.scoring import score_finding
from elhg_finder.web.app import create_app


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "web.db"
    db = Database(db_path)
    db.upsert_finding(score_finding(Finding(
        source="reddit", external_id="w1", url="https://example.com/1",
        title="I would pay for a bookkeeping service",
        body="Etsy seller drowning in reconciliation.", community="r/smallbusiness",
        topic="bookkeeping", created_at=datetime.now(timezone.utc),
        score=120, num_comments=40)))
    db.save_theme(Theme(label="Done-for-you bookkeeping", summary="s",
                        opportunity="A $79/mo service", audience="Etsy sellers",
                        confidence="high", evidence_ids=["1"], demand_score=12.0))
    db.close()

    config = tmp_path / "c.yaml"
    config.write_text(f"db_path: {db_path}\n")
    return TestClient(create_app(str(config)))


@pytest.mark.parametrize("path", [
    "/", "/themes", "/api/stats", "/api/findings", "/api/themes",
])
def test_pages_load(client, path):
    assert client.get(path).status_code == 200


def test_findings_page_shows_content(client):
    body = client.get("/").text
    assert "bookkeeping" in body
    assert "willing to pay" in body       # signal tag rendered


def test_themes_page_shows_opportunity(client):
    body = client.get("/themes").text
    assert "Done-for-you bookkeeping" in body
    assert "$79/mo" in body


def test_search_filter(client):
    assert "bookkeeping" in client.get("/?q=bookkeeping").text
    assert len(client.get("/api/findings?q=nonexistentterm").json()) == 0


def test_star_toggle_persists(client):
    fingerprint = client.get("/api/findings").json()[0]["fingerprint"]
    client.post(f"/star/{fingerprint}", data={"value": 1}, follow_redirects=False)
    assert client.get("/api/findings").json()[0]["starred"] == 1


def test_api_stats_shape(client):
    stats = client.get("/api/stats").json()
    assert stats["total_findings"] == 1
    assert "running" in stats
