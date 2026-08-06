"""El chat de Telegram: fiel por construcción, no por disciplina."""

from __future__ import annotations

import httpx
import pytest

from ordo_desk.events import EventBus
from ordo_desk.telegram_gw import TelegramGateway

pytestmark = pytest.mark.anyio

# Exactamente lo que produce `build_approval_messages` de IAM: el texto de
# `approval_summary` y dos botones con el callback_data ya firmado.
IAM_MESSAGE = {
    "chat_id": "900000001",
    "text": (
        "ORDO — aprobación pendiente\n\n"
        "Agente: caja-1\n"
        "Operación: pos.order.action_refund\n"
        "Solicitud: 3f2a1b\n"
        "Vence: 2026-08-06 19:40 UTC"
    ),
    "reply_markup": {
        "inline_keyboard": [
            [
                {"text": "✅ Aprobar", "callback_data": "a1:3f2a1b:a:9c1d0e2f3a4b5c6d7e8f"},
                {"text": "⛔ Rechazar", "callback_data": "a1:3f2a1b:r:44b7aa11bb22cc33dd44"},
            ]
        ]
    },
}


class TestFidelity:
    async def test_the_desk_composes_nothing(self, settings) -> None:
        """Si el escritorio armara el texto, se desincronizaría al primer
        cambio de formato de IAM y nadie se enteraría hasta ver el bot real."""
        bus = EventBus()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
        ) as client:
            gateway = TelegramGateway(settings, bus, client)
            gateway.receive(IAM_MESSAGE)
            [message] = gateway.history()

        assert message["text"] == IAM_MESSAGE["text"]
        assert [button["text"] for button in message["buttons"]] == ["✅ Aprobar", "⛔ Rechazar"]

    async def test_clicking_replays_the_signature_it_received(self, settings) -> None:
        """El escritorio no firma: reenvía lo que IAM firmó."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True, "action": "approved"})

        bus = EventBus()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = TelegramGateway(settings, bus, client)
            gateway.receive(IAM_MESSAGE)
            resolved = await gateway.click(1, 0)

        [forwarded] = seen
        assert forwarded.url.path.endswith("/iam/v1/telegram/webhook")
        body = forwarded.read().decode()
        assert "a1:3f2a1b:a:9c1d0e2f3a4b5c6d7e8f" in body
        assert resolved["label"] == "✅ Aprobar"

    async def test_an_unknown_button_is_refused(self, settings) -> None:
        bus = EventBus()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ) as client:
            gateway = TelegramGateway(settings, bus, client)
            gateway.receive(IAM_MESSAGE)
            with pytest.raises(LookupError):
                await gateway.click(1, 5)


class TestBus:
    async def test_the_message_reaches_the_browser(self, settings) -> None:
        bus = EventBus()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ) as client:
            TelegramGateway(settings, bus, client).receive(IAM_MESSAGE)
        [event] = bus.backlog(0)
        assert event["topic"] == "telegram.message"
        assert event["payload"]["text"].startswith("ORDO")

    def test_a_reconnecting_browser_gets_what_it_missed(self) -> None:
        bus = EventBus()
        for index in range(3):
            bus.publish("test", {"n": index})
        assert [event["payload"]["n"] for event in bus.backlog(1)] == [1, 2]


class TestEndpoints:
    async def test_the_emulator_refuses_a_remote_sender(self, remote_client) -> None:
        """El emisor legítimo es el worker de IAM en la misma máquina. Aceptarlo
        desde fuera dejaría a cualquiera inyectar mensajes en el chat."""
        response = await remote_client.post("/desk/tg/bot123:abc/sendMessage", json=IAM_MESSAGE)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "DESK_TELEGRAM_FOREIGN"

    async def test_the_local_worker_is_accepted(self, client) -> None:
        response = await client.post("/desk/tg/bot123:abc/sendMessage", json=IAM_MESSAGE)
        assert response.status_code == 200
        assert response.json()["ok"] is True

    async def test_history_needs_a_session(self, client) -> None:
        response = await client.get("/desk/tg/history")
        assert response.status_code == 401

    async def test_events_need_a_session(self, client) -> None:
        response = await client.get("/desk/events")
        assert response.status_code == 401


class TestSenderAllowList:
    def test_an_exact_address_matches(self) -> None:
        from ordo_desk.main import _allowed_sender

        assert _allowed_sender("127.0.0.1", ("127.0.0.1", "::1"))
        assert not _allowed_sender("10.0.0.9", ("127.0.0.1", "::1"))

    def test_a_declared_network_matches(self) -> None:
        from ordo_desk.main import _allowed_sender

        assert _allowed_sender("172.18.0.4", ("127.0.0.1", "172.18.0.0/16"))

    def test_it_never_matches_by_text_prefix(self) -> None:
        """Comparar cadenas dejaría pasar 172.18.0.99 con una regla "172.1",
        que es la clase de error que abre una puerta sin que nadie lo note."""
        from ordo_desk.main import _allowed_sender

        assert not _allowed_sender("172.18.0.99", ("172.1",))
        assert not _allowed_sender("127.0.0.11", ("127.0.0.1",))

    def test_garbage_is_not_a_sender(self) -> None:
        from ordo_desk.main import _allowed_sender

        assert not _allowed_sender("", ("127.0.0.1",))
        assert not _allowed_sender("no-una-ip", ("127.0.0.1",))


class TestWebhookSecret:
    async def test_the_secret_travels_with_the_callback(self, settings) -> None:
        """IAM lo exige y falla cerrado sin él. Leerlo del entorno a mitad de
        una función es como se pierde al desplegar."""
        import dataclasses

        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        configured = dataclasses.replace(settings, telegram_webhook_secret="s3cr3to")
        bus = EventBus()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = TelegramGateway(configured, bus, client)
            gateway.receive(IAM_MESSAGE)
            await gateway.click(1, 0)

        [forwarded] = seen
        assert forwarded.headers["x-telegram-bot-api-secret-token"] == "s3cr3to"
