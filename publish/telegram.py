"""Minimal Telegram Bot API client (stdlib only): sendRichMessage (Bot API 10.1+).

A rich message is a nested object, so we POST a JSON body. Media is passed by
HTTP URL (no multipart upload). The bot token is read from the environment at
call time so it never lands on argv.

Vendored verbatim from sm-th/researcher (publisher/publisher/telegram.py).
"""

import json
import re
import urllib.error
import urllib.request


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, bot_token: str):
        self.base = f"https://api.telegram.org/bot{bot_token}"

    def _call(self, method: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base}/{method}",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise TelegramError(f"{method} -> HTTP {e.code}: {detail}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method} -> {data.get('description', data)}")
        return data["result"]

    def send_rich_message(self, chat_id: str, rich_message: dict,
                          disable_notification: bool = False) -> dict:
        return self._call("sendRichMessage", {
            "chat_id": chat_id,
            "rich_message": rich_message,
            "disable_notification": disable_notification,
        })


def permalink(chat_id: str, username: str | None, message_id: int) -> str:
    """Public URL of a channel post. Prefer @username, else the private
    t.me/c/<internal>/<id> form for a numeric -100... channel."""
    name = username or (chat_id[1:] if chat_id.startswith("@") else "")
    if name:
        return f"https://t.me/{re.sub(r'^@', '', name)}/{message_id}"
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{message_id}"
    return f"https://t.me/{chat_id.lstrip('@')}/{message_id}"
