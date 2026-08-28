"""Core records passed between sources, storage, and analysis."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Finding:
    """One post, question, or answer that matched at least one demand signal."""

    source: str                     # "reddit" | "stackexchange" | "hackernews" | "websearch"
    external_id: str                # id within that source
    url: str
    title: str
    body: str = ""
    author: str = ""
    community: str = ""             # subreddit, SE site, or domain
    created_at: datetime | None = None
    score: int = 0                  # upvotes / points
    num_comments: int = 0
    is_answered: bool = True        # False is a strong unmet-demand signal
    topic: str = ""                 # seed topic that surfaced it
    query: str = ""                 # exact query used
    signals: list[tuple[str, str]] = field(default_factory=list)
    demand_score: float = 0.0

    @property
    def fingerprint(self) -> str:
        """Stable identity for dedup across overlapping queries.

        Keyed on source + external id, so the same Reddit thread found by six
        different queries is stored once with the best score it earned.
        """
        raw = f"{self.source}:{self.external_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @property
    def text(self) -> str:
        return f"{self.title}\n\n{self.body}".strip()

    @property
    def age_days(self) -> float:
        if not self.created_at:
            return 365.0
        created = self.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400)


@dataclass
class Theme:
    """A cluster of findings that represent one recurring demand."""

    label: str
    summary: str
    opportunity: str                # what could be sold against it
    audience: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: str = "medium"      # low | medium | high
    demand_score: float = 0.0
    created_at: datetime | None = None
