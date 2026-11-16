from __future__ import annotations

import requests


def button(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


class Telegram:
    def __init__(self, token: str, session: requests.Session | None = None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.s = session or requests.Session()

    def call(self, method: str, http_timeout: float = 30, **params):
        data = self.s.post(f"{self.base}/{method}", json=params, timeout=http_timeout).json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description')}")
        return data["result"]

    def send(self, chat_id: int, text: str, buttons: list[list[dict]] | None = None) -> dict:
        params = {"chat_id": chat_id, "text": text}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **params)

    def edit(self, chat_id: int, message_id: int, text: str) -> None:
        self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text)

    def answer(self, callback_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def updates(self, offset: int, wait: int = 50) -> list[dict]:
        return self.call("getUpdates", http_timeout=wait + 15, offset=offset, timeout=wait,
                         allowed_updates=["message", "callback_query"])
