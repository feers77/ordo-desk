"""El BFF: sirve la web y presta identidad. Nada más.

Su lista de rutas propias es cerrada a propósito. Cada ruta que se agregue aquí
es superficie que alguien tiene que mantener y que no está en el contrato de
ORDO; si una pantalla necesita datos, los pide por `/desk/api/*`.
"""

from __future__ import annotations

import ipaddress
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ordo_desk.config import PERSONAS, Settings, load_settings
from ordo_desk.events import EventBus
from ordo_desk.proxy import ApiProxy, ProxyRefusedError
from ordo_desk.session import COOKIE_NAME, new_session, sign, verify
from ordo_desk.telegram_gw import TelegramGateway
from ordo_desk.tokens import TokenBroker


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=config.request_timeout_s) as client:
            app.state.client = client
            app.state.broker = TokenBroker(config, client)
            app.state.proxy = ApiProxy(config, app.state.broker, client)
            app.state.bus = EventBus()
            app.state.telegram = TelegramGateway(config, app.state.bus, client)
            yield

    app = FastAPI(title="ordo-desk", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = config

    def current_session(request: Request) -> Any:
        cookie = request.cookies.get(COOKIE_NAME, "")
        if not cookie:
            return None
        return verify(cookie, config.session_secret, ttl_s=config.session_ttl_s)

    @app.get("/desk/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "desk"}

    @app.get("/desk/session")
    async def read_session(request: Request) -> Response:
        session = current_session(request)
        if session is None:
            return JSONResponse(
                {
                    "error": {
                        "code": "DESK_NO_SESSION",
                        "message": "Todavía no elegiste con quién entrar",
                        "retryable": False,
                        "requires_approval": False,
                        "hint": "Haz POST /desk/session con la persona.",
                    }
                },
                status_code=401,
            )
        return JSONResponse(
            {
                "tenant": session.tenant,
                "persona": session.persona,
                "personas": list(PERSONAS),
                # Se dice explícitamente para que nadie lo dude leyendo el
                # código de la web: el token vive en el servidor.
                "token_in_browser": False,
            }
        )

    @app.post("/desk/session")
    async def start_session(request: Request) -> Response:
        body = await _json(request)
        persona = str(body.get("persona") or "")
        if persona not in PERSONAS:
            return JSONResponse(
                {
                    "error": {
                        "code": "DESK_UNKNOWN_PERSONA",
                        "message": f"'{persona}' no es una persona de la demo",
                        "retryable": False,
                        "requires_approval": False,
                        "hint": f"Elige una de: {', '.join(PERSONAS)}.",
                    }
                },
                status_code=400,
            )
        session = new_session(config.tenant, persona)
        response = JSONResponse({"tenant": session.tenant, "persona": session.persona})
        response.set_cookie(
            COOKIE_NAME,
            sign(session, config.session_secret),
            max_age=config.session_ttl_s,
            httponly=True,
            samesite="strict",
            secure=config.cookie_secure,
            path="/",
        )
        return response

    # Dos rutas explícitas en vez de deducir el prefijo de la ruta pedida:
    # `/desk/api/v1/...` y `/desk/meta/v1/...` leen igual que sus equivalentes
    # en ORDO, y no hay magia que adivine cuál es cuál.
    @app.api_route("/desk/api/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    async def proxy_api(path: str, request: Request) -> Response:
        return await _proxy(request, f"/api/{path}")

    @app.api_route("/desk/meta/{path:path}", methods=["GET", "POST"])
    async def proxy_meta(path: str, request: Request) -> Response:
        return await _proxy(request, f"/meta/{path}")

    async def _proxy(request: Request, target: str) -> Response:
        session = current_session(request)
        if session is None:
            return ProxyRefusedError(
                "DESK_NO_SESSION",
                "Sesión ausente o vencida",
                status_code=401,
                hint="Vuelve a entrar eligiendo una persona.",
            ).to_response()
        try:
            proxied: Response = await request.app.state.proxy.forward(request, target, session)
            return proxied
        except ProxyRefusedError as refused:
            return refused.to_response()
        except httpx.HTTPError as exc:
            return ProxyRefusedError(
                "DESK_UPSTREAM_UNREACHABLE",
                f"No se pudo hablar con ORDO: {exc}",
                status_code=502,
                hint="Revisa que ordo-api esté arriba.",
            ).to_response()

    @app.get("/desk/events")
    async def events(request: Request) -> Response:
        """Lo que nace en el escritorio, empujado al navegador."""
        if current_session(request) is None:
            return ProxyRefusedError(
                "DESK_NO_SESSION", "Sesión ausente", status_code=401
            ).to_response()
        since = int(request.query_params.get("since", "0") or 0)
        return StreamingResponse(
            request.app.state.bus.stream(since),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/desk/tg/bot{token}/sendMessage")
    async def telegram_send(token: str, request: Request) -> Response:
        """Recibe lo que IAM creyó estar mandándole a Telegram.

        Solo desde la propia máquina: el emisor es el worker de IAM, no un
        navegador, y aceptarlo desde fuera dejaría a cualquiera inyectar
        mensajes en el chat de la demo.
        """
        client_host = request.client.host if request.client else ""
        if not _allowed_sender(client_host, config.telegram_senders):
            return ProxyRefusedError(
                "DESK_TELEGRAM_FOREIGN",
                "El emulador de Telegram solo acepta al emisor local",
                status_code=403,
            ).to_response()
        del token  # el token del bot no se valida: el receptor es el emulador
        payload = await _json(request)
        return JSONResponse(request.app.state.telegram.receive(payload))

    @app.get("/desk/tg/history")
    async def telegram_history(request: Request) -> Response:
        if current_session(request) is None:
            return ProxyRefusedError(
                "DESK_NO_SESSION", "Sesión ausente", status_code=401
            ).to_response()
        return JSONResponse({"messages": request.app.state.telegram.history()})

    @app.post("/desk/tg/click")
    async def telegram_click(request: Request) -> Response:
        """El navegador pulsó un botón inline.

        El escritorio no firma nada: reinyecta el `callback_data` que IAM firmó,
        tal cual, al webhook real. Quien verifica la firma y exige que el
        aprobador sea el dueño del agente sigue siendo IAM.
        """
        session = current_session(request)
        if session is None:
            return ProxyRefusedError(
                "DESK_NO_SESSION", "Sesión ausente", status_code=401
            ).to_response()
        body = await _json(request)
        try:
            resolved = await request.app.state.telegram.click(
                int(body.get("message_id", 0)), int(body.get("button_index", 0))
            )
        except (LookupError, ValueError) as exc:
            return ProxyRefusedError(
                "DESK_TELEGRAM_UNKNOWN_BUTTON", str(exc), status_code=404
            ).to_response()
        return JSONResponse(resolved)

    _mount_web(app, config.web_root)
    return app


def _allowed_sender(host: str, declared: tuple[str, ...]) -> bool:
    """Coincidencia exacta o por red declarada, nunca por prefijo de texto.

    Comparar cadenas dejaría pasar "172.18.0.99" con una regla "172.1", que es
    la clase de error que abre una puerta sin que nadie lo note.
    """
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    for entry in declared:
        try:
            if "/" in entry:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
            elif address == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


async def _json(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mount_web(app: FastAPI, root: Path) -> None:
    """Sirve `web/` desde el mismo origen que la API.

    Mismo origen es lo que hace innecesario el CORS: el core no lo tiene y no
    debe tenerlo. Servir los estáticos desde otro host obligaría a pedírselo.
    """

    @app.get("/")
    async def index() -> Response:
        return _file(root / "index.html")

    @app.get("/web/{path:path}")
    async def static_file(path: str) -> Response:
        candidate = (root / path).resolve()
        # Defensa contra path traversal: fuera de la raíz no se sirve nada,
        # por más que la ruta pedida parezca inocente.
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return JSONResponse({"error": {"code": "DESK_NOT_FOUND"}}, status_code=404)
        return _file(candidate)


def _file(path: Path) -> Response:
    if not path.is_file():
        return JSONResponse({"error": {"code": "DESK_NOT_FOUND"}}, status_code=404)
    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
