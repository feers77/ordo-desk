"""Bus de eventos del escritorio y su salida por SSE.

Lo único que viaja por aquí es lo que **nace en el BFF**: mensajes de Telegram,
resoluciones de aprobación. Los eventos de negocio son de ORDO y llegarán por
webhook; mezclarlos aquí haría creer que el escritorio los origina.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

# Cuántos eventos se guardan por si un navegador se reconecta. No es
# persistencia: es el margen para un F5, y por eso es pequeño.
BACKLOG = 50


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._backlog: list[dict[str, Any]] = []
        self._sequence = 0

    def publish(self, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._sequence += 1
        event = {"id": self._sequence, "topic": topic, "payload": payload}
        self._backlog.append(event)
        del self._backlog[:-BACKLOG]
        for queue in list(self._subscribers):
            # Si un suscriptor no lee, se le pierden eventos: preferimos eso a
            # que un navegador colgado bloquee al que publica.
            with_room = queue.qsize() < 100
            if with_room:
                queue.put_nowait(event)
        return event

    def backlog(self, since: int) -> list[dict[str, Any]]:
        return [event for event in self._backlog if event["id"] > since]

    async def stream(self, since: int = 0) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        try:
            for event in self.backlog(since):
                yield _frame(event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                except TimeoutError:
                    # Un comentario SSE mantiene viva la conexión sin inventar
                    # un evento que el cliente tendría que ignorar.
                    yield ": ping\n\n"
                    continue
                yield _frame(event)
        finally:
            self._subscribers.discard(queue)


def _frame(event: dict[str, Any]) -> str:
    body = json.dumps(event["payload"], ensure_ascii=False)
    return f"id: {event['id']}\nevent: {event['topic']}\ndata: {body}\n\n"
