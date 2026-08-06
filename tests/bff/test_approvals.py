"""El sello de la aprobación tiene que coincidir byte a byte con el del core."""

from __future__ import annotations

import pytest

from ordo_desk.approvals import fingerprint, route_to_operation, sealed_operation

pytestmark = pytest.mark.anyio


class TestSeal:
    def test_the_shape_is_the_public_contract(self) -> None:
        """Copiada de `sealed_operation` de ordo_runtime. Si esto se desvía, IAM
        responde IAM_APPROVAL_MISMATCH y la operación no se ejecuta nunca."""
        assert sealed_operation("pos.order", "action_refund", 42, {"params": {"reason": "x"}}) == {
            "model": "pos.order",
            "operation": "action_refund",
            "payload": {"record_id": 42, "body": {"params": {"reason": "x"}}},
        }

    def test_an_absent_body_is_an_empty_object_not_null(self) -> None:
        sealed = sealed_operation("pos.order", "action_refund", 42, None)
        assert sealed["payload"]["body"] == {}

    def test_only_business_actions_are_recognised(self) -> None:
        assert route_to_operation("/api/v1/pos.order/42/actions/action_refund") == (
            "pos.order",
            "action_refund",
            42,
        )
        assert route_to_operation("/api/v1/pos.order/42") is None
        assert route_to_operation("/api/v1/pos.order") is None
        assert route_to_operation("/meta/v1/schema") is None


class TestFingerprint:
    def test_the_same_intent_gives_the_same_key(self) -> None:
        """El reintento tras aprobar tiene que reconocerse como la misma
        intención, o el escritorio pediría una aprobación nueva cada vez."""
        operation = sealed_operation("pos.order", "action_refund", 42, {"params": {}})
        assert fingerprint("ropa", "cajero", operation) == fingerprint("ropa", "cajero", operation)

    def test_another_record_is_another_intent(self) -> None:
        first = sealed_operation("pos.order", "action_refund", 42, {"params": {}})
        second = sealed_operation("pos.order", "action_refund", 43, {"params": {}})
        assert fingerprint("ropa", "cajero", first) != fingerprint("ropa", "cajero", second)

    def test_another_persona_is_another_intent(self) -> None:
        """Aprobarle una devolución a una cajera no se la aprueba a otra."""
        operation = sealed_operation("pos.order", "action_refund", 42, {"params": {}})
        assert fingerprint("ropa", "cajero", operation) != fingerprint("ropa", "duena", operation)

    def test_key_order_in_the_body_does_not_matter(self) -> None:
        first = sealed_operation("pos.order", "action_refund", 1, {"a": 1, "b": 2})
        second = sealed_operation("pos.order", "action_refund", 1, {"b": 2, "a": 1})
        assert fingerprint("ropa", "cajero", first) == fingerprint("ropa", "cajero", second)


class TestChoreography:
    async def test_a_blocked_action_returns_the_approval_id(self, client, ordo) -> None:
        await client.post("/desk/session", json={"persona": "cajero"})
        ordo.status = 403
        ordo.payload = {
            "error": {
                "code": "IAM_APPROVAL_REQUIRED",
                "message": "La operación exige aprobación humana",
                "retryable": False,
                "requires_approval": True,
            }
        }
        response = await client.post(
            "/desk/api/v1/pos.order/42/actions/action_refund",
            json={"params": {"reason": "talla"}},
            headers={"Idempotency-Key": "k1"},
        )
        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "IAM_APPROVAL_REQUIRED"
        assert error["approval_id"]
        assert error["approval_status"] == "pending"

    async def test_the_browser_cannot_present_its_own_approval(self, client, ordo) -> None:
        """Si la cabecera del cliente sobreviviera, cualquiera presentaría
        aprobaciones ajenas."""
        await client.post("/desk/session", json={"persona": "cajero"})
        await client.get(
            "/desk/api/v1/product.product",
            headers={"X-Ordo-Approval": "aprobacion-ajena"},
        )
        [forwarded] = ordo.requests
        assert "x-ordo-approval" not in forwarded.headers
