"""SQLite persistence layer for See Tickets Resell monitoring."""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import aiosqlite

from src.models import AdvertModel, AvailabilityState


class DatabaseManager:
    """Manages SQLite persistence for advert states, transitions, and notification logs."""

    def __init__(self, db_path: str = "data/monitor.db") -> None:
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._connection is None:
            # Ensure parent directory exists
            parent = Path(self.db_path).parent
            if parent and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)

            self._connection = await aiosqlite.connect(self.db_path)
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA journal_mode = WAL")
            await self._connection.execute("PRAGMA synchronous = NORMAL")
        return self._connection

    async def close(self) -> None:
        """Closes active database connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def init_db(self) -> None:
        """Initializes tables and indexes."""
        conn = await self._get_conn()
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS advert_state (
                advert_id INTEGER PRIMARY KEY,
                category_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                nb_available INTEGER NOT NULL,
                nb_cart INTEGER NOT NULL,
                price_cents INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_advert_category
            ON advert_state (category_id, state);

            CREATE TABLE IF NOT EXISTS state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                advert_id INTEGER NOT NULL,
                previous_state TEXT,
                new_state TEXT NOT NULL,
                nb_available INTEGER NOT NULL,
                nb_cart INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_history_advert
            ON state_history (advert_id, created_at);

            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                advert_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                sent_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_notification_dedup
            ON notification_log (advert_id, notification_type);
            """
        )
        await conn.commit()

    async def get_advert_state(self, advert_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves current recorded state of an advert."""
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT * FROM advert_state WHERE advert_id = ?",
            (advert_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None

    async def record_advert_state(
        self,
        advert: AdvertModel,
        category_id: int,
    ) -> Tuple[bool, Optional[str], bool]:
        """
        Records or updates advert state in the database.

        Returns:
            Tuple[is_new, previous_state, is_cart_return]
            - is_new: True if advert was never seen before.
            - previous_state: Previous state string if existing, else None.
            - is_cart_return: True specifically if state transitioned from IN_CART to AVAILABLE.
        """
        conn = await self._get_conn()
        now_iso = datetime.now(timezone.utc).isoformat()
        current_state = advert.state.value

        existing = await self.get_advert_state(advert.id)

        if existing is None:
            # First time seeing this advert
            await conn.execute(
                """
                INSERT INTO advert_state (
                    advert_id, category_id, state, nb_available, nb_cart, price_cents, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    advert.id,
                    category_id,
                    current_state,
                    advert.nb_available_tickets,
                    advert.nb_cart_tickets,
                    advert.min_price_cents,
                    now_iso,
                    now_iso,
                ),
            )
            await conn.execute(
                """
                INSERT INTO state_history (
                    advert_id, previous_state, new_state, nb_available, nb_cart, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    advert.id,
                    None,
                    current_state,
                    advert.nb_available_tickets,
                    advert.nb_cart_tickets,
                    now_iso,
                ),
            )
            await conn.commit()
            return True, None, False

        prev_state = existing["state"]
        is_cart_return = (
            prev_state == AvailabilityState.IN_CART.value
            and current_state == AvailabilityState.AVAILABLE.value
        )
        state_changed = prev_state != current_state or (
            existing["nb_available"] != advert.nb_available_tickets
            or existing["nb_cart"] != advert.nb_cart_tickets
        )

        await conn.execute(
            """
            UPDATE advert_state SET
                state = ?,
                nb_available = ?,
                nb_cart = ?,
                price_cents = ?,
                updated_at = ?
            WHERE advert_id = ?
            """,
            (
                current_state,
                advert.nb_available_tickets,
                advert.nb_cart_tickets,
                advert.min_price_cents,
                now_iso,
                advert.id,
            ),
        )

        if state_changed:
            await conn.execute(
                """
                INSERT INTO state_history (
                    advert_id, previous_state, new_state, nb_available, nb_cart, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    advert.id,
                    prev_state,
                    current_state,
                    advert.nb_available_tickets,
                    advert.nb_cart_tickets,
                    now_iso,
                ),
            )

        await conn.commit()
        return False, prev_state, is_cart_return

    async def mark_advert_sold_out(self, advert_id: int) -> bool:
        """Marks an advert as SOLD_OUT when it disappears from active listings."""
        conn = await self._get_conn()
        existing = await self.get_advert_state(advert_id)
        if not existing or existing["state"] == AvailabilityState.SOLD_OUT.value:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """
            UPDATE advert_state SET
                state = ?,
                nb_available = 0,
                updated_at = ?
            WHERE advert_id = ?
            """,
            (AvailabilityState.SOLD_OUT.value, now_iso, advert_id),
        )
        await conn.execute(
            """
            INSERT INTO state_history (
                advert_id, previous_state, new_state, nb_available, nb_cart, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                advert_id,
                existing["state"],
                AvailabilityState.SOLD_OUT.value,
                0,
                existing["nb_cart"],
                now_iso,
            ),
        )
        await conn.commit()
        return True

    async def is_notification_duplicate(self, advert_id: int, notification_type: str) -> bool:
        """Checks if a notification of a given type was already sent for this advert."""
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT id FROM notification_log WHERE advert_id = ? AND notification_type = ?",
            (advert_id, notification_type),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def record_notification_sent(
        self,
        advert_id: int,
        state: str,
        notification_type: str,
    ) -> None:
        """Records a sent notification for deduplication."""
        conn = await self._get_conn()
        now_iso = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """
            INSERT INTO notification_log (advert_id, state, notification_type, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            (advert_id, state, notification_type, now_iso),
        )
        await conn.commit()

    async def get_active_adverts(self, category_id: int) -> List[Dict[str, Any]]:
        """Returns all adverts not marked as SOLD_OUT for a given category."""
        conn = await self._get_conn()
        async with conn.execute(
            """
            SELECT * FROM advert_state
            WHERE category_id = ? AND state != ?
            """,
            (category_id, AvailabilityState.SOLD_OUT.value),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
