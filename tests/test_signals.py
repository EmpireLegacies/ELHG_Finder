"""Tests for the demand-signal engine and scoring."""

from datetime import datetime, timedelta, timezone

import pytest

from elhg_finder.models import Finding
from elhg_finder.scoring import score_finding
from elhg_finder.signals import Intent, PATTERNS, build_queries, find_signals


def test_patterns_compile():
    for pattern in PATTERNS:
        assert pattern.compiled() is not None


@pytest.mark.parametrize("text,expected", [
    ("I would pay for a tool that does this", Intent.WILLING_TO_PAY),
    ("Looking to hire someone to edit my podcast", Intent.HIRING),
    ("Is there a tool that automates invoices?", Intent.UNMET_TOOL_NEED),
    ("How do I learn bookkeeping from scratch", Intent.LEARNING),
    ("Best side hustle for a stay-at-home mom", Intent.MONETIZE),
    ("We're still doing this manually in Excel", Intent.UNMET_TOOL_NEED),
])
def test_detects_intent(text, expected):
    intents = {i for i, _ in find_signals(text)}
    assert expected in intents


def test_no_signal_in_plain_text():
    assert find_signals("The weather is nice today in Ohio.") == []


def test_one_hit_per_pattern():
    text = "I would pay for this. Seriously I would pay for it. I would pay."
    pay = [s for s in find_signals(text) if s[0] == Intent.WILLING_TO_PAY]
    assert len(pay) == 1


def test_empty_text_is_safe():
    assert find_signals("") == []


def test_build_queries_crosses_topics():
    queries = build_queries(["bookkeeping"], [Intent.WILLING_TO_PAY])
    assert queries
    assert all("bookkeeping" in q for q in queries)


def test_pay_intent_outscores_curiosity():
    now = datetime.now(timezone.utc)
    pay = score_finding(Finding("reddit", "1", "u", "I would pay for X", created_at=now))
    how = score_finding(Finding("reddit", "2", "u", "Can someone explain X", created_at=now))
    assert pay.demand_score > how.demand_score


def test_recency_matters():
    now = datetime.now(timezone.utc)
    fresh = score_finding(Finding("reddit", "1", "u", "How do I learn X", created_at=now))
    stale = score_finding(Finding(
        "reddit", "2", "u", "How do I learn X", created_at=now - timedelta(days=1200)))
    assert fresh.demand_score > stale.demand_score


def test_unanswered_question_scores_higher():
    now = datetime.now(timezone.utc)
    common = dict(source="stackexchange", url="u", title="How do I learn X", created_at=now)
    open_q = score_finding(Finding(external_id="1", is_answered=False, **common))
    closed = score_finding(Finding(external_id="2", is_answered=True, num_comments=3, **common))
    assert open_q.demand_score > closed.demand_score


def test_engagement_is_log_scaled():
    now = datetime.now(timezone.utc)
    small = score_finding(Finding("reddit", "1", "u", "I would pay for X",
                                  created_at=now, score=10, num_comments=2))
    huge = score_finding(Finding("reddit", "2", "u", "I would pay for X",
                                 created_at=now, score=10000, num_comments=900))
    assert huge.demand_score > small.demand_score
    # Log scaling: a 1000x engagement gap must not produce a 1000x score gap.
    assert huge.demand_score < small.demand_score * 3


def test_distinct_intents_dedupes():
    from elhg_finder.signals import distinct_intents
    signals = [("hiring", "a"), ("hiring", "b"), ("learning", "c"), ("hiring", "d")]
    assert distinct_intents(signals) == ["hiring", "learning"]


def test_distinct_intents_handles_empty():
    from elhg_finder.signals import distinct_intents
    assert distinct_intents([]) == []
    assert distinct_intents(None) == []
