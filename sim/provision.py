"""Identidades de la demo en IAM: un agente por persona, una sola vez.

Lo que este script **sí** puede hacer con la API pública de ORDO: registrar el
agente de cada persona y darle su capacidad acotada. Lo que **no**: crear el
usuario IAM dueño de ese agente. IAM pre-aprovisiona usuarios y no los
auto-crea, y hoy el core no expone una forma soportada de sembrar el primero
(`tools/seed_iam_roles.py` siembra roles y ACL, no membresías).

Ese hueco es del core, no de aquí, y se anota en vez de taparlo con SQL a mano
metido en un script de demo: un despliegue con enforcement no debería necesitar
que alguien escriba INSERTs para tener su primer usuario.

Uso:

    OWNER_TOKEN=<access token OIDC de la dueña> \\
    uv run python sim/provision.py ropa
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import httpx

IAM_URL = os.environ.get("ORDO_IAM_URL", "http://127.0.0.1:8002").rstrip("/")

# Cada persona recibe exactamente lo que su trabajo necesita. El cajero no lee
# reportes financieros y el bodeguero no cobra: si una pantalla necesita más,
# la conversación es sobre el rol, no sobre ampliar el cap en silencio.
CAPABILITIES: dict[str, dict[str, Any]] = {
    "cajero": {
        "models": {
            "pos.config": ["read"],
            "pos.payment.method": ["read"],
            "pos.session": ["read", "write", "create"],
            "pos.order": ["read", "write", "create"],
            "pos.order.line": ["read", "write", "create"],
            "pos.payment": ["read", "write", "create"],
            "product.product": ["read"],
            "res.partner": ["read", "create"],
        },
        # El límite por venta va aquí y no en un requires_approval por ticket:
        # pedirle permiso a la dueña por cada polera mataría la caja (ADR-019).
        "limits": {"max_amount_per_op": {"CLP": 2000000}},
        "requires_approval": ["pos.session.action_close", "pos.order.action_refund"],
        "deny": ["res.users.*", "account.move.*"],
    },
    "bodeguero": {
        "models": {
            "stock.picking": ["read", "write", "create"],
            "stock.move": ["read", "write", "create"],
            "stock.location": ["read"],
            "stock.reorder.rule": ["read", "write", "create"],
            "product.product": ["read"],
            "product.template": ["read"],
            "reports": ["read"],
        },
        "deny": ["res.users.*", "account.move.*"],
    },
    "duena": {
        "models": {
            "pos.session": ["read"],
            "pos.order": ["read"],
            "purchase.order": ["read", "write", "create"],
            "product.product": ["read"],
            "product.template": ["read", "write", "create"],
            "stock.reorder.rule": ["read", "write", "create"],
            "reports": ["read"],
        },
        "requires_approval": ["purchase.order.action_confirm"],
        "deny": ["res.users.*"],
    },
}


async def provision(tenant: str, owner_token: str) -> None:
    headers = {"Authorization": f"Bearer {owner_token}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        me = await client.get(f"{IAM_URL}/iam/v1/me", headers=headers)
        if me.status_code != 200:
            raise SystemExit(
                f"El token del dueño no sirve ({me.status_code}): {me.text[:200]}\n"
                "IAM pre-aprovisiona usuarios: el usuario tiene que existir antes."
            )
        owner = me.json()
        if owner["tenant"] != tenant:
            raise SystemExit(f"El token pertenece al tenant '{owner['tenant']}', no a '{tenant}'.")
        print(f"Dueño: {owner['display_name']} ({owner['principal_id']}) en {tenant}")

        for persona, capability in CAPABILITIES.items():
            registered = await client.post(
                f"{IAM_URL}/iam/v1/agents",
                headers=headers,
                json={
                    "display_name": f"escritorio-{persona}",
                    "model": "ordo-desk",
                    "autonomy_level": "operator",
                },
            )
            if registered.status_code != 201:
                raise SystemExit(
                    f"No se pudo registrar el agente de {persona} "
                    f"({registered.status_code}): {registered.text[:200]}"
                )
            agent = registered.json()

            granted = await client.post(
                f"{IAM_URL}/iam/v1/agents/{agent['agent_id']}/grants",
                headers=headers,
                json={"cap": capability},
            )
            if granted.status_code != 201:
                raise SystemExit(
                    f"No se pudo otorgar la capacidad de {persona} "
                    f"({granted.status_code}): {granted.text[:200]}"
                )

            # El secreto se muestra una sola vez, aquí y nunca más.
            print(f"\nDESK_{persona.upper()}_AGENT_ID={agent['agent_id']}")
            print(f"DESK_{persona.upper()}_AGENT_SECRET={agent['agent_secret']}")

        print(
            "\nCopia esas variables a /etc/ordo-desk/env (modo 0600) junto con el "
            "usuario y la contraseña OIDC de cada persona."
        )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Uso: uv run python sim/provision.py <tenant>")
    token = os.environ.get("OWNER_TOKEN", "")
    if not token:
        raise SystemExit(
            "OWNER_TOKEN requerida: un access token OIDC de la persona que será "
            "dueña de los agentes. El intercambio RFC 8693 exige que el sujeto "
            "sea el dueño, así que sin él no hay agente que registrar."
        )
    asyncio.run(provision(sys.argv[1], token))


if __name__ == "__main__":
    main()
