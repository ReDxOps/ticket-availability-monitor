"""Tests for Telegram notification service."""

import pytest
import respx
from src.config import Settings
from src.models import AdvertModel, TicketModel
from src.notifier import TelegramNotifier


@pytest.fixture
def settings():
    return Settings(
        telegram_bot_token="test_bot_token",
        telegram_chat_id="987654321",
    )


@pytest.fixture
async def notifier(settings):
    n = TelegramNotifier(settings)
    yield n
    await n.close()


@pytest.mark.asyncio
@respx.mock
async def test_send_availability_alert_single(notifier):
    telegram_url = "https://api.telegram.org/bottest_bot_token/sendMessage"
    respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    advert = AdvertModel(
        id=705901,
        nb_available_tickets=1,
        nb_cart_tickets=0,
        min_price_cents=6195,
        tickets=[
            TicketModel(
                id=705901,
                resale_value_cents=5900,
                purchase_fees_cents=295,
                product_name="Vendredi Pass",
            )
        ],
    )

    sent = await notifier.send_availability_alert(advert)
    assert sent is True

    # Check request payload
    assert respx.calls.call_count == 1
    req_body = respx.calls.last.request.content.decode()
    assert "987654321" in req_body
    assert "705901" in req_body
    assert "61.95" in req_body
    assert "BILLET DISPONIBLE" in req_body


@pytest.mark.asyncio
@respx.mock
async def test_send_availability_alert_priority_two_tickets(notifier):
    telegram_url = "https://api.telegram.org/bottest_bot_token/sendMessage"
    respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    advert = AdvertModel(
        id=705902,
        nb_available_tickets=2,
        nb_cart_tickets=0,
        min_price_cents=6500,
        tickets=[
            TicketModel(id=1, resale_value_cents=6190, purchase_fees_cents=310),
            TicketModel(id=2, resale_value_cents=6190, purchase_fees_cents=310),
        ],
    )

    sent = await notifier.send_availability_alert(advert)
    assert sent is True

    req_body = respx.calls.last.request.content.decode()
    assert "2+ BILLETS DISPONIBLES" in req_body


@pytest.mark.asyncio
@respx.mock
async def test_send_availability_alert_cart_return(notifier):
    telegram_url = "https://api.telegram.org/bottest_bot_token/sendMessage"
    respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    advert = AdvertModel(
        id=705903,
        nb_available_tickets=1,
        nb_cart_tickets=0,
        min_price_cents=6195,
    )

    sent = await notifier.send_availability_alert(advert, is_cart_return=True)
    assert sent is True

    req_body = respx.calls.last.request.content.decode()
    assert "PANIER" in req_body


@pytest.mark.asyncio
@respx.mock
async def test_send_technical_alert(notifier):
    telegram_url = "https://api.telegram.org/bottest_bot_token/sendMessage"
    respx.post(telegram_url).respond(status_code=200, json={"ok": True})

    sent = await notifier.send_technical_alert("Erreur de connexion répétée", "10 erreurs consécutives 500")
    assert sent is True

    req_body = respx.calls.last.request.content.decode()
    assert "ALERTE TECHNIQUE" in req_body
    assert "10 erreurs" in req_body


@pytest.mark.asyncio
async def test_notifier_without_credentials():
    settings_no_token = Settings(telegram_bot_token=None, telegram_chat_id=None)
    n = TelegramNotifier(settings_no_token)
    advert = AdvertModel(id=1, nb_available_tickets=1)
    sent = await n.send_availability_alert(advert)
    assert sent is False
    await n.close()
