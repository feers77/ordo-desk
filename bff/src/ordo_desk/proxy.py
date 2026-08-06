"""El pasamanos a ORDO: inyecta el token, no toca el contenido.

Regla vinculante (AGENTS.md §2.2): mismo path, mismo cuerpo, misma respuesta,
mismo envelope de error. Cualquier "mejora" aquí crea un segundo contrato que
nadie mantiene y que se desincroniza al primer cambio del core.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import httpx
from fastapi import Request, Response

from ordo_desk.approvals import (
    ApprovalBroker,
    ApprovalFailedError,
    fingerprint,
    route_to_operation,
    sealed_operation,
)
from ordo_desk.config import Settings
from ordo_desk.session import Session
from ordo_desk.tokens import TokenBroker, TokenError

# Solo lo que una pantalla necesita. `/iam/v1/*` no está y no debe estar: el
# BFF lo consume desde el servidor y jamás lo expone (AGENTS.md §2.5).
ALLOWED_PREFIXES = ("/api/v1/", "/meta/v1/")

# `webhook.subscription` expone el secreto de firma al leerlo. Un frontend no
# tiene nada que hacer con él, y una pantalla comprometida lo publicaría.
DENIED_MODELS = frozenset({"webhook.subscription"})

# Cabeceras que el cliente no decide: la identidad la pone el BFF. Si llegaran
# del navegador, cualquiera podría suplantar tenant o presentar su propio token.
STRIPPED_REQUEST_HEADERS = frozenset(
    {"authorization", "x-ordo-tenant", "x-ordo-approval", "host", "cookie", "content-length"}
)
STRIPPED_RESPONSE_HEADERS = frozenset({"content-length", "content-encoding", "transfer-encoding"})


class ProxyRefusedError(Exception):
    """El BFF se niega antes de llegar a ORDO."""

    def __init__(self, code: str, message: str, *, status_code: int, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.hint = hint

    def to_response(self) -> Response:
        payload: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": False,
                "requires_approval": False,
            }
        }
        if self.hint:
            payload["error"]["hint"] = self.hint
        return Response(
            content=json.dumps(payload),
            status_code=self.status_code,
            media_type="application/json",
        )


def check_path(path: str) -> str:
    """Normaliza y valida la ruta pedida. Devuelve la ruta hacia ORDO."""
    target = path if path.startswith("/") else f"/{path}"
    if not any(target.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise ProxyRefusedError(
            "DESK_PATH_NOT_ALLOWED",
            f"El escritorio no expone {target}",
            status_code=403,
            hint="Solo se proxean /api/v1/ y /meta/v1/.",
        )
    model = _model_of(target)
    if model in DENIED_MODELS:
        raise ProxyRefusedError(
            "DESK_MODEL_NOT_ALLOWED",
            f"El modelo {model} no se expone al navegador",
            status_code=403,
            hint="Sus registros contienen secretos de firma.",
        )
    return target


def _model_of(path: str) -> str:
    parts = [piece for piece in path.split("/") if piece]
    # /api/v1/<model>/...
    return parts[2] if len(parts) > 2 and parts[0] == "api" else ""


QueryParams = list[tuple[str, str | int | float | bool | None]]


def clamp_limit(params: QueryParams, maximum: int) -> QueryParams:
    """Un `limit` de 500 en una pantalla es un error de diseño, no una opción."""
    clamped: QueryParams = []
    for key, value in params:
        if key == "limit":
            # Un limit no numérico lo rechaza ORDO con su propio código; aquí
            # no se inventa un error nuevo por algo que el core ya explica.
            with contextlib.suppress(ValueError):
                value = str(min(int(str(value)), maximum))
        clamped.append((key, value))
    return clamped


def forward_headers(request: Request, token: str, tenant: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in STRIPPED_REQUEST_HEADERS
    }
    headers["Authorization"] = f"Bearer {token}"
    # Redundante con el token —el tenant sale de sus claims— pero explícito:
    # si alguna vez no coincidieran, ORDO responde 403 en vez de operar sobre
    # el tenant equivocado.
    headers["X-Ordo-Tenant"] = tenant
    return headers


class ApiProxy:
    def __init__(
        self,
        settings: Settings,
        broker: TokenBroker,
        client: httpx.AsyncClient,
        approvals: ApprovalBroker | None = None,
    ) -> None:
        self._settings = settings
        self._broker = broker
        self._client = client
        self._approvals = approvals or ApprovalBroker(settings, client)

    async def forward(self, request: Request, path: str, session: Session) -> Response:
        target = check_path(path)

        body = await request.body()
        params: QueryParams = clamp_limit(
            list(request.query_params.multi_items()), self._settings.max_limit
        )

        try:
            token = await self._broker.agent_token(session.tenant, session.persona)
        except TokenError as exc:
            raise ProxyRefusedError(
                "DESK_NO_CREDENTIALS",
                str(exc),
                status_code=503,
                hint="Revisa la provisión de identidades del escritorio.",
            ) from exc

        approval_id = self._approval_for(target, body, session)
        upstream = await self._send(
            request, target, params, body, token, session, approval=approval_id
        )
        if upstream.status_code == 403:
            upstream = await self._resolve_approval(
                request, target, params, body, token, session, upstream
            )
        if upstream.status_code == 401:
            # El token murió antes de lo previsto. Un reintento, no más: si el
            # segundo también falla, el problema no es el token.
            self._broker.invalidate(session.tenant, session.persona)
            token = await self._broker.agent_token(session.tenant, session.persona)
            upstream = await self._send(request, target, params, body, token, session)

        headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in STRIPPED_RESPONSE_HEADERS
        }
        headers["Cache-Control"] = "no-store"
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=upstream.headers.get("content-type"),
        )

    # ------------------------------------------------------------ aprobaciones

    def _intent(
        self, target: str, body: bytes, session: Session
    ) -> tuple[str, dict[str, Any]] | None:
        """La huella de esta intención, si es una acción que puede pedir permiso."""
        route = route_to_operation(target)
        if route is None:
            return None
        model, action, record_id = route
        try:
            parsed = json.loads(body) if body else {}
        except ValueError:
            return None
        operation = sealed_operation(model, action, record_id, parsed)
        return fingerprint(session.tenant, session.persona, operation), operation

    def _approval_for(self, target: str, body: bytes, session: Session) -> str | None:
        intent = self._intent(target, body, session)
        return None if intent is None else self._approvals.known(intent[0])

    async def _resolve_approval(
        self,
        request: Request,
        target: str,
        params: QueryParams,
        body: bytes,
        token: str,
        session: Session,
        upstream: httpx.Response,
    ) -> httpx.Response:
        """Ante IAM_APPROVAL_REQUIRED, pide el permiso y devuelve su id.

        No se espera aquí a que alguien apruebe: bloquear el request dejaría al
        cajero mirando una pantalla congelada durante minutos. El navegador ve
        el 403 con el id, el mensaje aparece en Telegram, y cuando se aprueba
        vuelve a enviar exactamente el mismo request —que ahora sí lleva la
        cabecera.
        """
        try:
            payload = upstream.json()
        except ValueError:
            return upstream
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if error.get("code") != "IAM_APPROVAL_REQUIRED":
            return upstream
        intent = self._intent(target, body, session)
        if intent is None:
            return upstream
        key, operation = intent

        try:
            created = await self._approvals.request(token=token, key=key, operation=operation)
        except (ApprovalFailedError, httpx.HTTPError) as exc:
            raise ProxyRefusedError(
                "DESK_APPROVAL_FAILED",
                f"No se pudo pedir la aprobación: {exc}",
                status_code=502,
                hint="Revisa que el servicio IAM esté disponible.",
            ) from exc

        if created.get("status") == "approved":
            # Ya estaba aprobada de antes: se reintenta en el acto.
            return await self._send(
                request, target, params, body, token, session, approval=created["approval_id"]
            )

        error["approval_id"] = created["approval_id"]
        error["approval_status"] = created.get("status")
        return httpx.Response(
            upstream.status_code,
            json=payload,
            headers={"content-type": "application/json"},
        )

    async def _send(
        self,
        request: Request,
        target: str,
        params: QueryParams,
        body: bytes,
        token: str,
        session: Session,
        *,
        approval: str | None = None,
    ) -> httpx.Response:
        headers = forward_headers(request, token, session.tenant)
        if approval:
            # La cabecera la pone el BFF, nunca el cliente: si el navegador
            # pudiera fijarla, presentaría aprobaciones ajenas.
            headers["X-Ordo-Approval"] = approval
        return await self._client.request(
            request.method,
            f"{self._settings.api_url}{target}",
            params=params,
            content=body or None,
            headers=headers,
            timeout=self._settings.request_timeout_s,
        )
