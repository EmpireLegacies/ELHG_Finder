"""Search-API layer for sites that can't or shouldn't be crawled directly.

Quora and JustAnswer both forbid scraping in their terms and sit behind bot
protection. Their pages are, however, indexed — so we ask a search API for
``site:quora.com "phrase"`` and work from the returned titles and snippets.
Shallower than a crawl, and it keeps you on the right side of the line.

Three providers behind one interface; set whichever key you have.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..models import Finding
from ..signals import Intent, PATTERNS
from .base import Source, SourceError

PROVIDERS = {
    "brave": "https://api.search.brave.com/res/v1/web/search",
    "serper": "https://google.serper.dev/search",
    "google": "https://www.googleapis.com/customsearch/v1",
}


class WebSearchSource(Source):
    name = "websearch"

    def available(self) -> bool:
        if not self.config.search_api_key:
            return False
        if self.config.websearch_provider == "google" and not self.config.google_cse_id:
            return False
        return self.config.websearch_provider in PROVIDERS

    # ------------------------------------------------------------- providers

    def _brave(self, query: str, count: int) -> list[dict]:
        data = self.get_json(
            PROVIDERS["brave"],
            params={"q": query, "count": min(count, 20)},
            headers={"X-Subscription-Token": self.config.search_api_key,
                     "Accept": "application/json"},
        )
        return [
            {"title": r.get("title", ""), "snippet": r.get("description", ""),
             "url": r.get("url", ""), "age": r.get("age", "")}
            for r in data.get("web", {}).get("results", [])
        ]

    def _serper(self, query: str, count: int) -> list[dict]:
        self.throttle()
        self.queries_run += 1
        resp = self.client.post(
            PROVIDERS["serper"],
            json={"q": query, "num": min(count, 20)},
            headers={"X-API-KEY": self.config.search_api_key,
                     "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            raise SourceError(f"serper: HTTP {resp.status_code}")
        return [
            {"title": r.get("title", ""), "snippet": r.get("snippet", ""),
             "url": r.get("link", ""), "age": r.get("date", "")}
            for r in resp.json().get("organic", [])
        ]

    def _google(self, query: str, count: int) -> list[dict]:
        data = self.get_json(PROVIDERS["google"], params={
            "key": self.config.search_api_key, "cx": self.config.google_cse_id,
            "q": query, "num": min(count, 10),
        })
        return [
            {"title": r.get("title", ""), "snippet": r.get("snippet", ""),
             "url": r.get("link", ""), "age": ""}
            for r in data.get("items", [])
        ]

    def _run_query(self, query: str) -> list[dict]:
        provider = self.config.websearch_provider
        fn = {"brave": self._brave, "serper": self._serper, "google": self._google}[provider]
        return fn(query, self.config.max_results_per_query)

    # ---------------------------------------------------------------- search

    def search(self, topics: list[str], since_days: int) -> Iterator[Finding]:
        """Spend the metered quota only on high-intent phrasings.

        ``websearch_max_queries`` is a hard stop so a wide topic list can't
        silently burn through a month of your search allowance in one run.
        """
        wanted = {Intent(i) for i in self.config.websearch_intents}
        patterns = [p for p in PATTERNS if p.intent in wanted]
        budget = self.config.websearch_max_queries
        spent = 0
        seen: set[str] = set()

        for site in self.config.websearch_sites:
            for pattern in patterns:
                for topic in topics:
                    if spent >= budget:
                        return
                    query = f'site:{site} "{pattern.query}" {topic}'
                    spent += 1
                    try:
                        results = self._run_query(query)
                    except SourceError as exc:
                        self.record_error(exc)
                        continue
                    for r in results:
                        url = r.get("url", "")
                        if not url or url in seen:
                            continue
                        seen.add(url)
                        yield self._to_finding(r, topic, query)

    @staticmethod
    def _clean(text: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()

    def _to_finding(self, r: dict, topic: str, query: str) -> Finding:
        url = r["url"]
        domain = urlparse(url).netloc.replace("www.", "")
        return Finding(
            source="websearch",
            external_id=url,
            url=url,
            title=self._clean(r.get("title", "")),
            body=self._clean(r.get("snippet", "")),
            community=domain,
            created_at=self._parse_age(r.get("age", "")),
            topic=topic,
            query=query,
            # Search snippets never tell us whether the question got a good
            # answer, so we stay neutral rather than inventing a bonus.
            is_answered=True,
        )

    @staticmethod
    def _parse_age(age: str) -> datetime | None:
        if not age:
            return None
        try:
            from dateutil import parser
            return parser.parse(age).replace(tzinfo=timezone.utc)
        except Exception:
            return None
