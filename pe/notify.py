"""Optional Telegram push of the report (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)."""
import logging
import os

import requests


def telegram(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        logging.warning("Telegram credentials missing; skipping")
        return
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text}, timeout=15)
    if r.status_code != 200:
        logging.error("Telegram failed %s: %s", r.status_code, r.text[:200])
