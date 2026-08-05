"""Sintaxis de los módulos del navegador.

Existe por un error que llegó a producción: una edición dejó `import { ROUTES }`
y `export const ROUTES` en el mismo archivo. Es un `SyntaxError`, el navegador
no ejecuta nada y la página queda **en blanco, sin mensaje**. Los tests del BFF
no lo veían porque nunca miran el JavaScript.

Esto **no es un build**: `node --check` solo parsea. No genera artefactos, no
transpila y no participa del despliegue; si node no está, el test se salta. La
regla de "sin build" del AGENTS.md sigue en pie —lo que se despliega es
exactamente lo que se escribió— y esto solo verifica que lo escrito sea válido.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"
MODULES = sorted(WEB.rglob("*.js"))


def node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    # nvm no deja node en el PATH de un servicio ni de CI.
    candidates = sorted((Path.home() / ".nvm" / "versions" / "node").glob("*/bin/node"))
    return str(candidates[-1]) if candidates else None


def test_there_are_modules_to_check() -> None:
    """Si el glob deja de encontrar archivos, el test de abajo pasaría vacío."""
    assert len(MODULES) >= 8


@pytest.mark.parametrize("module", MODULES, ids=lambda path: str(path.relative_to(WEB)))
def test_module_parses(module: Path) -> None:
    binary = node()
    if binary is None:
        pytest.skip("node no disponible: la verificación de sintaxis se salta")
    result = subprocess.run(
        [binary, "--check", str(module)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{module.relative_to(WEB)}:\n{result.stderr}"


def test_no_duplicate_top_level_declarations() -> None:
    """El error concreto que se coló: importar y declarar el mismo nombre.

    `node --check` ya lo detecta, pero este test nombra el defecto para que
    quien lo rompa entienda de inmediato qué hizo.
    """
    for module in MODULES:
        text = module.read_text()
        imported = set()
        for line in text.splitlines():
            if line.startswith("import {"):
                names = line[line.index("{") + 1 : line.index("}")]
                imported.update(
                    piece.strip().split(" as ")[-1].strip() for piece in names.split(",")
                )
        for name in imported:
            if not name:
                continue
            for keyword in ("const", "let", "function", "class"):
                assert f"\nexport {keyword} {name}" not in text, (
                    f"{module.relative_to(WEB)} importa '{name}' y también lo declara"
                )


def test_every_import_resolves() -> None:
    """Un import a un archivo inexistente también deja la página en blanco.

    El import map traduce `desk/` a `/web/`, así que la comprobación es directa
    y no necesita ejecutar nada.
    """
    import re

    missing = []
    for module in MODULES:
        for target in re.findall(r'["\'](desk/[^"\']+)["\']', module.read_text()):
            candidate = WEB / target[len("desk/") :]
            if not candidate.is_file():
                missing.append(f"{module.relative_to(WEB)} -> {target}")
    assert not missing, "Imports que no existen:\n  " + "\n  ".join(missing)
