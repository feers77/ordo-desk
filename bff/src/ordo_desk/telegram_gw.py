"""Emulador de la API de Telegram, fiel por construcción.

El escritorio **no compone ni un solo carácter** del mensaje: lo recibe ya
armado por IAM, con su texto y sus botones. Esta es la diferencia entre un chat
simulado y un decorado — un decorado se desincroniza al primer cambio de formato
y nadie se entera hasta que el bot real dice otra cosa.

Pulsar un botón tampoco firma nada: se reinyecta el `callback_data` que llegó,
tal cual, al webhook real de IAM. Quien verifica la firma y quien decide si el
aprobador es el dueño del agente sigue siendo IAM.
"""

from __future__ import annotations

from typing import Any

import httpx

from ordo_desk.config import Settings
from ordo_desk.events import EventBus

# Los chats de la demo. Un chat_id de verdad nunca cae en este rango, así que
# el repartidor puede distinguirlos sin ambigüedad cuando llegue el bot real.
DEMO_CHAT_FLOOR = 900_000_000


class TelegramGateway:
    def __init__(self, settings: Settings, bus: EventBus, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._bus = bus
        self._client = client
        self._messages: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    def receive(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Lo que IAM creyó estar mandándole a Telegram."""
        message_id = self._next_id
        self._next_id += 1
        message = {
            "message_id": message_id,
            "chat_id": str(payload.get("chat_id", "")),
            "text": payload.get("text", ""),
            "buttons": _buttons(payload),
        }
        self._messages[message_id] = message
        self._bus.publish("telegram.message", message)
        return {"ok": True, "result": {"message_id": message_id}}

    def history(self) -> list[dict[str, Any]]:
        return [self._messages[key] for key in sorted(self._messages)]

    async def click(self, message_id: int, button_index: int) -> dict[str, Any]:
        """Reinyecta el callback firmado al webhook real de IAM."""
        message = self._messages.get(message_id)
        if message is None:
            raise LookupError(f"No existe el mensaje {message_id}")
        buttons = message["buttons"]
        if button_index >= len(buttons):
            raise LookupError(f"El mensaje {message_id} no tiene botón {button_index}")
        button = buttons[button_index]

        update = {
            "update_id": message_id,
            "callback_query": {
                "id": f"cb-{message_id}-{button_index}",
                "from": {"id": int(message["chat_id"])},
                "message": {
                    "message_id": message_id,
                    "chat": {"id": int(message["chat_id"])},
                },
                # El escritorio no firma: reenvía el dato que IAM firmó.
                "data": button["callback_data"],
            },
        }
        response = await self._client.post(
            f"{self._settings.iam_url}/iam/v1/telegram/webhook",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": self._settings.telegram_webhook_secret},
        )
        result: dict[str, Any] = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {"raw": response.text}
        )
        resolved = {
            "message_id": message_id,
            "label": button["text"],
            "status": response.status_code,
            "result": result,
        }
        self._bus.publish("telegram.resolved", resolved)
        return resolved


def _buttons(payload: dict[str, Any]) -> list[dict[str, str]]:
    markup = payload.get("reply_markup") or {}
    rows = markup.get("inline_keyboard") or []
    return [
        {"text": button.get("text", ""), "callback_data": button.get("callback_data", "")}
        for row in rows
        for button in row
    ]
