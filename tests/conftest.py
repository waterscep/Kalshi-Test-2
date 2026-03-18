"""Shared test fixtures."""

import pytest

from kalshi_bot.config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        kalshi_api_key_id="test-key",
        kalshi_private_key_path="test.pem",
        dry_run=True,
    )
