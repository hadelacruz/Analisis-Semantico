"""Validador del código intermedio: casos exitosos y casos fallidos.

El enunciado pide una batería con casos que pasan y casos que fallan. En esta
fase los "casos fallidos" no son programas de Compiscript mal escritos —de eso
se encarga el análisis semántico— sino **código intermedio mal formado**: se
construye a mano un programa TAC roto y se comprueba que el validador lo
detecta.
"""
import pytest

from conftest import compilar, tac_de

from compiscript.tac.quadruple import Op, Operand, Quadruple, TACFunction, TACProgram
from compiscript.tac.validator import CATALOG, TACValidator, validate

pytestmark = pytest.mark.tac


# ---------------------------------------------------------------------------
# Casos exitosos: lo que genera el compilador siempre es valido
# ---------------------------------------------------------------------------

PROGRAMAS_VALIDOS = [
    "print(1 + 2);",
    "let a: integer = 1; if (a > 0) { print(a); } else { print(-a); }",
    "for (let i: integer = 0; i < 3; i = i + 1) { print(i); }",
    "let xs: integer[] = [1, 2]; foreach (v in xs) { print(v); }",
    "function f(n: integer): integer { if (n <= 1) { return 1; } return n * f(n - 1); } print(f(5));",
    "function e(a: integer): integer { function i(x: integer): integer { return a + x; } return i(1); } print(e(1));",
    'class C { let x: integer; function constructor(x: integer) { this.x = x; } } print(new C(1).x);',
    'let n: integer = 1; switch (n) { case 1: print("a"); break; default: print("b"); }',
    'try { print(1); } catch (e) { print(e); }',
    'let s: string = "a" + 1 + true; print(s);',
]


@pytest.mark.parametrize("fuente", PROGRAMAS_VALIDOS, ids=range(len(PROGRAMAS_VALIDOS)))
def test_el_codigo_generado_pasa_el_validador(fuente):
    assert validate(tac_de(fuente)) == []


def test_los_programas_completos_del_repositorio_generan_codigo_valido(programa_valido):
    from compiscript import analyze_file

    resultado = analyze_file(programa_valido)
    assert resultado.ok
    assert resultado.tac is not None
    assert resultado.tac_issues == []


# ---------------------------------------------------------------------------
# Casos fallidos: TAC construido a mano con defectos
# ---------------------------------------------------------------------------

def programa_base(*quads: Quadruple) -> TACProgram:
    """Envuelve unas cuadruplas en una rutina bien delimitada."""
    programa = TACProgram()
    programa.append(Quadruple(Op.FUNC_BEGIN, Operand.func("main"), Operand.const(0)))
    for quad in quads:
        programa.append(quad)
    programa.append(Quadruple(Op.RETURN))
    programa.append(Quadruple(Op.FUNC_END, Operand.func("main")))
    programa.functions.append(
        TACFunction(name="main", label="main", start=0, end=len(programa) - 1)
    )
    return programa


def codigos(programa: TACProgram) -> list[str]:
    return [i.code for i in validate(programa)]


def test_t001_salto_a_una_etiqueta_inexistente():
    programa = programa_base(Quadruple(Op.GOTO, Operand.label("L_no_existe")))
    assert "T001" in codigos(programa)


def test_t001_tambien_detecta_los_saltos_condicionales():
    programa = programa_base(
        Quadruple(Op.IF_GOTO, Operand.temp("t0"), Operand.label("L_fantasma")),
        Quadruple(Op.ASSIGN, Operand.const(1), result=Operand.temp("t0")),
    )
    assert "T001" in codigos(programa)


def test_t002_etiqueta_duplicada():
    programa = programa_base(
        Quadruple(Op.LABEL, Operand.label("L1")),
        Quadruple(Op.LABEL, Operand.label("L1")),
    )
    assert "T002" in codigos(programa)


