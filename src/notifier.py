"""Telegram Notification Service for Dream Nation 2026 Ticket Availability."""

from datetime import datetime
import logging
from typing import Optional
from zoneinfo import ZoneInfo
import httpx

from src.config import Settings
from src.models import AdvertModel

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Dispatches real-time ticket availability and technical alerts via Telegram Bot API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=10.0)
        self._paris_tz = ZoneInfo("Europe/Paris")

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        await self._client.aclose()

    @property
    def is_configured(self) -> bool:
        """True if both Telegram bot token and chat ID are provided."""
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    def _now_paris(self) -> str:
        """Returns the current timestamp formatted in Europe/Paris timezone."""
        return datetime.now(self._paris_tz).strftime("%d/%m/%Y à %H:%M:%S")

    async def _send_message(self, text: str) -> bool:
        """Sends an HTML formatted message to the configured Telegram chat."""
        if not self.is_configured:
            logger.warning("Telegram credentials not configured. Notification was skipped.")
            return False

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            response = await self._client.post(url, json=payload)
            if response.status_code == 200:
                logger.info("Telegram notification sent successfully.")
                return True
            else:
                logger.error(
                    f"Failed to send Telegram message: status={response.status_code}, response={response.text}"
                )
                return False
        except Exception as ex:
            logger.exception(f"Exception sending Telegram message: {ex}")
            return False

    async def send_availability_alert(
        self,
        advert: AdvertModel,
        is_cart_return: bool = False,
    ) -> bool:
        """
        Sends a high-priority push notification when tickets are purchasable.
        """
        direct_url = self.settings.get_advert_url(advert.id)
        category_url = self.settings.category_url
        detection_time = self._now_paris()
        count = advert.truly_available_count
        price_str = f"{advert.price_eur:.2f} €" if advert.price_eur > 0 else "Non communiqué"

        if is_cart_return:
            status_banner = "🔄 <b>BILLET DE NOUVEAU DISPONIBLE (PANIER EXPIRÉ) !</b>"
        elif count >= self.settings.target_tickets_count:
            status_banner = f"🚨 <b>OFFRE {count}+ BILLETS DISPONIBLES (PRIORITAIRE) !</b>"
        else:
            status_banner = "🎟️ <b>BILLET DISPONIBLE À L'ACHAT !</b>"

        message = (
            f"{status_banner}\n\n"
            f"🎪 <b>Événement :</b> Dream Nation 2026\n"
            f"📅 <b>Date :</b> Vendredi 30 Octobre 2026 (20h30)\n"
            f"🎫 <b>Catégorie :</b> {self.settings.seetickets_category_name}\n"
            f"🔢 <b>Quantité disponible :</b> {count} billet(s)\n"
            f"💰 <b>Prix unitaire constaté :</b> {price_str}\n"
            f"🕒 <b>Détecté le :</b> {detection_time} (Paris)\n\n"
            f"👉 <a href=\"{direct_url}\"><b>ACCÉDER DIRECTEMENT À L'ANNONCE #{advert.id}</b></a>\n"
            f"🌐 <a href=\"{category_url}\">Voir la page de catégorie</a>\n\n"
            f"⚡ <i>Faites vite, les réservations partent en quelques secondes !</i>"
        )

        return await self._send_message(message)

    async def send_technical_alert(self, title: str, details: str) -> bool:
        """
        Sends an operational technical alert in case of persistent errors or service interruption.
        """
        now_time = self._now_paris()
        message = (
            f"⚠️ <b>ALERTE TECHNIQUE — Dream Nation Monitor</b>\n\n"
            f"<b>Incident :</b> {title}\n"
            f"<b>Détails :</b> {details}\n"
            f"<b>Heure :</b> {now_time} (Paris)\n\n"
            f"<i>Le moniteur continue d'appliquer le backoff automatique pour rétablir la surveillance.</i>"
        )
        return await self._send_message(message)

    async def send_test_message(self) -> bool:
        """Sends a verification test message to ensure bot credentials are functional."""
        now_time = self._now_paris()
        message = (
            f"🤖 <b>Test de Notification — Dream Nation 2026 Monitor</b>\n\n"
            f"✅ Le bot Telegram est correctement configuré et prêt à vous alerter !\n"
            f"🎯 <b>Cible surveillée :</b> PASS 1 JOUR VENDREDI\n"
            f"⏱️ <b>Intervalle :</b> {self.settings.poll_interval_seconds}s\n"
            f"🕒 <b>Test effectué le :</b> {now_time} (Paris)\n\n"
            f"🔗 <a href=\"{self.settings.category_url}\">Billetterie officielle See Tickets Resell</a>"
        )
        return await self._send_message(message)
