"""Configuration settings module for Dream Nation 2026 Ticket Availability Monitor."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # See Tickets Target configuration
    seetickets_base_url: str = Field(
        default="https://resell.seetickets.com",
        description="Base URL for See Tickets Resell service",
    )
    seetickets_site_id: int = Field(
        default=496,
        description="Site ID for Dream Nation 2026",
    )
    seetickets_event_id: int = Field(
        default=2768,
        description="Event ID for Dream Nation 2026",
    )
    seetickets_category_id: int = Field(
        default=7897,
        description="Category ID for Pass 1 Jour Vendredi",
    )
    seetickets_category_name: str = Field(
        default="DREAM NATION 2026 - PASS 1 JOUR VENDREDI",
        description="Official category label",
    )
    seetickets_category_slug: str = Field(
        default="dream-nation-2026-pass-1-jour-vendredi",
        description="Slug used in verified category URL",
    )
    seetickets_site_name: str = Field(
        default="dreamnation2026",
        description="Slug for the event website",
    )

    # Polling & targets
    poll_interval_seconds: int = Field(
        default=6,
        description="Interval between polling cycles in seconds",
    )
    target_tickets_count: int = Field(
        default=2,
        description="Desired ticket count for prioritization alert",
    )
    consecutive_errors_threshold: int = Field(
        default=10,
        description="Consecutive failure count before sending a technical alert",
    )

    # Cutoff date
    cutoff_date: str = Field(
        default="2026-10-31T05:00:00+02:00",
        description="ISO 8601 string for monitoring cutoff",
    )

    # Telegram configuration
    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram Bot API Token",
    )
    telegram_chat_id: Optional[str] = Field(
        default=None,
        description="Telegram Chat ID for notification delivery",
    )

    # Storage and logging
    db_path: str = Field(
        default="data/monitor.db",
        description="Path to SQLite database file",
    )
    log_level: str = Field(
        default="INFO",
        description="Application logging level",
    )

    @field_validator("poll_interval_seconds")
    @classmethod
    def validate_poll_interval(cls, v: int) -> int:
        if v < 4:
            raise ValueError("poll_interval_seconds must be at least 4 to respect platform constraints")
        return v

    @property
    def category_url(self) -> str:
        """Constructs verified category URL on See Tickets Resell."""
        return (
            f"{self.seetickets_base_url.rstrip('/')}/"
            f"{self.seetickets_site_name}/category/"
            f"{self.seetickets_category_id}/{self.seetickets_category_slug}"
        )

    def get_advert_url(self, advert_id: int) -> str:
        """Constructs direct link to the advert on See Tickets Resell."""
        return f"{self.category_url}?advert={advert_id}"

    @property
    def adverts_search_url(self) -> str:
        """Endpoint URL for polling active and purchasable adverts."""
        return (
            f"{self.seetickets_base_url.rstrip('/')}/api/adverts_search"
            f"?tickets.product.category={self.seetickets_category_id}"
            f"&existAvailableTickets=true&status=1"
            f"&orderby[nbCartTickets]=asc&orderby[tickets.resaleValue]=asc"
            f"&page=1&itemsPerPage=9"
        )

    @property
    def categories_url(self) -> str:
        """Endpoint URL for polling overall categories for the event."""
        return f"{self.seetickets_base_url.rstrip('/')}/api/categories?event={self.seetickets_event_id}"

    def is_cutoff_reached(self) -> bool:
        """Returns True if the current time has surpassed the configured cutoff date."""
        try:
            cutoff = datetime.fromisoformat(self.cutoff_date)
            # Ensure cutoff is timezone-aware
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) >= cutoff
        except Exception:
            return False
