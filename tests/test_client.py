"""Tests for See Tickets HTTP API client."""

import httpx
import pytest
import respx
from src.client import SeeTicketsClient
from src.config import Settings
from src.models import AvailabilityState


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
async def client(settings):
    c = SeeTicketsClient(settings)
    yield c
    await c.close()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_adverts_empty_sold_out(client, settings):
    respx.get(settings.adverts_search_url).respond(
        status_code=200,
        json={
            "@context": "/api/contexts/Advert",
            "@id": "/api/adverts_search",
            "@type": "hydra:Collection",
            "hydra:member": [],
            "hydra:totalItems": 0,
        },
    )

    state, adverts, err = await client.fetch_adverts()
    assert state == AvailabilityState.SOLD_OUT
    assert adverts == []
    assert err is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_adverts_available(client, settings):
    respx.get(settings.adverts_search_url).respond(
        status_code=200,
        json={
            "@context": "/api/contexts/Advert",
            "@id": "/api/adverts_search",
            "@type": "hydra:Collection",
            "hydra:member": [
                {
                    "id": 705901,
                    "status": 1,
                    "dynamicStatus": 1,
                    "nbAvailableTickets": 1,
                    "nbCartTickets": 0,
                    "minPrice": 6195,
                    "tickets": [
                        {
                            "id": 705901,
                            "resaleValue": 5900,
                            "purchaseFees": 295,
                            "product": {"name": {"en": "Vendredi Ticket"}},
                        }
                    ],
                }
            ],
            "hydra:totalItems": 1,
        },
    )

    state, adverts, err = await client.fetch_adverts()
    assert state == AvailabilityState.AVAILABLE
    assert len(adverts) == 1
    assert adverts[0].id == 705901
    assert adverts[0].price_eur == 61.95
    assert err is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_adverts_in_cart(client, settings):
    respx.get(settings.adverts_search_url).respond(
        status_code=200,
        json={
            "@context": "/api/contexts/Advert",
            "@id": "/api/adverts_search",
            "@type": "hydra:Collection",
            "hydra:member": [
                {
                    "id": 705901,
                    "status": 1,
                    "dynamicStatus": 1,
                    "nbAvailableTickets": 1,
                    "nbCartTickets": 1,
                    "minPrice": 6195,
                    "tickets": [],
                }
            ],
            "hydra:totalItems": 1,
        },
    )

    state, adverts, err = await client.fetch_adverts()
    assert state == AvailabilityState.IN_CART
    assert len(adverts) == 1
    assert adverts[0].is_purchasable is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_adverts_rate_limit_429(client, settings):
    respx.get(settings.adverts_search_url).respond(
        status_code=429,
        headers={"Retry-After": "5"},
        text="Too Many Requests",
    )

    state, adverts, err = await client.fetch_adverts()
    assert state == AvailabilityState.UNKNOWN
    assert adverts == []
    assert "429" in err
    assert client.backoff_delay >= 5.0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_adverts_server_error_500(client, settings):
    respx.get(settings.adverts_search_url).respond(
        status_code=500,
        text="Internal Server Error",
    )

    state, adverts, err = await client.fetch_adverts()
    assert state == AvailabilityState.UNKNOWN
    assert adverts == []
    assert "500" in err
    assert client.consecutive_errors == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_adverts_waf_403_cooldown(client, settings):
    respx.get(settings.adverts_search_url).respond(
        status_code=403,
        text="Forbidden by WAF",
    )

    state, adverts, err = await client.fetch_adverts()
    assert state == AvailabilityState.UNKNOWN
    assert adverts == []
    assert "403" in err
    assert client.backoff_delay == 300.0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_adverts_timeout(client, settings):
    respx.get(settings.adverts_search_url).mock(
        side_effect=httpx.ReadTimeout("Timeout connecting to server")
    )

    state, adverts, err = await client.fetch_adverts()
    assert state == AvailabilityState.UNKNOWN
    assert adverts == []
    assert "Timeout" in err
    assert client.consecutive_errors == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_category_overview(client, settings):
    respx.get(settings.categories_url).respond(
        status_code=200,
        json={
            "hydra:member": [
                {"id": 7897, "nbTicket": 0},
                {"id": 7898, "nbTicket": 40},
            ]
        },
    )

    overview = await client.fetch_category_overview()
    assert overview == {7897: 0, 7898: 40}


@pytest.mark.asyncio
async def test_add_to_cart_no_cookie(client):
    success, msg = await client.add_to_cart(705901)
    assert success is False
    assert "No session cookie" in msg


@pytest.mark.asyncio
@respx.mock
async def test_add_to_cart_success(settings):
    settings.seetickets_session_cookie = "resale=test_cookie_123"
    c = SeeTicketsClient(settings)
    respx.post(settings.cart_add_url).respond(
        status_code=200,
        json={"advert": {"id": 705901}, "nbItem": 1, "success": "Ticket ajouté"},
    )

    success, msg = await c.add_to_cart(705901)
    assert success is True
    assert "Added to cart" in msg
    await c.close()


@pytest.mark.asyncio
@respx.mock
async def test_add_to_cart_captcha_error(settings):
    settings.seetickets_session_cookie = "test_cookie_456"
    c = SeeTicketsClient(settings)
    respx.post(settings.cart_add_url).respond(
        status_code=200,
        json={"error": "captcha_error"},
    )

    success, msg = await c.add_to_cart(705901)
    assert success is False
    assert msg == "captcha_error"
    await c.close()


@pytest.mark.asyncio
@respx.mock
async def test_add_to_cart_http_error(settings):
    settings.seetickets_session_cookie = "test_cookie_789"
    c = SeeTicketsClient(settings)
    respx.post(settings.cart_add_url).respond(
        status_code=500,
        text="Internal Server Error",
    )

    success, msg = await c.add_to_cart(705901)
    assert success is False
    assert "HTTP 500" in msg
    await c.close()
