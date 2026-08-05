"""Servidor estático para trabajar solo en la interfaz.

Solo biblioteca estándar: sin dependencias, sin red, sin CDNs. Calcado del
patrón que el core usa para su documentación. No sustituye al BFF —sin él no
hay sesión ni datos— pero sirve para maquetar sin levantar nada más.
"""

from __future__ import annotations

import argparse
import http.server
import os
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "web"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8101


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean in ("/", ""):
            clean = "/index.html"
        if clean.startswith("/web/"):
            clean = clean[len("/web") :]
        candidate = (ROOT / clean.lstrip("/")).resolve()
        # Path traversal: fuera de web/ no se sirve nada.
        if not candidate.is_relative_to(ROOT):
            return str(ROOT / "index.html")
        return str(candidate)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("DESK_WEB_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("DESK_WEB_PORT", DEFAULT_PORT))
    )
    args = parser.parse_args()

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((args.host, args.port), Handler) as server:
        print(f"web/ en http://{args.host}:{args.port} (sin BFF: no hay sesión ni datos)")
        server.serve_forever()


if __name__ == "__main__":
    main()
