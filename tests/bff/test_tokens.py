"""El broker de tokens: la pieza que existe porque el navegador no puede."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from ordo_desk.tokens import CachedToken, TokenBroker, TokenError

pytestmark = pytest.mark.anyio


class TestCachedToken:
    def test_a_token_about_to_die_is_not_fresh(self) -> None:
        """Se renueva a los 12 de los 15 minutos: esperar al 401 convierte cada
        vencimiento en un error visible para el cajero."""
        token = CachedToken(value="x", expires_at=900.0)  # los 15 minutos de IAM
        assert token.fresh(now=0.0) is True
        assert token.fresh(now=700.0) is True
        # a falta de menos de 3 minutos ya se considera viejo
        assert token.fresh(now=750.0) is False


class TestBroker:
    async def test_the_token_is_reused_until_it_ages(self, settings, ordo) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(ordo.handler)) as client:
            broker = TokenBroker(settings, client)
            first = await broker.agent_token("ropa", "cajero")
            second = await broker.agent_token("ropa", "cajero")
        assert first == second
        assert ordo.token_calls == 1

    async def test_concurrent_requests_do_not_stampede_iam(self, settings, ordo) -> None:
        """Cuando el token vence y llegan diez requests a la vez, uno renueva y
        los otros nueve esperan su resultado."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(ordo.handler)) as client:
            broker = TokenBroker(settings, client)
            tokens = await asyncio.gather(
                *(broker.agent_token("ropa", "cajero") for _ in range(10))
            )
        assert len(set(tokens)) == 1
        assert ordo.token_calls == 1

    async def test_invalidating_forces_a_new_exchange(self, settings, ordo) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(ordo.handler)) as client:
            broker = TokenBroker(settings, client)
            first = await broker.agent_token("ropa", "cajero")
            broker.invalidate("ropa", "cajero")
            second = await broker.agent_token("ropa", "cajero")
        assert first != second
        assert ordo.token_calls == 2

    async def test_a_persona_without_credentials_is_a_clear_error(self, settings, ordo) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(ordo.handler)) as client:
            broker = TokenBroker(settings, client)
            with pytest.raises(TokenError) as excinfo:
                await broker.agent_token("ropa", "duena")
        assert "make provision" in str(excinfo.value)

    async def test_the_exchange_needs_both_credentials(self, settings, ordo) -> None:
        """RFC 8693 exige el secreto del agente **y** un token OIDC del dueño.
        Por eso esto no puede vivir en el navegador."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(ordo.handler)) as client:
            broker = TokenBroker(settings, client)
            await broker.agent_token("ropa", "cajero")
        assert ordo.oidc_calls == 1
        assert ordo.token_calls == 1
