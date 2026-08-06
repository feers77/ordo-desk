"""La secuencia exacta que hace la pantalla de caja, contra el escritorio vivo.

Existe por un defecto que llegó a producción: el botón **Simular** nunca
funcionó. La simulación corre sobre un ticket real y exige su cobro, pero el
cobro solo se creaba en la ruta de cobrar; simular respondía siempre
`POS_PAYMENT_INSUFFICIENT` y además dejaba borradores huérfanos que bloquean el
cierre del turno.

Los tests del BFF no podían verlo —no conocen el flujo de la pantalla— y
`sim/day_ropa.py` tampoco, porque vende sin simular. Este cubre el hueco:
reproduce el camino completo, incluido el que estaba roto.

Se salta si el escritorio no está arriba.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

DESK = "http://127.0.0.1:8100"
TAX_CODE = "IVA19I"

pytestmark = pytest.mark.anyio


def key() -> str:
    return f"e2e-{uuid.uuid4()}"


@pytest.fixture
async def cashier():
    try:
        async with httpx.AsyncClient(base_url=DESK, timeout=30.0) as client:
            health = await client.get("/desk/healthz")
            if health.status_code != 200:
                pytest.skip("El escritorio no responde")
            await client.post("/desk/session", json={"persona": "cajero"})
            yield client
    except httpx.HTTPError:
        pytest.skip("El escritorio no está arriba")


async def call(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = await client.request(method, f"/desk/api{path}", **kwargs)
    payload: dict[str, Any] = response.json()
    assert response.status_code < 400, payload
    return payload


async def open_shift(client: httpx.AsyncClient) -> int:
    config = (await call(client, "GET", "/v1/pos.config", params={"fields": "id", "limit": 1}))[
        "rows"
    ][0]["id"]
    opened = await call(
        client,
        "GET",
        "/v1/pos.session",
        params={
            "domain": f'[["config_id","=",{config}],["state","=","opened"]]',
            "fields": "id",
            "limit": 1,
        },
    )
    if opened["rows"]:
        return int(opened["rows"][0]["id"])
    created = await call(
        client,
        "POST",
        "/v1/pos.session",
        json={"values": {"config_id": config, "state": "draft", "company_id": 1}},
        headers={"Idempotency-Key": key()},
    )
    session_id = created["ids"][0]
    await call(
        client,
        "POST",
        f"/v1/pos.session/{session_id}/actions/action_open",
        json={"params": {"opening_cash": "50000"}},
        headers={"Idempotency-Key": key()},
    )
    return int(session_id)


async def materialise(client: httpx.AsyncClient, session_id: int, *, received: str) -> int:
    """Lo que hace la pantalla al pulsar Simular o Cobrar."""
    product = (
        await call(
            client,
            "GET",
            "/v1/product.product",
            params={
                "domain": '[["product_type","=","consu"]]',
                "fields": "id,name,list_price",
                "limit": 1,
            },
        )
    )["rows"][0]
    method = next(
        row
        for row in (
            await call(
                client,
                "GET",
                "/v1/pos.payment.method",
                params={"fields": "id,method_type", "limit": 20},
            )
        )["rows"]
        if row["method_type"] == "cash"
    )
    base = key()
    order_id = (
        await call(
            client,
            "POST",
            "/v1/pos.order",
            json={
                "values": {
                    "session_id": session_id,
                    "state": "draft",
                    "date_order": "2026-08-06",
                    "currency_id": 1,
                    "company_id": 1,
                }
            },
            headers={"Idempotency-Key": f"{base}:order"},
        )
    )["ids"][0]
    await call(
        client,
        "POST",
        "/v1/pos.order.line",
        json={
            "values": [
                {
                    "order_id": order_id,
                    "name": product["name"],
                    "product_id": product["id"],
                    "quantity": "1",
                    "price_unit": product["list_price"],
                    "discount_percent": "0",
                    "tax_codes": TAX_CODE,
                    "income_account_id": None,
                    "company_id": 1,
                }
            ]
        },
        headers={"Idempotency-Key": f"{base}:lines"},
    )
    await call(
        client,
        "POST",
        "/v1/pos.payment",
        json={
            "values": {
                "order_id": order_id,
                "method_id": method["id"],
                "amount": received,
                "company_id": 1,
            }
        },
        headers={"Idempotency-Key": f"{base}:payment"},
    )
    return int(order_id)


class TestSimulate:
    async def test_the_preview_says_what_would_happen(self, cashier) -> None:
        session_id = await open_shift(cashier)
        order_id = await materialise(cashier, session_id, received="20000")

        response = await call(
            cashier,
            "POST",
            f"/v1/pos.order/{order_id}/actions/action_validate",
            params={"dry_run": "true"},
            json={"params": {}},
        )
        outcome = response["result"]
        assert outcome["validations"] == [], outcome["validations"]
        would = outcome["would_return"]
        assert would["name"], "la simulación tiene que decir qué número usaría"
        assert would["amount_total"]
        assert "change" in would

        await call(
            cashier,
            "POST",
            f"/v1/pos.order/{order_id}/actions/action_cancel",
            json={"params": {}},
            headers={"Idempotency-Key": key()},
        )

    async def test_simulating_does_not_burn_the_number(self, cashier) -> None:
        session_id = await open_shift(cashier)
        order_id = await materialise(cashier, session_id, received="20000")
        first = (
            await call(
                cashier,
                "POST",
                f"/v1/pos.order/{order_id}/actions/action_validate",
                params={"dry_run": "true"},
                json={"params": {}},
            )
        )["result"]["would_return"]["name"]
        real = (
            await call(
                cashier,
                "POST",
                f"/v1/pos.order/{order_id}/actions/action_validate",
                json={"params": {}},
                headers={"Idempotency-Key": key()},
            )
        )["result"]
        assert real["name"] == first, "el número simulado se gastó"

    async def test_a_ticket_without_payment_says_why(self, cashier) -> None:
        """El caso que rompía la pantalla: simular sin cobro registrado."""
        session_id = await open_shift(cashier)
        base = key()
        order_id = (
            await call(
                cashier,
                "POST",
                "/v1/pos.order",
                json={
                    "values": {
                        "session_id": session_id,
                        "state": "draft",
                        "date_order": "2026-08-06",
                        "currency_id": 1,
                        "company_id": 1,
                    }
                },
                headers={"Idempotency-Key": f"{base}:order"},
            )
        )["ids"][0]
        outcome = (
            await call(
                cashier,
                "POST",
                f"/v1/pos.order/{order_id}/actions/action_validate",
                params={"dry_run": "true"},
                json={"params": {}},
            )
        )["result"]
        # La pantalla tiene que distinguir esto de un éxito: `would_return`
        # vacío con `validations` llenas significa que fallaría.
        assert outcome["would_return"] == {}
        assert outcome["validations"][0]["code"] in (
            "POS_ORDER_EMPTY",
            "POS_PAYMENT_INSUFFICIENT",
        )
        await call(
            cashier,
            "POST",
            f"/v1/pos.order/{order_id}/actions/action_cancel",
            json={"params": {}},
            headers={"Idempotency-Key": key()},
        )


class TestHygiene:
    async def test_a_discarded_ticket_is_cancelled(self, cashier) -> None:
        """Un borrador abandonado bloquea el cierre del turno, así que
        descartar tiene que cancelarlo de verdad."""
        session_id = await open_shift(cashier)
        order_id = await materialise(cashier, session_id, received="20000")
        await call(
            cashier,
            "POST",
            f"/v1/pos.order/{order_id}/actions/action_cancel",
            json={"params": {}},
            headers={"Idempotency-Key": key()},
        )
        [order] = (
            await call(cashier, "GET", f"/v1/pos.order/{order_id}", params={"fields": "state"}),
        )
        assert order["state"] == "cancelled"
