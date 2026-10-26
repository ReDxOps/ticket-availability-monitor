"""Tests for configuration loading and validation."""

from datetime import datetime, timezone, timedelta
import pytest
from src.config import Settings


def test_default_settings():
    settings = Settings(_env_file=None)
    assert settings.seetickets_site_id == 496
    assert settings.seetickets_event_id == 2768
    assert settings.seetickets_category_id == 7897
    assert settings.poll_interval_seconds == 6
    assert settings.target_tickets_count == 2
    assert settings.consecutive_errors_threshold == 10
    assert settings.db_path == "data/monitor.db"
    assert settings.category_url == (
        "https://resell.seetickets.com/dreamnation2026/category/7897/dream-nation-2026-pass-1-jour-vendredi"
    )
    assert settings.get_advert_url(705901) == (
        "https://resell.seetickets.com/dreamnation2026/category/7897/dream-nation-2026-pass-1-jour-vendredi?advert=705901"
    )


def test_poll_interval_minimum_validation():
    with pytest.raises(ValueError, match="poll_interval_seconds must be at least 4"):
        Settings(poll_interval_seconds=3)


def test_custom_settings():
    settings = Settings(
        poll_interval_seconds=15,
        target_tickets_count=4,
        telegram_bot_token="test_token",
        telegram_chat_id="123456",
        cutoff_date="2026-10-31T05:00:00+02:00",
    )
    assert settings.poll_interval_seconds == 15
    assert settings.target_tickets_count == 4
    assert settings.telegram_bot_token == "test_token"
    assert settings.telegram_chat_id == "123456"
    assert settings.is_cutoff_reached() is False


def test_cutoff_reached():
    past_date = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    settings = Settings(cutoff_date=past_date)
    assert settings.is_cutoff_reached() is True
