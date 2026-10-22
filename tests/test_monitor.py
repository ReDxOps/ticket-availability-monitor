"""Tests for Core Monitoring Engine and State Transitions."""

import pytest
import respx
from src.config import Settings
from src.db import DatabaseManager
from src.client import SeeTicketsClient
from src.notifier import TelegramNotifier
from src.monitor import TicketMonitor, MonitorCycleResult
from src.models import AvailabilityState


@pytest.fixture
async def monitor(tmp_path):
    db_file = tmp_path / "test_monitor.db"
    settings = Settings(
        db_path=str(db_file),
        telegram_bot_token="test_token",
        telegram_chat_id="123456",
        consecutive_errors_threshold=3,
    )
    db = DatabaseManager(str(db_file))
    await db.init_db()

    client = SeeTicketsClient(settings)
    notifier = TelegramNotifier(settings)

    m = TicketMonitor(settings, db, client, notifier)
    yield m

    await client.close()
    await notifier.close()
    await db.close()


@pytest.mark.asyncio
@respx.mock
async def test_monitor_cycle_sold_out(monitor):
    respx.get(monitor.settings.adverts_search_url).respond(
        status_code=200,
        json={"hydra:member": [], "hydra:totalItems": 0},
    )

    result = await monitor.poll_once()
    assert result.state == AvailabilityState.SOLD_OUT
    assert result.new_alerts == 0


@pytest.mark.asyncio
@respx.mock
async def test_monitor_cycle_single_ticket_and_deduplication(monitor):
    telegram_url = "https://api.telegram.org/bottest_token/sendMessage"
    respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    respx.get(monitor.settings.adverts_search_url).respond(
        status_code=200,
        json={
            "hydra:member": [
                {
                    "id": 705901,
                    "nbAvailableTickets": 1,
                    "nbCartTickets": 0,
                    "minPrice": 6195,
                    "tickets": [{"id": 705901, "resaleValue": 5900, "purchaseFees": 295}],
                }
            ],
            "hydra:totalItems": 1,
        },
    )

    # First cycle: Ticket detected -> 1 alert sent
    result1 = await monitor.poll_once()
    assert result1.state == AvailabilityState.AVAILABLE
    assert result1.new_alerts == 1

    # Second cycle with exact same ticket: Deduplication prevents spam -> 0 new alerts
    result2 = await monitor.poll_once()
    assert result2.state == AvailabilityState.AVAILABLE
    assert result2.new_alerts == 0


@pytest.mark.asyncio
@respx.mock
async def test_monitor_cycle_in_cart_then_released(monitor):
    telegram_url = "https://api.telegram.org/bottest_token/sendMessage"
    respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    search_route = respx.get(monitor.settings.adverts_search_url)

    # 1. Ticket enters someone's cart
    search_route.respond(
        status_code=200,
        json={
            "hydra:member": [
                {
                    "id": 705901,
                    "nbAvailableTickets": 1,
                    "nbCartTickets": 1,
                    "minPrice": 6195,
                    "tickets": [],
                }
            ],
            "hydra:totalItems": 1,
        },
    )
    result_cart = await monitor.poll_once()
    assert result_cart.state == AvailabilityState.IN_CART
    assert result_cart.new_alerts == 0

    # 2. Cart timer expires -> ticket released!
    search_route.respond(
        status_code=200,
        json={
            "hydra:member": [
                {
                    "id": 705901,
                    "nbAvailableTickets": 1,
                    "nbCartTickets": 0,
                    "minPrice": 6195,
                    "tickets": [{"id": 705901, "resaleValue": 5900, "purchaseFees": 295}],
                }
            ],
            "hydra:totalItems": 1,
        },
    )
    result_release = await monitor.poll_once()
    assert result_release.state == AvailabilityState.AVAILABLE
    assert result_release.new_alerts == 1


@pytest.mark.asyncio
@respx.mock
async def test_monitor_cycle_prolonged_errors_trigger_technical_alert(monitor):
    telegram_url = "https://api.telegram.org/bottest_token/sendMessage"
    telegram_route = respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    search_route = respx.get(monitor.settings.adverts_search_url)
    search_route.respond(status_code=500, text="Server Error")

    # Threshold is 3 consecutive errors
    res1 = await monitor.poll_once()
    assert res1.state == AvailabilityState.UNKNOWN
    assert telegram_route.call_count == 0

    res2 = await monitor.poll_once()
    assert res2.state == AvailabilityState.UNKNOWN
    assert telegram_route.call_count == 0

    # 3rd consecutive error -> technical alert dispatched!
    res3 = await monitor.poll_once()
    assert res3.state == AvailabilityState.UNKNOWN
    assert telegram_route.call_count == 1
    assert "ALERTE TECHNIQUE" in telegram_route.calls.last.request.content.decode()
