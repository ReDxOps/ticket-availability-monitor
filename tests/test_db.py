"""Tests for SQLite database persistence layer."""

import pytest
from src.db import DatabaseManager
from src.models import AdvertModel, AvailabilityState, TicketModel


@pytest.fixture
async def db(tmp_path):
    db_file = tmp_path / "test_monitor.db"
    manager = DatabaseManager(str(db_file))
    await manager.init_db()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_init_db(db):
    # Verify tables created without error
    active = await db.get_active_adverts(7897)
    assert active == []


@pytest.mark.asyncio
async def test_record_new_advert(db):
    advert = AdvertModel(
        id=705901,
        nb_available_tickets=1,
        nb_cart_tickets=0,
        min_price_cents=6195,
        tickets=[TicketModel(id=705901, resale_value_cents=5900, purchase_fees_cents=295)],
    )

    is_new, prev_state, is_cart_return = await db.record_advert_state(advert, category_id=7897)
    assert is_new is True
    assert prev_state is None
    assert is_cart_return is False

    # Second record with same state -> not new, no state change
    is_new2, prev_state2, is_cart_return2 = await db.record_advert_state(advert, category_id=7897)
    assert is_new2 is False
    assert prev_state2 == AvailabilityState.AVAILABLE.value
    assert is_cart_return2 is False


@pytest.mark.asyncio
async def test_cart_transition_and_return(db):
    advert = AdvertModel(
        id=705901,
        nb_available_tickets=1,
        nb_cart_tickets=0,
        min_price_cents=6195,
    )

    # 1. First seen as AVAILABLE
    await db.record_advert_state(advert, category_id=7897)

    # 2. Someone adds to cart -> IN_CART
    advert_in_cart = AdvertModel(
        id=705901,
        nb_available_tickets=1,
        nb_cart_tickets=1,
        min_price_cents=6195,
    )
    is_new, prev_state, is_cart_return = await db.record_advert_state(advert_in_cart, category_id=7897)
    assert is_new is False
    assert prev_state == AvailabilityState.AVAILABLE.value
    assert is_cart_return is False

    # 3. Cart expires -> AVAILABLE again (is_cart_return = True!)
    advert_released = AdvertModel(
        id=705901,
        nb_available_tickets=1,
        nb_cart_tickets=0,
        min_price_cents=6195,
    )
    is_new3, prev_state3, is_cart_return3 = await db.record_advert_state(advert_released, category_id=7897)
    assert is_new3 is False
    assert prev_state3 == AvailabilityState.IN_CART.value
    assert is_cart_return3 is True


@pytest.mark.asyncio
async def test_notification_deduplication(db):
    advert_id = 705901
    notif_type = "AVAILABILITY_1"

    # Initially not sent
    assert await db.is_notification_duplicate(advert_id, notif_type) is False

    # Record sent
    await db.record_notification_sent(advert_id, AvailabilityState.AVAILABLE.value, notif_type)

    # Now duplicate
    assert await db.is_notification_duplicate(advert_id, notif_type) is True

    # But different type (e.g. cart return) is not duplicate
    assert await db.is_notification_duplicate(advert_id, "CART_RETURN") is False


@pytest.mark.asyncio
async def test_mark_sold_out(db):
    advert = AdvertModel(id=705901, nb_available_tickets=1, nb_cart_tickets=0)
    await db.record_advert_state(advert, category_id=7897)

    changed = await db.mark_advert_sold_out(705901)
    assert changed is True

    # Verify state in DB
    state = await db.get_advert_state(705901)
    assert state["state"] == AvailabilityState.SOLD_OUT.value
