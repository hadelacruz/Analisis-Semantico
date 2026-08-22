"""Configuración común de la batería de tests.

Añade ``src/`` al ``sys.path`` para poder ejecutar los tests sin instalar el
paquete, y expone los ayudantes que usan todos los módulos de prueba.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compiscript import AnalysisResult, analyze, analyze_file  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent / "programs"

#: Anotación que llevan los programas de ``tests/programs/invalid``:
#: ``// @error E105`` o ``// @warning W902`` al final de la línea que falla.
#: Una misma línea puede llevar varias anotaciones.
ANNOTATION = re.compile(r"@(error|warning)\s+([EW]\d{3})")


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------

def check(source: str) -> AnalysisResult:
    """Analiza un fragmento de código Compiscript."""
    return analyze(source, filename="<test>")


def codes(source: str) -> list[str]:
    """Códigos de todos los diagnósticos emitidos, en orden."""
    return check(source).codes()


def error_codes(source: str) -> list[str]:
    """Códigos de los diagnósticos de severidad *error*."""
    return check(source).error_codes()


def assert_ok(source: str) -> AnalysisResult:
    """El programa debe compilar sin ningún error (caso exitoso)."""
    result = check(source)
    assert result.ok, (
        "Se esperaba un programa valido pero se reportaron errores:\n  "
        + "\n  ".join(str(d) for d in result.errors)
    )
    return result


def assert_error(source: str, code: str) -> AnalysisResult:
    """El programa debe reportar exactamente el diagnóstico ``code`` (caso fallido)."""
    result = check(source)
    assert code in result.codes(), (
        f"Se esperaba el diagnostico {code} y no aparecio.\n"
        f"Diagnosticos obtenidos: {result.codes() or '(ninguno)'}\n"
        + "\n".join("  " + str(d) for d in result.diagnostics)
    )
    return result


def assert_clean(source: str) -> AnalysisResult:
    """Ni errores ni advertencias."""
    result = check(source)
    assert not result.diagnostics, (
        "Se esperaba un analisis totalmente limpio:\n  "
        + "\n  ".join(str(d) for d in result.diagnostics)
    )
    return result


def expected_annotations(source: str) -> set[tuple[int, str]]:
    """Pares ``(linea, codigo)`` anotados con ``@error`` / ``@warning``."""
    found: set[tuple[int, str]] = set()
    for number, line in enumerate(source.splitlines(), start=1):
        if "//" not in line:
            continue
        comment = line.split("//", 1)[1]
        for _, code in ANNOTATION.findall(comment):
            found.add((number, code))
    return found


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def analizar():
    """Fixture equivalente a :func:`check`, por comodidad."""
    return check
