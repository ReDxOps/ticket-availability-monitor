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


@pytest.mark.asyncio
@respx.mock
async def test_monitor_cycle_imminent_expiration_alert(monitor):
    from datetime import datetime, timezone, timedelta
    telegram_url = "https://api.telegram.org/bottest_token/sendMessage"
    telegram_route = respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    search_route = respx.get(monitor.settings.adverts_search_url)
    search_route.respond(
        status_code=200,
        json={
            "hydra:member": [
                {
                    "id": 705999,
                    "nbAvailableTickets": 1,
                    "nbCartTickets": 1,
                    "minPrice": 6500,
                    "tickets": [],
                }
            ],
            "hydra:totalItems": 1,
        },
    )

    # 1. First cycle: advert enters cart -> 0 alert (too early)
    res1 = await monitor.poll_once()
    assert res1.state == AvailabilityState.IN_CART
    assert telegram_route.call_count == 0

    # 2. Simulate 9.5 minutes elapsed
    conn = await monitor.db._get_conn()
    ten_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=9, seconds=30)).isoformat()
    await conn.execute(
        "UPDATE advert_state SET cart_entered_at = ? WHERE advert_id = 705999",
        (ten_min_ago,),
    )
    await conn.commit()

    # 3. Next cycle: triggers the imminent expiration alert!
    res2 = await monitor.poll_once()
    assert res2.state == AvailabilityState.IN_CART
    assert telegram_route.call_count == 1
    assert "EXPIRATION IMMINENTE" in telegram_route.calls.last.request.content.decode()

    # 4. Third cycle: deduplication prevents re-alerting
    res3 = await monitor.poll_once()
    assert telegram_route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_monitor_cycle_auto_cart_success(monitor):
    telegram_url = "https://api.telegram.org/bottest_token/sendMessage"
    telegram_route = respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    # Enable auto-cart session cookie
    monitor.settings.seetickets_session_cookie = "resale=secret_cookie_123"

    respx.get(monitor.settings.adverts_search_url).respond(
        status_code=200,
        json={
            "hydra:member": [
                {
                    "id": 888111,
                    "nbAvailableTickets": 1,
                    "nbCartTickets": 0,
                    "minPrice": 6195,
                    "tickets": [{"id": 888111, "resaleValue": 5900, "purchaseFees": 295}],
                }
            ],
            "hydra:totalItems": 1,
        },
    )

    # Mock auto-cart endpoint
    cart_route = respx.post(monitor.settings.cart_add_url).respond(
        status_code=200,
        json={"advert": {"id": 888111}, "nbItem": 1},
    )

    res = await monitor.poll_once()
    assert res.state == AvailabilityState.AVAILABLE
    assert res.new_alerts == 1
    assert cart_route.call_count == 1
    assert telegram_route.call_count == 1
    assert "BILLET SÉCURISÉ DANS VOTRE PANIER" in telegram_route.calls.last.request.content.decode()


@pytest.mark.asyncio
@respx.mock
async def test_monitor_cycle_auto_cart_fallback(monitor):
    telegram_url = "https://api.telegram.org/bottest_token/sendMessage"
    telegram_route = respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    monitor.settings.seetickets_session_cookie = "resale=expired_cookie"

    respx.get(monitor.settings.adverts_search_url).respond(
        status_code=200,
        json={
            "hydra:member": [
                {
                    "id": 888222,
                    "nbAvailableTickets": 1,
                    "nbCartTickets": 0,
                    "minPrice": 6195,
                    "tickets": [{"id": 888222, "resaleValue": 5900, "purchaseFees": 295}],
                }
            ],
            "hydra:totalItems": 1,
        },
    )

    # Mock auto-cart failure (e.g. captcha_error)
    cart_route = respx.post(monitor.settings.cart_add_url).respond(
        status_code=200,
        json={"error": "captcha_error"},
    )

    res = await monitor.poll_once()
    assert res.state == AvailabilityState.AVAILABLE
    assert res.new_alerts == 1
    assert cart_route.call_count == 1
    assert telegram_route.call_count == 1
    # Fallback to standard alert
    assert "BILLET DISPONIBLE" in telegram_route.calls.last.request.content.decode()

