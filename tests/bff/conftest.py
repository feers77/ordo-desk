"""ORDO simulado: el BFF se prueba sin levantar el core."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from ordo_desk.config import AgentCredentials, Settings

REPO = Path(__file__).resolve().parents[2]


class FakeOrdo:
    """Registra lo que recibe y responde lo que se le diga.

    Sirve para lo único que hay que probar del proxy: qué cabeceras llegan,
    qué ruta, y qué se devuelve tal cual.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.payload: dict[str, Any] = {"rows": []}
        self.token_calls = 0
        self.oidc_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/iam/v1/approvals" in path:
            return httpx.Response(
                201, json={"approval_id": "apr-1", "status": "pending", "operation_hash": "h"}
            )
        if path.endswith("/iam/v1/token"):
            self.token_calls += 1
            return httpx.Response(
                200, json={"access_token": f"agent-token-{self.token_calls}", "expires_in": 900}
            )
        if "openid-connect/token" in path:
            self.oidc_calls += 1
            return httpx.Response(
                200, json={"access_token": f"owner-token-{self.oidc_calls}", "expires_in": 300}
            )
        self.requests.append(request)
        return httpx.Response(self.status, json=self.payload)


@pytest.fixture
def ordo() -> FakeOrdo:
    return FakeOrdo()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        api_url="http://ordo.test",
        iam_url="http://iam.test",
        oidc_token_url="http://keycloak.test/realms/ordo/protocol/openid-connect/token",
        oidc_client_id="ordo-desk",
        session_secret=b"secreto-de-prueba",
        web_root=REPO / "web",
        tenant="ropa",
        credentials={
            ("ropa", "cajero"): AgentCredentials(
                agent_id="agent-cajero",
                agent_secret="s3cr3t",
                owner_username="cajera@demo.cl",
                owner_password="clave",
            )
        },
    )


@pytest.fixture
async def client(settings: Settings, ordo: FakeOrdo):
    from ordo_desk.events import EventBus
    from ordo_desk.main import create_app
    from ordo_desk.proxy import ApiProxy
    from ordo_desk.telegram_gw import TelegramGateway
    from ordo_desk.tokens import TokenBroker

    app = create_app(settings)
    transport = httpx.MockTransport(ordo.handler)
    upstream = httpx.AsyncClient(transport=transport)
    app.state.client = upstream
    app.state.broker = TokenBroker(settings, upstream)
    app.state.proxy = ApiProxy(settings, app.state.broker, upstream)
    app.state.bus = EventBus()
    app.state.telegram = TelegramGateway(settings, app.state.bus, upstream)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://desk.test"
    ) as browser:
        browser.app = app  # type: ignore[attr-defined]
        yield browser
    await upstream.aclose()


@pytest.fixture
async def remote_client(settings: Settings, ordo: FakeOrdo):
    """Un navegador que no viene de la propia máquina.

    `ASGITransport` se presenta como 127.0.0.1 por defecto, así que sin fijarlo
    el guardia del emulador de Telegram pasaría siempre y el test no probaría
    nada.
    """
    from ordo_desk.events import EventBus
    from ordo_desk.main import create_app
    from ordo_desk.telegram_gw import TelegramGateway

    app = create_app(settings)
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(ordo.handler))
    app.state.client = upstream
    app.state.bus = EventBus()
    app.state.telegram = TelegramGateway(settings, app.state.bus, upstream)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("10.0.0.9", 40000)),
        base_url="https://desk.test",
    ) as browser:
        yield browser
    await upstream.aclose()
