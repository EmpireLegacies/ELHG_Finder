"""Reddit via the official OAuth API.

Uses the client-credentials ("script app") flow: no user account is read, only
public listings. Register an app at https://www.reddit.com/prefs/apps.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx

from ..models import Finding
from ..signals import Intent, PATTERNS
from .base import Source, SourceError

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"


class RedditSource(Source):
    name = "reddit"

    def __init__(self, config):
        super().__init__(config)
        self._token = ""
        self._token_expires = 0.0

    def available(self) -> bool:
        return bool(self.config.reddit_client_id and self.config.reddit_client_secret)

    def _authenticate(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        try:
            resp = self.client.post(
                TOKEN_URL,
                auth=(self.config.reddit_client_id, self.config.reddit_client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.config.reddit_user_agent},
            )
        except httpx.HTTPError as exc:
            raise SourceError(f"reddit: token request failed: {exc}") from exc
        if resp.status_code != 200:
            raise SourceError(f"reddit: auth failed ({resp.status_code}) — check credentials")
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires = time.time() + payload.get("expires_in", 3600)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"bearer {self._authenticate()}",
            "User-Agent": self.config.reddit_user_agent,
        }

    def _search_subreddit(self, subreddit: str, query: str, limit: int) -> list[dict]:
        data = self.get_json(
            f"{API}/r/{subreddit}/search",
            params={"q": query, "restrict_sr": "true", "sort": "relevance",
                    "t": "year", "limit": min(limit, 100)},
            headers=self._headers(),
        )
        return [c["data"] for c in data.get("data", {}).get("children", [])]

    def _search_all(self, query: str, limit: int) -> list[dict]:
        data = self.get_json(
            f"{API}/search",
            params={"q": query, "sort": "relevance", "t": "year",
                    "limit": min(limit, 100), "type": "link"},
            headers=self._headers(),
        )
        return [c["data"] for c in data.get("data", {}).get("children", [])]

    def search(self, topics: list[str], since_days: int) -> Iterator[Finding]:
        """Two passes: targeted subreddits, then a site-wide sweep.

        The subreddit pass finds demand among people already self-selected into
        business communities. The site-wide pass catches the rest of Reddit,
        where the same need shows up without the entrepreneurial framing.
        """
        limit = self.config.max_results_per_query
        seen: set[str] = set()

        # Pass 1 — high-signal phrasings inside business/work subreddits.
        strong = [p for p in PATTERNS if p.intent in {
            Intent.WILLING_TO_PAY, Intent.HIRING, Intent.UNMET_TOOL_NEED,
            Intent.MONETIZE, Intent.LEARNING,
        }]
        for subreddit in self.config.subreddits:
            for pattern in strong:
                try:
                    posts = self._search_subreddit(subreddit, f'"{pattern.query}"', limit)
                except SourceError as exc:
                    self.record_error(exc)
                    continue
                for post in posts:
                    if post["id"] in seen:
                        continue
                    seen.add(post["id"])
                    yield self._to_finding(post, topic="", query=pattern.query)

        # Pass 2 — topic seeds crossed with the strongest intents, site-wide.
        for topic in topics:
            for pattern in strong[:8]:
                query = f'"{pattern.query}" {topic}'
                try:
                    posts = self._search_all(query, limit)
                except SourceError as exc:
                    self.record_error(exc)
                    continue
                for post in posts:
                    if post["id"] in seen:
                        continue
                    seen.add(post["id"])
                    yield self._to_finding(post, topic=topic, query=query)

    @staticmethod
    def _to_finding(post: dict, topic: str, query: str) -> Finding:
        created = post.get("created_utc")
        return Finding(
            source="reddit",
            external_id=post["id"],
            url=f"https://reddit.com{post.get('permalink', '')}",
            title=post.get("title", ""),
            body=post.get("selftext", "")[:8000],
            author=post.get("author", ""),
            community=f"r/{post.get('subreddit', '')}",
            created_at=datetime.fromtimestamp(created, tz=timezone.utc) if created else None,
            score=int(post.get("score", 0)),
            num_comments=int(post.get("num_comments", 0)),
            is_answered=int(post.get("num_comments", 0)) > 0,
            topic=topic,
            query=query,
        )
