"""Un día de operación de la tienda, reproducible.

Habla **por el escritorio**, con la misma cookie de sesión y las mismas rutas
que usa el navegador. No es un atajo: hace que este script sea un test de
contrato de la pantalla. Si la caja deja de funcionar, esto también, y al
revés.

Reproducible de verdad: `random.Random(seed)` y las fechas se escriben
explícitamente. No hay reloj falso —sería un cambio en el core y no lo vale—,
así que los documentos se fechan hacia atrás y `create_date` queda con la hora
real, que es la verdad de cuándo se sembró.

Uso:

    uv run python sim/day_ropa.py --seed 42 --date 2026-08-05 --ventas 40
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from typing import Any

import httpx

DESK = "http://127.0.0.1:8100"
TAX_CODE = "IVA19I"

# Curva de un día de tienda de barrio: almuerzo y después del trabajo. Los pesos
# son relativos, no porcentajes; lo que importa es la forma.
HOURLY_WEIGHTS = {
    10: 2,
    11: 3,
    12: 4,
    13: 7,
    14: 6,
    15: 4,
    16: 4,
    17: 5,
    18: 8,
    19: 8,
    20: 5,
    21: 2,
}


def key() -> str:
    return f"sim-{uuid.uuid4()}"


class Desk:
    """Cliente del escritorio: la misma puerta que usa el navegador."""

    def __init__(self, persona: str) -> None:
        self.client = httpx.Client(base_url=DESK, timeout=30.0)
        response = self.client.post("/desk/session", json={"persona": persona})
        response.raise_for_status()

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self.client.get(f"/desk/api{path}", params=params)
        return self._unwrap(response)

    def post(self, path: str, body: dict[str, Any], *, idem: str | None = None) -> dict[str, Any]:
        headers = {"Idempotency-Key": idem} if idem else {}
        response = self.client.post(f"/desk/api{path}", json=body, headers=headers)
        return self._unwrap(response)

    @staticmethod
    def _unwrap(response: httpx.Response) -> dict[str, Any]:
        payload: dict[str, Any] = response.json()
        if response.status_code >= 400:
            error = payload.get("error", {})
            raise SystemExit(
                f"{response.status_code} {error.get('code')}: {error.get('message')}\n"
                f"  {error.get('hint', '')}"
            )
        return payload

    def close(self) -> None:
        self.client.close()


def open_shift(desk: Desk, config_id: int, opening_cash: str) -> dict[str, Any]:
    existing = desk.get(
        "/v1/pos.session",
        domain=f'[["config_id","=",{config_id}],["state","=","opened"]]',
        fields="id,name",
        limit=1,
    )
    if existing["rows"]:
        return existing["rows"][0]
    created = desk.post(
        "/v1/pos.session",
        {"values": {"config_id": config_id, "state": "draft", "company_id": 1}},
        idem=key(),
    )
    session_id = created["ids"][0]
    opened = desk.post(
        f"/v1/pos.session/{session_id}/actions/action_open",
        {"params": {"opening_cash": opening_cash}},
        idem=key(),
    )
    return {"id": session_id, "name": opened["result"]["name"]}


def sell(
    desk: Desk,
    *,
    session_id: int,
    date: str,
    basket: list[dict[str, Any]],
    cash_method: int,
    card_method: int,
    pay_with_card: bool,
    rng: random.Random,
) -> dict[str, Any]:
    """Una venta, por el mismo camino que la pantalla de caja."""
    base = key()
    created = desk.post(
        "/v1/pos.order",
        {
            "values": {
                "session_id": session_id,
                "state": "draft",
                "date_order": date,
                "currency_id": 1,
                "company_id": 1,
            }
        },
        idem=f"{base}:order",
    )
    order_id = created["ids"][0]
    desk.post(
        "/v1/pos.order.line",
        {
            "values": [
                {
                    "order_id": order_id,
                    "name": line["name"],
                    "product_id": line["product_id"],
                    "quantity": str(line["quantity"]),
                    "price_unit": line["price_unit"],
                    "discount_percent": "0",
                    "tax_codes": TAX_CODE,
                    "income_account_id": None,
                    "company_id": 1,
                }
                for line in basket
            ]
        },
        idem=f"{base}:lines",
    )

    total = sum(round(float(line["price_unit"]) * line["quantity"]) for line in basket)
    if pay_with_card:
        method, amount = card_method, total
    else:
        # En efectivo la gente paga con billetes: redondeo hacia arriba al
        # siguiente múltiplo de mil, que es de donde sale el vuelto.
        method, amount = cash_method, ((total // 1000) + 1) * 1000
    desk.post(
        "/v1/pos.payment",
        {
            "values": {
                "order_id": order_id,
                "method_id": method,
                "amount": str(amount),
                "company_id": 1,
            }
        },
        idem=f"{base}:payment",
    )
    result = desk.post(
        f"/v1/pos.order/{order_id}/actions/action_validate",
        {"params": {}},
        idem=f"{base}:validate",
    )
    del rng
    return result["result"]


def run(seed: int, date: str, sales: int) -> None:
    # Simulador, no criptografía: la reproducibilidad es justamente el punto.
    rng = random.Random(seed)  # noqa: S311
    nonlocal_shift: list[dict[str, Any]] = []
    desk = Desk("cajero")
    try:
        config = desk.get("/v1/pos.config", fields="id,name", limit=1)["rows"][0]
        methods = desk.get("/v1/pos.payment.method", fields="id,code,method_type", limit=20)
        cash = next(m["id"] for m in methods["rows"] if m["method_type"] == "cash")
        card = next(m["id"] for m in methods["rows"] if m["method_type"] == "card")
        catalog = desk.get(
            "/v1/product.product",
            domain='[["product_type","=","consu"]]',
            fields="id,name,list_price",
            limit=200,
        )["rows"]
        if not catalog:
            raise SystemExit("El catálogo está vacío: siembra el tenant primero.")

        shift = open_shift(desk, config["id"], "50000")
        print(f"Turno {shift['name']} en {config['name']}")
        nonlocal_shift.append(shift)

        hours = list(HOURLY_WEIGHTS)
        weights = [HOURLY_WEIGHTS[hour] for hour in hours]
        sold = 0
        failed = 0
        for index in range(sales):
            rng.choices(hours, weights=weights)[0]  # la hora modela el ritmo
            basket = [
                {
                    "product_id": product["id"],
                    "name": product["name"],
                    "price_unit": product["list_price"],
                    "quantity": rng.choice([1, 1, 1, 2]),
                }
                for product in rng.sample(catalog, rng.choice([1, 1, 2, 3]))
            ]
            try:
                ticket = sell(
                    desk,
                    session_id=shift["id"],
                    date=date,
                    basket=basket,
                    cash_method=cash,
                    card_method=card,
                    pay_with_card=rng.random() < 0.45,
                    rng=rng,
                )
                sold += 1
                if index < 3 or index % 10 == 0:
                    print(f"  {ticket['name']}  {ticket['amount_total']}")
            except SystemExit as stop:
                # Quedarse sin stock es un desenlace legítimo de un día de
                # tienda, no un fallo del simulador: se cuenta y se sigue.
                if "STOCK_INSUFFICIENT" not in str(stop):
                    raise
                failed += 1

        print(f"\n{sold} tickets cobrados; {failed} sin stock.")
    finally:
        desk.close()

    # El Z lo pide la dueña, no el cajero: su capability no incluye reportes, y
    # eso no es una traba a rodear sino el control funcionando.
    owner = Desk("duena")
    try:
        summary = owner.get("/v1/reports/pos.session_summary", session_id=nonlocal_shift[0]["id"])
        print(
            f"Z del turno {summary['name']}: {summary['tickets']} tickets, "
            f"neto {summary['net_total']}, por medio {summary['by_method']}"
        )
    finally:
        owner.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--date", default="2026-08-05")
    parser.add_argument("--ventas", type=int, default=40)
    args = parser.parse_args()
    if args.ventas < 1:
        raise SystemExit("--ventas tiene que ser al menos 1")
    run(args.seed, args.date, args.ventas)


if __name__ == "__main__":
    sys.exit(main())
