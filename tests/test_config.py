"""Tests for configuration loading."""

import pytest

from elhg_finder.config import Config


def test_defaults_are_usable():
    c = Config()
    assert c.topics and c.subreddits and c.sources


def test_missing_file_returns_defaults(tmp_path):
    assert Config.load(tmp_path / "nope.yaml").topics == Config().topics


def test_loads_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("topics:\n  - widgets\nbackfill_days: 30\n")
    c = Config.load(path)
    assert c.topics == ["widgets"]
    assert c.backfill_days == 30


def test_unknown_key_is_rejected(tmp_path):
    """A typo in config.yaml should fail loudly, not be silently ignored."""
    path = tmp_path / "config.yaml"
    path.write_text("toppics:\n  - widgets\n")
    with pytest.raises(ValueError, match="unknown config keys"):
        Config.load(path)


def test_missing_credentials_reported(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    missing = Config().missing_credentials()
    assert any("REDDIT" in m for m in missing)
    assert any("BRAVE" in m for m in missing)


def test_keyless_sources_need_nothing(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    c = Config(sources=["hackernews", "stackexchange"])
    assert c.missing_credentials() == []
