"""Telegram Notification Service for Dream Nation 2026 Ticket Availability."""

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
import httpx

from src.config import Settings
from src.models import AdvertModel

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Dispatches real-time ticket availability, pre-alerts, and technical alerts via Telegram Bot API."""

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

    async def _send_message(
        self,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Sends an HTML formatted message to the configured Telegram chat with raw URLs."""
        if not self.is_configured:
            logger.warning("Telegram credentials not configured. Notification was skipped.")
            return False

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": self.settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

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
        Uses raw URLs directly in text to prevent Telegram's 'Open this link?' confirmation modal.
        """
        direct_url = self.settings.get_advert_url(advert.id)
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
            f"👉 <b>Accès direct à l'annonce #{advert.id} :</b>\n"
            f"{direct_url}\n\n"
            f"⚡ <i>Faites vite, les réservations partent en quelques secondes !</i>"
        )

        return await self._send_message(message)

    async def send_cart_prealert(self, advert: AdvertModel) -> bool:
        """
        Sends a proactive pre-alert when tickets enter someone else's cart.
        Gives the user advance notice and raw direct link before cart expiration.
        """
        direct_url = self.settings.get_advert_url(advert.id)
        now_dt = datetime.now(self._paris_tz)
        detection_time = now_dt.strftime("%H:%M:%S")
        rel_10m = (now_dt + timedelta(minutes=10)).strftime("%H:%M")
        rel_15m = (now_dt + timedelta(minutes=15)).strftime("%H:%M")
        count = advert.nb_cart_tickets or 1
        price_str = f"{advert.price_eur:.2f} €" if advert.price_eur > 0 else "Non communiqué"

        message = (
            f"⏳ <b>PRÉ-ALERTE : BILLET EN COURS DE RÉSERVATION (EN PANIER)</b>\n\n"
            f"🎪 <b>Événement :</b> Dream Nation 2026\n"
            f"🎫 <b>Catégorie :</b> {self.settings.seetickets_category_name}\n"
            f"🔢 <b>Quantité bloquée :</b> {count} billet(s)\n"
            f"💰 <b>Prix unitaire :</b> {price_str}\n"
            f"🕒 <b>Mis en panier vers :</b> {detection_time} (Paris)\n\n"
            f"⚠️ <i>Un acheteur a ce billet dans son panier, mais plus de 50% des paniers expirent sans être payés !</i>\n\n"
            f"🎯 <b>Fenêtre estimée de libération si abandonné :</b>\n"
            f"👉 <b>Entre {rel_10m} et {rel_15m}</b>\n\n"
            f"👉 <b>Accès direct à l'annonce #{advert.id} :</b>\n"
            f"{direct_url}\n\n"
            f"💡 <i>Conseil : Ouvre la page dès maintenant pour être prêt à rafraîchir à la seconde de fin de panier !</i>"
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
            f"⏱️ <b>Intervalle :</b> {self.settings.poll_interval_seconds}s (avec jitter anti-détection)\n"
            f"🕒 <b>Test effectué le :</b> {now_time} (Paris)\n\n"
            f"🔗 <b>Billetterie officielle See Tickets Resell :</b>\n"
            f"{self.settings.category_url}"
        )
        return await self._send_message(message)

