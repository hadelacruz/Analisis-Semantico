"""Batería de programas completos ``.cps``.

* ``tests/programs/valid/``   — deben compilar sin ningún error.
* ``tests/programs/invalid/`` — cada línea marcada con ``// @error CODIGO`` o
  ``// @warning CODIGO`` debe producir exactamente ese diagnóstico en esa
  línea, y no debe aparecer ningún diagnóstico sin anotar.

Este último punto es lo que evita que la batería "pase" por accidente: un
cambio que introduzca un falso positivo rompe el test aunque siga detectando
los errores esperados.
"""
from pathlib import Path

import pytest

from conftest import PROGRAMS, expected_annotations
from compiscript import analyze_file

VALID = sorted((PROGRAMS / "valid").glob("*.cps"))
INVALID = sorted((PROGRAMS / "invalid").glob("*.cps"))

# El programa de ejemplo que entrega el curso también debe analizarse bien.
CURSO = Path(__file__).resolve().parent.parent / "compiscript" / "program" / "program.cps"


def _ids(paths):
    return [p.name for p in paths]


@pytest.mark.parametrize("path", VALID, ids=_ids(VALID))
def test_programas_validos(path):
    result = analyze_file(path)
    assert result.ok, "El programa deberia compilar sin errores:\n  " + "\n  ".join(
        str(d) for d in result.errors
    )
    assert result.semantic_ran
    assert result.symbol_table is not None


@pytest.mark.parametrize("path", INVALID, ids=_ids(INVALID))
def test_programas_invalidos(path):
    source = path.read_text(encoding="utf-8")
    expected = expected_annotations(source)
    assert expected, f"{path.name} no tiene ninguna anotacion @error/@warning"

    result = analyze_file(path)
    actual = {(d.line, d.code) for d in result.diagnostics}

    faltantes = sorted(expected - actual)
    sobrantes = sorted(actual - expected)

    detalle = "\n".join("  " + str(d) for d in result.diagnostics)
    assert not faltantes, f"Diagnosticos esperados que no aparecieron: {faltantes}\n{detalle}"
    assert not sobrantes, f"Diagnosticos no anotados: {sobrantes}\n{detalle}"
    assert not result.ok


@pytest.mark.skipif(not CURSO.is_file(), reason="no esta el ejemplo del curso")
def test_el_ejemplo_del_curso_es_valido():
    """``compiscript/program/program.cps`` es el archivo de prueba del enunciado."""
    result = analyze_file(CURSO)
    assert result.ok, "\n".join(str(d) for d in result.errors)
    # El propio ejemplo accede a numbers[10] dentro de un try a proposito.
    assert "W903" in result.codes()


def test_hay_cobertura_de_todas_las_categorias():
    """La batería de programas debe cubrir las 7 categorías del enunciado."""
    codigos = set()
    for path in INVALID:
        codigos.update(analyze_file(path).codes())

    prefijos = {c[:2] for c in codigos}
    assert {"E1", "E2", "E3", "E4", "E5", "E6", "E7", "W9"} <= prefijos
