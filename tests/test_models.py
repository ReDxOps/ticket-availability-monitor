"""Tests for domain models and availability state evaluation."""

import pytest
from src.models import (
    AvailabilityState,
    TicketModel,
    AdvertModel,
    CategorySummary,
)


def test_availability_state_values():
    assert AvailabilityState.AVAILABLE.value == "AVAILABLE"
    assert AvailabilityState.IN_CART.value == "IN_CART"
    assert AvailabilityState.SOLD_OUT.value == "SOLD_OUT"
    assert AvailabilityState.UNKNOWN.value == "UNKNOWN"


def test_ticket_model_price_calculation():
    ticket = TicketModel(
        id=705901,
        resale_value_cents=5900,
        purchase_fees_cents=295,
        product_name="Vendredi - Regular Ticket",
    )
    assert ticket.total_price_cents == 6195
    assert ticket.total_price_eur == 61.95


def test_advert_available_state():
    advert = AdvertModel(
        id=705901,
        nb_available_tickets=1,
        nb_cart_tickets=0,
        min_price_cents=6195,
        severability=False,
        tickets=[
            TicketModel(
                id=705901,
                resale_value_cents=5900,
                purchase_fees_cents=295,
                product_name="Vendredi - Pass 1 Jour",
            )
        ],
    )
    assert advert.state == AvailabilityState.AVAILABLE
    assert advert.is_purchasable is True
    assert advert.truly_available_count == 1
    assert advert.price_eur == 61.95


def test_advert_in_cart_state():
    advert = AdvertModel(
        id=705902,
        nb_available_tickets=1,
        nb_cart_tickets=1,
        min_price_cents=6500,
        severability=False,
        tickets=[
            TicketModel(
                id=705902,
                resale_value_cents=6190,
                purchase_fees_cents=310,
                product_name="Vendredi - Pass 1 Jour",
            )
        ],
    )
    assert advert.state == AvailabilityState.IN_CART
    assert advert.is_purchasable is False
    assert advert.truly_available_count == 0


def test_advert_two_tickets_priority():
    advert = AdvertModel(
        id=705903,
        nb_available_tickets=2,
        nb_cart_tickets=0,
        min_price_cents=6500,
        severability=False,
        tickets=[
            TicketModel(
                id=705903,
                resale_value_cents=6190,
                purchase_fees_cents=310,
                product_name="Vendredi - Pass 1 Jour",
            ),
            TicketModel(
                id=705904,
                resale_value_cents=6190,
                purchase_fees_cents=310,
                product_name="Vendredi - Pass 1 Jour",
            ),
        ],
    )
    assert advert.state == AvailabilityState.AVAILABLE
    assert advert.is_purchasable is True
    assert advert.truly_available_count == 2
    assert advert.has_multiple_tickets is True


def test_advert_sold_out_state():
    advert = AdvertModel(
        id=705905,
        nb_available_tickets=0,
        nb_cart_tickets=0,
        min_price_cents=0,
        tickets=[],
    )
    assert advert.state == AvailabilityState.SOLD_OUT
    assert advert.is_purchasable is False


def test_advert_from_api_payload():
    raw_item = {
        "id": 705901,
        "status": 1,
        "dynamicStatus": 1,
        "nbAvailableTickets": 1,
        "nbCartTickets": 0,
        "minPrice": 6195,
        "severability": False,
        "tickets": [
            {
                "id": 705901,
                "resaleValue": 5900,
                "purchaseFees": 295,
                "product": {
                    "name": {"en": "Vendredi - Super Late Ticket - Shotgun"}
                },
            }
        ],
    }
    advert = AdvertModel.from_api_dict(raw_item)
    assert advert.id == 705901
    assert advert.state == AvailabilityState.AVAILABLE
    assert advert.truly_available_count == 1
    assert advert.price_eur == 61.95
    assert len(advert.tickets) == 1
    assert advert.tickets[0].product_name == "Vendredi - Super Late Ticket - Shotgun"


def test_category_summary():
    summary = CategorySummary(
        category_id=7897,
        total_items=3,
        adverts=[
            AdvertModel(id=1, nb_available_tickets=1, nb_cart_tickets=0),
            AdvertModel(id=2, nb_available_tickets=1, nb_cart_tickets=1),
            AdvertModel(id=3, nb_available_tickets=2, nb_cart_tickets=0),
        ],
    )
    assert summary.available_count == 3  # 1 + 2
    assert summary.in_cart_count == 1
    assert summary.has_purchasable_tickets is True
