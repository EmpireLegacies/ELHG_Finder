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
        total_queries = 0
        empty_queries = 0
        sample = ""

        for site in self.config.stackexchange_sites:
            for topic in topics:
                for pattern in patterns[:6]:
                    query = f"{pattern.query} {topic}"
                    total_queries += 1
                    try:
                        data = self.get_json(SEARCH, params={
                            "order": "desc", "sort": "relevance", "q": query,
                            "site": site, "fromdate": from_date, "filter": "withbody",
                            "pagesize": min(self.config.max_results_per_query, 50),
                        })
                    except SourceError as exc:
                        self.record_error(exc)
                        continue

                    items = data.get("items", [])
                    quota = data.get("quota_remaining")

                    if not items:
                        # A 200 response can still be a refusal: Stack Exchange
                        # reports throttling and bad requests in the body, not
                        # in the status code. Reading only "items" makes an API
                        # saying no look exactly like an empty market.
                        api_error = data.get("error_message") or data.get("error_name")
                        if api_error:
                            self.record_error(SourceError(
                                f"{self.name}: {site}: API error: {api_error} "
                                f"(quota_remaining={quota}, backoff={data.get('backoff')})"
                            ))
                        else:
                            empty_queries += 1
                            if not sample:
                                sample = (
                                    f"first empty response: site={site} q={query!r} "
                                    f"keys={sorted(data.keys())} quota_remaining={quota}"
                                )
                    else:
                        for item in items:
                            qid = f"{site}:{item['question_id']}"
                            if qid in seen:
                                continue
                            seen.add(qid)
                            yield self._to_finding(item, site, topic, query)

                    if not data.get("has_more") and (quota if quota is not None else 1) < 10:
                        self.record_error(SourceError(
                            f"{self.name}: stopped early, daily quota nearly exhausted "
                            f"(quota_remaining={quota}) after {total_queries} queries"
                        ))
                        return  # out of daily quota; stop cleanly

        if total_queries and empty_queries == total_queries:
            # Reached only when every single query came back well-formed and
            # empty. That is a signal about the request shape, not the market.
            self.record_error(SourceError(
                f"{self.name}: all {total_queries} queries returned zero items with no "
                f"API error. Either these phrasings are too literal for Stack Exchange "
                f"full-text search, or the request shape is wrong. {sample}"
            ))

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
