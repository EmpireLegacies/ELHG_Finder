"""Demand scoring.

A finding's score answers one question: how strongly does this suggest someone
would hand over money? Four inputs, deliberately simple so you can argue with
the weights and change them.
"""

from __future__ import annotations

import math

from .models import Finding
from .signals import INTENT_WEIGHT, Intent, find_signals

# Relative contribution of each component to the final score.
W_INTENT = 1.0        # what the phrasing reveals
W_ENGAGEMENT = 0.8    # how many other people cared
W_RECENCY = 0.6       # whether the demand is current
W_UNANSWERED = 2.0    # nobody solved it = the gap is still open


def intent_component(signals: list[tuple[str, str]]) -> float:
    """Highest-weight intent, plus a small bonus for corroborating signals.

    Taking the max rather than the sum stops a rambling post from outscoring a
    short one that says "I'll pay for this."
    """
    if not signals:
        return 0.0
    weights = []
    for intent_value, _matched in signals:
        try:
            weights.append(INTENT_WEIGHT[Intent(intent_value)])
        except ValueError:
            continue
    if not weights:
        return 0.0
    return max(weights) + 0.3 * (len(weights) - 1)


def engagement_component(score: int, num_comments: int) -> float:
    """Log-scaled so a 5,000-upvote thread doesn't drown everything else."""
    return math.log1p(max(0, score)) + 1.5 * math.log1p(max(0, num_comments))


def recency_component(age_days: float) -> float:
    """Six-month half-life. Demand from 2019 is history, not a market."""
    return 5.0 * math.exp(-age_days / 180.0)


def unanswered_bonus(is_answered: bool, num_comments: int) -> float:
    """An unanswered question is an unserved customer.

    Applied to sources that actually tell us (Stack Exchange accepted answers,
    zero-comment Reddit threads).
    """
    if not is_answered:
        return W_UNANSWERED
    if num_comments == 0:
        return W_UNANSWERED * 0.5
    return 0.0


def score_finding(f: Finding) -> Finding:
    """Attach signals and a demand score to a finding, in place."""
    if not f.signals:
        f.signals = [(intent.value, matched) for intent, matched in find_signals(f.text)]
    total = (
        W_INTENT * intent_component(f.signals)
        + W_ENGAGEMENT * engagement_component(f.score, f.num_comments)
        + W_RECENCY * recency_component(f.age_days)
        + unanswered_bonus(f.is_answered, f.num_comments)
    )
    f.demand_score = round(total, 2)
    return f
