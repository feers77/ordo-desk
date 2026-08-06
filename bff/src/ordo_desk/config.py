"""Configuración del BFF, leída del entorno una sola vez.

Todo lo sensible —el secreto del agente, la contraseña del usuario de
servicio— vive en el entorno y nunca en el repositorio ni en el navegador.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Los tres roles de la tienda. No son roles de IAM: son las personas que el
# visitante puede encarnar en la demo, y cada una tiene su propio agente con
# su propio capability token.
PERSONAS = ("cajero", "bodeguero", "duena")


@dataclass(frozen=True)
class AgentCredentials:
    """Lo que hace falta para pedirle a IAM un token de agente.

    Son dos credenciales, no una: el intercambio RFC 8693 exige el secreto del
    agente **y** un access token OIDC de su dueño. Por eso el navegador no
    puede hacerlo ni aunque quisiéramos.
    """

    agent_id: str
    agent_secret: str
    owner_username: str
    owner_password: str


@dataclass(frozen=True)
class Settings:
    api_url: str
    iam_url: str
    oidc_token_url: str
    oidc_client_id: str
    session_secret: bytes
    web_root: Path
    tenant: str
    credentials: dict[tuple[str, str], AgentCredentials] = field(default_factory=dict)
    session_ttl_s: int = 8 * 3600
    # La cookie se emite con Secure por defecto. En una LAN sin TLS hay que
    # apagarlo o el navegador ni siquiera la guarda —y entonces nada funciona—,
    # a cambio de que viaje en claro por la red local. Es una decisión de
    # despliegue y por eso es explícita, no un silencio.
    cookie_secure: bool = True
    # Quién puede inyectar mensajes en el chat de la demo. El emisor legítimo
    # es el worker de IAM; si corre en un contenedor, su IP no es la de
    # loopback y hay que declararla. Ampliar esta lista es dejar entrar a
    # quien esté en esa red, así que se declara y no se adivina.
    telegram_senders: tuple[str, ...] = ("127.0.0.1", "::1")
    # El mismo secreto que IAM exige en su webhook. Se declara aquí y no se lee
    # del entorno a mitad de una función: un valor de configuración escondido
    # dentro de la lógica es un valor que alguien olvida al desplegar.
    telegram_webhook_secret: str = ""
    request_timeout_s: float = 15.0
    # El core acepta hasta 500 filas por página; para una pantalla eso ya es un
    # error de diseño, así que el BFF corta antes.
    max_limit: int = 200

    def credentials_for(self, tenant: str, persona: str) -> AgentCredentials | None:
        return self.credentials.get((tenant, persona))


def _secret() -> bytes:
    raw = os.environ.get("DESK_SESSION_SECRET", "")
    if not raw:
        # Sin secreto no se firman cookies. Preferimos no arrancar antes que
        # arrancar con una clave por defecto que alguien deje en producción.
        raise RuntimeError(
            "DESK_SESSION_SECRET es obligatoria: firma las cookies de sesión. "
            'Genera una con `python -c "import secrets;print(secrets.token_hex(32))"`.'
        )
    return raw.encode()


def load_settings() -> Settings:
    tenant = os.environ.get("DESK_TENANT", "ropa")
    credentials: dict[tuple[str, str], AgentCredentials] = {}
    for persona in PERSONAS:
        prefix = f"DESK_{persona.upper()}"
        agent_id = os.environ.get(f"{prefix}_AGENT_ID", "")
        secret = os.environ.get(f"{prefix}_AGENT_SECRET", "")
        user = os.environ.get(f"{prefix}_USER", "")
        password = os.environ.get(f"{prefix}_PASSWORD", "")
        if agent_id and secret and user and password:
            credentials[(tenant, persona)] = AgentCredentials(
                agent_id=agent_id,
                agent_secret=secret,
                owner_username=user,
                owner_password=password,
            )
    return Settings(
        api_url=os.environ.get("ORDO_API_URL", "http://127.0.0.1:8000").rstrip("/"),
        iam_url=os.environ.get("ORDO_IAM_URL", "http://127.0.0.1:8002").rstrip("/"),
        oidc_token_url=os.environ.get("OIDC_TOKEN_URL", ""),
        oidc_client_id=os.environ.get("OIDC_CLIENT_ID", "ordo-cli"),
        session_secret=_secret(),
        web_root=Path(os.environ.get("DESK_WEB_ROOT", "web")).resolve(),
        tenant=tenant,
        credentials=credentials,
        cookie_secure=os.environ.get("DESK_COOKIE_SECURE", "1") != "0",
        telegram_senders=_senders(),
        telegram_webhook_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET", ""),
    )


def _senders() -> tuple[str, ...]:
    raw = os.environ.get("DESK_TELEGRAM_SENDERS", "")
    declared = tuple(piece.strip() for piece in raw.split(",") if piece.strip())
    return declared or ("127.0.0.1", "::1")
