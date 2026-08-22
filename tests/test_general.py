"""Reglas generales y advertencias (E7xx, W9xx) — enunciado, sección 2.7."""
import pytest

from conftest import assert_error, assert_ok, check

pytestmark = pytest.mark.generales


# ---------------------------------------------------------------------------
# E701 — las expresiones deben tener sentido semántico
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "function f() { print(1); } f();",             # llamada
        "let x: integer = 1; x = 2;",                  # asignacion
        "let xs: integer[] = [1]; xs[0] = 2;",         # asignacion a elemento
        "class C {} new C();",                         # instanciacion
        "class C { let x: integer; } let c: C = new C(); c.x = 1;",
    ],
)
def test_e701_sentencias_con_efecto(source):
    assert_ok(source)


@pytest.mark.parametrize(
    "source",
    [
        "5 + 3;",
        "let x: integer = 1; x;",
        "let x: integer = 1; x > 2;",
        '"hola";',
    ],
)
def test_e701_sentencias_sin_efecto(source):
    assert_error(source, "E701")


@pytest.mark.parametrize(
    "source",
    [
        "function f(): integer { return 1; } f() = 5;",   # el resultado de una llamada
        "class C { let x: integer; } new C() = 1;",       # una instancia recien creada
    ],
)
def test_e701_destino_de_asignacion_invalido(source):
    assert_error(source, "E701")


def test_no_se_pueden_multiplicar_funciones():
    """Caso explícito del enunciado: 'no multiplicar funciones'."""
    source = """
    function a(): integer { return 1; }
    function b(): integer { return 2; }
    let mal = a * b;
    """
    assert_error(source, "E309")
    # Invocándolas sí es válido.
    assert_ok(
        """
        function a(): integer { return 1; }
        function b(): integer { return 2; }
        let bien: integer = a() * b();
        """
    )


# ---------------------------------------------------------------------------
# E702 — 'print' necesita un valor
# ---------------------------------------------------------------------------

def test_e702_print_valido():
    assert_ok('print("hola"); print(1); print(true); print(1 + 2);')


def test_e702_print_de_void():
    assert_error("function p() { } print(p());", "E702")


# ---------------------------------------------------------------------------
# W901 — variable usada antes de asignarle valor
# ---------------------------------------------------------------------------

def test_w901_variable_inicializada_no_avisa():
    assert "W901" not in check("let x: integer = 1; print(x);").codes()
    assert "W901" not in check("let x: integer; x = 1; print(x);").codes()


def test_w901_variable_sin_inicializar():
    result = check("let x: integer; print(x);")
    assert "W901" in result.codes()
    assert result.ok      # es sólo una advertencia


# ---------------------------------------------------------------------------
# W902 — código muerto
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "function f(): integer { return 1; }",
        "while (true) { break; }",
        "function f(n: integer): integer { if (n > 0) { return 1; } return 2; }",
    ],
)
def test_w902_sin_codigo_muerto(source):
    assert "W902" not in check(source).codes()


@pytest.mark.parametrize(
    "source",
    [
        'function f(): integer { return 1; print("nunca"); }',
        'while (true) { break; print("nunca"); }',
        'for (let i: integer = 0; i < 3; i = i + 1) { continue; print("nunca"); }',
        'function f(n: integer): integer { if (n > 0) { return 1; } else { return 2; } print("x"); }',
    ],
)
def test_w902_codigo_muerto_detectado(source):
    result = check(source)
    assert "W902" in result.codes()


def test_w902_solo_se_avisa_una_vez_por_bloque():
    source = 'function f(): integer { return 1; print("a"); print("b"); print("c"); }'
    assert check(source).codes().count("W902") == 1


# ---------------------------------------------------------------------------
# W904 — división entre la constante cero
# ---------------------------------------------------------------------------

def test_w904_division_normal_no_avisa():
    assert "W904" not in check("let x: integer = 10 / 2;").codes()


@pytest.mark.parametrize("source", ["let x: integer = 10 / 0;", "let x: integer = 10 % 0;"])
def test_w904_division_entre_cero(source):
    assert "W904" in check(source).codes()


# ---------------------------------------------------------------------------
# W905 — variable local declarada y nunca usada
# ---------------------------------------------------------------------------

def test_w905_variable_usada_no_avisa():
    source = "function f(): integer { let x: integer = 1; return x; }"
    assert "W905" not in check(source).codes()


def test_w905_variable_local_sin_usar():
    source = "function f(): integer { let sinUsar: integer = 1; return 2; }"
    result = check(source)
    assert "W905" in result.codes()
    assert result.ok


# ---------------------------------------------------------------------------
# Declaraciones duplicadas (resumen del requerimiento 2.7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("let x: integer = 1; let x: integer = 2;", "E202"),
        ("function f(a: integer, a: integer): integer { return a; }", "E307"),
        ("function f(): integer { return 1; } function f(): integer { return 2; }", "E306"),
        ("class C { let x: integer; let x: integer; }", "E506"),
    ],
)
def test_declaraciones_duplicadas(source, code):
    assert_error(source, code)


# ---------------------------------------------------------------------------
# Errores de sintaxis: el análisis semántico no llega a ejecutarse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    ["let x: integer = ;", "function f( { }", "let x: integer = 1", "if true { }"],
)
def test_errores_de_sintaxis(source):
    result = check(source)
    assert not result.ok
    assert result.semantic_ran is False
    assert any(code in ("E001", "E002") for code in result.codes())


def test_las_cadenas_no_generan_cascadas_de_errores():
    """Un único error real no debe producir una avalancha de errores derivados."""
    result = check('let x: integer = "mal"; let y: integer = x + 1; let z: integer = y * 2;')
    assert result.error_codes() == ["E105"]
