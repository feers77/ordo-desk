"""Lectura de la configuración.

Existe por un defecto real: `load_settings` construía el diccionario de
credenciales y no lo pasaba al `Settings`, así que el escritorio arrancaba
perfecto y respondía DESK_NO_CREDENTIALS a todo. Los tests del broker usaban
un `Settings` armado a mano y no lo veían.
"""

from __future__ import annotations

import pytest

from ordo_desk.config import PERSONAS, load_settings

FULL = {
    "DESK_SESSION_SECRET": "x" * 32,
    "DESK_TENANT": "ropa",
    "DESK_CAJERO_AGENT_ID": "agent-1",
    "DESK_CAJERO_AGENT_SECRET": "s3cr3t",
    "DESK_CAJERO_USER": "caja@ropa.cl",
    "DESK_CAJERO_PASSWORD": "clave",
}


def apply(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for persona in PERSONAS:
        for suffix in ("AGENT_ID", "AGENT_SECRET", "USER", "PASSWORD"):
            monkeypatch.delenv(f"DESK_{persona.upper()}_{suffix}", raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


class TestLoadSettings:
    def test_the_credentials_reach_the_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        apply(monkeypatch, FULL)
        settings = load_settings()
        assert settings.credentials_for("ropa", "cajero") is not None
        assert settings.credentials_for("ropa", "cajero").agent_id == "agent-1"

    def test_a_persona_configured_by_halves_is_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Con el secreto pero sin el dueño no hay intercambio posible: mejor
        decir que falta que fallar en el primer request."""
        partial = dict(FULL)
        del partial["DESK_CAJERO_PASSWORD"]
        apply(monkeypatch, partial)
        assert load_settings().credentials_for("ropa", "cajero") is None

    def test_without_a_signing_secret_it_refuses_to_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Preferimos no arrancar antes que arrancar con una clave por defecto
        que alguien deje en producción."""
        apply(monkeypatch, {})
        monkeypatch.delenv("DESK_SESSION_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="DESK_SESSION_SECRET"):
            load_settings()
