"""Hacker News via the Algolia search API. No key, no auth, generous limits."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from ..models import Finding
from ..signals import Intent, PATTERNS
from .base import Source, SourceError

SEARCH = "https://hn.algolia.com/api/v1/search"


class HackerNewsSource(Source):
    name = "hackernews"

    def available(self) -> bool:
        return True

    def search(self, topics: list[str], since_days: int) -> Iterator[Finding]:
        cutoff = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())
        patterns = [p for p in PATTERNS if p.intent in {
            Intent.WILLING_TO_PAY, Intent.UNMET_TOOL_NEED, Intent.HIRING,
            Intent.MONETIZE,
        }]
        seen: set[str] = set()

        for pattern in patterns:
            for query in (pattern.query, *(f"{pattern.query} {t}" for t in topics[:12])):
                try:
                    data = self.get_json(SEARCH, params={
                        "query": query,
                        "tags": "(story,comment)",
                        "numericFilters": f"created_at_i>{cutoff}",
                        "hitsPerPage": min(self.config.max_results_per_query, 50),
                    })
                except SourceError as exc:
                    self.record_error(exc)
                    continue
                for hit in data.get("hits", []):
                    oid = str(hit.get("objectID"))
                    if oid in seen:
                        continue
                    seen.add(oid)
                    yield self._to_finding(hit, query)

    @staticmethod
    def _to_finding(hit: dict, query: str) -> Finding:
        created = hit.get("created_at_i")
        title = hit.get("title") or hit.get("story_title") or "(comment)"
        return Finding(
            source="hackernews",
            external_id=str(hit["objectID"]),
            url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
            title=title,
            body=(hit.get("comment_text") or hit.get("story_text") or "")[:8000],
            author=hit.get("author", ""),
            community="Hacker News",
            created_at=datetime.fromtimestamp(created, tz=timezone.utc) if created else None,
            score=int(hit.get("points") or 0),
            num_comments=int(hit.get("num_comments") or 0),
            query=query,
        )
