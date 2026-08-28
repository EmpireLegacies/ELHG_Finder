"""Configuration: YAML file for choices, environment variables for secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .signals import DEFAULT_TOPICS

DEFAULT_SUBREDDITS = [
    "smallbusiness", "Entrepreneur", "sidehustle", "WorkOnline", "freelance",
    "digitalnomad", "SaaS", "startups", "AskMarketing", "Blogging",
    "juststart", "EntrepreneurRideAlong", "solopreneur", "smallbusinessowners",
    "WFH", "beermoney", "Upwork", "Fiverr", "passive_income",
    "learnprogramming", "NoCode", "Notion", "automation", "productivity",
    "consulting", "bookkeeping", "Accounting", "smallbusinessUK",
]

DEFAULT_SE_SITES = ["softwarerecs", "freelancing", "workplace", "money", "webapps"]


@dataclass
class Config:
    db_path: str = "data/findings.db"

    topics: list[str] = field(default_factory=lambda: list(DEFAULT_TOPICS))
    subreddits: list[str] = field(default_factory=lambda: list(DEFAULT_SUBREDDITS))
    stackexchange_sites: list[str] = field(default_factory=lambda: list(DEFAULT_SE_SITES))

    sources: list[str] = field(
        default_factory=lambda: ["reddit", "hackernews", "stackexchange", "websearch"]
    )

    # Free APIs get the broad sweep; the metered search API gets only the
    # phrasings most likely to sit near a purchase.
    websearch_intents: list[str] = field(
        default_factory=lambda: ["willing_to_pay", "hiring", "unmet_tool_need"]
    )
    websearch_sites: list[str] = field(
        default_factory=lambda: ["quora.com", "justanswer.com"]
    )
    websearch_provider: str = "brave"        # brave | serper | google
    websearch_max_queries: int = 60          # per run; protects your quota

    backfill_days: int = 365
    schedule_cron: str = "0 6 * * *"         # daily 6am local
    request_delay: float = 1.2               # seconds between API calls
    max_results_per_query: int = 50
    min_score_to_store: float = 2.0

    analysis_model: str = "claude-sonnet-5"
    analysis_batch: int = 300

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        p = Path(path)
        if not p.exists():
            return cls()
        data = yaml.safe_load(p.read_text()) or {}
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys in {p}: {sorted(unknown)}")
        return cls(**data)

    # ------------------------------------------------------------- credentials

    @property
    def reddit_client_id(self) -> str:
        return os.getenv("REDDIT_CLIENT_ID", "")

    @property
    def reddit_client_secret(self) -> str:
        return os.getenv("REDDIT_CLIENT_SECRET", "")

    @property
    def reddit_user_agent(self) -> str:
        return os.getenv("REDDIT_USER_AGENT", "elhg-finder/0.1 (market research)")

    @property
    def search_api_key(self) -> str:
        for var in ("BRAVE_API_KEY", "SERPER_API_KEY", "GOOGLE_API_KEY"):
            if os.getenv(var):
                return os.getenv(var, "")
        return ""

    @property
    def google_cse_id(self) -> str:
        return os.getenv("GOOGLE_CSE_ID", "")

    @property
    def anthropic_api_key(self) -> str:
        return os.getenv("ANTHROPIC_API_KEY", "")

    def missing_credentials(self) -> list[str]:
        """Which configured sources can't run with the current environment."""
        missing = []
        if "reddit" in self.sources and not (self.reddit_client_id and self.reddit_client_secret):
            missing.append("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET")
        if "websearch" in self.sources and not self.search_api_key:
            missing.append("BRAVE_API_KEY (or SERPER_API_KEY / GOOGLE_API_KEY)")
        return missing
