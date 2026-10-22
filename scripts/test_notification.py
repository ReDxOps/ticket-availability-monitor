#!/usr/bin/env python3
"""CLI utility to test Telegram notification setup."""

import asyncio
from pathlib import Path
import sys

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Settings
from src.notifier import TelegramNotifier


async def main() -> int:
    print("=" * 60)
    print("Test de la configuration Telegram — Dream Nation 2026 Monitor")
    print("=" * 60)

    settings = Settings()

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        print("\n❌ ERREUR : Les variables TELEGRAM_BOT_TOKEN et/ou TELEGRAM_CHAT_ID ne sont pas définies.")
        print("Veuillez renseigner votre fichier .env avec vos identifiants Telegram.")
        print("Exemple :")
        print('  TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"')
        print('  TELEGRAM_CHAT_ID="987654321"\n')
        return 1

    print(f"Token configuré : {settings.telegram_bot_token[:10]}... (masqué)")
    print(f"Chat ID cible  : {settings.telegram_chat_id}")
    print("Envoi du message de test en cours...")

    notifier = TelegramNotifier(settings)
    try:
        success = await notifier.send_test_message()
        if success:
            print("\n🎉 SUCCÈS ! Le message de test a été transmis avec succès à votre Telegram.")
            print("Vérifiez l'application Telegram sur votre iPhone.")
            return 0
        else:
            print("\n❌ ÉCHEC : Telegram a rejeté l'envoi du message. Vérifiez le token et le chat ID.")
            return 1
    finally:
        await notifier.close()


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
