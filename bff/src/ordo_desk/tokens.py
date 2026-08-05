"""Custodia y renovación de los tokens de agente.

Un token de agente vive 15 minutos y no tiene refresh. Renovarlo exige el
secreto del agente **y** un access token OIDC de su dueño, así que esto no
puede vivir en el navegador ni aunque quisiéramos: es la razón principal por la
que existe el BFF.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from ordo_desk.config import AgentCredentials, Settings

# URNs del RFC 8693. No son secretos; el linter los confunde con claves.
TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"  # noqa: S105
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"  # noqa: S105

# Se renueva a los 12 de los 15 minutos. Esperar al 401 para descubrir que el
# token venció convierte cada vencimiento en un error visible para el cajero.
REFRESH_MARGIN_S = 180


class TokenError(RuntimeError):
    """No se pudo obtener un token; el detalle va en el mensaje."""


@dataclass
class CachedToken:
    value: str
    expires_at: float

    def fresh(self, *, now: float, margin: int = REFRESH_MARGIN_S) -> bool:
        return now + margin < self.expires_at


class TokenBroker:
    """Caché de tokens por (tenant, persona), con un candado por clave.

    El candado por clave evita la estampida: cuando el token vence y llegan
    diez requests a la vez, uno renueva y los otros nueve esperan su resultado
    en vez de disparar diez intercambios contra IAM.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client
        self._agent: dict[tuple[str, str], CachedToken] = {}
        self._owner: dict[str, CachedToken] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _lock(self, key: tuple[str, str]) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    async def agent_token(self, tenant: str, persona: str) -> str:
        key = (tenant, persona)
        now = time.monotonic()
        cached = self._agent.get(key)
        if cached is not None and cached.fresh(now=now):
            return cached.value

        async with self._lock(key):
            # Otro request pudo renovarlo mientras esperábamos el candado.
            cached = self._agent.get(key)
            if cached is not None and cached.fresh(now=time.monotonic()):
                return cached.value
            credentials = self._settings.credentials_for(tenant, persona)
            if credentials is None:
                raise TokenError(
                    f"No hay credenciales configuradas para {persona} en {tenant}. "
                    f"Corre `make provision TENANT={tenant}` y exporta las variables."
                )
            token = await self._exchange(credentials)
            self._agent[key] = token
            return token.value

    def invalidate(self, tenant: str, persona: str) -> None:
        """Se llama ante un 401 de ORDO: el token murió antes de lo previsto."""
        self._agent.pop((tenant, persona), None)

    async def _exchange(self, credentials: AgentCredentials) -> CachedToken:
        subject = await self._owner_token(credentials)
        response = await self._client.post(
            f"{self._settings.iam_url}/iam/v1/token",
            data={
                "grant_type": TOKEN_EXCHANGE_GRANT,
                "subject_token": subject,
                "subject_token_type": ACCESS_TOKEN_TYPE,
                "client_id": credentials.agent_id,
                "client_secret": credentials.agent_secret,
            },
        )
        if response.status_code != 200:
            raise TokenError(
                f"IAM rechazó el intercambio ({response.status_code}): {response.text[:200]}"
            )
        payload = response.json()
        return CachedToken(
            value=payload["access_token"],
            expires_at=time.monotonic() + int(payload.get("expires_in", 900)),
        )

    async def _owner_token(self, credentials: AgentCredentials) -> str:
        """Access token OIDC del dueño del agente.

        Se cachea aparte porque un mismo dueño puede tener varios agentes, y
        porque su vencimiento no coincide con el del token de agente.
        """
        cached = self._owner.get(credentials.owner_username)
        if cached is not None and cached.fresh(now=time.monotonic()):
            return cached.value
        if not self._settings.oidc_token_url:
            raise TokenError(
                "OIDC_TOKEN_URL no está configurada: sin ella no se puede "
                "obtener el token del dueño que exige el intercambio."
            )
        response = await self._client.post(
            self._settings.oidc_token_url,
            data={
                "grant_type": "password",
                "client_id": self._settings.oidc_client_id,
                "username": credentials.owner_username,
                "password": credentials.owner_password,
                "scope": "openid",
            },
        )
        if response.status_code != 200:
            raise TokenError(
                f"El proveedor OIDC rechazó al dueño ({response.status_code}): "
                f"{response.text[:200]}"
            )
        payload = response.json()
        token = CachedToken(
            value=payload["access_token"],
            expires_at=time.monotonic() + int(payload.get("expires_in", 300)),
        )
        self._owner[credentials.owner_username] = token
        return token.value