def test_t003_operador_binario_invalido():
    programa = programa_base(
        Quadruple(
            Op.BINARY, Operand.const(1), Operand.const(2), Operand.temp("t0"), operator="@"
        )
    )
    assert "T003" in codigos(programa)


def test_t003_operador_relacional_invalido_en_un_salto():
    programa = programa_base(
        Quadruple(Op.LABEL, Operand.label("L1")),
        Quadruple(
            Op.IF_REL_GOTO, Operand.const(1), Operand.const(2), Operand.label("L1"), operator="+"
        ),
    )
    assert "T003" in codigos(programa)


def test_t004_sobran_parametros_para_la_llamada():
    programa = programa_base(
        Quadruple(Op.PARAM, Operand.const(1)),
        Quadruple(Op.PARAM, Operand.const(2)),
        Quadruple(Op.CALL, Operand.func("main"), Operand.const(1)),
    )
    assert "T004" in codigos(programa)


def test_t004_faltan_parametros_para_la_llamada():
    programa = programa_base(
        Quadruple(Op.PARAM, Operand.const(1)),
        Quadruple(Op.CALL, Operand.func("main"), Operand.const(3)),
    )
    assert "T004" in codigos(programa)


def test_t005_llamada_a_una_rutina_que_no_existe():
    programa = programa_base(Quadruple(Op.CALL, Operand.func("func_fantasma"), Operand.const(0)))
    assert "T005" in codigos(programa)


def test_t006_aridad_incorrecta_en_una_rutina_del_runtime():
    programa = programa_base(
        Quadruple(Op.PARAM, Operand.const(1)),
        Quadruple(Op.PARAM, Operand.const(2)),
        Quadruple(Op.CALL, Operand.func("__print"), Operand.const(2)),
    )
    assert "T006" in codigos(programa)


def test_t007_temporal_leido_sin_escribirse_nunca():
    programa = programa_base(
        Quadruple(Op.ASSIGN, Operand.temp("t9"), result=Operand.temp("t0"))
    )
    assert "T007" in codigos(programa)


def test_t009_una_rutina_que_no_termina_en_return():
    programa = TACProgram()
    programa.append(Quadruple(Op.FUNC_BEGIN, Operand.func("main"), Operand.const(0)))
    programa.append(Quadruple(Op.ASSIGN, Operand.const(1), result=Operand.temp("t0")))
    programa.append(Quadruple(Op.FUNC_END, Operand.func("main")))
    programa.functions.append(TACFunction(name="main", label="main", start=0, end=2))
    assert "T009" in codigos(programa)


def test_t010_instruccion_binaria_incompleta():
    programa = programa_base(
        Quadruple(Op.BINARY, Operand.const(1), None, Operand.temp("t0"), operator="+")
    )
    assert "T010" in codigos(programa)


# ---------------------------------------------------------------------------
# El validador en si
# ---------------------------------------------------------------------------

def test_todos_los_codigos_del_catalogo_tienen_descripcion():
    assert all(descripcion for descripcion in CATALOG.values())


def test_cada_problema_dice_donde_esta():
    programa = programa_base(Quadruple(Op.GOTO, Operand.label("L_no_existe")))
    problema = validate(programa)[0]
    assert problema.index >= 0
    assert problema.function == "main"
    assert "L_no_existe" in str(problema)


def test_el_validador_se_puede_reutilizar():
    programa = programa_base(Quadruple(Op.GOTO, Operand.label("L_no_existe")))
    validador = TACValidator(programa)
    assert len(validador.validate()) == len(validador.validate())


def test_un_problema_se_serializa_a_diccionario():
    programa = programa_base(Quadruple(Op.GOTO, Operand.label("L_no_existe")))
    datos = validate(programa)[0].to_dict()
    assert set(datos) == {"code", "message", "index", "function"}


def test_el_resultado_del_analisis_expone_los_problemas():
    resultado = compilar("print(1);")
    assert resultado.tac_ok
    assert resultado.tac_dict()["issues"] == []
