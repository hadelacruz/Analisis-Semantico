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


# ---------------------------------------------------------------------------
# Ayudantes de la fase de codigo intermedio
# ---------------------------------------------------------------------------

def compilar(source: str) -> AnalysisResult:
    """Compila hasta codigo intermedio y exige que el programa sea valido."""
    result = analyze(source, filename="<test>")
    assert result.ok, "el programa deberia compilar sin errores:\n  " + "\n  ".join(
        str(d) for d in result.errors
    )
    assert result.tac is not None, "no se genero codigo intermedio"
    assert not result.tac_issues, (
        "el validador encontro problemas en el codigo generado:\n  "
        + "\n  ".join(str(i) for i in result.tac_issues)
    )
    return result


def tac_de(source: str):
    """El programa TAC de un fragmento valido."""
    return compilar(source).tac


def tac_texto(source: str) -> str:
    """El codigo intermedio en texto, sin comentarios."""
    return compilar(source).tac_text(comments=False)


def ejecutar(source: str) -> list[str]:
    """Compila y ejecuta; devuelve las lineas impresas."""
    salida, fallo = compilar(source).run()
    assert fallo is None, f"la ejecucion se interrumpio: {fallo}"
    return salida


def ejecutar_con_fallo(source: str) -> tuple[list[str], str]:
    """Compila y ejecuta esperando que el programa aborte."""
    salida, fallo = compilar(source).run()
    assert fallo is not None, "se esperaba que la ejecucion abortara"
    return salida, fallo


def instrucciones(source: str, op: str) -> list:
    """Cuadruplas de un tipo concreto dentro del codigo generado."""
    return [q for q in tac_de(source).instructions if q.op.value == op]


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


@pytest.fixture(params=sorted((PROGRAMS / "valid").glob("*.cps")), ids=lambda p: p.name)
def programa_valido(request):
    """Cada uno de los programas .cps validos del repositorio."""
    return request.param
