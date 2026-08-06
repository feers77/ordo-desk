"""Coreografía de aprobaciones: del 403 al mensaje de Telegram y de vuelta.

Cuando ORDO responde `IAM_APPROVAL_REQUIRED`, alguien tiene que crear la
solicitud **con el token del agente** —que el navegador no tiene por diseño— y
sellarla con la operación exacta que se reintentará después. Ese alguien es el
BFF.

El sello es contrato público de ORDO (`sealed_operation` en `ordo_runtime`):

    {"model": ..., "operation": ..., "payload": {"record_id": ..., "body": ...}}

Se replica aquí porque el escritorio no depende del core, y hay un test que fija
la forma. Si no coincidiera byte a byte con lo que el middleware construye al
reintentar, IAM responde `IAM_APPROVAL_MISMATCH` y la operación no se ejecuta
nunca — que es exactamente la protección que se está usando.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import httpx

from ordo_desk.config import Settings

# /api/v1/<model>/<id>/actions/<accion>
ACTION_PATH = re.compile(r"^/api/v1/(?P<model>[^/]+)/(?P<record_id>\d+)/actions/(?P<action>[^/]+)$")


def route_to_operation(path: str) -> tuple[str, str, int] | None:
    """Solo las acciones de negocio piden aprobación; el CRUD no llega aquí."""
    found = ACTION_PATH.match(path)
    if found is None:
        return None
    return found["model"], found["action"], int(found["record_id"])


def sealed_operation(
    model: str, operation: str, record_id: int | None, body: Any
) -> dict[str, Any]:
    """Contrato público de ORDO. No inventar campos ni reordenar."""
    return {
        "model": model,
        "operation": operation,
        "payload": {"record_id": record_id, "body": body if body is not None else {}},
    }


def fingerprint(tenant: str, persona: str, operation: dict[str, Any]) -> str:
    """Identifica la intención para reconocerla en el reintento."""
    canonical = json.dumps(operation, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(f"{tenant}|{persona}|{canonical}".encode()).hexdigest()
    return digest[:32]


class ApprovalBroker:
    """Recuerda qué aprobación corresponde a qué intención.

    En memoria a propósito: una aprobación pendiente que sobreviva a un
    reinicio del escritorio sería estado de negocio fuera de ORDO, y eso está
    prohibido (AGENTS.md §2.1). Si el proceso se cae, el agente vuelve a pedirla.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client
        self._pending: dict[str, str] = {}

    def known(self, key: str) -> str | None:
        return self._pending.get(key)

    def forget(self, key: str) -> None:
        self._pending.pop(key, None)

    async def request(self, *, token: str, key: str, operation: dict[str, Any]) -> dict[str, Any]:
        """Crea la solicitud con el token del agente. Idempotente por la huella."""
        response = await self._client.post(
            f"{self._settings.iam_url}/iam/v1/approvals",
            json={"operation": operation},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        )
        if response.status_code not in (200, 201):
            raise ApprovalFailedError(
                f"IAM rechazó la solicitud ({response.status_code}): {response.text[:200]}"
            )
        payload: dict[str, Any] = response.json()
        self._pending[key] = payload["approval_id"]
        return payload

    async def status(self, *, token: str, approval_id: str) -> dict[str, Any]:
        response = await self._client.get(
            f"{self._settings.iam_url}/iam/v1/approvals/{approval_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        payload: dict[str, Any] = response.json()
        return payload


class ApprovalFailedError(RuntimeError):
    """No se pudo crear la solicitud de aprobación."""
