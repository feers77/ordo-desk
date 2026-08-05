"""El pasamanos: qué deja pasar, qué corta y qué nunca reenvía."""

from __future__ import annotations

import pytest

from ordo_desk.proxy import ProxyRefusedError, check_path, clamp_limit

pytestmark = pytest.mark.anyio


async def enter(client, persona: str = "cajero") -> None:
    response = await client.post("/desk/session", json={"persona": persona})
    assert response.status_code == 200


class TestPathRules:
    def test_only_the_api_and_meta_prefixes_are_exposed(self) -> None:
        assert check_path("/api/v1/product.product") == "/api/v1/product.product"
        assert check_path("/meta/v1/schema") == "/meta/v1/schema"

    def test_iam_is_never_proxied(self) -> None:
        """Si el BFF proxeara /approve con un bearer de dueño, cualquier XSS se
        convertiría en aprobador universal."""
        with pytest.raises(ProxyRefusedError) as excinfo:
            check_path("/iam/v1/approvals/1/approve")
        assert excinfo.value.code == "DESK_PATH_NOT_ALLOWED"

    def test_the_webhook_secret_stays_on_the_server(self) -> None:
        with pytest.raises(ProxyRefusedError) as excinfo:
            check_path("/api/v1/webhook.subscription")
        assert excinfo.value.code == "DESK_MODEL_NOT_ALLOWED"

    def test_limit_is_clamped(self) -> None:
        assert clamp_limit([("limit", "500")], 200) == [("limit", "200")]
        assert clamp_limit([("limit", "20")], 200) == [("limit", "20")]
        assert clamp_limit([("limit", "muchos")], 200) == [("limit", "muchos")]


class TestSession:
    async def test_without_a_session_nothing_passes(self, client) -> None:
        response = await client.get("/desk/api/v1/product.product")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "DESK_NO_SESSION"

    async def test_an_unknown_persona_is_refused(self, client) -> None:
        response = await client.post("/desk/session", json={"persona": "gerente"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "DESK_UNKNOWN_PERSONA"

    async def test_a_tampered_cookie_is_no_session_not_a_crash(self, client) -> None:
        await enter(client)
        client.cookies.set("desk_session", "eyJhIjoxfQ.firmafalsa", domain="desk.test")
        response = await client.get("/desk/session")
        assert response.status_code == 401

    async def test_the_session_never_carries_a_token(self, client) -> None:
        await enter(client)
        payload = (await client.get("/desk/session")).json()
        assert payload["token_in_browser"] is False
        assert "token" not in str(payload).lower().replace("token_in_browser", "")


class TestForwarding:
    async def test_the_bff_puts_the_bearer_the_browser_never_sees(self, client, ordo) -> None:
        await enter(client)
        response = await client.get("/desk/api/v1/product.product")
        assert response.status_code == 200
        [forwarded] = ordo.requests
        assert forwarded.headers["authorization"] == "Bearer agent-token-1"
        assert forwarded.headers["x-ordo-tenant"] == "ropa"

    async def test_a_client_supplied_authorization_is_dropped(self, client, ordo) -> None:
        """La identidad la pone el BFF. Si la cabecera del cliente sobreviviera,
        cualquiera podría presentar su propio token."""
        await enter(client)
        await client.get(
            "/desk/api/v1/product.product",
            headers={"Authorization": "Bearer robado", "X-Ordo-Tenant": "otro"},
        )
        [forwarded] = ordo.requests
        assert forwarded.headers["authorization"] == "Bearer agent-token-1"
        assert forwarded.headers["x-ordo-tenant"] == "ropa"

    async def test_the_error_envelope_travels_untouched(self, client, ordo) -> None:
        await enter(client)
        ordo.status = 403
        ordo.payload = {
            "error": {
                "code": "AUTH_DENIED",
                "message": "El rol no permite esta operación",
                "retryable": False,
                "requires_approval": False,
                "hint": "Pide el rol adecuado.",
            }
        }
        response = await client.get("/desk/api/v1/account.move")
        assert response.status_code == 403
        assert response.json() == ordo.payload

    async def test_a_persona_without_credentials_says_so(self, client) -> None:
        await enter(client, "duena")
        response = await client.get("/desk/api/v1/product.product")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DESK_NO_CREDENTIALS"

    async def test_responses_are_never_cached(self, client) -> None:
        await enter(client)
        response = await client.get("/desk/api/v1/product.product")
        assert response.headers["cache-control"] == "no-store"
