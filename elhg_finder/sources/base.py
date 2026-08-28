"""Source adapter interface and shared HTTP behavior."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator

import httpx

from ..config import Config
from ..models import Finding


class SourceError(RuntimeError):
    """A source failed in a way the pipeline should record but survive."""


class Source(ABC):
    name: str = "base"

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.Client(
            timeout=30.0, follow_redirects=True,
            headers={"User-Agent": config.reddit_user_agent},
        )
        self._last_call = 0.0
        self.errors: list[str] = []
        self.queries_run = 0

    def throttle(self) -> None:
        """Space out calls so we stay a polite client of every API."""
        elapsed = time.monotonic() - self._last_call
        wait = self.config.request_delay - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def record_error(self, exc: Exception) -> None:
        """Remember a failure instead of swallowing it.

        Adapters skip past a failed query so one bad response can't end the
        crawl, but the pipeline still needs to know it happened — otherwise a
        total outage is indistinguishable from a quiet market.
        """
        message = str(exc)
        if message not in self.errors:
            self.errors.append(message)

    def get_json(self, url: str, **kwargs) -> dict:
        self.throttle()
        self.queries_run += 1
        try:
            resp = self.client.get(url, **kwargs)
        except httpx.HTTPError as exc:
            raise SourceError(f"{self.name}: request failed: {exc}") from exc
        if resp.status_code == 429:
            raise SourceError(f"{self.name}: rate limited (429)")
        if resp.status_code >= 400:
            raise SourceError(f"{self.name}: HTTP {resp.status_code} for {url}")
        return resp.json()

    @abstractmethod
    def available(self) -> bool:
        """Whether this source has what it needs to run."""

    @abstractmethod
    def search(self, topics: list[str], since_days: int) -> Iterator[Finding]:
        """Yield candidate findings. Scoring and dedup happen downstream."""

    def close(self) -> None:
        self.client.close()
