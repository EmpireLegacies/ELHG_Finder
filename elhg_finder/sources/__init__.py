"""Source adapters. Add a new site by subclassing Source and registering here."""

from ..config import Config
from .base import Source, SourceError
from .hackernews import HackerNewsSource
from .reddit import RedditSource
from .stackexchange import StackExchangeSource
from .websearch import WebSearchSource

REGISTRY: dict[str, type[Source]] = {
    "reddit": RedditSource,
    "hackernews": HackerNewsSource,
    "stackexchange": StackExchangeSource,
    "websearch": WebSearchSource,
}


def build_sources(config: Config, names: list[str] | None = None) -> list[Source]:
    """Instantiate the configured sources that can actually run."""
    wanted = names or config.sources
    built = []
    for name in wanted:
        cls = REGISTRY.get(name)
        if cls is None:
            raise ValueError(f"unknown source: {name} (known: {sorted(REGISTRY)})")
        source = cls(config)
        if source.available():
            built.append(source)
        else:
            source.close()
    return built


__all__ = ["Source", "SourceError", "REGISTRY", "build_sources"]
