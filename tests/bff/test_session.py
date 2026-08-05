"""La cookie de sesión: firmada, sin secretos y sin lanzar nunca."""

from __future__ import annotations

from ordo_desk.session import new_session, sign, verify

SECRET = b"secreto"


class TestSigning:
    def test_a_roundtrip_preserves_who_you_are(self) -> None:
        session = new_session("ropa", "cajero", now=1_000)
        restored = verify(sign(session, SECRET), SECRET, ttl_s=3600, now=1_100)
        assert restored == session

    def test_another_secret_does_not_open_it(self) -> None:
        cookie = sign(new_session("ropa", "cajero", now=1_000), SECRET)
        assert verify(cookie, b"otro", ttl_s=3600, now=1_100) is None

    def test_a_flipped_payload_is_detected(self) -> None:
        """Cambiar la persona en la cookie no debería ascender a nadie."""
        cookie = sign(new_session("ropa", "cajero", now=1_000), SECRET)
        body, _, signature = cookie.partition(".")
        forged = f"{body[:-2]}XY.{signature}"
        assert verify(forged, SECRET, ttl_s=3600, now=1_100) is None

    def test_an_expired_cookie_is_no_session(self) -> None:
        cookie = sign(new_session("ropa", "cajero", now=1_000), SECRET)
        assert verify(cookie, SECRET, ttl_s=60, now=2_000) is None

    def test_garbage_never_raises(self) -> None:
        """Una cookie manipulada es un visitante sin sesión, no un 500."""
        for bad in ("", ".", "sinfirma", "a.b", "!!!.???", "eyJ9.zzz"):
            assert verify(bad, SECRET, ttl_s=3600, now=1) is None

    def test_the_cookie_carries_no_token(self) -> None:
        cookie = sign(new_session("ropa", "cajero", now=1_000), SECRET)
        assert "agent" not in cookie.lower()
