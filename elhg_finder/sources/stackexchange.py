"""Stack Exchange network search.

Unauthenticated calls get 300/day per IP, which is plenty here. The real prize
is ``is_answered``: a question with no accepted answer is demand nobody served.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from ..models import Finding
from ..signals import Intent, PATTERNS
from .base import Source, SourceError

SEARCH = "https://api.stackexchange.com/2.3/search/advanced"


class StackExchangeSource(Source):
    name = "stackexchange"

    def available(self) -> bool:
        return True

    def search(self, topics: list[str], since_days: int) -> Iterator[Finding]:
        from_date = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())
        patterns = [p for p in PATTERNS
                    if p.intent in {Intent.UNMET_TOOL_NEED, Intent.LEARNING, Intent.HOW_TO}]
        seen: set[str] = set()

        for site in self.config.stackexchange_sites:
            for topic in topics:
                for pattern in patterns[:6]:
                    query = f"{pattern.query} {topic}"
                    try:
                        data = self.get_json(SEARCH, params={
                            "order": "desc", "sort": "relevance", "q": query,
                            "site": site, "fromdate": from_date, "filter": "withbody",
                            "pagesize": min(self.config.max_results_per_query, 50),
                        })
                    except SourceError as exc:
                        self.record_error(exc)
                        continue
                    for item in data.get("items", []):
                        qid = f"{site}:{item['question_id']}"
                        if qid in seen:
                            continue
                        seen.add(qid)
                        yield self._to_finding(item, site, topic, query)
                    if not data.get("has_more") and data.get("quota_remaining", 1) < 10:
                        return  # out of daily quota; stop cleanly

    @staticmethod
    def _to_finding(item: dict, site: str, topic: str, query: str) -> Finding:
        created = item.get("creation_date")
        return Finding(
            source="stackexchange",
            external_id=f"{site}:{item['question_id']}",
            url=item.get("link", ""),
            title=item.get("title", ""),
            body=(item.get("body") or "")[:8000],
            author=(item.get("owner") or {}).get("display_name", ""),
            community=site,
            created_at=datetime.fromtimestamp(created, tz=timezone.utc) if created else None,
            score=int(item.get("score") or 0),
            num_comments=int(item.get("answer_count") or 0),
            is_answered=bool(item.get("is_answered")),
            topic=topic,
            query=query,
        )
