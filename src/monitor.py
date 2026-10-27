"""Core orchestration engine for ticket availability monitoring."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import random
import signal
import sys
from typing import List, Optional, Set
from pydantic import BaseModel

from src.client import SeeTicketsClient
from src.config import Settings
from src.db import DatabaseManager
from src.models import AdvertModel, AvailabilityState
from src.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


@dataclass
class MonitorCycleResult:
    """Outcome of a single polling iteration."""

    state: AvailabilityState
    new_alerts: int = 0
    total_adverts: int = 0
    error: Optional[str] = None
    cutoff_reached: bool = False


class TicketMonitor:
    """Continuous monitor coordinating HTTP polling, database state tracking, and Telegram alerts."""

    def __init__(
        self,
        settings: Settings,
        db: DatabaseManager,
        client: SeeTicketsClient,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.db = db
        self.client = client
        self.notifier = notifier

        self._running: bool = False
        self._technical_alert_sent: bool = False

    async def poll_once(self) -> MonitorCycleResult:
        """Executes a single monitoring cycle."""
        # 1. Check cutoff date
        if self.settings.is_cutoff_reached():
            logger.info("Cutoff date reached. Monitoring complete.")
            return MonitorCycleResult(state=AvailabilityState.SOLD_OUT, cutoff_reached=True)

        # 2. Query See Tickets API
        state, adverts, err = await self.client.fetch_adverts()

        # 3. Handle errors / UNKNOWN state
        if state == AvailabilityState.UNKNOWN:
            logger.warning(f"Polling cycle returned UNKNOWN state: {err}")
            if (
                self.client.consecutive_errors >= self.settings.consecutive_errors_threshold
                and not self._technical_alert_sent
            ):
                logger.error(
                    f"Consecutive errors ({self.client.consecutive_errors}) exceeded threshold. "
                    "Dispatching technical alert to Telegram."
                )
                await self.notifier.send_technical_alert(
                    "Interruption temporaire de la surveillance",
                    f"{self.client.consecutive_errors} erreurs consécutives détectées : {err}",
                )
                self._technical_alert_sent = True

            return MonitorCycleResult(state=AvailabilityState.UNKNOWN, error=err)

        # 4. If recovered from technical alert, reset flag
        if self._technical_alert_sent:
            logger.info("Service recovered after technical alert.")
            self._technical_alert_sent = False

        # 5. Handle SOLD_OUT
        if state == AvailabilityState.SOLD_OUT:
            active_adverts = await self.db.get_active_adverts(self.settings.seetickets_category_id)
            for adv in active_adverts:
                await self.db.mark_advert_sold_out(adv["advert_id"])

            logger.debug("Category currently SOLD_OUT (0 tickets).")
            return MonitorCycleResult(state=AvailabilityState.SOLD_OUT, total_adverts=0)

        # 6. Process adverts in batch
        new_alerts = 0
        seen_advert_ids: Set[int] = set()

        for adv in adverts:
            seen_advert_ids.add(adv.id)
            is_new, prev_state, is_cart_return = await self.db.record_advert_state(
                adv,
                category_id=self.settings.seetickets_category_id,
            )

            # Check if this advert is purchasable right now
            if adv.is_purchasable:
                count = adv.truly_available_count
                cart_success = False

                # 1. Attempt auto-cart if session cookie is configured
                if self.settings.seetickets_session_cookie:
                    logger.info(f"Attempting auto-cart for advert #{adv.id}...")
                    cart_success, cart_msg = await self.client.add_to_cart(adv.id)
                    if cart_success:
                        logger.info(f"Auto-cart SUCCESS for advert #{adv.id}!")
                    else:
                        logger.warning(
                            f"Auto-cart failed for advert #{adv.id}: {cart_msg}. Falling back to standard alert."
                        )

                # 2. Dispatch appropriate notification
                if cart_success:
                    notif_type = f"AUTO_CART_SUCCESS_{adv.id}"
                    is_duplicate = await self.db.is_notification_duplicate(adv.id, notif_type)
                    if not is_duplicate:
                        logger.info(f"ALERT! Ticket locked in cart! Advert #{adv.id}")
                        sent = await self.notifier.send_auto_cart_success_alert(adv)
                        if sent:
                            await self.db.record_notification_sent(
                                adv.id,
                                adv.state.value,
                                notif_type,
                            )
                            new_alerts += 1
                else:
                    if is_cart_return:
                        notif_type = f"CART_RETURN_{adv.id}_{count}"
                    elif adv.has_multiple_tickets:
                        notif_type = f"AVAIL_2PLUS_{adv.id}_{count}"
                    else:
                        notif_type = f"AVAIL_{adv.id}_{count}"

                    # Deduplication check
                    is_duplicate = await self.db.is_notification_duplicate(adv.id, notif_type)
                    if not is_duplicate:
                        logger.info(
                            f"ALERT! Purchasable ticket(s) found! Advert #{adv.id}, "
                            f"Count={count}, CartReturn={is_cart_return}"
                        )
                        sent = await self.notifier.send_availability_alert(
                            adv,
                            is_cart_return=is_cart_return,
                        )
                        if sent:
                            await self.db.record_notification_sent(
                                adv.id,
                                adv.state.value,
                                notif_type,
                            )
                            new_alerts += 1

            elif adv.state == AvailabilityState.IN_CART:
                # Check how long this advert has been continuously held in cart
                duration_sec = await self.db.get_cart_duration_seconds(adv.id)
                # Alert when held for ~9 minutes without purchase (threshold in settings)
                if (
                    duration_sec is not None
                    and duration_sec >= self.settings.cart_expiration_alert_delay_seconds
                ):
                    advert_row = await self.db.get_advert_state(adv.id)
                    entered_str = advert_row.get("cart_entered_at") if advert_row else ""
                    notif_type = f"IMMINENT_EXPIRATION_{adv.id}_{entered_str}"
                    is_duplicate = await self.db.is_notification_duplicate(adv.id, notif_type)
                    if not is_duplicate:
                        logger.info(
                            f"IMMINENT EXPIRATION! Advert #{adv.id} has been in cart for {duration_sec:.0f}s. Dispatching sniper alert..."
                        )
                        minutes_in_cart = max(1, int(round(duration_sec / 60.0)))
                        sent = await self.notifier.send_imminent_expiration_alert(
                            adv,
                            minutes_in_cart=minutes_in_cart,
                        )
                        if sent:
                            await self.db.record_notification_sent(
                                adv.id,
                                adv.state.value,
                                notif_type,
                            )

        # Mark any previously active adverts that disappeared as SOLD_OUT
        active_db_adverts = await self.db.get_active_adverts(self.settings.seetickets_category_id)
        for adv in active_db_adverts:
            if adv["advert_id"] not in seen_advert_ids:
                await self.db.mark_advert_sold_out(adv["advert_id"])

        logger.info(
            f"Cycle completed. State={state.value}, Adverts={len(adverts)}, NewAlerts={new_alerts}"
        )
        return MonitorCycleResult(
            state=state,
            new_alerts=new_alerts,
            total_adverts=len(adverts),
        )

    async def run(self) -> None:
        """Runs the continuous monitoring loop until stopped or cutoff reached."""
        self._running = True
        logger.info(
            f"Starting Ticket Availability Monitor for {self.settings.seetickets_category_name}..."
        )
        logger.info(f"Poll interval: {self.settings.poll_interval_seconds}s (with anti-WAF jitter)")
        logger.info(f"Telegram configured: {self.notifier.is_configured}")
        logger.info(
            f"Auto-cart configured: {bool(self.settings.seetickets_session_cookie)} "
            f"({'Cookie actif' if self.settings.seetickets_session_cookie else 'Désactivé'})"
        )

        while self._running:
            try:
                result = await self.poll_once()

                if result.cutoff_reached:
                    logger.info("Cutoff date reached. Shutting down monitor loop.")
                    break

                # Determine sleep duration: backoff if error, else poll_interval_seconds with anti-WAF jitter
                if result.state == AvailabilityState.UNKNOWN and self.client.backoff_delay > 0:
                    sleep_time = self.client.backoff_delay
                    logger.info(f"Backoff sleep for {sleep_time:.1f}s...")
                else:
                    base_sleep = float(self.settings.poll_interval_seconds)
                    jitter = random.uniform(-0.5, 0.5)
                    sleep_time = max(3.5, base_sleep + jitter)

                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                logger.info("Monitor received cancellation request.")
                break
            except Exception as ex:
                logger.exception(f"Unhandled exception in monitor cycle: {ex}")
                await asyncio.sleep(float(self.settings.poll_interval_seconds))

        logger.info("Monitor run loop terminated.")

    def stop(self) -> None:
        """Signals the monitoring loop to stop."""
        self._running = False


async def entrypoint() -> None:
    """Application CLI entrypoint."""
    settings = Settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    db = DatabaseManager(settings.db_path)
    await db.init_db()

    client = SeeTicketsClient(settings)
    notifier = TelegramNotifier(settings)

    monitor = TicketMonitor(settings, db, client, notifier)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, monitor.stop)
        except NotImplementedError:
            pass  # Windows fallback if needed

    try:
        await monitor.run()
    finally:
        logger.info("Cleaning up resources before exit...")
        await client.close()
        await notifier.close()
        await db.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(entrypoint())
