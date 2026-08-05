"""Sesión del navegador: una cookie firmada, sin estado de negocio.

Lo único que guarda es quién dice ser el visitante y contra qué tenant opera.
Los tokens viven en el servidor; la cookie solo los referencia indirectamente.
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

COOKIE_NAME = "desk_session"


@dataclass(frozen=True)
class Session:
    tenant: str
    persona: str
    issued_at: int

    def to_payload(self) -> dict[str, Any]:
        return {"tenant": self.tenant, "persona": self.persona, "iat": self.issued_at}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def sign(session: Session, secret: bytes) -> str:
    body = _b64(json.dumps(session.to_payload(), sort_keys=True, separators=(",", ":")).encode())
    mac = hmac.new(secret, body.encode(), sha256).digest()
    return f"{body}.{_b64(mac)}"


def verify(cookie: str, secret: bytes, *, ttl_s: int, now: int | None = None) -> Session | None:
    """Devuelve la sesión, o `None` si la cookie no es de fiar.

    Nunca lanza: una cookie manipulada es un visitante sin sesión, no un error
    del servidor. Y la comparación del MAC es en tiempo constante.
    """
    body, _, signature = cookie.partition(".")
    if not body or not signature:
        return None
    expected = hmac.new(secret, body.encode(), sha256).digest()
    try:
        given = _unb64(signature)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, given):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    issued_at = payload.get("iat")
    tenant = payload.get("tenant")
    persona = payload.get("persona")
    if (
        not isinstance(issued_at, int)
        or not isinstance(tenant, str)
        or not isinstance(persona, str)
    ):
        return None
    current = int(time.time()) if now is None else now
    if issued_at + ttl_s < current:
        return None
    return Session(tenant=tenant, persona=persona, issued_at=issued_at)


def new_session(tenant: str, persona: str, *, now: int | None = None) -> Session:
    return Session(
        tenant=tenant,
        persona=persona,
        issued_at=int(time.time()) if now is None else now,
    )
